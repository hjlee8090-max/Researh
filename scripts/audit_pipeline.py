#!/usr/bin/env python3
"""Pipeline health audit for the KOSPI autoflow repository.

This script is intentionally dependency-free so Codex can run it locally and
GitHub Actions can run it without extra setup.
"""
from __future__ import annotations

import json
import re
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
    ]:
        path = ROOT / rel
        try:
            data[rel] = read_json(path)
            messages.append(result("OK", f"{rel} is valid JSON"))
        except Exception as exc:  # noqa: BLE001 - audit should report all parse failures
            messages.append(result("FAIL", f"{rel} is not valid JSON: {exc}"))
    return data


def audit_trade_log(messages: list[str]) -> None:
    path = ROOT / "state" / "trade_log.jsonl"
    if not path.exists():
        messages.append(result("WARN", "state/trade_log.jsonl is missing"))
        return
    bad = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            bad.append(f"line {idx}: {exc}")
    if bad:
        messages.append(result("FAIL", "trade_log has invalid JSONL entries: " + "; ".join(bad[:3])))
    else:
        messages.append(result("OK", f"trade_log JSONL is valid ({len(lines)} lines)"))


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


def audit_prompts_and_scripts(messages: list[str]) -> None:
    required_prompts = [
        "0000_global.md",
        "0900_pre_market.md",
        "1200_midday.md",
        "1500_close.md",
        "1800_report.md",
        "saturday_review.md",
        "sunday_strategy.md",
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
    reports = [
        path for path in all_reports
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", path.name)
    ]
    if not reports:
        messages.append(result("WARN", "no daily reports found"))
        return
    latest = reports[-1]
    text = latest.read_text(encoding="utf-8")
    messages.append(result("INFO", f"latest daily report: {latest.name}"))
    if "-weekend" not in latest.stem and "(아래는" in text:
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
    required = ["weekly:", "audit:", "sat-review:", "sun-strategy:"]
    missing = [prefix for prefix in required if prefix not in w_text or prefix not in s_text]
    if not missing:
        messages.append(result("OK", "audit and weekend report commits trigger Kakao notification"))
    else:
        messages.append(result("WARN", "notification triggers incomplete: " + ", ".join(missing)))


def main() -> int:
    messages: list[str] = []
    messages.append(f"Pipeline audit @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    data = audit_json_files(messages)
    audit_trade_log(messages)
    audit_weekly_alignment(data, messages)
    audit_prompts_and_scripts(messages)
    audit_reports(messages)
    audit_github_notify(messages)

    print("\n".join(messages))
    return 1 if any(m.startswith("[FAIL]") for m in messages) else 0


if __name__ == "__main__":
    raise SystemExit(main())
