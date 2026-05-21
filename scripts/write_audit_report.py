#!/usr/bin/env python3
"""Run the pipeline audit, apply safe fixes, and write a human report."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def read_json(rel_path: str) -> dict[str, Any]:
    path = ROOT / rel_path
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def write_json(rel_path: str, data: dict[str, Any]) -> None:
    path = ROOT / rel_path
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def round_money(value: float) -> int:
    return int(round(value))


def round_pct(value: float) -> float:
    return round(value, 2)


def format_money(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return "확인 불가"
    return f"{round_money(number):,}원"


def format_pct(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return "확인 불가"
    return f"{number:.2f}%"


def values_differ(old: Any, new: Any) -> bool:
    old_num = as_number(old)
    new_num = as_number(new)
    if old_num is not None and new_num is not None:
        return abs(old_num - new_num) > 0.005
    return old != new


def set_if_changed(target: dict[str, Any], key: str, value: Any, fixes: list[str], label: str | None) -> None:
    if values_differ(target.get(key), value):
        target[key] = value
        if label and label not in fixes:
            fixes.append(label)


def auto_fix_weekly_plan(now: datetime) -> list[str]:
    """Fix only deterministic bookkeeping fields in weekly_plan.json."""
    fixes: list[str] = []

    try:
        policy = read_json("config/policy.json")
        portfolio = read_json("config/portfolio.json")
        weekly = read_json("config/weekly_plan.json")
    except Exception as exc:  # noqa: BLE001 - report should explain the blocker
        return [f"자동 수정 실패: 설정 파일을 읽을 수 없습니다. ({exc})"]

    before = json.dumps(weekly, ensure_ascii=False, sort_keys=True)
    risk = policy.get("risk", {}) if isinstance(policy.get("risk"), dict) else {}
    objective = weekly.setdefault("objective", {})
    if not isinstance(objective, dict):
        objective = {}
        weekly["objective"] = objective
        fixes.append("주간 목표 영역이 깨져 있어 다시 만들었습니다.")

    capital_plan = weekly.setdefault("capital_plan", {})
    if not isinstance(capital_plan, dict):
        capital_plan = {}
        weekly["capital_plan"] = capital_plan
        fixes.append("현금/투자 비중 영역이 깨져 있어 다시 만들었습니다.")

    portfolio_equity = as_number(portfolio.get("equity"))
    portfolio_cash = as_number(portfolio.get("cash"))
    initial_capital = as_number(portfolio.get("initial_capital"))
    starting_equity = as_number(objective.get("starting_equity")) or initial_capital or portfolio_equity
    target_return_pct = (
        as_number(risk.get("weekly_account_target_return_pct"))
        or as_number(objective.get("target_return_pct"))
        or 10.0
    )

    set_if_changed(weekly, "as_of", now.isoformat(timespec="seconds"), fixes, None)

    if starting_equity is not None:
        set_if_changed(objective, "starting_equity", round_money(starting_equity), fixes, "주간 시작 자산 기준을 확인했습니다.")
    if target_return_pct is not None:
        set_if_changed(objective, "target_return_pct", round_pct(target_return_pct), fixes, "주간 목표 수익률을 정책값과 맞췄습니다.")

    if starting_equity is not None and target_return_pct is not None:
        target_equity = round_money(starting_equity * (1 + target_return_pct / 100))
        set_if_changed(objective, "target_equity", target_equity, fixes, "주간 목표 금액을 다시 계산했습니다.")
    else:
        target_equity = as_number(objective.get("target_equity"))

    if portfolio_equity is not None:
        set_if_changed(objective, "current_equity", round_money(portfolio_equity), fixes, "주간 계획표의 현재 자산을 포트폴리오와 맞췄습니다.")
        if target_equity is not None:
            gap = round_money(float(target_equity) - portfolio_equity)
            set_if_changed(objective, "gap_to_target", gap, fixes, "목표까지 남은 금액을 다시 계산했습니다.")
            required = round_pct((gap / portfolio_equity) * 100) if portfolio_equity else 0.0
            set_if_changed(objective, "required_return_from_now_pct", required, fixes, "지금부터 필요한 수익률을 다시 계산했습니다.")

    max_weekly_drawdown = as_number(risk.get("max_weekly_drawdown_pct"))
    max_trade_risk = as_number(risk.get("max_single_trade_risk_pct_of_equity"))
    if max_weekly_drawdown is not None:
        set_if_changed(objective, "max_weekly_drawdown_pct", round_pct(max_weekly_drawdown), fixes, "주간 최대 손실 한도를 정책값과 맞췄습니다.")
    if max_trade_risk is not None:
        set_if_changed(objective, "max_single_trade_risk_pct_of_equity", round_pct(max_trade_risk), fixes, "한 번의 거래에서 감수할 손실 한도를 정책값과 맞췄습니다.")

    if portfolio_cash is not None:
        set_if_changed(capital_plan, "cash", round_money(portfolio_cash), fixes, "현금 보유액을 포트폴리오와 맞췄습니다.")
        if portfolio_equity and portfolio_equity > 0:
            cash_weight = round_pct((portfolio_cash / portfolio_equity) * 100)
            invested_weight = round_pct(max(0.0, 100 - cash_weight))
            set_if_changed(capital_plan, "cash_weight_pct", cash_weight, fixes, "현금 비중을 다시 계산했습니다.")
            set_if_changed(capital_plan, "invested_weight_pct", invested_weight, fixes, "투자 중인 비중을 다시 계산했습니다.")

    after = json.dumps(weekly, ensure_ascii=False, sort_keys=True)
    if before != after:
        write_json("config/weekly_plan.json", weekly)

    return fixes


def run_audit() -> tuple[str, list[str], int]:
    audit_script = ROOT / "scripts" / "audit_pipeline.py"
    proc = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    output = proc.stdout.strip()
    if proc.stderr.strip():
        output = (output + "\n" + proc.stderr.strip()).strip()
    lines = [line for line in output.splitlines() if line.strip()]
    return output, lines, proc.returncode


def classify(lines: list[str]) -> tuple[str, int, int, int]:
    fail = sum(1 for line in lines if line.startswith("[FAIL]"))
    warn = sum(1 for line in lines if line.startswith("[WARN]"))
    ok = sum(1 for line in lines if line.startswith("[OK]"))
    if fail:
        status = "FAIL"
    elif warn:
        status = "WARN"
    else:
        status = "OK"
    return status, ok, warn, fail


def status_label(status: str) -> str:
    return {
        "OK": "정상 - 자동화가 다음 루틴을 진행할 수 있습니다.",
        "WARN": "주의 - 루틴은 돌 수 있지만 확인하면 좋은 항목이 있습니다.",
        "FAIL": "문제 - 다음 루틴 전에 손봐야 할 항목이 있습니다.",
    }.get(status, status)


def humanize_audit_line(line: str) -> str:
    clean = line.replace("[WARN] ", "").replace("[FAIL] ", "").replace("[INFO] ", "")
    translations = [
        ("weekly target gap from portfolio equity", "포트폴리오 기준으로 주간 목표까지 남은 금액을 계산했습니다."),
        ("weekly_plan objective.current_equity differs from portfolio.equity", "주간 계획표의 현재 자산이 포트폴리오와 달랐습니다."),
        ("cannot compute weekly target gap", "목표까지 남은 금액을 계산할 수 없습니다. 현재 자산이나 목표 금액 숫자를 확인해야 합니다."),
        ("state/trade_log.jsonl is missing", "거래 기록 파일이 없습니다. 매매 이력을 쌓으려면 파일을 만들어야 합니다."),
        ("routine placeholders", "오늘 리포트에 아직 채워지지 않은 시간대가 있습니다. 해당 루틴이 지나기 전이면 정상입니다."),
        ("may be missing disclaimer language", "리포트에 투자 권유가 아니라는 안내 문구가 약할 수 있습니다."),
        ("notification triggers incomplete", "카카오 알림으로 이어지는 연결고리 중 일부가 빠져 있을 수 있습니다."),
        ("weekly theses missing daily_linkage", "주간 투자 가설과 데일리 리포트의 연결 설명이 부족합니다."),
        ("no daily reports found", "아직 데일리 리포트가 없습니다."),
    ]
    if clean.startswith("latest daily report:"):
        return f"최신 데일리 리포트를 확인했습니다: {clean.split(':', 1)[1].strip()}"
    for needle, text in translations:
        if needle in clean:
            if ":" in clean and needle == "weekly target gap from portfolio equity":
                amount = clean.split(":", 1)[1].strip().replace(" KRW", "원").replace("KRW", "원")
                return f"{text} 현재 부족분: {amount}"
            return text
    return clean


def load_weekly_snapshot() -> dict[str, Any]:
    try:
        weekly = read_json("config/weekly_plan.json")
        objective = weekly.get("objective", {}) if isinstance(weekly.get("objective"), dict) else {}
        capital_plan = weekly.get("capital_plan", {}) if isinstance(weekly.get("capital_plan"), dict) else {}
        return {
            "current_equity": objective.get("current_equity"),
            "target_equity": objective.get("target_equity"),
            "gap_to_target": objective.get("gap_to_target"),
            "required_return_from_now_pct": objective.get("required_return_from_now_pct"),
            "cash": capital_plan.get("cash"),
            "cash_weight_pct": capital_plan.get("cash_weight_pct"),
            "invested_weight_pct": capital_plan.get("invested_weight_pct"),
        }
    except Exception:
        return {}


def build_report(now: datetime, fixes: list[str], output: str, lines: list[str]) -> tuple[str, dict[str, Any]]:
    status, ok, warn, fail = classify(lines)
    snapshot = load_weekly_snapshot()
    important = [line for line in lines if line.startswith("[FAIL]") or line.startswith("[WARN]") or line.startswith("[INFO]")]
    remaining = [line for line in lines if line.startswith("[FAIL]") or line.startswith("[WARN]")]
    user_action = "없음" if not remaining else "아래 남은 주의사항을 확인"

    body = [
        f"# 파이프라인 자동 점검 리포트 - {now.strftime('%Y-%m-%d')}",
        "",
        f"> 마지막 점검: {now.strftime('%Y-%m-%d %H:%M')} KST",
        "> 이 리포트는 자동화 운영 점검용이며 실제 투자 권유가 아닙니다.",
        "",
        "## 요약",
        f"- 오늘 자동화 상태: {status_label(status)}",
        f"- 자동으로 고친 항목: {len(fixes)}건",
        f"- 남은 주의사항: {warn + fail}건",
        f"- 내가 지금 할 일: {user_action}",
        "",
        "## 자동으로 고친 것",
    ]

    if fixes:
        body.extend(f"- {fix}" for fix in fixes)
    else:
        body.append("- 자동으로 고칠 항목이 없었습니다.")

    body.extend(["", "## 아직 남은 주의사항"])
    if remaining:
        body.extend(f"- {humanize_audit_line(line)}" for line in remaining)
    else:
        body.append("- 남은 주의사항이 없습니다.")

    body.extend(
        [
            "",
            "## 숫자 확인",
            f"- 현재 자산: {format_money(snapshot.get('current_equity'))}",
            f"- 이번 주 목표 자산: {format_money(snapshot.get('target_equity'))}",
            f"- 목표까지 남은 금액: {format_money(snapshot.get('gap_to_target'))}",
            f"- 지금부터 필요한 수익률: {format_pct(snapshot.get('required_return_from_now_pct'))}",
            f"- 현금 비중: {format_pct(snapshot.get('cash_weight_pct'))}",
            f"- 투자 중인 비중: {format_pct(snapshot.get('invested_weight_pct'))}",
            "",
            "## 감사가 보는 것",
            "- 포트폴리오의 현재 자산과 주간 목표표가 서로 맞는지 확인합니다.",
            "- 목표까지 남은 금액과 필요한 수익률이 최신 숫자인지 확인합니다.",
            "- 데일리/주말 루틴, GitHub Pages, 카카오 알림 연결이 끊기지 않았는지 확인합니다.",
            "- 거래 기록과 리포트 파일이 읽을 수 있는 형태인지 확인합니다.",
            "",
            "## 이번 점검에서 확인한 신호",
        ]
    )

    if important:
        body.extend(f"- {humanize_audit_line(line)}" for line in important[:10])
    else:
        body.append("- 특별히 확인할 신호가 없습니다.")

    body.extend(
        [
            "",
            "## 개발자용 상세 로그",
            "```text",
            output,
            "```",
            "",
            "## 다음 액션",
        ]
    )
    if fail:
        body.append("- 문제 항목이 있어 다음 루틴 전에 설정 파일이나 자동화 연결을 수정해야 합니다.")
    elif warn:
        body.append("- 루틴은 계속 돌 수 있습니다. 주의사항이 반복되면 자동 수정 범위를 넓히거나 원인을 따로 고칩니다.")
    else:
        body.append("- 자동화 상태가 정상입니다. 다음 루틴 결과를 기다리면 됩니다.")

    log = {
        "ts": now.isoformat(),
        "status": status,
        "ok": ok,
        "warn": warn,
        "fail": fail,
        "auto_fixed": len(fixes),
        "report": f"reports/{now.strftime('%Y-%m-%d')}-audit.md",
    }
    return "\n".join(body) + "\n", log


def main() -> int:
    now = datetime.now(KST)
    fixes = auto_fix_weekly_plan(now)
    output, lines, _ = run_audit()

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"{now.strftime('%Y-%m-%d')}-audit.md"

    report, log = build_report(now, fixes, output, lines)
    report_path.write_text(report, encoding="utf-8")

    log_path = ROOT / "state" / "audit_log.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    print(f"wrote {report_path.relative_to(ROOT)} status={log['status']} auto_fixed={log['auto_fixed']}")
    return 1 if log["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
