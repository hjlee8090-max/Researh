#!/usr/bin/env python3
"""trade_log 를 CI 에서 하드 검증한다 — (1) price_source(출처) + (2) 장중 시각(세션) + (3) 출처 게재일/재활용 종가.

pre_trade_gate·market_hours·web_verify_guard(프롬프트 의존)를 우회해 묵은/미검증 가격이나 장중 시간 밖에서
체결되거나, 묵은 날짜의 기사를 '오늘 시세'로 도용하는 것을 막는 '마지막 하드 안전장치'. 프롬프트가 무시돼도
이 게이트가 비정상 종료(exit 1)하면:
  - build_and_notify.yml 의 audit 스텝(audit_pipeline.py) 실패 → main push 빌드 FAIL(가시적)
  - auto_merge_routines.yml 의 게이트 스텝 실패 → 세션 브랜치 routine 커밋이 main 에 병합되지 못함(격리)

(1) trade provenance(policy.price_data_quality.trade_provenance_gate) — BUY/SELL 계열만:
  - price_source_required_since(기본 2026-06-02) 이후 ts 의 booking 만 검사(이전은 grandfather).
  - price_source ∈ allowed_price_sources(snapshot_fresh | web_verified). web_verified 면 verify_url 필수.

(2) trade timing(policy.market_hours.trade_timing_gate) — BUY/SELL 계열만:
  - enforced_since(기본 2026-06-02) 이후 ts 의 booking 만 검사(이전은 grandfather).
  - 체결 ts 의 시각이 정규장(regular_session 09:00~15:30, 경계 포함) 밖이면 위반.
  - 단 execution_venue ∈ allowed_eod_venues(closing_auction) 인 SELL 계열(EOD 종가 청산)은 예외.
  - BUY(신규/추가매수)는 정규장 밖이면 예외 없이 위반(마감 후 신규진입 금지).
  (1)(2) 는 EOD_EVAL/OPEN_CHECK/HOLD 등 비체결 액션은 대상 아님(reconcile_portfolio 분류 재사용).

(3) source provenance(policy.price_data_quality.source_provenance_gate) — 모든 액션(OPEN_CHECK 포함):
  - source_date_gate: web_verify 출처(verify_url·web_verify_url·web_verify_source·web_verified 블록의 source)에서
    게재일(YYYY-MM-DD, URL path /YYYY/MM/DD/)을 추출해 가장 최근 날짜가 항목 ts 일자보다
    max_source_age_days 초과로 과거이면 위반. (스냅샷 source_method/last_date 는 stale 허용 → 대상 아님.)
  - recycled_value_gate: 항목이 주장하는 '오늘 KOSPI 종가'(kospi*close 경로, prev/stale/last 제외)가
    직전 일자 종가와 ±match_tolerance_pct 안에서 동일하면 묵은 값 재활용으로 위반(2026-06-08 6/1 MBC 기사 오인).
  enforced_since(기본 2026-06-08) 이후 ts 만 검사(이전은 grandfather).

표준 라이브러리만. 출력: stdout JSON + exit code(0=통과, 1=위반).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
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
        # verify_url 은 routine 에 따라 `verify_url` 또는 `web_verify_url` 로 기록된다(필드명 불일치).
        # 둘 중 하나라도 출처가 있으면 통과시킨다(2026-06-04 삼성전자 매수: 실제 출처 URL 을
        # web_verify_url 에 기록했는데 gate 가 verify_url 만 보고 FAIL → build_and_notify 차단 사례).
        if ps in need_url and not (e.get("verify_url") or e.get("web_verify_url")):
            violations.append(f"{tag}: price_source=web_verified 인데 verify_url/web_verify_url 없음")
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


# ── (3) source provenance — 출처 게재일/재활용 종가 ─────────────────────────────
# trade_log 항목은 중첩 dict/list 다(orange_resolution, kospi_608_web_verified, holdings[] 등).
# 평탄화해서 (dotted-path, value) 로 훑는다.
def _flatten(obj, prefix: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


# YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD (URL path 의 /2026/06/01/ 포함) — 게재일 토큰.
_DATE_RE = re.compile(r"(20\d{2})[\-./](\d{1,2})[\-./](\d{1,2})")


def _extract_dates(text: str) -> list[date]:
    out: list[date] = []
    for y, m, d in _DATE_RE.findall(text):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return out


def _is_web_verify_provenance(path: str) -> bool:
    """web_verify '오늘 라이브가' 주장의 출처 필드인가. 스냅샷 source_method/last_date(=stale 허용)는 제외."""
    last = path.split(".")[-1].split("[")[0].lower()
    if last in ("verify_url", "web_verify_url", "web_verify_source"):
        return True
    # web_verified 블록 안의 source (예: kospi_608_web_verified.source)
    return last == "source" and "web_verif" in path.lower()


def _is_kospi_close_path(path: str) -> bool:
    p = path.lower()
    return "kospi" in p and "close" in p and not any(x in p for x in ("change", "chg", "pct"))


def _is_asserted_today_close(path: str) -> bool:
    """'오늘자' KOSPI 종가 주장 — prev/stale/last/known/ref/history 는 제외(과거 참조)."""
    p = path.lower()
    return _is_kospi_close_path(path) and not any(
        x in p for x in ("prev", "stale", "last", "known", "ref", "history")
    )


def _is_stale_ref_path(path: str) -> bool:
    p = path.lower()
    return "kospi" in p and any(x in p for x in ("stale", "prev", "last", "known"))


def find_source_date_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    """web_verify 출처의 게재일이 항목 ts 일자보다 과거이면 위반. policy...source_provenance_gate.source_date_gate."""
    since = str(gate_cfg.get("enforced_since", "2026-06-08"))[:10]
    sub = gate_cfg.get("source_date_gate", {}) if isinstance(gate_cfg.get("source_date_gate"), dict) else {}
    max_age = int(sub.get("max_source_age_days", 0))
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        ed_str = str(e.get("ts", ""))[:10]
        if ed_str < since:
            continue  # grandfather
        try:
            ed = datetime.strptime(ed_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        for path, val in _flatten(e):
            if not isinstance(val, str) or not _is_web_verify_provenance(path):
                continue
            dates = _extract_dates(val)
            if not dates:
                continue  # URL/문구에 게재일 토큰 없음 — recycled_value_gate 가 보완
            checked += 1
            newest = max(dates)
            if (ed - newest).days > max_age:
                violations.append(
                    f"[출처게재일] {e.get('ts')} {e.get('action')} {e.get('ticker')}: "
                    f"web_verify 출처({path})의 게재일 {newest} 이 리포트 일자 {ed_str} 보다 "
                    f"{(ed - newest).days}일 과거 — 묵은 기사 오인(동일자 출처로 재검증 필요)"
                )
    return violations, checked, since


def find_recycled_value_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    """'오늘 KOSPI 종가' 가 직전 일자 종가와 동일하면 묵은 값 재활용으로 위반(URL 날짜 토큰 없는 출처 보완)."""
    since = str(gate_cfg.get("enforced_since", "2026-06-08"))[:10]
    sub = gate_cfg.get("recycled_value_gate", {}) if isinstance(gate_cfg.get("recycled_value_gate"), dict) else {}
    tol = float(sub.get("match_tolerance_pct", 0.1)) / 100.0
    vmin = float(sub.get("value_min", 1000))
    vmax = float(sub.get("value_max", 20000))

    # 전체 항목에서 (ts일자, 반올림 종가) 수집 — kospi_close·kospi_prev_close 등 명시적 종가 경로만.
    dated_closes: list[tuple[str, int]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        d = str(e.get("ts", ""))[:10]
        for path, val in _flatten(e):
            if isinstance(val, (int, float)) and not isinstance(val, bool) and vmin <= val <= vmax and _is_kospi_close_path(path):
                dated_closes.append((d, round(val)))

    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        ed = str(e.get("ts", ""))[:10]
        if ed < since:
            continue  # grandfather
        asserted: list[tuple[str, float]] = []
        stale_refs: set[int] = set()
        for path, val in _flatten(e):
            if not (isinstance(val, (int, float)) and not isinstance(val, bool) and vmin <= val <= vmax):
                continue
            if _is_asserted_today_close(path):
                asserted.append((path, val))
            if _is_stale_ref_path(path):
                stale_refs.add(round(val))
        if not asserted:
            continue
        checked += 1
        prior = {v for (d, v) in dated_closes if d < ed}  # 직전(strictly earlier) 일자 종가 집합
        for path, val in asserted:
            rv = round(val)
            if rv in stale_refs:
                continue  # 본인이 인용한 stale 참조값과 같으면 정상(예: 오늘=stale 유지)
            match = next((pv for pv in prior if pv and abs(rv - pv) / pv <= tol), None)
            if match is not None:
                violations.append(
                    f"[재활용종가] {e.get('ts')} {e.get('action')} {e.get('ticker')}: "
                    f"'오늘' KOSPI {val} ({path}) 이 직전 일자 종가 {match} 와 동일(±{tol * 100:.2f}%) "
                    "— 묵은 값 재활용 의심(동일자 출처로 재검증 필요)"
                )
                break
    return violations, checked, since


def main() -> int:
    policy = load_json("config/policy.json", {})
    pdq = policy.get("price_data_quality", {}) if isinstance(policy, dict) else {}
    mh = policy.get("market_hours", {}) if isinstance(policy, dict) else {}
    prov_gate = pdq.get("trade_provenance_gate", {}) if isinstance(pdq.get("trade_provenance_gate"), dict) else {}
    timing_gate = mh.get("trade_timing_gate", {}) if isinstance(mh.get("trade_timing_gate"), dict) else {}
    source_gate = pdq.get("source_provenance_gate", {}) if isinstance(pdq.get("source_provenance_gate"), dict) else {}

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

    source_date_violations: list[str] = []
    recycled_violations: list[str] = []
    source_checked = 0
    recycled_checked = 0
    source_since = None
    if source_gate.get("enabled", True):
        source_date_violations, source_checked, source_since = find_source_date_violations(entries, source_gate)
        recycled_violations, recycled_checked, source_since = find_recycled_value_violations(entries, source_gate)

    source_violations = source_date_violations + recycled_violations
    # audit_pipeline 이 읽는 통합 목록(셋 중 하나라도 FAIL)
    violations = prov_violations + timing_violations + source_violations
    out = {
        "enabled": True,
        "price_source_required_since": prov_since,
        "timing_enforced_since": timing_since,
        "source_enforced_since": source_since,
        "checked": prov_checked,
        "timing_checked": timing_checked,
        "source_checked": source_checked,
        "recycled_checked": recycled_checked,
        "provenance_violations": prov_violations,
        "timing_violations": timing_violations,
        "source_date_violations": source_date_violations,
        "recycled_value_violations": recycled_violations,
        "violations": violations,
        "ok": not violations,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))  # stdout = 순수 JSON (audit 가 subprocess 로 파싱)
    summary = (
        f"TRADE_LOG_GATE=FAIL (provenance {len(prov_violations)} + timing {len(timing_violations)} "
        f"+ source {len(source_violations)} violation) — 묵은/미검증 가격·장중 시간 밖·묵은 출처 booking 차단"
        if violations
        else (
            f"TRADE_LOG_GATE=PASS (provenance {prov_checked}건 + timing {timing_checked}건 "
            f"+ source {source_checked + recycled_checked}건 검증)"
        )
    )
    print(summary, file=sys.stderr)  # 사람용 요약은 stderr 로(stdout JSON 오염 방지)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
