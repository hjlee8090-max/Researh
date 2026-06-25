#!/usr/bin/env python3
"""매매(booking) 직전 게이트 — 묵은 스냅샷에 신규매수가 체결되던 레이스(2026-06-01) 방지.

routine prompt 가 신규/추가 매수·청산을 trade_log/portfolio 에 기록하기 **직전** 호출한다.
스냅샷 신선도(freshness), 점수·비중의 스냅샷 동기화 여부, 장부 정합성(reconcile),
평가금액 산식, 스냅샷 대비 평가가격 괴리를 점검하고 verdict 를 낸다.

verdict:
- block               : 장부 정합성/평가 산식 불일치 — 매매 금지(사용자 보고·수정 후 재실행).
- resync_required     : candidate_scores/allocation 이 현재 스냅샷과 불일치 — 재수집·재점수 후 재판정.
- live_verify_required: freshness 가 fresh 가 아니거나 가격 last_date 가 오늘이 아님(또는 stale 보존본) —
                        신규/추가 매수·임계 근접 청산은 웹 실시간 교차확인가로 재계산 후 booking.
- ok                  : 스냅샷 가격으로 booking 가능.

정책: policy.price_data_quality.pre_trade_gate / new_entry_freshness_rule / data_freshness
      / web_verify_unavailable_fallback.
표준 라이브러리만 사용. 출력: stdout(JSON + 1줄 verdict). exit code: 0=ok/live_verify, 1=block/resync.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import reconcile_portfolio as rp  # 같은 scripts/ 디렉토리 — 장부·평가 점검 재사용(단일 출처)

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
# 세션 웹 검증(live_verify) 가능 여부 자동 판정용 — 이그레스 정책이 막혔는지 한 번 찔러본다.
EGRESS_PROBE_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/%5EKS11?range=1d&interval=1d"
)
EGRESS_PROBE_TIMEOUT = 3.0


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default if default is not None else {}


def compute_freshness(snapshot_as_of: str | None, fresh_max: float, intraday_max: float) -> tuple[int | None, str]:
    """스냅샷 수집시각 대비 현재 나이(분)·freshness 등급. compute_allocation.py 와 동일 로직."""
    if not snapshot_as_of:
        return None, "unknown"
    try:
        collected = datetime.fromisoformat(snapshot_as_of)
    except (ValueError, TypeError):
        return None, "unknown"
    age = round((datetime.now(KST) - collected).total_seconds() / 60)
    if age <= fresh_max:  # 음수(시계 스큐)도 fresh 로 본다
        return age, "fresh"
    if age <= intraday_max:
        return age, "acceptable"
    return age, "stale_intraday"


def ticker_source_dates(ticker_snap: dict) -> list[str]:
    """종목 스냅샷의 ok 출처별 last_date 목록 (Yahoo 전일자 지연 판정용)."""
    return [
        s["last_date"]
        for s in (ticker_snap.get("sources") or [])
        if isinstance(s, dict) and s.get("ok") and s.get("last_date")
    ]


def probe_web_egress(url: str = EGRESS_PROBE_URL, timeout: float = EGRESS_PROBE_TIMEOUT) -> str:
    """세션의 라이브 웹 검증(live_verify) 통로가 살아 있는지 한 번 찔러본다.

    리모트 세션은 정책 집행 이그레스 프록시를 거치며, 조직 정책이 금융 호스트를
    허용하지 않으면 프록시가 CONNECT 터널을 403 으로 거부한다(2026-06-23~). 그 경우
    세션은 어떤 종목도 웹으로 교차확인할 수 없어 live_verify_required 가 영구 미충족이 된다.

    반환:
      "open"    — 상류에서 HTTP 응답을 받음(프록시 통과). 검증 가능 → 폴백 불필요.
      "blocked" — 프록시가 403/터널 거부. 세션 웹 검증 불가 → 폴백 후보.
      "unknown" — 타임아웃·기타 일시 오류. 보수적으로 현 게이트 유지(폴백 미적용).
    예외를 절대 밖으로 던지지 않는다(게이트는 네트워크 상태와 무관하게 항상 verdict 를 내야 한다).
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        urllib.request.urlopen(req, timeout=timeout)
        return "open"
    except urllib.error.HTTPError:
        # 상류(야후)가 4xx/5xx 를 돌려줬다 = 프록시는 통과 = 이그레스 열림.
        return "open"
    except Exception as exc:  # noqa: BLE001 — URLError/OSError/타임아웃 전부 무해 분류
        reason = str(getattr(exc, "reason", exc)).lower()
        if "403" in reason or "tunnel" in reason or "forbidden" in reason:
            return "blocked"
        return "unknown"


def resolve_web_egress(explicit: str | None) -> str:
    """웹 이그레스 상태를 결정한다 — 명시값(플래그/env) > 자동 프로브.

    explicit: "blocked"|"open"|None. None 이면 env SESSION_WEB_EGRESS 를 보고,
    그래도 없으면 auto 프로브. 명시 신호가 자동 판정보다 항상 우선한다(운영자 오버라이드).
    """
    val = (explicit or os.environ.get("SESSION_WEB_EGRESS") or "").strip().lower()
    if val in ("blocked", "open"):
        return val
    return probe_web_egress()


def authoritative_same_day(ticker_snap: dict, today: str) -> bool:
    """이 종목 스냅샷이 '오늘자·복수출처 일치·high 신뢰도'인 권위 가격인지.

    web_verify_unavailable_fallback 의 핵심 가드: 세션 웹 검증이 막혔을 때 묵은/단일출처
    가격으로 체결되는 것은 막되, 정기 수집(GitHub Actions)이 산출한 '오늘자 ≥2출처 일치
    high' 스냅샷은 snapshot_fresh 권위 가격으로 인정한다(2026-06-08 단일출처 갭업 도용류는
    여전히 차단 — 오늘자 출처가 2개 미만이거나 high 미만이면 False).
    """
    if not isinstance(ticker_snap, dict):
        return False
    today_sources = [
        s
        for s in (ticker_snap.get("sources") or [])
        if isinstance(s, dict) and s.get("ok") and s.get("last_date") == today
    ]
    return len(today_sources) >= 2 and ticker_snap.get("confidence") == "high"


def main() -> int:
    parser = argparse.ArgumentParser(description="매매 직전 게이트 — 스냅샷 신선도·동기화·정합성 점검")
    parser.add_argument(
        "--egress",
        choices=["auto", "blocked", "open"],
        default="auto",
        help="세션 웹 검증 통로 상태. auto=env SESSION_WEB_EGRESS 또는 자동 프로브(기본).",
    )
    args = parser.parse_args()

    policy = load_json("config/policy.json", {})
    snapshot = load_json("state/market_snapshot.json", {})
    scores = load_json("state/candidate_scores.json", {})
    alloc = load_json("state/allocation.json", {})
    portfolio = load_json("config/portfolio.json", {})

    pdq = policy.get("price_data_quality", {}) if isinstance(policy, dict) else {}
    fresh_cfg = pdq.get("data_freshness", {}) if isinstance(pdq.get("data_freshness"), dict) else {}
    fresh_max = float(fresh_cfg.get("fresh_max_min", 20))
    intraday_max = float(fresh_cfg.get("intraday_acceptable_max_min", 75))

    snap_as_of = snapshot.get("as_of") if isinstance(snapshot, dict) else None
    age_min, freshness = compute_freshness(snap_as_of, fresh_max, intraday_max)

    # 점수·비중이 현재 스냅샷과 같은 as_of 로 산출됐는지(동기화)
    scores_as_of = scores.get("snapshot_as_of") if isinstance(scores, dict) else None
    alloc_as_of = alloc.get("snapshot_as_of") if isinstance(alloc, dict) else None
    scores_in_sync = bool(snap_as_of) and scores_as_of == snap_as_of
    alloc_in_sync = bool(snap_as_of) and alloc_as_of == snap_as_of

    # 스냅샷 가격의 거래일(last_date)이 오늘인지 — 전일자뿐이면 신규 진입에 부적합.
    # 2026-06-23 — 종목별 '오늘자 출처 ≥1개' 보유로 판정한다(기존: 전 출처가 모두 오늘이어야 통과).
    # Yahoo 가 KST 오전에 KRX 종가를 전일자로 보고하는 알려진 지연 탓에 naver 당일자·2출처 일치·
    # fresh 스냅샷인데도 live_verify_required 가 상시 발령돼 '신규 매수만' 비대칭 봉쇄되던 문제 해소
    # (2026-06-23 lessons — SK하이닉스 4영업일 미배치의 직접 원인). 진짜 묵은 스냅샷(전 출처 전일자·
    # 주말 carry)은 today 출처가 0이라 그대로 live_verify_required + freshness(age) 게이트가 이중 차단.
    today = datetime.now(KST).date().isoformat()
    ts = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    dated_tickers = [v for v in ts.values() if isinstance(v, dict) and ticker_source_dates(v)]
    prices_last_date_today = bool(dated_tickers) and all(
        today in ticker_source_dates(v) for v in dated_tickers
    )
    snapshot_stale = bool(snapshot.get("stale")) if isinstance(snapshot, dict) else False

    # web_verify_unavailable_fallback — 세션 웹 검증이 막혔는지(이그레스 정책 403) + 스냅샷이
    # '오늘자 ≥2출처 일치 high' 권위 가격인지를 함께 판정한다. 둘 다 충족이면 live_verify_required
    # 의 '웹 1회 교차확인' 요구를 snapshot_fresh 권위 가격으로 대체(불가능한 검증 요구 → 교착 해소).
    explicit_egress = None if args.egress == "auto" else args.egress
    web_egress = resolve_web_egress(explicit_egress)
    authoritative = bool(dated_tickers) and all(
        authoritative_same_day(v, today) for v in dated_tickers
    )

    # 장부 정합성(reconcile) + 평가 산식 (reconcile_portfolio 재사용)
    trade_log = rp.load_trade_log()
    initial_capital = rp.num(portfolio.get("initial_capital", 5000000))
    expected = rp.compute_expected(trade_log, initial_capital)
    recon_issues = rp.compare(expected, portfolio)
    val_issues, val_warnings = rp.valuation_checks(portfolio, snapshot)
    issues = recon_issues + val_issues

    # verdict — 더 보수적인 쪽 우선
    if issues:
        verdict = "block"
    elif not scores_in_sync or not alloc_in_sync:
        verdict = "resync_required"
    elif freshness != "fresh" or not prices_last_date_today or snapshot_stale:
        verdict = "live_verify_required"
    else:
        verdict = "ok"

    # web_verify_unavailable_fallback — live_verify_required 인데 (a)세션 웹 검증이 막혀
    # 있고(blocked) (b)스냅샷이 오늘자 ≥2출처 일치 high 권위 가격이면, 불가능한 '웹 1회
    # 교차확인' 요구를 snapshot_fresh 권위 가격으로 대체한다. block/resync 는 데이터·정합성
    # 문제라 폴백 대상이 아니다(여전히 차단). open/unknown 이면 기존 보수 동작 유지.
    fallback_applied = False
    if verdict == "live_verify_required" and web_egress == "blocked" and authoritative:
        verdict = "ok"
        fallback_applied = True

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "verdict": verdict,
        "snapshot_as_of": snap_as_of,
        "snapshot_age_min": age_min,
        "freshness": freshness,
        "snapshot_stale": snapshot_stale,
        "prices_last_date_today": prices_last_date_today,
        "web_egress": web_egress,
        "authoritative_same_day_snapshot": authoritative,
        "web_verify_unavailable_fallback_applied": fallback_applied,
        "recommended_price_source": "snapshot_fresh" if verdict == "ok" else None,
        "scores_in_sync": scores_in_sync,
        "alloc_in_sync": alloc_in_sync,
        "scores_snapshot_as_of": scores_as_of,
        "alloc_snapshot_as_of": alloc_as_of,
        "portfolio_heat": alloc.get("portfolio_heat") if isinstance(alloc, dict) else None,
        "reconcile_issues": recon_issues,
        "valuation_issues": val_issues,
        "warnings": val_warnings,
        "new_entry_without_verify_allowed": verdict == "ok",
        "guidance": _guidance(verdict, fallback_applied),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(
        f"\nPRE_TRADE_VERDICT={verdict} freshness={freshness}(age={age_min}m) "
        f"egress={web_egress} authoritative={authoritative} fallback={fallback_applied} "
        f"sync(scores={scores_in_sync},alloc={alloc_in_sync}) "
        f"issues={len(issues)} warnings={len(val_warnings)}"
    )
    return 1 if verdict in ("block", "resync_required") else 0


def _guidance(verdict: str, fallback_applied: bool = False) -> str:
    if verdict == "ok" and fallback_applied:
        return (
            "freshness≠fresh 이나 세션 웹 검증 통로가 막혀(이그레스 403) 라이브 교차확인이 "
            "구조적으로 불가능하고, 스냅샷이 오늘자 ≥2출처 일치 high 권위 가격이라 "
            "web_verify_unavailable_fallback 적용 — snapshot_fresh 가격으로 booking 가능. "
            "trade_log 에 price_source=snapshot_fresh 로 기록(web_verified 아님). "
            "손절·목표 임계 근접(±3%/±2%) 보유 종목은 이 폴백 대상이 아니다(보수적 즉시 판정)."
        )
    return {
        "block": "장부/평가 정합성 불일치 — 매매 금지. 원인 수정·사용자 보고 후 재실행.",
        "resync_required": "candidate_scores/allocation 이 현재 스냅샷과 불일치 — "
        "fetch_market_data → score_candidates → compute_allocation 재실행 후 재판정.",
        "live_verify_required": "freshness≠fresh 또는 가격 last_date≠오늘(또는 stale 보존본) — "
        "신규/추가 매수·임계 근접 청산은 해당 종목 실시간가를 웹으로 1회 교차확인해 "
        "진입가·R/R·사이징을 재계산한 뒤 booking(trade_log 에 price_source=web_verified + URL 기록). "
        "묵은 스냅샷 가격으로 먼저 체결하는 조건부 체결 금지. (세션 웹 검증이 막힌(이그레스 403) "
        "상태이고 스냅샷이 오늘자 ≥2출처 high 면 web_verify_unavailable_fallback 으로 snapshot_fresh "
        "체결 가능 — pre_trade_check 가 자동 판정하나, 단일출처·stale·전일자면 medium_new_entry_rule "
        "축소비중으로 집행하거나 보류한다.)",
        "ok": "fresh·동기화·정합성 충족 — 스냅샷 가격으로 booking 가능.",
    }.get(verdict, "")


if __name__ == "__main__":
    raise SystemExit(main())
