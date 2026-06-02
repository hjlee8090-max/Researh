#!/usr/bin/env python3
"""trade_log 의 모든 체결(BUY/SELL 계열)을 CI 에서 하드 검증한다 — (1) price_source(출처) + (2) 장중 시각(세션).

pre_trade_gate·market_hours(프롬프트 의존)를 우회해 묵은/미검증 가격이나 장중 시간 밖에서 체결되는 것을
막는 '마지막 하드 안전장치'. 프롬프트가 무시돼도 이 게이트가 비정상 종료(exit 1)하면:
  - build_and_notify.yml 의 audit 스텝(audit_pipeline.py) 실패 → main push 빌드 FAIL(가시적)
  - auto_merge_routines.yml 의 게이트 스텝 실패 → 세션 브랜치 routine 커밋이 main 에 병합되지 못함(격리)

(1) trade provenance(policy.price_data_quality.trade_provenance_gate):
  - price_source_required_since(기본 2026-06-02) 이후 ts 의 booking 만 검사(이전은 grandfather).
  - price_source ∈ allowed_price_sources(snapshot_fresh | web_verified). web_verified 면 verify_url 필수.

(2) trade timing(policy.market_hours.trade_timing_gate):
  - enforced_since(기본 2026-06-02) 이후 ts 의 booking 만 검사(이전은 grandfather).
  - 체결 ts 의 시각이 정규장(regular_session 09:00~15:30, 경계 포함) 밖이면 위반.
  - 단 execution_venue ∈ allowed_eod_venues(closing_auction) 인 SELL 계열(EOD 종가 청산)은 예외.
  - BUY(신규/추가매수)는 정규장 밖이면 예외 없이 위반(마감 후 신규진입 금지).

EOD_EVAL/OPEN_CHECK/HOLD 등 비체결 액션은 두 검사 모두 대상 아님(BUY/SELL 계열만 — reconcile_portfolio 분류 재사용).
표준 라이브러리만. 출력: stdout JSON + exit code(0=통과, 1=위반).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import reconcile_portfolio as rp  # 같은 scripts/ — BUY/SELL 분류(_is_buy/_is_sell)·load_trade_log 재사용

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load_json(rel: str, default=None):
    p = ROOT / rel
    if not p.exists():
        return default if default is not None else {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default if default is not None else {}


def find_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    since = str(gate_cfg.get("price_source_required_since", "2026-06-02"))[:10]
    allowed = set(gate_cfg.get("allowed_price_sources", ["snapshot_fresh", "web_verified"]))
    need_url = set(gate_cfg.get("require_verify_url_for", ["web_verified"]))
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        action = e.get("action")
        if not (rp._is_buy(action) or rp._is_sell(action)):
            continue  # 비체결 액션(EOD_EVAL/OPEN_CHECK/HOLD 등)은 대상 아님
        ts = str(e.get("ts", ""))
        if ts[:10] < since:
            continue  # grandfather — 게이트 도입 이전 체결
        checked += 1
        tag = f"{ts} {action} {e.get('ticker')}"
        ps = e.get("price_source")
        if ps not in allowed:
            violations.append(
                f"{tag}: price_source 누락/유효하지 않음(={ps!r}) — 허용 {sorted(allowed)}"
            )
            continue
        if ps in need_url and not e.get("verify_url"):
            violations.append(f"{tag}: price_source=web_verified 인데 verify_url 없음")
    return violations, checked, since


def _hhmm_to_min(value: str, fallback: int) -> int:
    try:
        hh, mm = str(value).split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return fallback


def _ts_minute_of_day(ts: str) -> int | None:
    """ts(ISO)의 KST 시각을 분(0~1439)으로. 파싱 실패 시 None."""
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    dt = dt.astimezone(KST)
    return dt.hour * 60 + dt.minute


def find_timing_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    """체결 ts 시각이 정규장 밖이면 위반(EOD closing_auction SELL 은 예외). policy.market_hours.trade_timing_gate."""
    since = str(gate_cfg.get("enforced_since", "2026-06-02"))[:10]
    rs = gate_cfg.get("regular_session", {}) if isinstance(gate_cfg.get("regular_session"), dict) else {}
    open_min = _hhmm_to_min(rs.get("open", "09:00"), 9 * 60)
    close_min = _hhmm_to_min(rs.get("close", "15:30"), 15 * 60 + 30)
    allowed_eod = set(gate_cfg.get("allowed_eod_venues", ["closing_auction"]))
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        action = e.get("action")
        is_buy = rp._is_buy(action)
        is_sell = rp._is_sell(action)
        if not (is_buy or is_sell):
            continue  # 비체결 액션은 대상 아님
        ts = str(e.get("ts", ""))
        if ts[:10] < since:
            continue  # grandfather — 게이트 도입 이전 체결
        checked += 1
        tag = f"{ts} {action} {e.get('ticker')}"
        minute = _ts_minute_of_day(ts)
        if minute is None:
            violations.append(f"[장중시간] {tag}: ts 파싱 불가 — 시각 검증 불가")
            continue
        if open_min <= minute <= close_min:
            continue  # 정규장 시각 — OK
        # 정규장(09:00~15:30) 밖 체결
        if is_buy:
            violations.append(f"[장중시간] {tag}: 정규장(09:00~15:30) 밖 신규/추가매수 — 마감 후 진입 금지")
            continue
        venue = e.get("execution_venue")
        if venue in allowed_eod:
            continue  # EOD 종가 청산(closing_auction) 예외 허용
        violations.append(
            f"[장중시간] {tag}: 정규장 밖 체결인데 execution_venue 가 {sorted(allowed_eod)} 가 아님(={venue!r}) "
            "— 종가 청산이면 ts=15:30 + execution_venue=closing_auction 로 기록"
        )
    return violations, checked, since


def main() -> int:
    policy = load_json("config/policy.json", {})
    pdq = policy.get("price_data_quality", {}) if isinstance(policy, dict) else {}
    mh = policy.get("market_hours", {}) if isinstance(policy, dict) else {}
    prov_gate = pdq.get("trade_provenance_gate", {}) if isinstance(pdq.get("trade_provenance_gate"), dict) else {}
    timing_gate = mh.get("trade_timing_gate", {}) if isinstance(mh.get("trade_timing_gate"), dict) else {}

    entries = rp.load_trade_log()

    prov_violations: list[str] = []
    prov_checked = 0
    prov_since = None
    if prov_gate.get("enabled", True):
        prov_violations, prov_checked, prov_since = find_violations(entries, prov_gate)

    timing_violations: list[str] = []
    timing_checked = 0
    timing_since = None
    if timing_gate.get("enabled", True):
        timing_violations, timing_checked, timing_since = find_timing_violations(entries, timing_gate)

    violations = prov_violations + timing_violations  # audit_pipeline 이 읽는 통합 목록(둘 중 하나라도 FAIL)
    out = {
        "enabled": True,
        "price_source_required_since": prov_since,
        "timing_enforced_since": timing_since,
        "checked": prov_checked,
        "timing_checked": timing_checked,
        "provenance_violations": prov_violations,
        "timing_violations": timing_violations,
        "violations": violations,
        "ok": not violations,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))  # stdout = 순수 JSON (audit 가 subprocess 로 파싱)
    summary = (
        f"TRADE_LOG_GATE=FAIL (provenance {len(prov_violations)} + timing {len(timing_violations)} violation) "
        "— price_source 누락/장중 시간 밖 booking 차단"
        if violations
        else f"TRADE_LOG_GATE=PASS (provenance booking {prov_checked}건 + timing {timing_checked}건 검증)"
    )
    print(summary, file=sys.stderr)  # 사람용 요약은 stderr 로(stdout JSON 오염 방지)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
