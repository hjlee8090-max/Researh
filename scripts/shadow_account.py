#!/usr/bin/env python3
"""그림자 계좌 — '명세 그대로의 전략'을 결정론적으로 페이퍼 체결해 라이브 계좌와 나란히 기록한다.
(Stage 0 — reports/2026-09-02-pipeline-review.md §6-1 D-2)

왜: 백테스트로 검증된 것은 듀얼모멘텀 바스켓뿐인데, 라이브는 그 위에 LLM 게이트·청산 오버레이를
얹어 운용했고 실제 보유는 바스켓과 달랐다(P1 전략-집행 괴리). "LLM+게이트 레이어가 검증 전략에
더하는가, 빼는가"는 같은 날짜·같은 출발 자본으로 나란히 기록해야만 답할 수 있다.

무엇: price_history.json(레포 커밋본) 만으로 매 실행 시 출발일부터 **전체 경로를 재계산**한다
(상태 파일 누적 없음 → 드리프트·오염 없음, 멱등). 변형(variant) 2종:
  - spec_backtest : backtest_strategy.json.recommended_config (Top10·42거래일 리밸·MA200·60/120) — 검증된 명세
  - spec_live     : policy.momentum_strategy.config (Top6·21거래일·min_score 30) — 라이브가 따른다고 선언한 명세.
                    tracked_only 는 과거 시점의 candidates 를 복원할 수 없어 적용하지 않는다(명시).
두 변형 모두 **오버레이 없음**(하드스톱·트레일링·orange/red·R/R 룰·thesis 무효화 전부 없음).
리밸런스일에만 회전: 자격 이탈 종목 매도, 신규 편입 종목 매수. 유지 종목은 손대지 않는다.

계좌 제약(백테스트와 다른 점 — 이 계좌 크기에서 재현 가능한지 보기 위해 넣는다):
  - 정수주. 종목당 비중 ≤ policy.position_sizing.max_position_weight_pct, 현금 ≥ min_cash_weight_pct.
  - 1주가 종목당 상한을 넘는 초고가주는 제외(momentum_signal.executable_allocation 과 동일 규칙).
  - 거래비용 = policy.trading_cost (매수 슬리피지+수수료, 매도 슬리피지+거래세+수수료).

출발: 기본은 state/policy_freeze.json.since 이하 마지막 거래일에 라이브 equity(portfolio_history)를
현금으로 상속 — 두 곡선이 같은 점에서 출발한다. 참고용으로 라이브 첫 가동일(2026-05-20)·초기자본
5,000,000원 출발 경로도 함께 산출한다(reference — "순수 전략이었다면").

산출: state/shadow_account.json (기계) + state/shadow_account.md (사람, 짧게). 핫패스 아님 — 어떤
프롬프트도 의무 적재하지 않는다. 표준 라이브러리만. 네트워크 0.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_JSON = ROOT / "state" / "shadow_account.json"
OUT_MD = ROOT / "state" / "shadow_account.md"
LIVE_START = "2026-05-20"
LIVE_INITIAL_CAPITAL = 5_000_000


# ── 입력 ─────────────────────────────────────────────────────────────────────
def load_json(rel: str, default=None):
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def load_history():
    d = load_json("state/price_history.json")
    if not d:
        raise SystemExit("state/price_history.json 없음")
    tickers = {}
    for tk, v in d["tickers"].items():
        bars = [b for b in (v.get("bars") or []) if b.get("close")]
        if len(bars) < 200:
            continue
        tickers[tk] = {"name": v.get("name", tk),
                       "series": {b["date"]: float(b["close"]) for b in bars}}
    index_series = {b["date"]: float(b["close"]) for b in d["index"]["bars"] if b.get("close")}
    dates = sorted(index_series)
    return tickers, index_series, dates, d.get("as_of")


def load_costs(policy):
    tc = (policy or {}).get("trading_cost") or {}
    slip = float(tc.get("slippage_pct", 0.2)) / 100
    tax = float(tc.get("tax_pct", 0.18)) / 100
    comm = float(tc.get("commission_pct", 0.015)) / 100
    return {"buy": slip + comm, "sell": slip + tax + comm}


def variants(policy, backtest):
    ps = (policy or {}).get("position_sizing") or {}
    cap_pct = float(ps.get("max_position_weight_pct", 35.0))
    min_cash_pct = float(ps.get("min_cash_weight_pct", 5.0))
    rc = (backtest or {}).get("recommended_config") or {}
    live = ((policy or {}).get("momentum_strategy") or {}).get("config") or {}
    return {
        "spec_backtest": {
            "label": "검증 명세(backtest_strategy recommended_config)",
            "top_n": int(rc.get("top_n", 10)), "rebal_days": int(rc.get("rebal_days", 42)),
            "trend_ma": int(rc.get("trend_ma", 200)), "mom_fast": int(rc.get("mom_fast", 60)),
            "mom_slow": int(rc.get("mom_slow", 120)), "min_score": 0.0,
            "cap_pct": cap_pct, "min_cash_pct": min_cash_pct,
            "note": "오버레이 없음. 정수주·종목당 상한·현금 하한만 계좌 제약으로 적용.",
        },
        "spec_live": {
            "label": "라이브 선언 명세(policy.momentum_strategy.config, tracked_only 미적용)",
            "top_n": int(live.get("top_n", 6)), "rebal_days": int(live.get("rebalance_days", 21)),
            "trend_ma": int(live.get("trend_ma", 200)), "mom_fast": int(live.get("mom_fast_days", 60)),
            "mom_slow": int(live.get("mom_slow_days", 120)), "min_score": float(live.get("min_score", 30.0)),
            "cap_pct": cap_pct, "min_cash_pct": min_cash_pct,
            "note": "오버레이 없음. tracked_only 는 과거 candidates 복원 불가로 미적용(30종목 풀 전체).",
        },
    }


# ── 신호 ─────────────────────────────────────────────────────────────────────
def pct_return(series, dates, i, lookback):
    if i - lookback < 0:
        return None
    a, b = series.get(dates[i]), series.get(dates[i - lookback])
    if not a or not b:
        return None
    return (a / b - 1) * 100


def sma(series, dates, i, window):
    if i - window + 1 < 0:
        return None
    vals = [series.get(dates[j]) for j in range(i - window + 1, i + 1)]
    vals = [v for v in vals if v]
    if len(vals) < window * 0.8:
        return None
    return sum(vals) / len(vals)


def target_basket(tickers, dates, i, cfg):
    """dates[i] 종가 기준 자격 통과 종목을 점수순으로 반환 (top_n 절단은 사이징에서)."""
    scored = []
    for tk, v in tickers.items():
        s = v["series"]
        cur = s.get(dates[i])
        if not cur:
            continue
        mf, ms, ma = pct_return(s, dates, i, cfg["mom_fast"]), pct_return(s, dates, i, cfg["mom_slow"]), sma(s, dates, i, cfg["trend_ma"])
        if mf is None or ms is None or ma is None:
            continue
        score = 0.5 * mf + 0.5 * ms
        if score > 0 and score >= cfg["min_score"] and cur >= ma:
            scored.append({"ticker": tk, "name": v["name"], "score": round(score, 2), "close": cur})
    scored.sort(key=lambda r: -r["score"])
    return scored


# ── 시뮬레이션 ────────────────────────────────────────────────────────────────
def simulate(tickers, index_series, dates, cfg, costs, start_date, capital):
    """start_date(포함) 종가에 capital 현금으로 출발, 마지막 거래일까지 일별 평가."""
    if start_date not in index_series:
        # 출발일이 휴장이면 그 이하 마지막 거래일
        cands = [d for d in dates if d <= start_date]
        if not cands:
            raise SystemExit(f"출발일 {start_date} 이전 거래일 없음")
        start_date = cands[-1]
    i0 = dates.index(start_date)
    cash = float(capital)
    pos = {}       # ticker -> {"shares", "avg_cost"}
    trades = []
    curve = []
    last_price = {}
    costs_paid = 0.0
    turnover = 0.0

    def mark(i):
        d = dates[i]
        val = 0.0
        for tk, p in pos.items():
            px = tickers[tk]["series"].get(d) or last_price.get(tk)
            if px:
                last_price[tk] = px
                val += p["shares"] * px
        return val

    for i in range(i0, len(dates)):
        d = dates[i]
        # 리밸런스 판정(출발일 포함, 이후 rebal_days 마다) — 종가 체결
        if (i - i0) % cfg["rebal_days"] == 0:
            eligible = target_basket(tickers, dates, i, cfg)
            elig_set = {r["ticker"] for r in eligible[:cfg["top_n"]]}
            # 1) 자격 이탈 매도
            for tk in list(pos):
                if tk not in elig_set:
                    px = tickers[tk]["series"].get(d) or last_price.get(tk)
                    if not px:
                        continue
                    sh = pos[tk]["shares"]
                    gross = sh * px
                    fee = gross * costs["sell"]
                    cash += gross - fee
                    costs_paid += fee
                    turnover += gross
                    pnl = gross - fee - sh * pos[tk]["avg_cost"]
                    trades.append({"date": d, "action": "SELL", "ticker": tk, "name": tickers[tk]["name"],
                                   "shares": sh, "price": px, "fee": round(fee), "realized_pnl": round(pnl),
                                   "reason": "rebalance: 자격 이탈(추세/모멘텀/순위)"})
                    del pos[tk]
            # 2) 신규 편입 매수 — 동일가중(고정 분모 top_n), 정수주, 상한·현금 하한
            equity_now = cash + mark(i)
            cap_krw = equity_now * cfg["cap_pct"] / 100
            deployable = equity_now * (1 - cfg["min_cash_pct"] / 100)
            per_name = deployable / cfg["top_n"]
            for r in eligible[:cfg["top_n"]]:
                tk = r["ticker"]
                if tk in pos:
                    continue
                px = r["close"]
                if px > cap_krw:
                    trades.append({"date": d, "action": "SKIP", "ticker": tk, "name": r["name"], "price": px,
                                   "reason": f"1주 {px:,.0f}원 > 종목당 상한 {cap_krw:,.0f}원"})
                    continue
                invested = mark(i)
                room = min(per_name, deployable - invested, cash / (1 + costs["buy"]))
                sh = int(math.floor(room / px))
                while sh > 0 and sh * px > cap_krw:
                    sh -= 1
                if sh <= 0:
                    trades.append({"date": d, "action": "SKIP", "ticker": tk, "name": r["name"], "price": px,
                                   "reason": f"예산 {room:,.0f}원 < 1주"})
                    continue
                gross = sh * px
                fee = gross * costs["buy"]
                cash -= gross + fee
                costs_paid += fee
                turnover += gross
                pos[tk] = {"shares": sh, "avg_cost": (gross + fee) / sh}
                last_price[tk] = px
                trades.append({"date": d, "action": "BUY", "ticker": tk, "name": r["name"], "shares": sh,
                               "price": px, "fee": round(fee), "score": r["score"], "reason": "rebalance: 편입"})
        equity = cash + mark(i)
        curve.append({"date": d, "equity": round(equity), "cash": round(cash),
                      "n_pos": len(pos), "stock_pct": round((equity - cash) / equity * 100, 1) if equity else 0.0})

    final_pos = [{"ticker": tk, "name": tickers[tk]["name"], "shares": p["shares"],
                  "avg_cost": round(p["avg_cost"]), "last": last_price.get(tk),
                  "unrealized_pnl": round(p["shares"] * ((last_price.get(tk) or p["avg_cost"]) - p["avg_cost"]))}
                 for tk, p in pos.items()]
    return {"start_date": start_date, "capital": capital, "curve": curve, "trades": trades,
            "positions": final_pos, "costs_paid": round(costs_paid), "turnover": round(turnover)}


def metrics(curve, index_series):
    if len(curve) < 2:
        return {"trading_days": len(curve), "note": "표본 부족(2거래일 미만)"}
    vals = [c["equity"] for c in curve]
    total = vals[-1] / vals[0] - 1
    rets = [vals[k] / vals[k - 1] - 1 for k in range(1, len(vals))]
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    k0, k1 = index_series.get(curve[0]["date"]), index_series.get(curve[-1]["date"])
    kospi = (k1 / k0 - 1) * 100 if k0 and k1 else None
    avg_stock = sum(c["stock_pct"] for c in curve) / len(curve)
    return {"trading_days": len(vals), "total_return_pct": round(total * 100, 2),
            "sharpe_annualized": round(mean / sd * math.sqrt(252), 2) if sd > 0 else None,
            "max_drawdown_pct": round(mdd * 100, 2), "kospi_pct": round(kospi, 2) if kospi is not None else None,
            "vs_kospi_pp": round(total * 100 - kospi, 2) if kospi is not None else None,
            "avg_stock_pct": round(avg_stock, 1)}


# ── 라이브 대조 ───────────────────────────────────────────────────────────────
def live_equity_by_date():
    out = {}
    p = ROOT / "state" / "portfolio_history.jsonl"
    if not p.exists():
        return out
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        d = str(r.get("date", ""))[:10]
        eq = r.get("equity") or r.get("equity_snapshot")
        if len(d) == 10 and eq:
            out[d] = float(eq)  # 같은 날짜 여러 줄이면 마지막(EOD) 값이 남는다
    return out


def compare_live(curve, live, index_series, live_base=None):
    """live_base: 라이브 출발 자본을 명시할 때(첫 가동일 기준 참고 구간 — 첫날 EOD 값이 아니라 초기자본 5,000,000)."""
    dates = [c["date"] for c in curve]
    common = [d for d in dates if d in live]
    if len(common) < 1:
        return {"note": "라이브 equity 와 겹치는 날짜 없음"}
    d0, d1 = common[0], common[-1]
    sh = {c["date"]: c["equity"] for c in curve}
    shadow_ret = (sh[d1] / sh[d0] - 1) * 100
    live_ret = (live[d1] / (live_base or live[d0]) - 1) * 100
    k0, k1 = index_series.get(d0), index_series.get(d1)
    kospi = (k1 / k0 - 1) * 100 if k0 and k1 else None
    rows = [{"date": d, "shadow": sh[d], "live": round(live[d]), "gap_krw": round(sh[d] - live[d])} for d in common]
    return {"from": d0, "to": d1, "overlap_days": len(common),
            "shadow_pct": round(shadow_ret, 2), "live_pct": round(live_ret, 2),
            "live_minus_shadow_pp": round(live_ret - shadow_ret, 2),
            "kospi_pct": round(kospi, 2) if kospi is not None else None,
            "series": rows}


# ── 실행 ─────────────────────────────────────────────────────────────────────
def resolve_start(dates, live, freeze, arg_start, arg_capital):
    if arg_start:
        start = arg_start
    else:
        since = (freeze or {}).get("since") or datetime.now(KST).strftime("%Y-%m-%d")
        cands = [d for d in dates if d <= since and d in live]
        start = cands[-1] if cands else [d for d in dates if d <= since][-1]
    if arg_capital:
        capital = float(arg_capital)
        basis = "인자 지정"
    elif start in live:
        capital = live[start]
        basis = f"라이브 equity 상속(portfolio_history {start})"
    else:
        capital = float(LIVE_INITIAL_CAPITAL)
        basis = "라이브 초기자본 폴백"
    return start, capital, basis


def write_md(out):
    L = [f"# 그림자 계좌 — {out['as_of'][:16]} KST", "",
         "> `scripts/shadow_account.py` 산출(기계 생성, 매 실행 전체 재계산). 명세 그대로의 듀얼모멘텀을 오버레이 없이 정수주로 페이퍼 체결한 결과를 라이브와 나란히 놓는다. 학습·시뮬레이션 용도.", ""]
    L.append(f"- 출발: **{out['start']['date']}** · 자본 {out['start']['capital']:,.0f}원 ({out['start']['basis']}) · 데이터 {out['data_as_of']}")
    L.append(f"- 정책 동결: {out['freeze_status']}")
    L.append("")
    L.append("## 동결 이후 (Stage 0 본선)")
    L.append("")
    L.append("| 변형 | 거래일 | 수익률 | KOSPI | vs KOSPI | MDD | 평균 주식비중 | 체결 | 비용 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for k, v in out["since_freeze"].items():
        m = v["metrics"]
        L.append(f"| {k} | {m.get('trading_days')} | {m.get('total_return_pct')}% | {m.get('kospi_pct')}% | {m.get('vs_kospi_pp')}%p | {m.get('max_drawdown_pct')}% | {m.get('avg_stock_pct')}% | {v['n_trades']} | {v['costs_paid']:,}원 |")
    L.append("")
    L.append("| 변형 | 라이브 대조 구간 | 그림자 | 라이브 | 라이브−그림자 |")
    L.append("|---|---|---|---|---|")
    for k, v in out["since_freeze"].items():
        c = v["vs_live"]
        if "note" in c:
            L.append(f"| {k} | — | — | — | {c['note']} |")
        else:
            L.append(f"| {k} | {c['from']}~{c['to']} ({c['overlap_days']}일) | {c['shadow_pct']}% | {c['live_pct']}% | **{c['live_minus_shadow_pp']}%p** |")
    L.append("")
    for k, v in out["since_freeze"].items():
        L.append(f"### {k} 현재 보유 ({v['config']['label']})")
        if not v["positions"]:
            L.append("- (없음)")
        for p in v["positions"]:
            L.append(f"- {p['name']}({p['ticker']}) {p['shares']}주 · 평단 {p['avg_cost']:,}원 · 현재 {p['last']:,.0f}원 · 평가손익 {p['unrealized_pnl']:,}원")
        L.append("")
    L.append("## 참고 — 라이브 첫 가동일부터 순수 전략이었다면 (2026-05-20, 5,000,000원)")
    L.append("")
    L.append("| 변형 | 거래일 | 수익률 | KOSPI | vs KOSPI | MDD | 평균 주식비중 | 체결 | 비용 | 라이브 동일구간 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for k, v in out["reference_since_live_start"].items():
        m, c = v["metrics"], v["vs_live"]
        lv = f"{c.get('live_pct')}% (격차 {c.get('live_minus_shadow_pp')}%p)" if "live_pct" in c else "—"
        L.append(f"| {k} | {m.get('trading_days')} | {m.get('total_return_pct')}% | {m.get('kospi_pct')}% | {m.get('vs_kospi_pp')}%p | {m.get('max_drawdown_pct')}% | {m.get('avg_stock_pct')}% | {v['n_trades']} | {v['costs_paid']:,}원 | {lv} |")
    L.append("")
    L.append("주의: 참고 구간은 사후 계산(look-back)이라 Stage 0 판정에 쓰지 않는다. 판정은 동결 이후 구간만.")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="그림자 계좌(명세 그대로의 전략) 페이퍼 체결")
    ap.add_argument("--start", help="출발 거래일(YYYY-MM-DD). 기본: policy_freeze.since 이하 라이브 equity 가 있는 마지막 거래일")
    ap.add_argument("--capital", type=float, help="출발 자본(원). 기본: 출발일 라이브 equity 상속")
    ap.add_argument("--dry-run", action="store_true", help="파일 미기록, 요약만 출력")
    args = ap.parse_args()

    policy = load_json("config/policy.json", {})
    backtest = load_json("state/backtest_strategy.json", {})
    freeze = load_json("state/policy_freeze.json")
    tickers, index_series, dates, data_as_of = load_history()
    costs = load_costs(policy)
    live = live_equity_by_date()
    cfgs = variants(policy, backtest)

    start, capital, basis = resolve_start(dates, live, freeze, args.start, args.capital)
    freeze_status = (f"active since {freeze.get('since')} (baseline v{freeze.get('baseline_version')})"
                     if freeze and freeze.get("active") else "미설정/비활성")

    def run(start_date, cap, live_base=None):
        res = {}
        for key, cfg in cfgs.items():
            sim = simulate(tickers, index_series, dates, cfg, costs, start_date, cap)
            res[key] = {"config": cfg, "start_date": sim["start_date"], "capital": cap,
                        "metrics": metrics(sim["curve"], index_series),
                        "vs_live": compare_live(sim["curve"], live, index_series, live_base),
                        "n_trades": sum(1 for t in sim["trades"] if t["action"] in ("BUY", "SELL")),
                        "costs_paid": sim["costs_paid"], "turnover": sim["turnover"],
                        "positions": sim["positions"], "trades": sim["trades"],
                        "curve": sim["curve"]}
        return res

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "data_as_of": data_as_of,
        "purpose": "Stage 0 — 명세 그대로의 전략(오버레이 없음)을 라이브와 같은 출발점에서 나란히 기록. 판정 기준: reports/2026-09-02-pipeline-review.md §6-2",
        "costs": costs,
        "freeze_status": freeze_status,
        "start": {"date": start, "capital": capital, "basis": basis},
        "since_freeze": run(start, capital),
        "reference_since_live_start": run(LIVE_START, float(LIVE_INITIAL_CAPITAL), float(LIVE_INITIAL_CAPITAL)),
        "caveats": [
            "매 실행 전체 재계산(멱등) — price_history 가 소급 정정되면 곡선도 바뀐다. 판정 시점의 파일을 git 으로 고정할 것.",
            "체결가 = 당일 종가 + policy.trading_cost 슬리피지. 실제 종가 체결 가능성·호가 단위는 반영하지 않는다(낙관 편향 가능).",
            "reference 구간은 사후 계산이라 Stage 0 판정에 쓰지 않는다.",
            "spec_live 는 tracked_only 미적용(과거 candidates 복원 불가) — 라이브 선언 명세와 완전 동일하지 않다.",
        ],
    }
    # reference 구간은 곡선·체결 전문을 빼 파일 크기를 억제(요약만)
    for v in out["reference_since_live_start"].values():
        v["curve"] = v["curve"][-1:]
        v["trades"] = [t for t in v["trades"] if t["action"] != "SKIP"]

    summary = {k: {"days": v["metrics"].get("trading_days"), "ret": v["metrics"].get("total_return_pct"),
                   "vs_kospi": v["metrics"].get("vs_kospi_pp"), "live_minus_shadow": v["vs_live"].get("live_minus_shadow_pp")}
               for k, v in out["since_freeze"].items()}
    print(json.dumps({"start": out["start"], "since_freeze": summary,
                      "reference": {k: v["metrics"] for k, v in out["reference_since_live_start"].items()}},
                     ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_md(out)
    print(f"→ {OUT_JSON.relative_to(ROOT)} ({OUT_JSON.stat().st_size:,}B), {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
