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
            # (2026-07-08) venue 라벨만으로 무조건 통과시키던 구멍 폐쇄 — 정책은 EOD 종가
            # 청산의 ts 를 15:30 으로 기록하라고 명시한다(eod_settlement_timestamp). 15:30 은
            # 정규장 경계 안이라 위 분기에서 이미 통과하므로, 여기 도달한 eod venue 는
            # 전부 ts 오기록(예: 18:00 체결에 closing_auction 라벨)이다.
            violations.append(
                f"[장중시간] {tag}: execution_venue={venue!r} 인데 ts 가 15:30 이 아님 — "
                "종가 청산은 ts=15:30(마감 동시호가)으로 기록해야 함 (라벨만으로 통과 불가)"
            )
            continue
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


def _is_kospi_change_pct_path(path: str) -> bool:
    p = path.lower()
    return "kospi" in p and any(x in p for x in ("change_pct", "chg_pct", "change", "chg"))


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
    # 재활용이 아니라 '지수가 과거 레벨로 되돌아온 우연' 을 면제하는 내부 정합성 허용오차.
    consist_tol = float(sub.get("internal_consistency_tolerance_pct", 0.15)) / 100.0

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
        change_pcts: list[float] = []
        for path, val in _flatten(e):
            if isinstance(val, (int, float)) and not isinstance(val, bool) and _is_kospi_change_pct_path(path):
                change_pcts.append(float(val))
            if not (isinstance(val, (int, float)) and not isinstance(val, bool) and vmin <= val <= vmax):
                continue
            if _is_asserted_today_close(path):
                asserted.append((path, val))
            if _is_stale_ref_path(path):
                stale_refs.add(round(val))
        if not asserted:
            continue
        checked += 1
        prior_dated = sorted([(d, v) for (d, v) in dated_closes if d < ed])
        prior = {v for (_, v) in prior_dated}  # 직전(strictly earlier) 일자 종가 집합
        # 직전 영업일(가장 최근 strictly-earlier 일자) 종가 — 내부 정합성 면제의 기준선
        last_day = prior_dated[-1][0] if prior_dated else None
        last_day_closes = [v for (d, v) in prior_dated if d == last_day] if last_day else []
        for path, val in asserted:
            rv = round(val)
            if rv in stale_refs:
                continue  # 본인이 인용한 stale 참조값과 같으면 정상(예: 오늘=stale 유지)
            # 항목이 스스로 기록한 등락률이 직전 영업일 종가와 오늘 종가를 잇는다면 재활용이 아니다
            # — 묵은 값을 도용하면 close 와 change_pct 가 서로 어긋난다(지수가 과거 레벨로
            #   되돌아온 우연을 재활용으로 오탐하던 것을 좁힌다. 2026-08-05 실측: 오늘 6,598.26
            #   = 8/4 6,358.95 × (1+3.76%) 인데 7/31 종가 6,595.45 와 0.04% 차이로 충돌).
            if change_pcts and last_day_closes:
                if any(
                    pc and abs(rv - pc * (1 + cp / 100.0)) / (pc * (1 + cp / 100.0)) <= consist_tol
                    for pc in last_day_closes
                    for cp in change_pcts
                ):
                    continue
            match = next((pv for pv in prior if pv and abs(rv - pv) / pv <= tol), None)
            if match is not None:
                violations.append(
                    f"[재활용종가] {e.get('ts')} {e.get('action')} {e.get('ticker')}: "
                    f"'오늘' KOSPI {val} ({path}) 이 직전 일자 종가 {match} 와 동일(±{tol * 100:.2f}%) "
                    "— 묵은 값 재활용 의심(동일자 출처로 재검증 필요)"
                )
                break
    return violations, checked, since


# ── (4) 급등 추격 차단 — policy.risk.chase_entry_filter (2026-07-06 감사 처방③) ─────
def _load_price_series() -> dict[str, dict]:
    """price_history.json → {ticker: {"dates": [...], "closes": {date: close}}} (지수 포함 아님)."""
    hist = load_json("state/price_history.json", {})
    out: dict[str, dict] = {}
    for tk, v in (hist.get("tickers") or {}).items():
        bars = v.get("bars") or []
        closes = {b["date"]: float(b["close"]) for b in bars if isinstance(b, dict) and b.get("close")}
        if closes:
            out[tk] = {"dates": sorted(closes), "closes": closes}
    return out


def find_chase_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    """BUY 종목의 직전 N거래일 수익률이 상한 초과인데 chase_exception 사유가 없으면 위반.

    근거(2026-07-06 감사): 6/4 삼성전자(3거래일 +13.7% 후 진입→즉시 orange/red 양분 손절
    -82,480원)·6/30 LS ELECTRIC(2거래일 +13% 후 진입→트레일 손실 청산) — 급등 추격 진입이
    반복적으로 즉시 손실 전환. 기준가는 price_history 의 매수일 '직전' 5번째 거래일 종가
    (매수일 종가는 미확정이므로 매수가 자체와 비교 — 룩어헤드 없음).
    """
    since = str(gate_cfg.get("enforced_since", "2026-07-07"))[:10]
    lookback = int(gate_cfg.get("lookback_trading_days", 5))
    max_runup = float(gate_cfg.get("max_runup_pct", 10.0))
    series = _load_price_series()
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict) or not rp._is_buy(e.get("action")):
            continue
        ts = str(e.get("ts", ""))
        if ts[:10] < since:
            continue  # grandfather
        t = e.get("ticker")
        buy_px = e.get("price")
        s = series.get(t)
        if not s or not isinstance(buy_px, (int, float)) or buy_px <= 0:
            continue  # 히스토리 없는 종목은 검증 불가 — pre_trade_check 의 사전 판정에 위임
        prior = [d for d in s["dates"] if d < ts[:10]]
        if len(prior) < lookback:
            continue
        ref_close = s["closes"][prior[-lookback]]
        runup = (buy_px / ref_close - 1) * 100
        checked += 1
        if runup > max_runup and not e.get("chase_exception"):
            violations.append(
                f"[추격진입] {ts} BUY {t}: 직전 {lookback}거래일 수익률 {runup:+.1f}% > 상한 +{max_runup:.0f}% "
                f"(기준가 {ref_close:,.0f}→매수가 {buy_px:,.0f}) — 급등 추격 차단. "
                "예외 진입이면 chase_exception 사유 + 50% 축소 비중 기록 필요"
            )
    return violations, checked, since


# ── (5) 지수 급변동일 스톱 유예 — policy.risk.index_shock_stop_deferral (감사 처방④) ──
_STOP_SELL_MARKERS = ("STOP", "TRAILING")


def find_index_shock_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    """KOSPI |일간등락|≥임계 인 날의 스톱/트레일 SELL 체결에 유예 이력이 없으면 위반.

    근거(2026-07-06 감사): 실현 손실 청산 6건 전부 지수 급락일 격발 후 15거래일 내 +8~16% 회복
    (개별 thesis 훼손 0건). 쇼크일 스톱은 익일 종가 재확인이 기본 — 즉시 체결은 shock_deferral_ack
    (ATR 관통/thesis 무효화 예외) 또는 reason 의 '익일 재확인' 이력을 요구한다.
    """
    since = str(gate_cfg.get("enforced_since", "2026-07-07"))[:10]
    threshold = float(gate_cfg.get("kospi_abs_daily_move_pct", 5.0))
    ack_field = str(gate_cfg.get("ack_field", "shock_deferral_ack"))
    hist = load_json("state/price_history.json", {})
    idx_bars = ((hist.get("index") or {}).get("bars")) or []
    idx_closes = {b["date"]: float(b["close"]) for b in idx_bars if isinstance(b, dict) and b.get("close")}
    idx_dates = sorted(idx_closes)
    day_move: dict[str, float] = {}
    for i in range(1, len(idx_dates)):
        prev, cur = idx_closes[idx_dates[i - 1]], idx_closes[idx_dates[i]]
        if prev > 0:
            day_move[idx_dates[i]] = (cur / prev - 1) * 100
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        action = str(e.get("action") or "")
        if not rp._is_sell(action) or not any(m in action.upper() for m in _STOP_SELL_MARKERS):
            continue  # 스톱/트레일 계열 SELL 만 대상(목표 익절·재량 매도 제외)
        ts = str(e.get("ts", ""))
        d = ts[:10]
        if d < since:
            continue  # grandfather
        move = day_move.get(d)
        if move is None or abs(move) < threshold:
            continue  # 쇼크일 아님
        checked += 1
        reason = str(e.get("reason") or "")
        deferred = ("익일 재확인" in reason) or ("2일 연속" in reason) or ("이틀 연속" in reason)
        if not deferred and not e.get(ack_field):
            violations.append(
                f"[지수쇼크스톱] {ts} {action} {e.get('ticker')}: KOSPI 일간 {move:+.2f}% 쇼크일의 스톱 체결인데 "
                f"유예 이력(reason '익일 재확인'/'2일 연속') 또는 {ack_field}(ATR 관통·thesis 무효화 예외) 없음 "
                "— 쇼크일 스톱은 익일 종가 재확인이 기본"
            )
    return violations, checked, since


# ── (6) 판단 카드 — policy.price_data_quality.decision_card_gate (감사: 사람이 읽는 매매 논리) ──
def find_decision_card_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    """BUY/SELL 항목에 구조화된 decision_card 필수 필드가 없으면 위반 (enforced_since 이후)."""
    since = str(gate_cfg.get("enforced_since", "2026-07-07"))[:10]
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        action = e.get("action")
        is_buy, is_sell = rp._is_buy(action), rp._is_sell(action)
        if not (is_buy or is_sell):
            continue
        ts = str(e.get("ts", ""))
        if ts[:10] < since:
            continue  # grandfather — 이전 체결은 render_trade_cards 가 reason 폴백
        checked += 1
        tag = f"{ts} {action} {e.get('ticker')}"
        card = e.get("decision_card")
        if not isinstance(card, dict):
            violations.append(f"[판단카드] {tag}: decision_card 객체 없음 — 사람이 검증 가능한 매매 논리 기록 의무")
            continue
        missing: list[str] = []
        if is_buy:
            if len(str(card.get("thesis") or "")) < 20:
                missing.append("thesis(≥20자)")
            ev = card.get("evidence")
            if not isinstance(ev, list) or len(ev) < 2:
                missing.append("evidence(리스트 ≥2개)")
            if len(str(card.get("invalidation") or "")) < 10:
                missing.append("invalidation(≥10자)")
            if not isinstance(card.get("horizon_days"), int):
                missing.append("horizon_days(정수)")
        else:
            trig = str(card.get("trigger") or "")
            if len(trig) < 10 or not any(c.isdigit() for c in trig):
                missing.append("trigger(≥10자·수치 포함)")
            if len(str(card.get("human_summary") or "")) < 20:
                missing.append("human_summary(≥20자)")
        if missing:
            violations.append(f"[판단카드] {tag}: decision_card 필수 필드 미충족 — {', '.join(missing)}")
    return violations, checked, since


# ── (7) R/R 하한 게이트 (2026-07-08 신설) ────────────────────────────────────────
# 신규 진입 R/R 하한(reward_risk_management.regime_adaptive_rr)이 프롬프트 지시로만
# 존재해 LLM 이 잊으면 하한 미달 진입이 main 에 도달하던 구멍을 CI 로 닫는다.
def find_rr_entry_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    since = str(gate_cfg.get("ci_enforced_since", "2026-07-08"))[:10]
    tiers = gate_cfg.get("min_rr_by_tier") if isinstance(gate_cfg.get("min_rr_by_tier"), dict) else {}
    tiers = tiers or {"strong_bull": 1.0, "bull": 1.1, "neutral": 1.2, "bear": 1.4, "deep_bear": 1.6}
    floor = min(float(v) for v in tiers.values())
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not rp._is_buy(e.get("action")):
            continue
        ts = str(e.get("ts", ""))
        if ts[:10] < since:
            continue
        checked += 1
        tag = f"{ts} {e.get('action')} {e.get('ticker')}"
        price, stop, target = rp.num(e.get("price")), rp.num(e.get("stop_price")), rp.num(e.get("target_price"))
        if not price or not stop or not target:
            violations.append(f"[R/R하한] {tag}: price/stop_price/target_price 누락 — 신규 진입은 세 값 기록 의무(R/R 검증 불가)")
            continue
        if price <= stop:
            violations.append(f"[R/R하한] {tag}: price({price:,.0f}) <= stop_price({stop:,.0f}) — 손절선 역전")
            continue
        rr = (target - price) / (price - stop)
        tier = str(e.get("regime_tier") or "")
        # tier 미기록이면 최저 하한만 적용(관대) — 목적은 바닥 뚫린 진입 차단이지 tier 소급 추정이 아니다
        min_rr = float(tiers.get(tier, floor))
        if rr + 1e-9 < min_rr:
            violations.append(
                f"[R/R하한] {tag}: R/R={rr:.2f} < 하한 {min_rr}(tier={tier or '미기록→최저하한'}) — regime_adaptive_rr 미달 진입"
            )
    return violations, checked, since


# ── (8) 실적 블랙아웃 게이트 (2026-07-08 신설) ───────────────────────────────────
# policy.fundamentals.earnings_blackout("실적 발표 D-1~당일 신규 진입 보류")이 어느
# 스크립트도 검사하지 않던 프롬프트 전용 규칙이었다 — catalysts.json 의 earnings 계열
# 이벤트와 대조해 CI 로 강제한다.
def find_earnings_blackout_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    since = str(gate_cfg.get("enforced_since", "2026-07-08"))[:10]
    days_before = int(gate_cfg.get("days_before", 1))
    cat = load_json("config/catalysts.json", {}) or {}
    events: list[dict] = []
    for key in ("generated_events", "manual_events"):
        for ev in cat.get(key) or []:
            if isinstance(ev, dict) and "earnings" in str(ev.get("type", "")) and ev.get("ticker") and ev.get("date"):
                events.append(ev)
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not rp._is_buy(e.get("action")):
            continue
        ts = str(e.get("ts", ""))
        entry_day = ts[:10]
        if entry_day < since:
            continue
        checked += 1
        for ev in events:
            if ev.get("ticker") != e.get("ticker"):
                continue
            try:
                ev_date = date.fromisoformat(str(ev["date"])[:10])
                d = date.fromisoformat(entry_day)
            except ValueError:
                continue
            if 0 <= (ev_date - d).days <= days_before:
                confirmed = "확정" if ev.get("confirmed") else "법정기한 추정"
                violations.append(
                    f"[실적블랙아웃] {ts} {e.get('action')} {e.get('ticker')}: 실적 이벤트 {ev.get('date')}({confirmed}, {ev.get('id')}) "
                    f"D-{(ev_date - d).days} 이내 신규/추가매수 — earnings_blackout(D-{days_before}~당일 진입 보류) 위반"
                )
    return violations, checked, since


def main() -> int:
    policy = load_json("config/policy.json", {})
    pdq = policy.get("price_data_quality", {}) if isinstance(policy, dict) else {}
    mh = policy.get("market_hours", {}) if isinstance(policy, dict) else {}
    risk = policy.get("risk", {}) if isinstance(policy, dict) else {}
    prov_gate = pdq.get("trade_provenance_gate", {}) if isinstance(pdq.get("trade_provenance_gate"), dict) else {}
    timing_gate = mh.get("trade_timing_gate", {}) if isinstance(mh.get("trade_timing_gate"), dict) else {}
    source_gate = pdq.get("source_provenance_gate", {}) if isinstance(pdq.get("source_provenance_gate"), dict) else {}
    chase_gate = risk.get("chase_entry_filter", {}) if isinstance(risk.get("chase_entry_filter"), dict) else {}
    shock_gate = risk.get("index_shock_stop_deferral", {}) if isinstance(risk.get("index_shock_stop_deferral"), dict) else {}
    card_gate = pdq.get("decision_card_gate", {}) if isinstance(pdq.get("decision_card_gate"), dict) else {}

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

    chase_violations: list[str] = []
    chase_checked = 0
    chase_since = None
    if chase_gate.get("enabled", True):
        chase_violations, chase_checked, chase_since = find_chase_violations(entries, chase_gate)

    shock_violations: list[str] = []
    shock_checked = 0
    shock_since = None
    if shock_gate.get("enabled", True):
        shock_violations, shock_checked, shock_since = find_index_shock_violations(entries, shock_gate)

    card_violations: list[str] = []
    card_checked = 0
    card_since = None
    if card_gate.get("enabled", True):
        card_violations, card_checked, card_since = find_decision_card_violations(entries, card_gate)

    # (2026-07-08 신설) R/R 하한·실적 블랙아웃 — 프롬프트 전용 규칙의 CI 강제
    rr_gate = policy.get("reward_risk_management", {}) if isinstance(policy, dict) else {}
    rr_cfg = rr_gate.get("regime_adaptive_rr", {}) if isinstance(rr_gate.get("regime_adaptive_rr"), dict) else {}
    rr_violations: list[str] = []
    rr_checked = 0
    rr_since = None
    if rr_cfg.get("enabled", True):
        rr_violations, rr_checked, rr_since = find_rr_entry_violations(entries, rr_cfg)

    ef = policy.get("entry_filters", {}) if isinstance(policy, dict) else {}
    eb_cfg = ef.get("earnings_blackout_gate", {}) if isinstance(ef.get("earnings_blackout_gate"), dict) else {}
    eb_violations: list[str] = []
    eb_checked = 0
    eb_since = None
    if eb_cfg.get("enabled", True):
        eb_violations, eb_checked, eb_since = find_earnings_blackout_violations(entries, eb_cfg)

    source_violations = source_date_violations + recycled_violations
    # audit_pipeline 이 읽는 통합 목록(하나라도 FAIL)
    violations = (
        prov_violations + timing_violations + source_violations
        + chase_violations + shock_violations + card_violations
        + rr_violations + eb_violations
    )
    out = {
        "enabled": True,
        "price_source_required_since": prov_since,
        "timing_enforced_since": timing_since,
        "source_enforced_since": source_since,
        "chase_enforced_since": chase_since,
        "shock_enforced_since": shock_since,
        "decision_card_enforced_since": card_since,
        "checked": prov_checked,
        "timing_checked": timing_checked,
        "source_checked": source_checked,
        "recycled_checked": recycled_checked,
        "chase_checked": chase_checked,
        "shock_checked": shock_checked,
        "decision_card_checked": card_checked,
        "rr_enforced_since": rr_since,
        "rr_checked": rr_checked,
        "earnings_blackout_enforced_since": eb_since,
        "earnings_blackout_checked": eb_checked,
        "provenance_violations": prov_violations,
        "timing_violations": timing_violations,
        "source_date_violations": source_date_violations,
        "recycled_value_violations": recycled_violations,
        "chase_violations": chase_violations,
        "index_shock_violations": shock_violations,
        "decision_card_violations": card_violations,
        "rr_violations": rr_violations,
        "earnings_blackout_violations": eb_violations,
        "violations": violations,
        "ok": not violations,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))  # stdout = 순수 JSON (audit 가 subprocess 로 파싱)
    summary = (
        f"TRADE_LOG_GATE=FAIL (provenance {len(prov_violations)} + timing {len(timing_violations)} "
        f"+ source {len(source_violations)} + chase {len(chase_violations)} + shock {len(shock_violations)} "
        f"+ card {len(card_violations)} + rr {len(rr_violations)} + earnings {len(eb_violations)} violation) "
        "— 묵은/미검증 가격·장외 체결·묵은 출처·추격 진입·쇼크일 스톱·판단카드 누락·R/R 하한 미달·"
        "실적 블랙아웃 booking 차단"
        if violations
        else (
            f"TRADE_LOG_GATE=PASS (provenance {prov_checked}건 + timing {timing_checked}건 "
            f"+ source {source_checked + recycled_checked}건 + chase {chase_checked}건 "
            f"+ shock {shock_checked}건 + card {card_checked}건 + rr {rr_checked}건 "
            f"+ earnings {eb_checked}건 검증)"
        )
    )
    print(summary, file=sys.stderr)  # 사람용 요약은 stderr 로(stdout JSON 오염 방지)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
