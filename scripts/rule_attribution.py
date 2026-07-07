#!/usr/bin/env python3
"""rule_attribution — 자기보완 루프의 '의사결정 채점' 레이어 (v2.11).

배경: 기존 18시 루프는 '목표가 예측 오차(±5%)'만 채점하고 '청산 룰이 실제 손익에 끼친
비용'은 집계하지 않았다. 2026-05-20~06-09 운용에서 강제청산 6/6·목표도달 0건·PF 0.68·
마찰비용이 실현손실의 41%였는데 어떤 lessons 항목도 이를 표면화하지 못했다
(reports/2026-06-10-pipeline-research.md). 이 스크립트가 룰별 손익 기여를 숫자로 채점한다.

산출(state/rule_attribution.json + stdout 마크다운):
1) round_trips     — trade_log 의 BUY/SELL 계열 FIFO 매칭 라운드트립(청산 이벤트당 1건)
2) by_rule         — 청산 룰(action)별 건수·실현손익·청산 후 t1/t5/t10 일실(forgone)·평균보유일
                     forgone = (청산 후 N번째 관측 종가 − 청산가) × 매도주수. 양수 = 팔고 나서
                     올랐다(조기청산 비용), 음수 = 청산이 손실을 줄였다.
3) account         — profit factor·expectancy·회전대금·마찰비용 추정·보유기간 중앙값
4) benchmarks      — KOSPI / 진입종목 단순보유(no-stop) / 실제 equity 3종 나란히
5) blocked_day     — OPEN_CHECK 의 후보 전원 차단(BLOCKED/DEFERRED) 일수 비율

가격 관측은 trade_log 전 항목(holdings/체결가/today_ohlc/target_check)에서 수집하고,
청산 후 candidates 에서 빠진 종목은 state/exit_tracking.json 에 스냅샷 종가를 계속
캐시해 전방 추적한다(fetch_market_data.collect_tickers 가 이 파일의 종목을 수집 대상에
포함). 표준 라이브러리만 사용(의존성 0). 주말 saturday_review·sunday_policy_review 가
이 산출을 인용한다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "rule_attribution.json"
TRACK_PATH = ROOT / "state" / "exit_tracking.json"

BUY_ACTIONS = {"BUY"}
# 재계산 손익 vs 로그 손익 허용 오차 — 반올림(net/주수 2dp) 잡음은 무시하고
# 실제 이중계상(누적치 혼입)만 잡는다.
PNL_MISMATCH_TOLERANCE_KRW = 50
# SELL 계열 — reconcile_portfolio 분류와 동일한 관점(체결 액션만, EVAL/CHECK 류 제외).
SELL_PREFIXES = ("SELL", "TRAILING_STOP")
BLOCKED_DECISIONS = {"BLOCKED", "DEFERRED", "DEFERRED_12H"}

# 가격 관측 우선순위 — 같은 날짜에 복수 관측이 있으면 높은 쪽 채택.
PRIO_CLOSE, PRIO_SNAPSHOT, PRIO_TRADE, PRIO_STALE = 3, 2, 1, 0


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_trade_log() -> list[dict]:
    path = ROOT / "state" / "trade_log.jsonl"
    entries = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def date_of(entry: dict) -> str | None:
    ts = entry.get("ts") or ""
    return ts[:10] if len(ts) >= 10 else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def observe(prices: dict, ticker: str, date: str | None, value: Any, prio: int) -> None:
    v = _num(value)
    if not ticker or not date or v is None or v <= 0:
        return
    cur = prices.setdefault(ticker, {})
    old = cur.get(date)
    if old is None or prio >= old[1]:
        cur[date] = (v, prio)


def collect_price_observations(entries: list[dict], snapshot: dict, track: dict) -> dict:
    """trade_log 전 항목 + 스냅샷 + exit_tracking 캐시에서 종목별 {date: (close, prio)} 수집."""
    prices: dict[str, dict[str, tuple[float, int]]] = {}
    for e in entries:
        d = date_of(e)
        t = e.get("ticker")
        # 체결가 (BUY price 는 슬리피지 포함 — 관측치로는 충분)
        if t and t != "ALL":
            ohlc = e.get("today_ohlc")
            if isinstance(ohlc, dict):
                observe(prices, t, ohlc.get("date") or d, ohlc.get("close"), PRIO_CLOSE)
            for k, prio in (("close_price", PRIO_CLOSE), ("snapshot_price", PRIO_SNAPSHOT),
                            ("execution_price", PRIO_TRADE), ("price", PRIO_TRADE),
                            ("net_price_per_share", PRIO_TRADE), ("price_approx", PRIO_TRADE),
                            ("web_price", PRIO_SNAPSHOT)):
                observe(prices, t, d, e.get(k), prio)
        # holdings 배열들 (EOD/OPEN/MIDDAY 평가)
        for key in ("holdings", "holdings_pre_trade", "holdings_post_trade"):
            for h in e.get(key) or []:
                if not isinstance(h, dict):
                    continue
                ht = h.get("ticker")
                ohlc = h.get("ohlc") or h.get("today_ohlc")
                if isinstance(ohlc, dict):
                    observe(prices, ht, d, ohlc.get("close"), PRIO_CLOSE)
                observe(prices, ht, d, h.get("close"), PRIO_CLOSE)
                observe(prices, ht, d, h.get("close_approx"), PRIO_SNAPSHOT)
                for k in ("price", "current_price", "snapshot_price", "web_price"):
                    observe(prices, ht, d, h.get(k), PRIO_SNAPSHOT)
                for k in ("price_stale", "stale_price", "price_carried_over"):
                    observe(prices, ht, d, h.get(k), PRIO_STALE)
        # target_check: {ticker: {close: ...}}
        tc = e.get("target_check")
        if isinstance(tc, dict):
            for tt, info in tc.items():
                if isinstance(info, dict):
                    observe(prices, tt, d, info.get("close"), PRIO_CLOSE)
    # 스냅샷 (오늘 관측)
    for t, ts in (snapshot.get("tickers") or {}).items():
        if not isinstance(ts, dict):
            continue
        last_date = None
        for s in ts.get("sources") or []:
            if isinstance(s, dict) and s.get("last_date"):
                last_date = max(last_date or "", s["last_date"])
        ohlc = ts.get("today_ohlc")
        if isinstance(ohlc, dict) and ohlc.get("date"):
            observe(prices, t, ohlc["date"], ohlc.get("close"), PRIO_CLOSE)
        observe(prices, t, last_date, ts.get("last_close"), PRIO_SNAPSHOT)
    # exit_tracking 캐시 (과거 실행이 모아둔 청산 종목 관측)
    for t, obs in (track.get("tickers") or {}).items():
        if isinstance(obs, dict):
            for dte, px in obs.items():
                observe(prices, t, dte, px, PRIO_SNAPSHOT)
    return prices


def sell_exit_price(e: dict) -> float | None:
    shares = _num(e.get("shares")) or _num(e.get("shares_sold"))
    net = _num(e.get("net_proceeds"))
    if net and shares:
        return round(net / shares, 2)
    for k in ("execution_price", "net_price_per_share", "price_approx", "price"):
        v = _num(e.get(k))
        if v:
            return v
    return None


def build_round_trips(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """FIFO 매칭 — 청산(SELL 계열) 이벤트당 1 라운드트립. 반환: (round_trips, open_lots)."""
    lots: dict[str, list[dict]] = {}
    trips: list[dict] = []
    for e in entries:
        action = e.get("action") or ""
        t = e.get("ticker")
        d = date_of(e)
        if action in BUY_ACTIONS and t:
            sh = _num(e.get("shares")) or 0
            px = _num(e.get("price")) or 0
            if sh and px:
                lots.setdefault(t, []).append({"date": d, "price": px, "shares": sh})
        elif action.startswith(SELL_PREFIXES) and t:
            sh = _num(e.get("shares")) or _num(e.get("shares_sold")) or 0
            exit_px = sell_exit_price(e)
            if not sh or exit_px is None:
                continue
            remain = sh
            entry_date, entry_cost = None, 0.0
            q = lots.get(t, [])
            while remain > 0 and q:
                lot = q[0]
                take = min(lot["shares"], remain)
                entry_cost += take * lot["price"]
                entry_date = entry_date or lot["date"]
                lot["shares"] -= take
                remain -= take
                if lot["shares"] <= 0:
                    q.pop(0)
            hold_days = None
            if entry_date and d:
                hold_days = (datetime.fromisoformat(d) - datetime.fromisoformat(entry_date)).days
            # 실현손익은 원장 필드를 신뢰하지 않고 체결가로 재계산한다 — trade_log 의
            # realized_pnl 필드 의미가 중간에 바뀌었다(구 SELL 라인 = 왕복분, 2026-07-06
            # LS ELECTRIC 라인 = 누적 -77,928 + 왕복분은 realized_delta -12,858). 이 스키마
            # 드리프트를 왕복분으로 읽는 바람에 손실 65,070원 과대계상(2026-07-06 감사 발견).
            # 로그값은 realized_delta 우선으로 읽어 logged_realized_pnl 로 보존하고,
            # 재계산값과 어긋나면 pnl_mismatch 로 표면화한다(원장 정합성 경보).
            logged_pnl = _num(e.get("realized_delta"))
            if logged_pnl is None:
                logged_pnl = _num(e.get("realized_pnl"))
            computed_pnl = None
            if remain <= 0 and entry_date is not None:
                computed_pnl = round(exit_px * sh - entry_cost, 0)
            realized = computed_pnl if computed_pnl is not None else logged_pnl
            mismatch = (
                computed_pnl is not None and logged_pnl is not None
                and abs(computed_pnl - logged_pnl) > PNL_MISMATCH_TOLERANCE_KRW
            )
            trips.append({
                "ticker": t, "name": e.get("name") or t,
                "entry_date": entry_date, "exit_date": d,
                "entry_cost": round(entry_cost, 0), "exit_price": exit_px,
                "shares": sh, "hold_days": hold_days,
                "realized_pnl": realized,
                "logged_realized_pnl": logged_pnl,
                "pnl_mismatch": mismatch,
                "exit_rule": action,
                # 선제추론 P&L 결합(v2.21 안건⑥→구현): trade_log SELL 항목의 inference_id 를
                # 라운드트립에 전파 — score_inferences 가 rt.inference_id 로 결합 손익·PF 를 집계한다
                # (기존엔 score 쪽만 읽고 쓰는 쪽이 없어 pnl_linked_n=0 영구 고착).
                "inference_id": e.get("inference_id"),
            })
    open_lots = [
        {"ticker": t, "date": lot["date"], "price": lot["price"], "shares": lot["shares"]}
        for t, q in lots.items() for lot in q if lot["shares"] > 0
    ]
    return trips, open_lots


def post_exit_marks(trip: dict, prices: dict) -> dict:
    """청산 후 N번째 '관측' 종가 기준 t1/t5/t10 일실(forgone). 관측일 동봉(정직성)."""
    obs = prices.get(trip["ticker"], {})
    after = sorted(d for d in obs if trip["exit_date"] and d > trip["exit_date"])
    out = {}
    for label, idx in (("t1", 0), ("t5", 4), ("t10", 9)):
        if len(after) > idx:
            dte = after[idx]
            px = obs[dte][0]
            out[label] = {
                "date": dte, "close": px,
                "forgone_krw": round((px - trip["exit_price"]) * trip["shares"], 0),
            }
        else:
            out[label] = None
    return out


def kospi_window(entries: list[dict]) -> dict:
    series: list[tuple[str, float]] = []
    for e in entries:
        d = date_of(e)
        for k in ("kospi_close", "kospi_close_approx"):
            v = _num(e.get(k))
            if d and v and v > 1000:
                series.append((d, v))
                break
    if len(series) < 2:
        return {"pct": None}
    series.sort()
    first, last = series[0], series[-1]
    return {
        "from": first[0], "to": last[0],
        "from_close": first[1], "to_close": last[1],
        "pct": round((last[1] / first[1] - 1) * 100, 2),
    }


def buy_and_hold(entries: list[dict], prices: dict) -> dict:
    """종목별 첫 진입가 → 최신 관측가 (no-stop 단순보유 counterfactual)."""
    first_buy: dict[str, dict] = {}
    for e in entries:
        if e.get("action") in BUY_ACTIONS and e.get("ticker") and e["ticker"] not in first_buy:
            px = _num(e.get("price"))
            if px:
                first_buy[e["ticker"]] = {"date": date_of(e), "price": px, "name": e.get("name") or e["ticker"]}
    per: dict[str, dict] = {}
    rets = []
    for t, fb in first_buy.items():
        obs = prices.get(t, {})
        if not obs:
            continue
        latest = max(obs)
        pct = round((obs[latest][0] / fb["price"] - 1) * 100, 2)
        per[t] = {"name": fb["name"], "first_entry": fb["date"], "entry_price": fb["price"],
                  "latest_date": latest, "latest_close": obs[latest][0], "pct": pct}
        rets.append(pct)
    return {
        "per_ticker": per,
        "equal_weight_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "note": "각 종목 첫 진입가→최신 관측가, no-stop 가정. latest_date 가 오래됐으면 stale.",
    }


def blocked_days(entries: list[dict]) -> dict:
    days: dict[str, bool] = {}
    for e in entries:
        if e.get("action") != "OPEN_CHECK":
            continue
        cands = e.get("candidates_checked")
        d = date_of(e)
        if not d or not isinstance(cands, list) or not cands:
            continue
        days[d] = all(
            (c.get("decision") or "").upper() in BLOCKED_DECISIONS
            for c in cands if isinstance(c, dict)
        )
    n = len(days)
    blocked = sum(1 for v in days.values() if v)
    return {
        "days_with_candidates": n, "blocked_days": blocked,
        "blocked_day_rate_pct": round(blocked / n * 100, 1) if n else None,
        "dates_blocked": sorted(d for d, v in days.items() if v),
    }


def update_exit_tracking(track: dict, trips: list[dict], snapshot: dict) -> dict:
    """청산 이력이 있는 종목의 스냅샷 종가를 캐시에 누적(전방 추적 — candidates 이탈 후 대비)."""
    tickers = track.setdefault("tickers", {})
    exited = {tr["ticker"] for tr in trips}
    for t in exited:
        ts = (snapshot.get("tickers") or {}).get(t)
        if not isinstance(ts, dict):
            continue
        last_date = None
        for s in ts.get("sources") or []:
            if isinstance(s, dict) and s.get("last_date"):
                last_date = max(last_date or "", s["last_date"])
        lc = _num(ts.get("last_close"))
        if last_date and lc:
            tickers.setdefault(t, {})[last_date] = lc
    track["as_of"] = datetime.now(KST).isoformat(timespec="seconds")
    track["exited_tickers"] = sorted(exited)
    return track


def aggregate(trips: list[dict], prices: dict, policy: dict) -> tuple[dict, dict]:
    by_rule: dict[str, dict] = {}
    wins, losses, holds = [], [], []
    for tr in trips:
        marks = post_exit_marks(tr, prices)
        tr["post_exit"] = marks
        r = by_rule.setdefault(tr["exit_rule"], {
            "n": 0, "realized_pnl_sum": 0.0, "hold_days": [],
            "post_exit_t1_forgone_sum": 0.0, "t1_n": 0,
            "post_exit_t5_forgone_sum": 0.0, "t5_n": 0,
        })
        r["n"] += 1
        pnl = tr.get("realized_pnl") or 0.0
        r["realized_pnl_sum"] += pnl
        if tr.get("hold_days") is not None:
            r["hold_days"].append(tr["hold_days"])
            holds.append(tr["hold_days"])
        for label in ("t1", "t5"):
            m = marks.get(label)
            if m:
                r[f"post_exit_{label}_forgone_sum"] += m["forgone_krw"]
                r[f"{label}_n"] += 1
        (wins if pnl > 0 else losses).append(pnl)
    for r in by_rule.values():
        r["avg_hold_days"] = round(sum(r["hold_days"]) / len(r["hold_days"]), 1) if r["hold_days"] else None
        del r["hold_days"]
        r["realized_pnl_sum"] = round(r["realized_pnl_sum"], 0)
        r["post_exit_t1_forgone_sum"] = round(r["post_exit_t1_forgone_sum"], 0)
        r["post_exit_t5_forgone_sum"] = round(r["post_exit_t5_forgone_sum"], 0)

    gross_win, gross_loss = sum(wins), sum(losses)
    cost = policy.get("trading_cost", {})
    buy_rate = (float(cost.get("slippage_pct", 0.2)) + float(cost.get("commission_pct", 0.015))) / 100
    sell_rate = buy_rate + float(cost.get("tax_pct", 0.18)) / 100
    buy_turnover = sum(tr["entry_cost"] for tr in trips)
    sell_turnover = sum(tr["exit_price"] * tr["shares"] for tr in trips)
    account = {
        "closed_exits": len(trips),
        "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trips) * 100, 1) if trips else None,
        "gross_profit": round(gross_win, 0), "gross_loss": round(gross_loss, 0),
        "net_realized": round(gross_win + gross_loss, 0),
        "profit_factor": round(gross_win / abs(gross_loss), 2) if gross_loss else None,
        "expectancy_per_exit": round((gross_win + gross_loss) / len(trips), 0) if trips else None,
        "median_hold_days": median(holds) if holds else None,
        "turnover_krw": round(buy_turnover + sell_turnover, 0),
        "friction_est_krw": round(buy_turnover * buy_rate + sell_turnover * sell_rate, 0),
        "friction_note": "추정 — policy.trading_cost 요율 × 회전대금(라운드트립 기준, 미청산 매수 제외)",
    }
    return by_rule, account


def render_markdown(out: dict) -> str:
    a, b = out["account"], out["benchmarks"]
    lines = [
        "### 룰 채점 (rule_attribution)",
        f"- 청산 {a['closed_exits']}건 (승 {a['wins']}/패 {a['losses']}, 승률 {a['win_rate_pct']}%) · "
        f"PF {a['profit_factor']} · expectancy {a['expectancy_per_exit']:+,.0f}원/건 · "
        f"보유 중앙값 {a['median_hold_days']}일",
        f"- 순실현 {a['net_realized']:+,.0f}원 · 회전대금 {a['turnover_krw']:,.0f}원 · "
        f"마찰비용 ≈{a['friction_est_krw']:,.0f}원",
        f"- 벤치마크: KOSPI {b['kospi'].get('pct')}% · 진입종목 단순보유(동일가중) "
        f"{b['buy_and_hold'].get('equal_weight_pct')}% · 실제 계좌 {b.get('actual_cumulative_pct')}%",
        f"- blocked-day: {out['blocked_day']['blocked_days']}/{out['blocked_day']['days_with_candidates']}일 "
        f"({out['blocked_day']['blocked_day_rate_pct']}%)",
        "",
        "| 청산 룰 | n | 실현손익 | t1 일실 | t5 일실 | 평균보유 |",
        "|---|---|---|---|---|---|",
    ]
    for rule, r in sorted(out["by_rule"].items()):
        lines.append(
            f"| {rule} | {r['n']} | {r['realized_pnl_sum']:+,.0f} | "
            f"{r['post_exit_t1_forgone_sum']:+,.0f} ({r['t1_n']}) | "
            f"{r['post_exit_t5_forgone_sum']:+,.0f} ({r['t5_n']}) | {r['avg_hold_days']}일 |"
        )
    lines.append("")
    lines.append("> t1/t5 일실(forgone) = (청산 후 N번째 관측 종가 − 청산가) × 매도주수. "
                 "양수 = 조기청산 비용(팔고 올랐다), 음수 = 청산이 손실 방어.")
    mismatches = [tr for tr in out["round_trips"] if tr.get("pnl_mismatch")]
    if mismatches:
        lines.append("")
        lines.append("#### ⚠️ 원장 불일치 (trade_log realized_pnl ≠ 체결가 재계산)")
        for tr in mismatches:
            lines.append(
                f"- {tr['exit_date']} {tr['name']}({tr['ticker']}) {tr['exit_rule']}: "
                f"로그 {tr['logged_realized_pnl']:+,.0f}원 vs 재계산 {tr['realized_pnl']:+,.0f}원 "
                f"(차이 {tr['logged_realized_pnl'] - tr['realized_pnl']:+,.0f}원) — "
                f"집계는 재계산값 사용. trade_log 라인 점검 필요(누적치 혼입/스키마 드리프트 의심)."
            )
    return "\n".join(lines)


def main() -> int:
    entries = load_trade_log()
    snapshot = load_json(ROOT / "state" / "market_snapshot.json", {})
    policy = load_json(ROOT / "config" / "policy.json", {})
    portfolio = load_json(ROOT / "config" / "portfolio.json", {})
    track = load_json(TRACK_PATH, {})

    trips, open_lots = build_round_trips(entries)
    track = update_exit_tracking(track, trips, snapshot)
    prices = collect_price_observations(entries, snapshot, track)
    by_rule, account = aggregate(trips, prices, policy)

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "round_trips": trips,
        "open_lots": open_lots,
        "by_rule": by_rule,
        "account": account,
        "benchmarks": {
            "kospi": kospi_window(entries),
            "buy_and_hold": buy_and_hold(entries, prices),
            "actual_cumulative_pct": portfolio.get("cumulative_return_pct"),
        },
        "blocked_day": blocked_days(entries),
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRACK_PATH.write_text(json.dumps(track, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(render_markdown(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
