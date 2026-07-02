#!/usr/bin/env python3
"""score_ratchet_shadow — 본전 래칫 스톱 그림자 채점 (v1.0).

track_ratchet_shadow.py 가 적재한 가상 breach(래칫 스톱 종가 이탈) 이벤트를
반사실(counterfactual)로 채점한다 — "래칫이 라이브였다면 그 종가에 팔았을 것"
vs "실제로는 계속 보유했다"의 t+1/t+5 거래일 손익 차이. rule_attribution 의
forgone(기회비용) 채점과 동일 철학: 노이즈 익절이면 래칫의 비용, 이후 더 빠졌으면
래칫의 보호. 추가로 실제 청산(trade_log SELL 계열)과 join 해 "래칫이 실제 청산가보다
높은 레벨에서 먼저 나갔을" 보호액도 계산한다.

sunday_policy_review(일 20시)가 0-E 단계에서 실행해 §1-8 승격 심사의 1차 입력으로 쓴다.
승격 기준은 policy.risk.breakeven_ratchet.promotion_criteria — 표본 미달이면 '채점 보류'
(소표본 과신 금지, score_target_estimates 와 동일 원칙).

입력: state/ratchet_shadow.json, state/price_history.json (반사실 가격),
      state/trade_log.jsonl (실제 청산 join), config/policy.json (promotion_criteria·비용)
출력: state/ratchet_shadow_scorecard.json — 채점 통계 + verdict + 리포트 MD 섹션
의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "ratchet_shadow_scorecard.json"
HORIZONS = [1, 5]  # 거래일


def load_json(rel: str, default: Any) -> Any:
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_trade_log() -> list[dict]:
    p = ROOT / "state" / "trade_log.jsonl"
    rows: list[dict] = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def bars_for(history: dict, ticker: str) -> list[dict]:
    tk = (history.get("tickers") or {}).get(ticker) or {}
    return tk.get("bars") or []


def close_after(bars: list[dict], date: str, n: int) -> tuple[float | None, bool]:
    """date(거래일) 로부터 n 거래일 뒤 종가. (값, 확정여부) — 봉 부족 시 (마지막 가용가, False)."""
    idx = None
    for i, b in enumerate(bars):
        if b.get("date") == date:
            idx = i
            break
        if b.get("date", "") > date:  # date 가 봉에 없으면 직전 봉 기준
            idx = max(0, i - 1)
            break
    if idx is None:
        if not bars or bars[-1].get("date", "") < date:
            return None, False
        idx = len(bars) - 1
    j = idx + n
    if j < len(bars):
        return float(bars[j]["close"]), True
    if bars:
        return float(bars[-1]["close"]), False
    return None, False


def is_sell(action: str) -> bool:
    return action.startswith("SELL") or action == "TRAILING_STOP"


def main() -> int:
    policy = load_json("config/policy.json", {})
    cfg = (policy.get("risk") or {}).get("breakeven_ratchet") or {}
    crit = cfg.get("promotion_criteria") or {}
    min_days = int(crit.get("min_shadow_trading_days", 10))
    min_events = int(crit.get("min_breach_events", 3))

    shadow = load_json("state/ratchet_shadow.json", {})
    positions = shadow.get("positions") or {}
    if not positions:
        print("[ratchet-score] state/ratchet_shadow.json 비어 있음 — track_ratchet_shadow.py 선실행 필요")
        return 0
    history = load_json("state/price_history.json", {})
    trades = load_trade_log()

    tc = policy.get("trading_cost", {})
    sell_cost = (float(tc.get("slippage_pct", 0.2)) + float(tc.get("tax_pct", 0.18))
                 + float(tc.get("commission_pct", 0.015))) / 100.0

    # ── 1) 가상 breach 반사실 채점: 래칫 매도 vs 계속 보유의 t+N 차이
    events_scored: list[dict] = []
    completed: list[dict] = []
    for key, rec in positions.items():
        ticker = rec.get("ticker", "")
        bars = bars_for(history, ticker)
        for ev in rec.get("breach_events", []):
            shares = int(ev.get("shares") or 0)
            b_close = float(ev.get("close") or 0)
            row: dict[str, Any] = {
                "position": key,
                "name": rec.get("name", ""),
                "date": ev.get("date"),
                "stage": ev.get("stage"),
                "breach_close": b_close,
                "shares": shares,
                "shadow_exit_net": round(b_close * (1 - sell_cost) * shares, 0),
                "confidence": ev.get("confidence"),
            }
            final = True
            for n in HORIZONS:
                px, ok = close_after(bars, str(ev.get("date")), n)
                if px is None:
                    row[f"t{n}_close"] = None
                    final = False
                    continue
                # +면 래칫이 노이즈 익절(놓친 상승 = forgone), −면 래칫이 보호(피한 하락)
                row[f"t{n}_close"] = px
                row[f"t{n}_delta_krw"] = round((px - b_close) * shares, 0)
                final = final and ok
            row["final"] = final
            if final and row.get("t5_delta_krw") is not None:
                row["noise_exit"] = row["t5_delta_krw"] > 0
                completed.append(row)
            else:
                row["noise_exit"] = None
            events_scored.append(row)

    n_completed = len(completed)
    forgone = sum(r["t5_delta_krw"] for r in completed if r["t5_delta_krw"] > 0)
    protected = sum(-r["t5_delta_krw"] for r in completed if r["t5_delta_krw"] < 0)
    net_protection = protected - forgone
    noise_rate = (sum(1 for r in completed if r["noise_exit"]) / n_completed) if n_completed else None

    # ── 2) 실제 청산 join: 래칫이 실제 청산가보다 높았던 만큼 = 라이브였다면의 보호액
    shadow_start = min((h["date"] for r in positions.values() for h in r.get("history", [])), default=None)
    protected_vs_real: list[dict] = []
    if shadow_start:
        for t in trades:
            action = str(t.get("action", ""))
            if not is_sell(action):
                continue
            ts_date = str(t.get("ts", ""))[:10]
            if ts_date < shadow_start:
                continue
            ticker = str(t.get("ticker", ""))
            exec_price = t.get("execution_price")
            if not exec_price:
                continue
            for key, rec in positions.items():
                if rec.get("ticker") != ticker:
                    continue
                levels = [h.get("ratchet_level") for h in rec.get("history", [])
                          if h.get("date") <= ts_date and h.get("ratchet_level")]
                if not levels:
                    continue
                lvl = max(levels)
                if lvl > float(exec_price):
                    krw = round((lvl - float(exec_price)) * int(t.get("shares") or 0) * (1 - sell_cost), 0)
                    protected_vs_real.append({
                        "position": key, "exit_date": ts_date, "action": action,
                        "real_exit_price": exec_price, "ratchet_level_before": lvl,
                        "protection_krw": krw,
                    })

    # ── 3) 해방가능 heat 평균 (일자별 합의 평균 — 래칫의 '배치 여력' 실익)
    by_date: dict[str, float] = {}
    for rec in positions.values():
        for h in rec.get("history", []):
            by_date[h["date"]] = by_date.get(h["date"], 0.0) + float(h.get("freed_heat_krw") or 0)
    shadow_days = len(by_date)
    avg_freed = round(sum(by_date.values()) / shadow_days, 0) if shadow_days else 0

    # ── 4) verdict (promotion_criteria 대조 — 소표본 과신 금지)
    if shadow_days < min_days and n_completed < min_events:
        verdict = f"채점 보류 — 표본 부족 (관측 {shadow_days}/{min_days}거래일, 확정 breach {n_completed}/{min_events}건)"
    elif n_completed >= min_events:
        if net_protection >= 0 and (noise_rate is None or noise_rate <= 0.5):
            verdict = "승격 후보 — net 보호 ≥ 0 AND noise율 ≤ 0.5 (sunday_policy_review §1-8 에서 mode=live 전환 상정)"
        elif noise_rate is not None and noise_rate > 0.5:
            verdict = "기각·완화 후보 — 본전 노이즈 체결 과다 (steps.when_gain_atr 상향 또는 기각 상정)"
        else:
            verdict = "관측 연장 — net 보호 음수이나 noise율 낮음 (표본 추가 후 재판정)"
    elif shadow_days >= 20 and n_completed == 0:
        verdict = "승격 상정 가능(무해) — 20거래일+ breach 0건: 노이즈 비용 없이 heat 해방 실익만 확인됨 (관측 병행)"
    else:
        verdict = f"채점 보류 — breach 표본 부족 (확정 {n_completed}/{min_events}건, 관측 {shadow_days}거래일)"

    md = [
        "### 본전 래칫 스톱 그림자 채점 (breakeven_ratchet — mode=shadow)",
        f"- 관측: {shadow_days}거래일 · 추적 {len(positions)}포지션 · 가상 breach {len(events_scored)}건(확정 {n_completed})",
        f"- 반사실 t+5: 보호 {protected:,.0f}원 / 노이즈 익절(forgone) {forgone:,.0f}원 / **net {net_protection:+,.0f}원**"
        + (f" / noise율 {noise_rate:.0%}" if noise_rate is not None else ""),
        f"- 실제 청산 대비 보호액: {sum(p['protection_krw'] for p in protected_vs_real):,.0f}원 ({len(protected_vs_real)}건)",
        f"- 해방가능 heat 일평균: {avg_freed:,.0f}원 (배치 여력 실익 — 히트 잠금 해소분)",
        f"- **판정: {verdict}**",
    ]

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "params": {"min_shadow_trading_days": min_days, "min_breach_events": min_events,
                   "sell_cost_pct": round(sell_cost * 100, 4), "horizons_td": HORIZONS},
        "sample": {"positions": len(positions), "shadow_trading_days": shadow_days,
                   "breach_events": len(events_scored), "breach_completed": n_completed},
        "scoring": {
            "protected_krw_t5": round(protected, 0),
            "forgone_krw_t5": round(forgone, 0),
            "net_protection_krw": round(net_protection, 0),
            "noise_exit_rate": round(noise_rate, 3) if noise_rate is not None else None,
            "protected_vs_real_exits_krw": round(sum(p["protection_krw"] for p in protected_vs_real), 0),
            "avg_freed_heat_krw": avg_freed,
        },
        "events_scored": events_scored,
        "protected_vs_real": protected_vs_real,
        "verdict": verdict,
        "report_section_md": "\n".join(md),
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ratchet-score] breach 확정 {n_completed}건 · net 보호 {net_protection:+,.0f}원"
          + (f" · noise율 {noise_rate:.0%}" if noise_rate is not None else "")
          + f" · heat 해방 일평균 {avg_freed:,.0f}원")
    print(f"  판정: {verdict}")
    print(f"  → {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
