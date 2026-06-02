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
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def result(level: str, message: str) -> str:
    return f"[{level}] {message}"


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


ALLOWED_TRADE_ACTIONS = {
    "BUY", "SELL", "HOLD", "EVAL", "EOD_EVAL", "OPEN_CHECK",
    "TRAILING_STOP", "SCALE_IN", "SCALE_OUT", "DEFERRED", "WATCH",
}


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
        for field in ("ts", "action", "ticker"):
            if field not in entry:
                issues.append(f"line {idx}: '{field}' 누락")
        action = entry.get("action")
        if action and action not in ALLOWED_TRADE_ACTIONS:
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
            if action == "BUY" and delta > 0:
                issues.append(f"BUY 인데 cash_after 가 증가 ({prev_cash}→{cash})")
            if action in {"SELL", "TRAILING_STOP", "SCALE_OUT"} and delta < 0:
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


def audit_reward_risk(data: dict[str, object], messages: list[str]) -> None:
    """보유 종목의 R/R 1.2 미달 여부를 점검 (policy.reward_risk_management 기준)."""
    policy = data.get("config/policy.json") or {}
    portfolio = data.get("config/portfolio.json") or {}
    watchlist = data.get("config/watchlist.json") or {}
    if not isinstance(policy, dict) or not isinstance(portfolio, dict) or not isinstance(watchlist, dict):
        return
    rrm = policy.get("reward_risk_management", {})
    threshold = rrm.get("min_reward_risk_ratio_for_new_entry", 1.2) if isinstance(rrm, dict) else 1.2

    stocks_by_ticker = {
        s.get("ticker"): s for s in watchlist.get("stocks", []) if isinstance(s, dict)
    }
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
        messages.append(result("WARN", "R/R 1.2 미만 보유 종목 — 18시에 목표가/손절가 재조정 필요: " + ", ".join(flagged)))
    else:
        messages.append(result("OK", "보유 종목 모두 R/R 임계(1.2) 이상"))


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
    reconcile = ROOT / "scripts" / "reconcile_portfolio.py"
    pre_trade = ROOT / "scripts" / "pre_trade_check.py"
    trade_gate = ROOT / "scripts" / "check_trade_log_gate.py"
    lessons_idx = ROOT / "scripts" / "build_lessons_index.py"
    candidates = ROOT / "config" / "candidates.json"
    themes = ROOT / "config" / "themes.json"
    calendar = ROOT / "config" / "market_calendar.json"
    for path, label in [
        (fetch, "scripts/fetch_market_data.py"),
        (check, "scripts/check_market_open.py"),
        (session_check, "scripts/check_market_session.py"),
        (score, "scripts/score_candidates.py"),
        (allocation, "scripts/compute_allocation.py"),
        (fundamentals_script, "scripts/fetch_fundamentals.py"),
        (reconcile, "scripts/reconcile_portfolio.py"),
        (pre_trade, "scripts/pre_trade_check.py"),
        (trade_gate, "scripts/check_trade_log_gate.py"),
        (lessons_idx, "scripts/build_lessons_index.py"),
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
            count = len(payload.get("holidays_2026", []))
            messages.append(result("OK", f"config/market_calendar.json lists {count} holidays"))
        except Exception as exc:  # noqa: BLE001
            messages.append(result("FAIL", f"config/market_calendar.json parse failed: {exc}"))
    else:
        messages.append(result("WARN", "config/market_calendar.json missing — 휴장일 가드 비활성"))


def audit_prompts_and_scripts(messages: list[str]) -> None:
    required_prompts = [
        "0000_global.md",
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


def audit_reports(messages: list[str]) -> None:
    all_reports = sorted((ROOT / "reports").glob("*.md"))
    # 시간대별 분리 파일(YYYY-MM-DD-{00,09,12,15,18}.md) 및 구버전 단일 파일(YYYY-MM-DD.md) 모두 인식
    reports = [
        path for path in all_reports
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-(?:00|09|12|15|18))?\.md", path.name)
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
    audit_reconciliation(messages)
    audit_weekly_alignment(data, messages)
    audit_reward_risk(data, messages)
    audit_recovery_stage(data, messages)
    audit_market_data_tooling(messages)
    audit_prompts_and_scripts(messages)
    audit_reports(messages)
    audit_github_notify(messages)

    print("\n".join(messages))
    return 1 if any(m.startswith("[FAIL]") for m in messages) else 0


if __name__ == "__main__":
    raise SystemExit(main())
