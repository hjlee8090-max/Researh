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

정책: policy.price_data_quality.pre_trade_gate / new_entry_freshness_rule / data_freshness.
표준 라이브러리만 사용. 출력: stdout(JSON + 1줄 verdict). exit code: 0=ok/live_verify, 1=block/resync.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import reconcile_portfolio as rp  # 같은 scripts/ 디렉토리 — 장부·평가 점검 재사용(단일 출처)

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


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


def main() -> int:
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

    # 스냅샷 가격의 거래일(last_date)이 모두 오늘인지 — 전일자면 신규 진입에 부적합
    today = datetime.now(KST).date().isoformat()
    ts = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    last_dates: list[str] = []
    for v in ts.values():
        if isinstance(v, dict):
            for s in v.get("sources", []) or []:
                if isinstance(s, dict) and s.get("ok") and s.get("last_date"):
                    last_dates.append(s["last_date"])
    prices_last_date_today = bool(last_dates) and all(d == today for d in last_dates)
    snapshot_stale = bool(snapshot.get("stale")) if isinstance(snapshot, dict) else False

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

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "verdict": verdict,
        "snapshot_as_of": snap_as_of,
        "snapshot_age_min": age_min,
        "freshness": freshness,
        "snapshot_stale": snapshot_stale,
        "prices_last_date_today": prices_last_date_today,
        "scores_in_sync": scores_in_sync,
        "alloc_in_sync": alloc_in_sync,
        "scores_snapshot_as_of": scores_as_of,
        "alloc_snapshot_as_of": alloc_as_of,
        "portfolio_heat": alloc.get("portfolio_heat") if isinstance(alloc, dict) else None,
        "reconcile_issues": recon_issues,
        "valuation_issues": val_issues,
        "warnings": val_warnings,
        "new_entry_without_verify_allowed": verdict == "ok",
        "guidance": _guidance(verdict),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(
        f"\nPRE_TRADE_VERDICT={verdict} freshness={freshness}(age={age_min}m) "
        f"sync(scores={scores_in_sync},alloc={alloc_in_sync}) "
        f"issues={len(issues)} warnings={len(val_warnings)}"
    )
    return 1 if verdict in ("block", "resync_required") else 0


def _guidance(verdict: str) -> str:
    return {
        "block": "장부/평가 정합성 불일치 — 매매 금지. 원인 수정·사용자 보고 후 재실행.",
        "resync_required": "candidate_scores/allocation 이 현재 스냅샷과 불일치 — "
        "fetch_market_data → score_candidates → compute_allocation 재실행 후 재판정.",
        "live_verify_required": "freshness≠fresh 또는 가격 last_date≠오늘(또는 stale 보존본) — "
        "신규/추가 매수·임계 근접 청산은 해당 종목 실시간가를 웹으로 1회 교차확인해 "
        "진입가·R/R·사이징을 재계산한 뒤 booking(trade_log 에 price_source=web_verified + URL 기록). "
        "묵은 스냅샷 가격으로 먼저 체결하는 조건부 체결 금지.",
        "ok": "fresh·동기화·정합성 충족 — 스냅샷 가격으로 booking 가능.",
    }.get(verdict, "")


if __name__ == "__main__":
    raise SystemExit(main())
