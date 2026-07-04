#!/usr/bin/env python3
"""보유 종목 청산 레벨(트레일링 1차선·샹들리에·손절·목표)의 단일 소스 산출 (의존성 0).

배경 (docs/plan_hourly_report_gap_fix.md Phase 3-5 · 진단 I8·I10):
- 트레일링 1차선을 routine 이 손계산·전 리포트 이월하다 ATR 배수 오기입(239,495원)이
  7/1 18시→7/2 09시→7/2 15시 세 리포트에 유통된 뒤 EOD 에야 222,117원으로 정정됐다
  (6/18 동일 계열 재발). 실행 수치는 이 스크립트 산출값만 인용한다 — 손계산·이월 금지.

공식 (policy.risk.trailing_stop v2.14 산문 규칙의 기계 사본 — 정책 개정 시 함께 갱신):
- 1차 부분익절선 = 최고 종가 × (1 − max(3.0, 1.5×ATR%)/100)  → 이탈 시 50% 부분익절
- 잔여 샹들리에  = 최고 종가 × (1 − 2.0×ATR%/100)             → 이탈 시 잔여 전량 청산
- 활성화: 목표 진행률(최고 종가 기준) ≥ activate_at_target_progress_pct
  또는 portfolio 포지션의 trailing_activated=true

입력: config/portfolio.json(보유·진입/손절/목표·trailing_activated),
      state/exit_tracking.json(일별 종가 → 진입 이후 최고 종가),
      state/market_snapshot.json(volatility.atr_pct·last_close)
출력: state/exit_levels.json
검증: --selftest 가 2026-07-02 EOD 정정 사례(최고 263,500·ATR 10.47% → 222,117/208,323)를 재현한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# policy.risk.trailing_stop v2.14 — first_trail_rule/residual_trail_rule 산문의 수치 사본
FLOOR_PCT = 3.0
FIRST_MULT = 1.5
RESID_MULT = 2.0
DEFAULT_ACTIVATE_PCT = 70.0  # activate_at_target_progress_pct 폴백


def trail_levels(highest_close: float, atr_pct: float) -> tuple[int, int]:
    """(1차 부분익절선, 잔여 샹들리에) — 원 단위 반올림."""
    first_width = max(FLOOR_PCT, FIRST_MULT * atr_pct)
    first = round(highest_close * (1 - first_width / 100))
    residual = round(highest_close * (1 - RESID_MULT * atr_pct / 100))
    return int(first), int(residual)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="청산 레벨 단일 소스 산출")
    parser.add_argument("--selftest", action="store_true", help="7/2 정정 사례 재현 검증")
    args = parser.parse_args()

    if args.selftest:
        first, residual = trail_levels(263_500, 10.47)
        ok = (first, residual) == (222_117, 208_323)
        print(json.dumps({
            "case": "2026-07-02 EOD 정정(LS ELECTRIC) 재현",
            "input": {"highest_close": 263_500, "atr_pct": 10.47},
            "expected": [222_117, 208_323],
            "got": [first, residual],
            "ok": ok,
        }, ensure_ascii=False))
        return 0 if ok else 1

    portfolio = load_json(ROOT / "config" / "portfolio.json") or {}
    tracking = (load_json(ROOT / "state" / "exit_tracking.json") or {}).get("tickers", {})
    snapshot = (load_json(ROOT / "state" / "market_snapshot.json") or {}).get("tickers", {})
    policy = load_json(ROOT / "config" / "policy.json") or {}
    activate_pct = (
        policy.get("risk", {}).get("trailing_stop", {}).get("activate_at_target_progress_pct")
        or DEFAULT_ACTIVATE_PCT
    )

    out: dict[str, dict] = {}
    for p in portfolio.get("positions", []):
        if not isinstance(p, dict) or not p.get("shares"):
            continue
        ticker = str(p.get("ticker", ""))
        snap = snapshot.get(ticker, {}) if isinstance(snapshot, dict) else {}
        entry = p.get("entry_price")
        target = p.get("target_price")
        stop = p.get("stop_price")
        opened = str(p.get("opened", ""))[:10]

        # 진입 이후 최고 종가 — exit_tracking(EOD 마크)과 snapshot five_day_history 를
        # 날짜 기준 합집합해 산출한다. exit_tracking 이 신규 진입 종목을 아직 커버하지
        # 못하는 공백(실측: 6/30 진입분 미등재)을 five_day_history 가 메운다.
        closes: dict[str, float] = {}
        raw = tracking.get(ticker, {}) if isinstance(tracking, dict) else {}
        if isinstance(raw, dict):
            for d, c in raw.items():
                if isinstance(c, (int, float)):
                    closes[str(d)] = float(c)
        for bar in snap.get("five_day_history") or []:
            if isinstance(bar, dict) and bar.get("date") and isinstance(bar.get("close"), (int, float)):
                closes.setdefault(str(bar["date"]), float(bar["close"]))
        since_entry = {d: c for d, c in closes.items() if not opened or d >= opened}
        highest_close = None
        highest_date = None
        source = "exit_tracking ∪ five_day_history"
        if since_entry:
            highest_date = max(since_entry, key=lambda d: since_entry[d])
            highest_close = float(since_entry[highest_date])
        elif isinstance(snap.get("last_close"), (int, float)):
            highest_close = float(snap["last_close"])
            source = "market_snapshot.last_close (일별 종가 이력 결측 — 강등)"

        atr_pct = None
        vol = snap.get("volatility")
        if isinstance(vol, dict) and isinstance(vol.get("atr_pct"), (int, float)):
            atr_pct = float(vol["atr_pct"])

        progress = None
        if (
            isinstance(entry, (int, float)) and isinstance(target, (int, float))
            and isinstance(highest_close, (int, float)) and target > entry
        ):
            progress = round((highest_close - entry) / (target - entry) * 100, 1)
        activated = bool(p.get("trailing_activated")) or (
            isinstance(progress, (int, float)) and progress >= activate_pct
        )

        entry_out: dict = {
            "name": p.get("name"),
            "entry_price": entry,
            "stop_price": stop,
            "target_price": target,
            "last_close": snap.get("last_close"),
            "highest_close": highest_close,
            "highest_close_date": highest_date,
            "highest_close_source": source,
            "atr_pct": atr_pct,
            "target_progress_pct": progress,
            "trailing_activated": activated,
        }
        if isinstance(highest_close, (int, float)) and isinstance(atr_pct, (int, float)):
            first, residual = trail_levels(highest_close, atr_pct)
            entry_out["trailing_first_level"] = first
            entry_out["trailing_residual_level"] = residual
        else:
            entry_out["note"] = "최고 종가 또는 ATR 결측 — 트레일 레벨 산출 불가(리포트에 결측 명기)"
        out[ticker] = entry_out

    payload = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "policy_ref": "policy.risk.trailing_stop (v2.14) — 이 파일 값만 인용, 손계산·전 리포트 이월 금지",
        "formula": {
            "trailing_first_level": "최고종가 × (1 − max(3.0, 1.5×ATR%)/100) — 이탈 시 50% 부분익절",
            "trailing_residual_level": "최고종가 × (1 − 2.0×ATR%/100) — 이탈 시 잔여 전량",
            "activation": f"목표 진행률 ≥ {activate_pct}% 또는 포지션 trailing_activated",
        },
        "tickers": out,
    }
    dest = ROOT / "state" / "exit_levels.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(dest.relative_to(ROOT)), "tickers": len(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
