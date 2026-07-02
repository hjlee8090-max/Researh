#!/usr/bin/env python3
"""track_ratchet_shadow — 본전 래칫 스톱 그림자 트래커 (v1.0, 관측 전용·체결 없음).

policy.risk.breakeven_ratchet(mode=shadow)의 규칙을 실제 체결 없이 기록만 한다:
보유 종목의 이익이 ATR 단위로 진행되면(steps.when_gain_atr) 손절선을 본전 이상으로
끌어올렸다고 '가정'하고, 그 가상 스톱(래칫 레벨)의 종가 이탈(가상 breach)과
해방 가능 히트(open_risk 감소분)를 일자별로 적재한다. 실제 손절가·트레일링·
orange/red 판정은 어떤 것도 바꾸지 않는다.

근거: reports/2026-07-02-position-management-research.md P1 — 트레일링 활성화(목표진행
70%) 전 구간에서 손절선이 진입가-2×ATR 에 고정된 채 주가만 오르면 open_risk 가 부풀어
히트 예산을 잠근다(7/2 실측 LIG넥스원 1종목 = 예산 42%). 래칫의 실익(heat 재활용·좌측
꼬리 절단) vs 부작용(본전 노이즈 체결 — KB금융 give-back 교훈)을 그림자 채점으로 먼저
검증한 뒤 승격을 심사한다(score_ratchet_shadow.py → sunday_policy_review §1-8).

입력: config/policy.json (risk.breakeven_ratchet·trading_cost),
      config/portfolio.json (positions — entry_price·shares·stop_price·opened),
      state/market_snapshot.json (today_ohlc.close·last_close·volatility.atr14·confidence)
출력: state/ratchet_shadow.json — 포지션별 stage/래칫레벨/일자 히스토리/가상 breach 이벤트
      (멱등 — 같은 가격일자 재실행은 그 날짜 기록을 덮어쓴다. 18시 EOD 실행이 권위,
       다른 슬롯 실행분은 잠정값으로 upsert 되고 마지막 실행이 이긴다)
의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "ratchet_shadow.json"
HISTORY_KEEP = 40  # 포지션별 일자 히스토리 보존 상한 (그림자 관측은 수 주 단위)


def load_json(rel: str, default: Any) -> Any:
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def round_trip_cost_pct(policy: dict) -> float:
    """왕복 거래비용(비율) = 매수(슬리피지+수수료) + 매도(슬리피지+거래세+수수료)."""
    tc = policy.get("trading_cost", {})
    slip = float(tc.get("slippage_pct", 0.2))
    tax = float(tc.get("tax_pct", 0.18))
    comm = float(tc.get("commission_pct", 0.015))
    return (slip + comm + slip + tax + comm) / 100.0


def pick_close(tk: dict) -> tuple[float | None, str | None]:
    """스냅샷 종목 블록에서 (판정용 종가, 가격일자)를 고른다.

    today_ohlc.close 우선(18시 실행 시 확정 종가), 없으면 last_close + 출처 최신 일자.
    """
    ohlc = tk.get("today_ohlc") or {}
    if ohlc.get("close") and ohlc.get("date"):
        return float(ohlc["close"]), str(ohlc["date"])
    close = tk.get("last_close")
    if not close:
        return None, None
    dates = [s.get("last_date") for s in tk.get("sources", []) if s.get("ok") and s.get("last_date")]
    return float(close), (max(dates) if dates else None)


def atr_krw(tk: dict, close: float) -> float | None:
    vol = tk.get("volatility") or {}
    if vol.get("atr14"):
        return float(vol["atr14"])
    if vol.get("atr_pct"):
        return close * float(vol["atr_pct"]) / 100.0
    return None


def level_for(stop_to: str, entry: float, rt_cost: float, atr: float) -> float | None:
    """steps[].stop_to 문자열 → 가상 스톱 레벨 (원). 알 수 없는 값은 None(결측 래칫 방지)."""
    breakeven = entry * (1.0 + rt_cost)
    if stop_to == "entry_plus_costs":
        return breakeven
    if stop_to == "entry_plus_half_atr":
        return breakeven + 0.5 * atr
    return None


def main() -> int:
    policy = load_json("config/policy.json", {})
    cfg = (policy.get("risk") or {}).get("breakeven_ratchet") or {}
    mode = cfg.get("mode", "off")
    if mode == "off" or not cfg:
        print("[ratchet-shadow] policy.risk.breakeven_ratchet 없음 또는 mode=off — 기록 생략")
        return 0

    portfolio = load_json("config/portfolio.json", {})
    snapshot = load_json("state/market_snapshot.json", {})
    tickers = snapshot.get("tickers") or {}
    if not portfolio.get("positions") or not tickers:
        print("[ratchet-shadow] WARN: portfolio.positions 또는 market_snapshot.tickers 결측 — 이번 회차 기록 생략")
        return 0

    steps = sorted(cfg.get("steps", []), key=lambda s: float(s.get("when_gain_atr", 0)))
    rt_cost = round_trip_cost_pct(policy)
    now_kst = datetime.now(KST).isoformat(timespec="seconds")

    state = load_json("state/ratchet_shadow.json", {})
    positions_state: dict[str, dict] = state.get("positions", {})
    seen_keys: set[str] = set()
    daily_freed_total = 0.0
    staged_count = 0
    skipped: list[str] = []
    lines: list[str] = []

    for pos in portfolio["positions"]:
        ticker = str(pos.get("ticker", ""))
        entry = pos.get("entry_price")
        shares = int(pos.get("shares") or 0)
        actual_stop = pos.get("stop_price")
        opened = pos.get("opened") or "unknown"
        if not ticker or not entry or shares <= 0 or not actual_stop:
            skipped.append(f"{ticker}(필드 결측)")
            continue
        tk = tickers.get(ticker)
        if not tk:
            skipped.append(f"{ticker}(스냅샷 없음)")
            continue
        close, price_date = pick_close(tk)
        if not close or not price_date:
            skipped.append(f"{ticker}(가격 결측)")
            continue
        atr = atr_krw(tk, close)
        if not atr or atr <= 0:
            skipped.append(f"{ticker}(ATR 결측)")  # 결측 래칫 방지 — 판정 자체를 생략
            continue

        entry = float(entry)
        actual_stop = float(actual_stop)
        key = f"{ticker}:{opened}"
        seen_keys.add(key)
        rec = positions_state.setdefault(key, {
            "ticker": ticker,
            "name": pos.get("name", ""),
            "entry_price": entry,
            "opened": opened,
            "stage": 0,
            "ratchet_level": None,
            "history": [],
            "breach_events": [],
        })
        rec["shares_latest"] = shares
        rec["actual_stop_latest"] = actual_stop
        rec.pop("closed_detected", None)  # 재보유 감지 시 닫힘 표시 해제

        # ── stage 판정 (종가 기준, 래칫 — stage·레벨은 내려가지 않는다)
        gain = close - entry
        computed_stage = 0
        computed_level: float | None = None
        for i, step in enumerate(steps, start=1):
            if gain >= float(step.get("when_gain_atr", 9e9)) * atr:
                lvl = level_for(str(step.get("stop_to", "")), entry, rt_cost, atr)
                if lvl is not None:
                    computed_stage = i
                    computed_level = lvl
        prev_stage = int(rec.get("stage") or 0)
        prev_level = rec.get("ratchet_level")
        stage = max(prev_stage, computed_stage)
        ratchet_level: float | None = None
        cands = [v for v in (prev_level, computed_level) if v is not None]
        if stage >= 1 and cands:
            ratchet_level = round(max(cands), 2)
        rec["stage"] = stage
        rec["ratchet_level"] = ratchet_level
        if stage >= 1:
            staged_count += 1

        # ── 유효 가상 스톱·해방 가능 heat·가상 breach (실제 체결 없음)
        effective_stop = max(actual_stop, ratchet_level) if ratchet_level else actual_stop
        open_risk_real = shares * max(0.0, close - actual_stop)
        open_risk_shadow = shares * max(0.0, close - effective_stop)
        freed = round(open_risk_real - open_risk_shadow, 2)
        daily_freed_total += freed
        breach = bool(ratchet_level and actual_stop < close < effective_stop)

        row = {
            "date": price_date,
            "close": close,
            "gain_atr": round(gain / atr, 3),
            "stage": stage,
            "ratchet_level": ratchet_level,
            "effective_shadow_stop": round(effective_stop, 2),
            "freed_heat_krw": freed,
            "confidence": tk.get("confidence"),
            "breach": breach,
        }
        hist = [h for h in rec.get("history", []) if h.get("date") != price_date]
        hist.append(row)
        rec["history"] = sorted(hist, key=lambda h: h["date"])[-HISTORY_KEEP:]

        # breach 이벤트: 포지션당 최초 1회, 이후에는 stage 가 올라간 재이탈만 추가 기록
        events = rec.get("breach_events", [])
        same_day = [e for e in events if e.get("date") == price_date]
        if breach and not same_day:
            last_stage = max((int(e.get("stage", 0)) for e in events), default=0)
            if not events or stage > last_stage:
                events.append({
                    "date": price_date,
                    "close": close,
                    "stage": stage,
                    "ratchet_level": ratchet_level,
                    "effective_shadow_stop": round(effective_stop, 2),
                    "actual_stop": actual_stop,
                    "shares": shares,
                    "confidence": tk.get("confidence"),
                })
                rec["breach_events"] = events
        lines.append(
            f"  {ticker} {rec['name']}: close {close:,.0f} / gain {row['gain_atr']:+.2f}×ATR"
            f" / stage {stage}"
            + (f" / 래칫 {ratchet_level:,.0f} / heat 해방 {freed:,.0f}원" if ratchet_level else "")
            + (" / ⚠️ 가상 breach" if breach else "")
        )

    # 더 이상 보유하지 않는 포지션은 닫힘 표시만 하고 보존 (scorer 가 trade_log 와 join)
    for key, rec in positions_state.items():
        if key not in seen_keys and not rec.get("closed_detected"):
            rec["closed_detected"] = now_kst

    breach_total = sum(len(r.get("breach_events", [])) for r in positions_state.values())
    all_dates = {h["date"] for r in positions_state.values() for h in r.get("history", [])}
    out = {
        "as_of": now_kst,
        "mode": mode,
        "params": {
            "basis": cfg.get("basis", "close"),
            "steps": steps,
            "round_trip_cost_pct": round(rt_cost * 100, 4),
        },
        "summary": {
            "tracked": len(seen_keys),
            "staged": staged_count,
            "shadow_trading_days": len(all_dates),
            "breach_events_total": breach_total,
            "freed_heat_krw_latest": round(daily_freed_total, 2),
            "skipped": skipped,
        },
        "positions": positions_state,
        "_note": "관측 전용(mode=shadow) — 실제 손절가·체결·리포트 판단을 바꾸지 않는다. 승격 심사는 score_ratchet_shadow.py → sunday_policy_review §1-8.",
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ratchet-shadow] {len(seen_keys)}종목 기록 (stage≥1: {staged_count}, 누적 breach {breach_total}건, "
          f"관측 {len(all_dates)}거래일, 오늘 해방가능 heat {daily_freed_total:,.0f}원)")
    for ln in lines:
        print(ln)
    if skipped:
        print(f"  스킵: {', '.join(skipped)}")
    print(f"  → {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
