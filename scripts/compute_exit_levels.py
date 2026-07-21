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

v2.24 (2026-07-21) — 추정 기준선 병기 + 보유측 재검토 게이트 (policy.reward_risk_management.holding_estimate_review):
- 매수측 estimate_gate(기대수익<0 신규진입 차단)의 보유측 대응물. 보유 종목의 A/B 등급 추정
  기대수익이 임계(0%) 미만으로 target_estimate_log 기준 2회 연속이면 tickers.<t>.estimate 에
  review_required=true 를 표면화한다 — 18시 §2-2 가 (a)목표가 재조정/(b)손절 상향/(c)부분 익절
  중 택1 을 의무 결정(자동 청산·목표가 자동 변경 아님 — 참고 레이어 원칙 불변).
- 부호·지속성 신호만 쓴다: 추정 수치는 상방 낙관 편향(estimate_scorecard 5td 중앙오차
  -10.4%p)이라 목표가에 이식하지 않는다. 등급 C·결측·24h stale 은 게이트 미적용(결측 래칫 방지).
- 배경 실측(2026-07-20): 한미반도체 운용 목표 332,696 vs 추정 210,300(-5.3%) 인데 보유측은
  무반응 — 신규였다면 estimate_gate 차단인 상태가 보유에선 어떤 룰도 발동하지 않았다.

입력: config/portfolio.json(보유·진입/손절/목표·trailing_activated),
      state/exit_tracking.json(일별 종가 → 진입 이후 최고 종가),
      state/market_snapshot.json(volatility.atr_pct·last_close),
      state/target_estimate.json + state/target_estimate_log.jsonl(추정 기준선·연속음수 streak),
      config/policy.json(risk.trailing_stop·reward_risk_management.holding_estimate_review)
출력: state/exit_levels.json
검증: --selftest 가 2026-07-02 EOD 정정 사례(최고 263,500·ATR 10.47% → 222,117/208,323)와
      v2.24 streak 판정(연속/등급 이탈/기록 부재)을 재현한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
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


def read_estimate_log_tail(path: Path, max_records: int = 8) -> list[dict]:
    """target_estimate_log.jsonl 마지막 max_records 행 파싱(오래된 것 → 최신 순).

    streak 판정에는 최근 몇 회만 필요하다 — 원장 전체(수 MB)를 파싱하지 않는다.
    """
    if not path.exists():
        return []
    tail: deque[str] = deque(maxlen=max_records)
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    tail.append(line)
    except OSError:
        return []
    out: list[dict] = []
    for line in tail:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def negative_streak(records: list[dict], ticker: str, threshold: float, grades: set[str]) -> int:
    """최신 기록부터 거꾸로 'A/B 등급 + 기대수익 < threshold' 가 몇 회 연속인지 센다.

    기록에 종목이 없거나 등급·기대수익이 조건 밖이면 거기서 끊는다(보수 —
    등급 강등·결측이 streak 를 잇는 래칫 방지, policy.missing_data_rule).
    """
    streak = 0
    for rec in reversed(records):
        est = None
        for e in rec.get("estimates", []) or []:
            if isinstance(e, dict) and e.get("ticker") == ticker:
                est = e
                break
        ret = est.get("expected_return_pct") if isinstance(est, dict) else None
        if (
            isinstance(est, dict) and est.get("grade") in grades
            and isinstance(ret, (int, float)) and ret < threshold
        ):
            streak += 1
        else:
            break
    return streak


def build_estimate_review(
    est: dict, est_as_of: str | None, est_age_h: float | None,
    target, ticker: str, records: list[dict], cfg: dict,
) -> dict:
    """보유 종목 청산 수치 옆에 추정 기준선을 병기하고 재검토 의무 여부를 판정한다 (v2.24).

    판정은 부호·지속성만 쓴다 — 추정 수치를 목표가로 이식하지 않는다(낙관 편향).
    """
    ret = est.get("expected_return_pct")
    grade = est.get("grade")
    estimate = est.get("estimate")
    gap_pct = None
    if isinstance(target, (int, float)) and isinstance(estimate, (int, float)) and estimate > 0:
        gap_pct = round((target / estimate - 1.0) * 100.0, 1)

    threshold = float(cfg.get("trigger_if_expected_return_below_pct", 0.0))
    grades = set(cfg.get("allowed_grades") or ["A", "B"])
    need = max(1, int(cfg.get("consecutive_reports", 2)))
    max_age = float(cfg.get("max_age_hours", 24))
    streak = negative_streak(records, ticker, threshold, grades)

    fresh = est_age_h is not None and est_age_h <= max_age
    qualifies_now = grade in grades and isinstance(ret, (int, float)) and ret < threshold
    review = bool(cfg.get("enabled")) and fresh and qualifies_now and streak >= need

    block: dict = {
        "estimate": estimate,
        "expected_return_pct": ret,
        "grade": grade,
        "as_of": est_as_of,
        "target_vs_estimate_gap_pct": gap_pct,
        "negative_streak": streak,
        "review_required": review,
    }
    if review:
        block["review_reason"] = (
            f"추정 기대수익 {ret:+.1f}% < {threshold:.0f}% 가 {streak}회 연속(등급 {grade}) — "
            "18시 §2-2 재조정 의무: (a)목표가 재조정 (b)손절 상향(트레일링 강화) (c)부분 익절 중 택1"
            " (holding_estimate_review — 자동 청산 아님)"
        )
    elif bool(cfg.get("enabled")) and qualifies_now and not fresh:
        block["note"] = "추정 stale(>max_age_hours) — 재검토 게이트 보류(결측 래칫 방지)"
    return block


def main() -> int:
    parser = argparse.ArgumentParser(description="청산 레벨 단일 소스 산출")
    parser.add_argument("--selftest", action="store_true", help="7/2 정정 사례 재현 검증")
    args = parser.parse_args()

    if args.selftest:
        first, residual = trail_levels(263_500, 10.47)
        ok_trail = (first, residual) == (222_117, 208_323)
        # v2.24 — 보유측 추정 재검토 streak 판정 (합성 로그: 오래된 것 → 최신 순)
        recs = [
            {"estimates": [{"ticker": "042700", "grade": "B", "expected_return_pct": -4.9}]},
            {"estimates": [{"ticker": "042700", "grade": "B", "expected_return_pct": -5.3}]},
        ]
        got_streak = (
            negative_streak(recs, "042700", 0.0, {"A", "B"}),                # 2회 연속 음수 → 2
            negative_streak(recs + [{"estimates": [{"ticker": "042700", "grade": "C",
                "expected_return_pct": -9.0}]}], "042700", 0.0, {"A", "B"}),  # 최신이 C 등급 → 끊김 0
            negative_streak(recs, "005930", 0.0, {"A", "B"}),                # 기록 부재 → 0
        )
        ok_streak = got_streak == (2, 0, 0)
        print(json.dumps({
            "case_trail": "2026-07-02 EOD 정정(LS ELECTRIC) 재현",
            "input": {"highest_close": 263_500, "atr_pct": 10.47},
            "expected": [222_117, 208_323],
            "got": [first, residual],
            "ok": ok_trail,
            "case_estimate_streak": "v2.24 연속음수/등급이탈/기록부재 판정",
            "expected_streak": [2, 0, 0],
            "got_streak": list(got_streak),
            "ok_streak": ok_streak,
        }, ensure_ascii=False))
        return 0 if (ok_trail and ok_streak) else 1

    portfolio = load_json(ROOT / "config" / "portfolio.json") or {}
    tracking = (load_json(ROOT / "state" / "exit_tracking.json") or {}).get("tickers", {})
    snapshot = (load_json(ROOT / "state" / "market_snapshot.json") or {}).get("tickers", {})
    policy = load_json(ROOT / "config" / "policy.json") or {}
    activate_pct = (
        policy.get("risk", {}).get("trailing_stop", {}).get("activate_at_target_progress_pct")
        or DEFAULT_ACTIVATE_PCT
    )

    # v2.24 — 추정 기준선(참고 레이어) 병기 + 보유측 재검토 게이트 입력
    her_cfg = (policy.get("reward_risk_management", {}) or {}).get("holding_estimate_review", {})
    her_cfg = her_cfg if isinstance(her_cfg, dict) else {}
    te = load_json(ROOT / "state" / "target_estimate.json") or {}
    est_map = {
        e["ticker"]: e for e in (te.get("estimates", []) or [])
        if isinstance(e, dict) and e.get("ticker")
    }
    est_as_of = te.get("as_of") if isinstance(te.get("as_of"), str) else None
    est_age_h = None
    if est_as_of:
        try:
            est_age_h = (datetime.now(KST) - datetime.fromisoformat(est_as_of)).total_seconds() / 3600
        except ValueError:
            pass
    est_records = read_estimate_log_tail(ROOT / "state" / "target_estimate_log.jsonl")

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

        # v2.24 — 추정 기준선 병기(있을 때만) + review_required 판정. 추정 결측은 키 자체를
        # 만들지 않는다(결측 래칫 방지 — estimate_gate 동형).
        est = est_map.get(ticker)
        if isinstance(est, dict):
            entry_out["estimate"] = build_estimate_review(
                est, est_as_of, est_age_h, target, ticker, est_records, her_cfg,
            )
        out[ticker] = entry_out

    payload = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "policy_ref": "policy.risk.trailing_stop (v2.14) — 이 파일 값만 인용, 손계산·전 리포트 이월 금지",
        "formula": {
            "trailing_first_level": "최고종가 × (1 − max(3.0, 1.5×ATR%)/100) — 이탈 시 50% 부분익절",
            "trailing_residual_level": "최고종가 × (1 − 2.0×ATR%/100) — 이탈 시 잔여 전량",
            "activation": f"목표 진행률 ≥ {activate_pct}% 또는 포지션 trailing_activated",
        },
        "estimate_layer": {
            "as_of": est_as_of,
            "policy_ref": "policy.reward_risk_management.holding_estimate_review (v2.24) — 매수측 estimate_gate 의 보유측 대응물. 추정은 참고 레이어(목표가·트리거 자동 변경 없음), review_required 는 18시 §2-2 재조정 의무만 발동. 수치 이식 금지(낙관 편향 — estimate_scorecard).",
        },
        "tickers": out,
    }
    dest = ROOT / "state" / "exit_levels.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(dest.relative_to(ROOT)), "tickers": len(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
