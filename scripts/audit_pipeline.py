#!/usr/bin/env python3
"""Pipeline health audit for the KOSPI autoflow repository.

This script is intentionally dependency-free so Codex can run it locally and
GitHub Actions can run it without extra setup.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


ROOT = Path(__file__).resolve().parent.parent


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def result(level: str, message: str) -> str:
    return f"[{level}] {message}"


def load_json(rel: str):
    """레포 루트 상대경로 JSON 을 안전 로드(없거나 깨지면 None)."""
    p = ROOT / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def audit_json_files(messages: list[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    for rel in [
        "config/policy.json",
        "config/weekly_plan.json",
        "config/watchlist.json",
        "config/portfolio.json",
        "config/candidates.json",
        "config/market_calendar.json",
    ]:
        path = ROOT / rel
        try:
            data[rel] = read_json(path)
            messages.append(result("OK", f"{rel} is valid JSON"))
        except Exception as exc:  # noqa: BLE001 - audit should report all parse failures
            messages.append(result("FAIL", f"{rel} is not valid JSON: {exc}"))
    return data


# 체결(매매) 액션 — ticker 필수. BUY_/SELL_ 변형은 reconcile_portfolio 분류와 동일하게 prefix 로 수용.
ALLOWED_TRADE_ACTIONS = {
    "BUY", "SELL", "TRAILING_STOP", "SCALE_IN", "SCALE_OUT",
}
# 비매매 기록 액션(점검·평가 마커) — ticker 없어도 정상 (예: HOLIDAY_EVAL 은 계좌 단위 기록).
ALLOWED_NONTRADE_ACTIONS = {
    "HOLD", "EVAL", "EOD_EVAL", "OPEN_CHECK", "MIDDAY_CHECK", "CLOSE_CHECK",
    "HOLIDAY_EVAL", "DEFERRED", "WATCH",
}


def is_known_action(action: str | None) -> bool:
    if not action:
        return False
    if action in ALLOWED_TRADE_ACTIONS or action in ALLOWED_NONTRADE_ACTIONS:
        return True
    # SELL_GIVE_BACK_STOP / SELL_ORANGE_STOP / BUY_PROBE 등 체결 변형 수용 (reconcile 과 정합)
    if action.startswith("BUY_") or action.startswith("SELL_"):
        return True
    # 관측·마커 계열 비매매 액션의 화이트리스트 추격전 종료 (INTRADAY_CHECK 13회 연속 WARN 방치 재발 방지):
    # _CHECK/_MARK/_EVAL 접미 액션은 점검·기록 마커로 수용한다. 매매 판정(is_trade_action)에는 불포함.
    return action.endswith("_CHECK") or action.endswith("_MARK") or action.endswith("_EVAL")


def is_trade_action(action: str | None) -> bool:
    if not action:
        return False
    return action in ALLOWED_TRADE_ACTIONS or action.startswith("BUY_") or action.startswith("SELL_")


def audit_trade_log(messages: list[str]) -> None:
    path = ROOT / "state" / "trade_log.jsonl"
    if not path.exists():
        messages.append(result("WARN", "state/trade_log.jsonl is missing"))
        return
    bad: list[str] = []
    issues: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict] = []
    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            bad.append(f"line {idx}: {exc}")
            continue
        if not isinstance(entry, dict):
            issues.append(f"line {idx}: 객체가 아님")
            continue
        action = entry.get("action")
        required = ("ts", "action", "ticker") if is_trade_action(action) else ("ts", "action")
        for field in required:
            if field not in entry:
                issues.append(f"line {idx}: '{field}' 누락")
        if action and not is_known_action(action):
            issues.append(f"line {idx}: 알 수 없는 action='{action}'")
        entries.append(entry)
    if bad:
        messages.append(result("FAIL", "trade_log has invalid JSONL entries: " + "; ".join(bad[:3])))
        return
    messages.append(result("OK", f"trade_log JSONL is valid ({len(lines)} lines)"))

    # 시간순 정렬 점검
    timestamps = [e.get("ts", "") for e in entries if e.get("ts")]
    sorted_ts = sorted(timestamps)
    if timestamps != sorted_ts:
        issues.append("ts 가 시간순으로 정렬되지 않음")

    # cash_after 단조 흐름 점검 (BUY → 감소, SELL/TRAILING_STOP → 증가)
    prev_cash: float | None = None
    for e in entries:
        cash = e.get("cash_after")
        action = e.get("action")
        if cash is None or not isinstance(cash, (int, float)):
            continue
        if prev_cash is not None:
            delta = cash - prev_cash
            is_buy = action == "BUY" or (isinstance(action, str) and action.startswith("BUY_"))
            is_sell = action in {"SELL", "TRAILING_STOP", "SCALE_OUT"} or (
                isinstance(action, str) and action.startswith("SELL_")
            )
            if is_buy and delta > 0:
                issues.append(f"BUY 인데 cash_after 가 증가 ({prev_cash}→{cash})")
            if is_sell and delta < 0:
                issues.append(f"{action} 인데 cash_after 가 감소 ({prev_cash}→{cash})")
        prev_cash = float(cash)

    if issues:
        for line in issues[:5]:
            messages.append(result("WARN", f"trade_log: {line}"))
    else:
        messages.append(result("OK", "trade_log 액션·정렬·cash 흐름 무결성 확인"))


def audit_weekly_alignment(data: dict[str, object], messages: list[str]) -> None:
    policy = data.get("config/policy.json") or {}
    weekly = data.get("config/weekly_plan.json") or {}
    portfolio = data.get("config/portfolio.json") or {}

    risk = policy.get("risk", {}) if isinstance(policy, dict) else {}
    objective = weekly.get("objective", {}) if isinstance(weekly, dict) else {}
    required = [
        "weekly_account_target_return_pct",
        "max_weekly_drawdown_pct",
        "max_single_trade_risk_pct_of_equity",
        "dynamic_exit_model",
    ]
    missing = [k for k in required if k not in risk]
    if missing:
        messages.append(result("FAIL", "policy.risk missing weekly fields: " + ", ".join(missing)))
    else:
        messages.append(result("OK", "policy.risk has weekly/dynamic exit controls"))

    current_equity = portfolio.get("equity")
    target_equity = objective.get("target_equity")
    weekly_equity = objective.get("current_equity")
    if isinstance(current_equity, (int, float)) and isinstance(target_equity, (int, float)):
        gap = target_equity - current_equity
        messages.append(result("INFO", f"weekly target gap from portfolio equity: {gap:,.0f} KRW"))
        if isinstance(weekly_equity, (int, float)) and abs(weekly_equity - current_equity) > 1:
            messages.append(result("WARN", "weekly_plan objective.current_equity differs from portfolio.equity"))
    else:
        messages.append(result("WARN", "cannot compute weekly target gap"))

    theses = weekly.get("weekly_thesis", []) if isinstance(weekly, dict) else []
    if not theses:
        messages.append(result("FAIL", "weekly_plan.weekly_thesis is empty"))
    else:
        missing_linkage = [t.get("id", "?") for t in theses if not t.get("daily_linkage")]
        if missing_linkage:
            messages.append(result("WARN", "weekly theses missing daily_linkage: " + ", ".join(missing_linkage)))
        else:
            messages.append(result("OK", f"weekly_plan has {len(theses)} linked theses"))


def audit_reconciliation(messages: list[str]) -> None:
    """reconcile_portfolio.py 를 subprocess 로 실행하여 정합성 점검 결과를 audit 로 흡수."""
    script = ROOT / "scripts" / "reconcile_portfolio.py"
    if not script.exists():
        return
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        messages.append(result("WARN", "reconcile_portfolio output 파싱 실패"))
        return
    issues = payload.get("issues", [])
    if proc.returncode == 0 and not issues:
        messages.append(result("OK", "trade_log ↔ portfolio.json 정합성 확인"))
    else:
        for issue in issues[:5]:
            messages.append(result("FAIL", f"reconcile: {issue}"))
        if not issues and proc.returncode != 0:
            messages.append(result("WARN", "reconcile 비정상 종료 (issue 미보고)"))


def holding_rr_threshold(policy: dict) -> tuple[float, str]:
    """보유 R/R 검토 임계 — 레짐 적응 하한(min_rr_by_tier)을 진입과 동일하게 따른다.

    고정 1.2 는 strong_bull 에서 승자 조기 청산 압력(6/10 구조 진단의 '조기청산 비용')을
    만들어 v2.11 과 모순 — tier 미확정/allocation 부재 시에만 review_holding_if_rr_below 폴백.
    """
    rrm = policy.get("reward_risk_management", {}) if isinstance(policy, dict) else {}
    fallback = rrm.get("review_holding_if_rr_below", 1.2) if isinstance(rrm, dict) else 1.2
    adaptive = rrm.get("regime_adaptive_rr", {}) if isinstance(rrm, dict) else {}
    by_tier = adaptive.get("min_rr_by_tier", {}) if isinstance(adaptive, dict) else {}
    if not (isinstance(adaptive, dict) and adaptive.get("enabled") and isinstance(by_tier, dict)):
        return float(fallback), "고정"
    try:
        allocation = read_json(ROOT / "state" / "allocation.json")
    except (OSError, json.JSONDecodeError):
        return float(fallback), "고정(allocation 부재)"
    tier = allocation.get("effective_tier") or allocation.get("tier")
    threshold = by_tier.get(tier)
    if isinstance(threshold, (int, float)):
        return float(threshold), f"tier={tier}"
    return float(fallback), "고정(tier 미확정)"


def audit_reward_risk(data: dict[str, object], messages: list[str]) -> None:
    """보유 종목의 R/R 하한 미달 여부 점검 — 레짐 적응 하한(진입과 동일 기준)."""
    policy = data.get("config/policy.json") or {}
    portfolio = data.get("config/portfolio.json") or {}
    watchlist = data.get("config/watchlist.json") or {}
    if not isinstance(policy, dict) or not isinstance(portfolio, dict) or not isinstance(watchlist, dict):
        return
    threshold, basis = holding_rr_threshold(policy)

    flagged: list[str] = []
    for pos in portfolio.get("positions", []):
        if not isinstance(pos, dict):
            continue
        ticker = pos.get("ticker")
        current = pos.get("current_price_approx")
        target = pos.get("target_price")
        stop = pos.get("stop_price")
        if not all(isinstance(v, (int, float)) for v in (current, target, stop)):
            continue
        if current <= stop or current >= target:
            continue
        rr = (target - current) / (current - stop)
        if rr < threshold:
            flagged.append(f"{ticker} R/R={rr:.2f}<{threshold}")
    if flagged:
        messages.append(result(
            "WARN",
            f"R/R 하한({threshold}, {basis}) 미만 보유 종목 — 18시에 목표가/손절가 재조정 필요: " + ", ".join(flagged),
        ))
    else:
        messages.append(result("OK", f"보유 종목 모두 R/R 하한({threshold}, {basis}) 이상"))


def audit_thesis(data: dict[str, object], messages: list[str]) -> None:
    """watchlist.stocks[].thesis(thesis-tracker, Part B) 스키마·enum 정합 점검."""
    policy = data.get("config/policy.json") or {}
    watchlist = data.get("config/watchlist.json") or {}
    if not isinstance(policy, dict) or not isinstance(watchlist, dict):
        return
    cfg = policy.get("thesis", {}) if isinstance(policy.get("thesis"), dict) else {}
    if not cfg.get("enabled", True):
        return
    type_enum = set(cfg.get("invalidation_type_enum", ["매크로", "섹터", "개별", "가정오류"]))
    status_enum = set(cfg.get("status_enum", ["intact", "weakening", "invalidated"]))
    stocks = [s for s in watchlist.get("stocks", []) if isinstance(s, dict)]
    held = [s for s in stocks if (s.get("shares_held") or 0) > 0]
    with_thesis = [s for s in stocks if isinstance(s.get("thesis"), dict)]
    problems: list[str] = []
    for s in with_thesis:
        th = s["thesis"]
        tk = s.get("ticker", "?")
        if th.get("status") not in status_enum:
            problems.append(f"{tk} status={th.get('status')}")
        for inv in th.get("invalidation", []):
            if not isinstance(inv, dict):
                problems.append(f"{tk} invalidation 항목 형식 오류")
                continue
            if inv.get("type") not in type_enum:
                problems.append(f"{tk} invalidation.type={inv.get('type')}")
            if not isinstance(inv.get("hard"), bool):
                problems.append(f"{tk} invalidation.hard 비불리언")
    held_no_thesis = [s.get("ticker") for s in held if not isinstance(s.get("thesis"), dict)]
    if problems:
        messages.append(result("FAIL", "watchlist thesis 스키마 오류: " + "; ".join(problems)))
    if held_no_thesis:
        messages.append(result("WARN", "보유 종목 thesis 누락 — 09시에 작성 필요: " + ", ".join(map(str, held_no_thesis))))
    if with_thesis and not problems:
        messages.append(result("OK", f"watchlist thesis-tracker {len(with_thesis)}종목 스키마 정상"))
    elif not with_thesis:
        messages.append(result("WARN", "watchlist thesis 미설정 — thesis-tracker 비활성(옵셔널)"))


def audit_target_consensus(data: dict[str, object], messages: list[str]) -> None:
    """보유 종목 우리 목표가 ↔ 컨센 목표주가 교차검증 (policy.consensus.target_cross_check)."""
    policy = data.get("config/policy.json") or {}
    watchlist = data.get("config/watchlist.json") or {}
    if not isinstance(policy, dict) or not isinstance(watchlist, dict):
        return
    cc = (policy.get("consensus", {}) or {}).get("target_cross_check", {})
    if not isinstance(cc, dict) or not cc.get("enabled", False):
        return
    ceiling = cc.get("ceiling_multiple", 1.15)
    cons_path = ROOT / "state" / "consensus.json"
    if not cons_path.exists():
        return
    try:
        cons = json.loads(cons_path.read_text(encoding="utf-8")).get("tickers", {})
    except Exception:  # noqa: BLE001
        return
    over: list[str] = []
    for s in watchlist.get("stocks", []):
        if not isinstance(s, dict) or (s.get("shares_held") or 0) <= 0:
            continue
        our = s.get("target_price")
        c = cons.get(s.get("ticker"), {})
        ctp = c.get("target_price")
        if not isinstance(our, (int, float)) or not isinstance(ctp, (int, float)) or ctp <= 0:
            continue
        if c.get("stale") or (c.get("baseline", {}) or {}).get("confidence") == "low":
            continue
        if our > ctp * ceiling:
            over.append(f"{s.get('ticker')} 우리 {our:,.0f} > 컨센 {ctp:,.0f}×{ceiling}")
    if over:
        messages.append(result("WARN", "목표가 컨센 상한 초과(근거 명시 또는 상한 적용 필요): " + "; ".join(over)))
    else:
        messages.append(result("OK", "보유 종목 목표가 컨센 교차검증 통과(또는 컨센 미확보)"))


def audit_recovery_stage(data: dict[str, object], messages: list[str]) -> None:
    """누적 수익률 기준 회복 전략 단계 판정 (policy.weekly_recovery_plan).

    policy.weekly_recovery_plan.stages 의 각 stage 는
    `weekly_cumulative_return_pct_floor` (해당 stage 가 적용되는 누적 수익률의 하한선) 을 가진다.
    예: normal floor=-2.0 → 누적 ≥ -2.0% 이면 normal
        caution floor=-3.5 → -3.5% ≤ 누적 < -2.0% 이면 caution
        defensive floor=-5.0 → 누적 < -3.5% 이면 defensive (defensive 의 floor 는 더 하향 강등 시 사용)

    floor 가 가장 높은 stage 부터 내려가며 누적이 그 floor 이상이면 매칭.
    """
    policy = data.get("config/policy.json") or {}
    weekly = data.get("config/weekly_plan.json") or {}
    if not isinstance(policy, dict) or not isinstance(weekly, dict):
        return
    plan = policy.get("weekly_recovery_plan", {})
    if not isinstance(plan, dict):
        return
    stages = plan.get("stages", [])
    objective = weekly.get("objective", {}) if isinstance(weekly.get("objective"), dict) else {}
    starting_equity = as_number_simple(objective.get("starting_equity"))
    current_equity = as_number_simple(objective.get("current_equity"))
    if not starting_equity or not current_equity:
        messages.append(result("WARN", "recovery_stage 판정 불가 — starting/current equity 누락"))
        return
    cumulative_pct = (current_equity - starting_equity) / starting_equity * 100

    # floor 내림차순 정렬 (입력 순서 의존성 제거)
    valid_stages = [
        s for s in stages
        if isinstance(s, dict) and isinstance(s.get("weekly_cumulative_return_pct_floor"), (int, float))
    ]
    valid_stages.sort(key=lambda s: s["weekly_cumulative_return_pct_floor"], reverse=True)

    chosen = valid_stages[-1].get("stage", "defensive") if valid_stages else "normal"
    for stage in valid_stages:
        floor = stage["weekly_cumulative_return_pct_floor"]
        if cumulative_pct >= floor:
            chosen = stage.get("stage", chosen)
            break

    if chosen == "normal":
        messages.append(result("INFO", f"recovery_stage=normal (누적 {cumulative_pct:+.2f}%)"))
    else:
        messages.append(result("WARN", f"recovery_stage={chosen} (누적 {cumulative_pct:+.2f}%) — 신규 진입·비중·후보 검색 자동 축소 적용 필요"))


def as_number_simple(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def audit_market_data_tooling(messages: list[str]) -> None:
    """fetch_market_data.py·check_market_open.py·check_market_session.py 및 그 입력 설정의 무결성 확인."""
    fetch = ROOT / "scripts" / "fetch_market_data.py"
    check = ROOT / "scripts" / "check_market_open.py"
    session_check = ROOT / "scripts" / "check_market_session.py"
    score = ROOT / "scripts" / "score_candidates.py"
    allocation = ROOT / "scripts" / "compute_allocation.py"
    fundamentals_script = ROOT / "scripts" / "fetch_fundamentals.py"
    catalysts_script = ROOT / "scripts" / "fetch_catalysts.py"
    consensus_script = ROOT / "scripts" / "fetch_consensus.py"
    reconcile = ROOT / "scripts" / "reconcile_portfolio.py"
    pre_trade = ROOT / "scripts" / "pre_trade_check.py"
    trade_gate = ROOT / "scripts" / "check_trade_log_gate.py"
    lessons_idx = ROOT / "scripts" / "build_lessons_index.py"
    lessons_applied = ROOT / "scripts" / "check_lessons_applied.py"
    intraday_alerts = ROOT / "scripts" / "check_intraday_alerts.py"
    candidates = ROOT / "config" / "candidates.json"
    themes = ROOT / "config" / "themes.json"
    calendar = ROOT / "config" / "market_calendar.json"
    catalysts = ROOT / "config" / "catalysts.json"
    for path, label in [
        (fetch, "scripts/fetch_market_data.py"),
        (catalysts_script, "scripts/fetch_catalysts.py"),
        (consensus_script, "scripts/fetch_consensus.py"),
        (check, "scripts/check_market_open.py"),
        (session_check, "scripts/check_market_session.py"),
        (score, "scripts/score_candidates.py"),
        (allocation, "scripts/compute_allocation.py"),
        (fundamentals_script, "scripts/fetch_fundamentals.py"),
        (reconcile, "scripts/reconcile_portfolio.py"),
        (pre_trade, "scripts/pre_trade_check.py"),
        (trade_gate, "scripts/check_trade_log_gate.py"),
        (lessons_idx, "scripts/build_lessons_index.py"),
        (lessons_applied, "scripts/check_lessons_applied.py"),
        (intraday_alerts, "scripts/check_intraday_alerts.py"),
    ]:
        if path.exists():
            messages.append(result("OK", f"{label} present"))
        else:
            messages.append(result("FAIL", f"missing {label}"))
    if candidates.exists():
        try:
            payload = json.loads(candidates.read_text(encoding="utf-8"))
            count = len(payload.get("candidates", []))
            messages.append(result("OK", f"config/candidates.json tracks {count} candidates"))
        except Exception as exc:  # noqa: BLE001
            messages.append(result("FAIL", f"config/candidates.json parse failed: {exc}"))
    else:
        messages.append(result("WARN", "config/candidates.json missing — 신규 후보 자동 발굴 비활성"))
    if themes.exists():
        try:
            payload = json.loads(themes.read_text(encoding="utf-8"))
            count = len(payload.get("themes", []))
            messages.append(result("OK", f"config/themes.json tracks {count} themes (thematic 점수)"))
        except Exception as exc:  # noqa: BLE001
            messages.append(result("FAIL", f"config/themes.json parse failed: {exc}"))
    else:
        messages.append(result("WARN", "config/themes.json missing — thematic 점수 비활성(0.3 중립 폴백)"))
    if calendar.exists():
        try:
            payload = json.loads(calendar.read_text(encoding="utf-8"))
            year_key = f"holidays_{datetime.now(KST).year}"
            holiday_list = payload.get(year_key)
            if holiday_list is None:
                messages.append(result("WARN", f"config/market_calendar.json 에 {year_key} 없음 — 올해 휴장일 가드 무력화(연도별 갱신 필요)"))
            else:
                messages.append(result("OK", f"config/market_calendar.json lists {len(holiday_list)} holidays ({year_key})"))
        except Exception as exc:  # noqa: BLE001
            messages.append(result("FAIL", f"config/market_calendar.json parse failed: {exc}"))
    else:
        messages.append(result("WARN", "config/market_calendar.json missing — 휴장일 가드 비활성"))
    if catalysts.exists():
        try:
            payload = json.loads(catalysts.read_text(encoding="utf-8"))
            gen = payload.get("generated_events", [])
            man = payload.get("manual_events", [])
            if not isinstance(gen, list) or not isinstance(man, list):
                messages.append(result("FAIL", "config/catalysts.json: generated_events/manual_events 는 배열이어야 함"))
            else:
                today = datetime.now(KST).date().isoformat()
                stale_gen = [e for e in gen if isinstance(e, dict) and e.get("date", "") < today]
                bad = [e for e in (gen + man) if not isinstance(e, dict) or "date" not in e or "type" not in e]
                if bad:
                    messages.append(result("WARN", f"config/catalysts.json: date/type 누락 이벤트 {len(bad)}건"))
                if stale_gen:
                    messages.append(result("WARN",
                        f"config/catalysts.json: 경과한 generated 이벤트 {len(stale_gen)}건 — fetch_catalysts.py 재실행 권장"))
                messages.append(result("OK",
                    f"config/catalysts.json tracks {len(gen)} generated + {len(man)} manual catalysts"))
        except Exception as exc:  # noqa: BLE001
            messages.append(result("FAIL", f"config/catalysts.json parse failed: {exc}"))
    else:
        messages.append(result("WARN", "config/catalysts.json missing — 촉매 캘린더 비활성(옵셔널)"))
    consensus = ROOT / "state" / "consensus.json"
    if consensus.exists():
        try:
            payload = json.loads(consensus.read_text(encoding="utf-8"))
            tks = payload.get("tickers", {})
            ok = payload.get("fetched_ok", 0)
            if not isinstance(tks, dict):
                messages.append(result("FAIL", "state/consensus.json: tickers 는 객체여야 함"))
            elif ok == 0 and tks:
                messages.append(result("WARN",
                    "state/consensus.json: fetched_ok=0 — FnGuide 수집 실패(전부 stale). Phase 2 입력 점검 필요"))
            else:
                messages.append(result("OK", f"state/consensus.json: {ok}/{len(tks)} 종목 컨센 수집"))
        except Exception as exc:  # noqa: BLE001
            messages.append(result("FAIL", f"state/consensus.json parse failed: {exc}"))
    else:
        messages.append(result("WARN", "state/consensus.json missing — 컨센서스 레이어 비활성(Phase 2 입력)"))
    epreview = ROOT / "state" / "earnings_preview.json"
    espec = ROOT / "prompts" / "earnings_preview.md"
    if epreview.exists():
        try:
            payload = json.loads(epreview.read_text(encoding="utf-8"))
            act = payload.get("active", [])
            sc = payload.get("scorecard", [])
            if not isinstance(act, list) or not isinstance(sc, list):
                messages.append(result("FAIL", "state/earnings_preview.json: active/scorecard 는 배열이어야 함"))
            else:
                spec_ok = "present" if espec.exists() else "MISSING(prompts/earnings_preview.md)"
                messages.append(result("OK",
                    f"state/earnings_preview.json: active={len(act)} scored={len(sc)} (spec {spec_ok})"))
        except Exception as exc:  # noqa: BLE001
            messages.append(result("FAIL", f"state/earnings_preview.json parse failed: {exc}"))
    else:
        messages.append(result("WARN", "state/earnings_preview.json missing — earnings-preview(Phase 2) 비활성(옵셔널)"))


def audit_prompts_and_scripts(messages: list[str]) -> None:
    required_prompts = [
        "0000_global.md",
        "0630_us_close.md",
        "0900_pre_market.md",
        "1200_midday.md",
        "1500_close.md",
        "1800_report.md",
        "saturday_review.md",
        "sunday_strategy.md",
        "sunday_archive.md",
        "sunday_policy_review.md",
        "weekend_report.md",
    ]
    for name in required_prompts:
        path = ROOT / "prompts" / name
        if not path.exists():
            messages.append(result("FAIL", f"missing prompt: prompts/{name}"))
            continue
        text = path.read_text(encoding="utf-8")
        if name != "weekend_report.md" and "weekly_plan.json" not in text:
            messages.append(result("WARN", f"prompts/{name} does not reference weekly_plan.json"))
        else:
            messages.append(result("OK", f"prompts/{name} present"))

    run_prompt = (ROOT / "scripts" / "run_prompt.ps1").read_text(encoding="utf-8")
    if "C:\\Users\\zzxx7" in run_prompt:
        messages.append(result("FAIL", "run_prompt.ps1 still contains old hard-coded user path"))
    elif "saturday_review" in run_prompt and "sunday_strategy" in run_prompt and "0000_global" in run_prompt:
        messages.append(result("OK", "run_prompt.ps1 supports 00:30 and split weekend prompts"))
    else:
        messages.append(result("WARN", "run_prompt.ps1 may not support all prompt slots"))

    register = (ROOT / "scripts" / "register_tasks.ps1").read_text(encoding="utf-8")
    if "C:\\Users\\zzxx7" in register:
        messages.append(result("FAIL", "register_tasks.ps1 still contains old hard-coded user path"))
    elif "saturday_review" in register and "sunday_strategy" in register and "0000_global" in register:
        messages.append(result("OK", "register_tasks.ps1 supports 00:30 and split weekend schedules"))
    else:
        messages.append(result("WARN", "register_tasks.ps1 may not schedule all slots"))


# '한눈에 보기'(카톡 발송부)에 노출되면 안 되는 운영 용어 — 리포트 가독성 원칙 §3 의 기계 점검.
# 행동을 바꾼 요인은 사람 말로 녹여 쓰는 것이 규칙이며, 게이트/내부 지표 명칭 노출은 WARN.
GLANCE_BANNED_TOKENS = [
    "live_verify", "web_verify", "pre_trade", "resync", "HTTP 403",
    "freshness", "snapshot_age", "tier=", "stale", "mark-to-market", "time_stop", "§",
]


def _holidays_map() -> dict[str, str]:
    """market_calendar.json 의 holidays_<YYYY> 연도 키를 전부 병합해 {date: name} 으로 반환.
    (기존 버그 수정: 'holidays' 라는 존재하지 않는 키를 읽어 공휴일 판정이 항상 무력화돼 있었다.)"""
    try:
        calendar = read_json(ROOT / "config" / "market_calendar.json")
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(calendar, dict):
        return {}
    merged: dict[str, str] = {}
    for key, value in calendar.items():
        if isinstance(key, str) and key.startswith("holidays_") and isinstance(value, list):
            for h in value:
                if isinstance(h, dict) and h.get("date"):
                    merged[str(h["date"])] = str(h.get("name", "공휴일"))
                elif isinstance(h, str):
                    merged[h] = "공휴일"
    return merged


def is_business_day(target) -> bool:
    """주말 + market_calendar.json 휴장일 판정 (의존성 0 유지 — check_market_open 로직 축약)."""
    if target.weekday() >= 5:
        return False
    return target.isoformat() not in _holidays_map()


def is_business_day_today() -> bool:
    return is_business_day(datetime.now(KST).date())


def extract_glance_block(text: str) -> str:
    """'### 한눈에 보기' 섹션 본문만 추출 (다음 ###/## 헤더 전까지)."""
    m = re.search(r"^###\s*한눈에 보기.*?$", text, re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^#{2,3}\s", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def audit_reports(messages: list[str]) -> None:
    all_reports = sorted((ROOT / "reports").glob("*.md"))
    # 시간대별 분리 파일(YYYY-MM-DD-{00,06,09,12,15,18}.md) 및 구버전 단일 파일(YYYY-MM-DD.md) 모두 인식
    reports = [
        path for path in all_reports
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-(?:00|06|09|12|15|18))?\.md", path.name)
    ]
    if not reports:
        messages.append(result("WARN", "no daily reports found"))
        return
    # 시간대별 분리 파일이 있으면 그것 우선 검사
    latest = reports[-1]
    text = latest.read_text(encoding="utf-8")
    messages.append(result("INFO", f"latest daily report: {latest.name}"))
    # 구버전 단일 파일에만 자리표시자가 존재
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", latest.name) and "(아래는" in text:
        messages.append(result("WARN", f"{latest.name} still has routine placeholders"))
    if not re.search(r"본 산출물은 학습|실제 투자", text):
        messages.append(result("WARN", f"{latest.name} may be missing disclaimer language"))

    # ---- 오늘자 파일 한정 점검 (과거 리포트는 불변 히스토리 — 소급 경고 금지) ----
    today_str = datetime.now(KST).date().isoformat()
    today_files = [p for p in reports if p.name.startswith(today_str)]

    # (1) 00시 슬롯 누락 — 월요일 00시 routine 미발화가 3주 연속 관측됨(2026-05-25·06-01·06-08).
    #     등록은 레포 밖(claude.ai routines)이라 여기서는 표면화만 한다.
    if is_business_day_today() and today_files and not (ROOT / "reports" / f"{today_str}-00.md").exists():
        messages.append(result(
            "WARN",
            f"reports/{today_str}-00.md 누락 — 00시(자정 글로벌) routine 등록/실행 확인 필요",
        ))

    # (2) 카톡 발송부('한눈에 보기') 운영 용어 노출 점검 — 오늘 생성분만.
    leaked: list[str] = []
    for p in today_files:
        glance = extract_glance_block(p.read_text(encoding="utf-8"))
        if not glance:
            continue
        tokens = sorted({tok for tok in GLANCE_BANNED_TOKENS if tok in glance})
        if tokens:
            leaked.append(f"{p.name}({', '.join(tokens)})")
    if leaked:
        messages.append(result(
            "WARN",
            "리포트 '한눈에 보기'에 운영 용어 노출(가독성 원칙 §3 — 사람 말로 풀어쓸 것): " + "; ".join(leaked),
        ))


SLOT_MATRIX_06_SINCE = "2026-07-02"  # 06시 슬롯 신설일 — 이전 날짜는 06 부재를 따지지 않는다


def audit_slot_matrix(messages: list[str]) -> None:
    """지난 7일(어제~D-7) 슬롯·주말 산출물 발화 매트릭스 (plan_hourly_report_gap_fix Phase 1-1).

    기존 감사는 '당일 00시 부재' 1종만 봐서 주간 아카이브 3주 사망(W24~W26)·주말 루틴 미발화를
    아무도 감지하지 못했다. 여기서는 완결된 날짜(어제까지)만 검사해 장중 push 오탐을 피한다.
    관측 전용 — WARN/INFO 만 내고 FAIL 은 내지 않는다(빌드 차단 금지).
    """
    reports_dir = ROOT / "reports"
    today = datetime.now(KST).date()
    holidays = _holidays_map()
    missing_days: list[str] = []
    missing_06: list[str] = []
    for back in range(1, 8):
        d = today - timedelta(days=back)
        ds = d.isoformat()
        missing: list[str] = []
        wd = d.weekday()
        if wd < 5:  # 평일
            if ds in holidays:
                # 휴장 평일: 00(무가드)·09(축약 의무 생성)·18(축약 모드)은 기대, 12/15는 프롬프트가 생략 허용
                expected = ("00", "09", "18")
            else:
                expected = ("00", "09", "12", "15", "18")
            for hh in expected:
                if not (reports_dir / f"{ds}-{hh}.md").exists():
                    missing.append(f"{hh}시")
            if not (reports_dir / f"{ds}-audit.md").exists():
                missing.append("audit")
            if ds >= SLOT_MATRIX_06_SINCE and not (reports_dir / f"{ds}-06.md").exists():
                missing_06.append(ds)
        elif wd == 5:  # 토요일 — 00시(매일 발화) + 사후분석
            if not (reports_dir / f"{ds}-00.md").exists():
                missing.append("00시")
            if not (reports_dir / f"{ds}-saturday-review.md").exists():
                missing.append("saturday-review")
        else:  # 일요일 — 00시 + 전략 + 정책리뷰 + 주간 아카이브(그 주 ISO 주차)
            if not (reports_dir / f"{ds}-00.md").exists():
                missing.append("00시")
            if not (reports_dir / f"{ds}-sunday-strategy.md").exists():
                missing.append("sunday-strategy")
            if not (reports_dir / f"{ds}-policy-review.md").exists():
                missing.append("policy-review")
            iso = d.isocalendar()
            archive_name = f"{iso[0]}-W{iso[1]:02d}-archive.md"
            if not (reports_dir / archive_name).exists():
                missing.append(f"주간아카이브({archive_name})")
        if missing:
            missing_days.append(f"{ds}: {', '.join(missing)}")
    if missing_days:
        messages.append(result(
            "WARN",
            "슬롯 산출물 누락(지난 7일): " + "; ".join(missing_days)
            + " — 루틴 미발화 의심, claude.ai/code/routines 등록 상태 확인",
        ))
    else:
        messages.append(result("OK", "지난 7일 슬롯·주말 산출물 매트릭스 결손 없음"))
    if missing_06:
        messages.append(result("INFO", "06시 리포트 부재(시행 초기 관찰 — 2주 후 WARN 승격 예정): " + ", ".join(missing_06)))


def audit_state_schema(messages: list[str]) -> None:
    """LLM 이 손으로 쓰는 state 파일의 스키마 검증 (plan_hourly_report_gap_fix Phase 1-5).

    check_state_schema.py 를 subprocess 로 실행(체크 자체는 의존성 0 유지)해 위반을 WARN 으로 흡수.
    형식이 어긋난 예측은 채점 스크립트가 조용히 스킵하는 무음 실패가 되므로 표면화가 목적이다.
    """
    script = ROOT / "scripts" / "check_state_schema.py"
    if not script.exists():
        messages.append(result("WARN", "scripts/check_state_schema.py missing — state 스키마 게이트 비활성"))
        return
    try:
        proc = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        payload = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        messages.append(result("WARN", f"state 스키마 검사 실행 실패: {exc}"))
        return
    violations = payload.get("violations", [])
    if violations:
        detail = "; ".join(str(v) for v in violations[:6])
        more = f" 외 {len(violations) - 6}건" if len(violations) > 6 else ""
        messages.append(result("WARN", f"state 스키마 위반(채점 누락 위험): {detail}{more}"))
    else:
        messages.append(result("OK", "state 스키마 정상 (inference_log·pending_orders·weekly_plan)"))


# 핫패스 파일 크기 상한 — 초과 시 콘텍스트 오버 위험 (docs/plan_context_compaction.md 진단 근거).
CONTEXT_BUDGET = {
    "config/watchlist.json": {"max_bytes": 100_000, "max_lines": 1_500},
    "config/policy.json": {"max_bytes": 95_000},
    "config/weekly_plan.json": {"max_bytes": 35_000},
    "state/lessons.md": {"max_bytes": 60_000},
    "state/inference_checklist.md": {"max_bytes": 4_000, "max_lines": 40},
}
PROMPT_INFO_BYTES = 35_000   # 참고 표시(성장 추적)
PROMPT_WARN_BYTES = 60_000   # 경고 — 프롬프트 감량 필요


def audit_context_budget(data: dict[str, object], messages: list[str]) -> None:
    """매 routine 이 의무 적재하는 핫패스 파일의 크기 래칫 감시.

    매매 룰 래칫(blocked_day_rate)과 동형의 '콘텍스트 래칫' 안전장치 — 무한 누적 필드가
    다시 자라면 compact_state.py 실행(또는 정책 검토)을 촉구한다.
    """
    over: list[str] = []
    for rel, limits in CONTEXT_BUDGET.items():
        path = ROOT / rel
        if not path.exists():
            continue
        size = path.stat().st_size
        if size > limits.get("max_bytes", float("inf")):
            over.append(f"{rel} {size:,}B>{limits['max_bytes']:,}B")
            continue
        max_lines = limits.get("max_lines")
        if max_lines:
            n_lines = path.read_text(encoding="utf-8").count("\n") + 1
            if n_lines > max_lines:
                over.append(f"{rel} {n_lines:,}줄>{max_lines:,}줄")

    weekly = data.get("config/weekly_plan.json")
    if isinstance(weekly, dict) and len(weekly.get("watch_items") or []) > 20:
        over.append(f"weekly_plan.watch_items {len(weekly['watch_items'])}개>20개")
    portfolio = data.get("config/portfolio.json")
    if isinstance(portfolio, dict) and len(portfolio.get("history") or []) > 20:
        over.append(f"portfolio.history {len(portfolio['history'])}건>20건")

    if over:
        messages.append(result(
            "WARN",
            "핫패스 콘텍스트 예산 초과 — scripts/compact_state.py 실행 필요: " + "; ".join(over),
        ))
    else:
        messages.append(result("OK", "핫패스 콘텍스트 예산(watchlist/policy/weekly_plan/lessons/history) 정상"))

    heavy = []
    for p in sorted((ROOT / "prompts").glob("*.md")):
        size = p.stat().st_size
        if size > PROMPT_WARN_BYTES:
            messages.append(result("WARN", f"프롬프트 감량 필요: prompts/{p.name} {size:,}B (상한 {PROMPT_WARN_BYTES:,}B)"))
        elif size > PROMPT_INFO_BYTES:
            heavy.append(f"{p.name} {size:,}B")
    if heavy:
        messages.append(result("INFO", "프롬프트 크기 추적: " + ", ".join(heavy) + f" (참고 기준 {PROMPT_INFO_BYTES:,}B)"))


def audit_inference_loop(messages: list[str]) -> None:
    """선제적 추론 루프(proactive_inference) 가동·채점 무결성 감시 (Phase 2).

    체크리스트 크기 래칫은 audit_context_budget 가 담당하고, 여기서는
    ①루프 가동(예측 적재) 여부 ②미채점 누적 ③high-confidence 적중률을 표면화한다.
    Phase 1(관측 시작 직후)의 0건은 정상 — INFO 로만 알린다(오탐 방지).
    """
    pol = load_json("config/policy.json")
    pi = (pol or {}).get("proactive_inference") if isinstance(pol, dict) else None
    if not isinstance(pi, dict) or not pi.get("enabled"):
        return  # 루프 비활성 — 감시 대상 아님

    log = ROOT / "state" / "inference_log.jsonl"
    n_pred = 0
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("_meta") and "prediction" in rec:
                n_pred += 1

    sc = load_json("state/inference_scorecard.json")
    scoring = (sc or {}).get("scoring") if isinstance(sc, dict) else None
    if n_pred == 0:
        messages.append(result("INFO", f"선제 추론 루프 Phase {pi.get('phase', '?')} — 예측 적재 대기(원장 0건, 다음 routine 부터 누적)"))
    elif isinstance(scoring, dict):
        n_scored = scoring.get("n_scored", 0)
        unscored = n_pred - n_scored
        if unscored >= 5:
            messages.append(result("WARN", f"선제 추론 미채점 누적 {unscored}건(예측 {n_pred}/채점 {n_scored}) — 18시·09시 채점 단계 점검"))
        else:
            messages.append(result("OK", f"선제 추론 루프 가동 — 예측 {n_pred}건/채점 {n_scored}건"))
        # high-confidence 적중률 — 공격(Tier2) 개방 자격 신호
        hi = (scoring.get("by_confidence_band") or {}).get("high")
        if isinstance(hi, dict) and not hi.get("status") and hi.get("hit_rate") is not None:
            hr = hi["hit_rate"]
            if hr < 0.5:
                messages.append(result("INFO", f"high-confidence 적중률 {hr:.0%}(<50%) — Tier2 공격 개방 보류 권고(action_ladder)"))
    else:
        messages.append(result("OK", f"선제 추론 루프 가동 — 예측 {n_pred}건"))


def audit_github_notify(messages: list[str]) -> None:
    workflow = ROOT / ".github" / "workflows" / "build_and_notify.yml"
    sender = ROOT / "scripts" / "send_kakao.py"
    if not workflow.exists():
        messages.append(result("FAIL", "GitHub workflow missing"))
        return
    w_text = workflow.read_text(encoding="utf-8")
    s_text = sender.read_text(encoding="utf-8") if sender.exists() else ""
    required = ["weekly:", "weekly-archive:", "audit:", "sat-review:", "sun-strategy:", "policy-review:"]
    missing = [prefix for prefix in required if prefix not in w_text or prefix not in s_text]
    if not missing:
        messages.append(result("OK", "audit and weekend report commits trigger Kakao notification"))
    else:
        messages.append(result("WARN", "notification triggers incomplete: " + ", ".join(missing)))


def audit_lessons_applied(messages: list[str]) -> None:
    """check_lessons_applied.py 를 실행 — lessons.md 의 자기-인지 미반영 교훈(명문화 필요·미적용 등 +
    반복 마커)이 policy/prompts 에 실제 반영됐는지 대조한다(v2.5).

    hard 미반영은 WARN 으로 표면화(자기보완 루프가 교훈을 드롭하던 갭을 매 감사에서 노출).
    하드 차단(FAIL)을 원하면 워크플로우에서 LESSONS_ENFORCE=1 로 이 스크립트를 별도 게이트로 돌린다.
    """
    script = ROOT / "scripts" / "check_lessons_applied.py"
    if not script.exists():
        messages.append(result("WARN", "scripts/check_lessons_applied.py 없음 — 교훈 반영 점검 비활성"))
        return
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    payload_path = ROOT / "state" / "lessons_applied.json"
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        messages.append(result("WARN", "lessons_applied.json 파싱 실패 — 교훈 반영 점검 건너뜀"))
        return
    hard = payload.get("open_items_hard", [])
    soft = payload.get("open_items_soft", [])
    manual = payload.get("open_items_manual", [])
    if hard:
        for it in hard[:3]:
            messages.append(result("WARN", f"교훈 미반영(반복): {it.get('section')} — policy/prompt 에 강제 필요"))
        if len(hard) > 3:
            messages.append(result("WARN", f"교훈 미반영(반복) 외 {len(hard) - 3}건 더 — state/lessons_applied.json 참조"))
    elif soft:
        messages.append(result("INFO", f"교훈 미반영(단발) {len(soft)}건 — sunday_policy_review 에서 검토"))
    else:
        messages.append(result("OK", "lessons.md 자기-인지 미반영(반복/단발) 교훈 없음"))
    if manual:
        messages.append(result("INFO", f"교훈 수동검토 {len(manual)}건(자동 검증 불가 앵커 부재) — sunday_policy_review 확인"))


def audit_trade_provenance(messages: list[str]) -> None:
    """check_trade_log_gate.py 를 subprocess 로 실행 — price_source 누락(묵은/미검증) + 장중 시간 밖 booking 을 FAIL 로 차단.

    위반이 있으면 [FAIL] 을 남겨 audit_pipeline 이 exit 1 → build_and_notify 빌드 실패로 가시화한다.
    """
    script = ROOT / "scripts" / "check_trade_log_gate.py"
    if not script.exists():
        messages.append(result("WARN", "scripts/check_trade_log_gate.py 없음 — trade log 게이트 비활성"))
        return
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        messages.append(result("WARN", "check_trade_log_gate output 파싱 실패"))
        return
    violations = payload.get("violations", [])
    if proc.returncode == 0 and not violations:
        messages.append(
            result(
                "OK",
                f"trade log gate OK (provenance {payload.get('checked', 0)}건 "
                f"+ timing {payload.get('timing_checked', 0)}건 검증)",
            )
        )
    else:
        for v in violations[:5]:
            messages.append(result("FAIL", f"trade log gate: {v}"))
        if not violations and proc.returncode != 0:
            messages.append(result("WARN", "check_trade_log_gate 비정상 종료(violation 미보고)"))


def main() -> int:
    messages: list[str] = []
    messages.append(f"Pipeline audit @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    data = audit_json_files(messages)
    audit_trade_log(messages)
    audit_trade_provenance(messages)
    audit_lessons_applied(messages)
    audit_reconciliation(messages)
    audit_weekly_alignment(data, messages)
    audit_reward_risk(data, messages)
    audit_thesis(data, messages)
    audit_target_consensus(data, messages)
    audit_recovery_stage(data, messages)
    audit_market_data_tooling(messages)
    audit_prompts_and_scripts(messages)
    audit_reports(messages)
    audit_slot_matrix(messages)
    audit_state_schema(messages)
    audit_context_budget(data, messages)
    audit_inference_loop(messages)
    audit_github_notify(messages)

    print("\n".join(messages))
    return 1 if any(m.startswith("[FAIL]") for m in messages) else 0


if __name__ == "__main__":
    raise SystemExit(main())
