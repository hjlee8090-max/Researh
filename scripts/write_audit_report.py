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


def classify(lines: list[str], returncode: int = 0) -> tuple[str, int, int, int]:
    fail = sum(1 for line in lines if line.startswith("[FAIL]"))
    warn = sum(1 for line in lines if line.startswith("[WARN]"))
    ok = sum(1 for line in lines if line.startswith("[OK]"))
    # 감사 스크립트가 크래시하면 태그 라인이 0개가 되어 "OK"로 위장된다 —
    # returncode 비정상 또는 검사 결과 전무는 정상이 아니라 ERROR 다
    if ok + warn + fail == 0 or (returncode != 0 and not fail):
        status = "ERROR"
    elif fail:
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
        "ERROR": "감사 실패 - 점검 스크립트 자체가 비정상 종료되어 오늘 파이프라인 상태를 확인하지 못했습니다. 상세 로그를 확인해야 합니다.",
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
        ("trade_log 액션·정렬·cash 흐름 무결성", "거래 기록의 액션·시간순서·현금 잔액 흐름이 모두 정상입니다."),
        ("trade_log: ", "거래 기록에서 이상한 항목을 발견했습니다: "),
        ("R/R 1.2 미만 보유 종목", "보유 종목 중 기대 수익/손실 비율(R/R) 이 1.2 미만인 항목이 있습니다. 오늘 18시 점검에서 목표가나 손절가를 다시 정해야 합니다."),
        ("미만 보유 종목 — 18시에 목표가/손절가 재조정", "보유 종목 중 기대 수익/손실 비율(R/R)이 하한에 미달한 항목이 있습니다. 오늘 18시 점검에서 목표가나 손절가를 다시 정해야 합니다: "),
        ("보유 종목 모두 R/R 임계", "보유 종목의 기대 수익/손실 비율은 모두 안전 구간에 있습니다."),
        ("보유 종목 모두 R/R 하한", "보유 종목의 기대 수익/손실 비율은 모두 안전 구간에 있습니다."),
        ("핫패스 콘텍스트 예산 초과", "루틴이 매번 읽는 파일이 너무 커졌습니다. 압축 스크립트(compact_state.py) 실행이 필요합니다: "),
        ("핫패스 콘텍스트 예산", "루틴이 매번 읽는 파일들의 크기는 모두 정상 범위입니다."),
        ("00시(자정 글로벌) routine 등록/실행 확인 필요", "오늘 자정(00시) 글로벌 점검 리포트가 없습니다. 자정 루틴 등록 상태를 확인해 주세요."),
        ("리포트 '한눈에 보기'에 운영 용어 노출(가독성 원칙 §3 — 사람 말로 풀어쓸 것): ", "오늘 리포트의 카카오톡 발송 부분에 내부 운영 용어가 섞여 있습니다. 다음 리포트부터 사람 말로 풀어 쓰도록 합니다: "),
        ("프롬프트 크기 추적: ", "참고: 일부 루틴 프롬프트 파일이 커지고 있어 추적 중입니다: "),
        ("프롬프트 감량 필요: ", "루틴 프롬프트 파일이 너무 커졌습니다. 내용 감량이 필요합니다: "),
        ("recovery_stage=defensive", "회복 전략 단계: 수비 — 신규 진입 금지, 비중 15% 상한, 후보 검색 일시 정지가 필요합니다."),
        ("recovery_stage=caution", "회복 전략 단계: 주의 — 신규 진입 1건/일·비중 20% 상한·구조적 악재 매칭 금지가 필요합니다."),
        ("recovery_stage=normal", "회복 전략 단계: 정상 — 정책 default 그대로 운영 가능합니다."),
        ("recovery_stage 판정 불가", "회복 전략 단계를 판정할 자산 정보가 부족합니다."),
        ("출처 모두 실패", "오늘 시장 데이터 수집이 양쪽 출처 모두 실패했습니다."),
        ("config/candidates.json tracks", "신규 진입 후보 종목 목록을 자동 추적 중입니다."),
        ("config/market_calendar.json lists", "한국거래소 휴장일 캘린더가 등록되어 있습니다."),
        ("trade_log ↔ portfolio.json 정합성", "거래 기록과 포트폴리오 잔액·보유수량·실현손익이 모두 일치합니다."),
        ("reconcile:", "거래 기록과 포트폴리오 사이에 불일치가 발견됐습니다 — 다음 routine 전에 수동 확인이 필요합니다: "),
        ("지난 7일 슬롯·주말 산출물 매트릭스 결손 없음", "지난 7일간 시간대별 리포트와 주말 산출물이 모두 제때 생성되었습니다."),
        ("슬롯 산출물 누락(지난 7일): ", "지난 7일 사이 생성되지 않은 리포트가 있습니다 — 해당 루틴이 실행되지 않은 것으로 보이니 claude.ai routines 등록 상태를 확인해 주세요: "),
        ("06시 리포트 부재(시행 초기 관찰", "참고: 새로 만든 06시(미국장 마감) 슬롯 리포트가 없는 날이 있어 관찰 중입니다: "),
        ("state 스키마 정상", "루틴이 직접 기록하는 상태 파일(추론 원장·사전 주문·주간 계획)의 형식이 모두 정상입니다."),
        ("state 스키마 위반(채점 누락 위험): ", "상태 파일에 형식이 어긋난 기록이 있습니다 — 이대로면 채점에서 조용히 빠집니다. 다음 루틴에서 해당 라인을 보정해야 합니다: "),
        ("state 스키마 검사 실행 실패", "상태 파일 형식 검사 스크립트가 실행되지 못했습니다."),
        ("건 계약 검사 통과", "오늘 생성된 리포트가 형식 계약(고정 헤더·한눈에 보기·시리즈 줄·게이지)을 모두 지켰습니다."),
        ("리포트 계약 위반: ", "오늘 리포트가 형식 계약을 위반했습니다 — 카톡 추출·주간 응축이 깨질 수 있어 다음 슬롯부터 보정이 필요합니다: "),
        ("계약 검사 대상 없음", "오늘은 아직 계약 검사할 슬롯 리포트가 없습니다."),
        ("리포트 계약 검사 실행 실패", "리포트 형식 계약 검사 스크립트가 실행되지 못했습니다."),
        ("notify_log 원장 없음", "카카오 발송 이력 원장이 아직 없습니다 — 다음 발송부터 기록됩니다."),
        ("notify_log 원장 비어", "카카오 발송 이력 원장이 아직 비어 있습니다 — 다음 발송부터 기록됩니다."),
        ("어제 슬롯 발송 원장 대사 일치", "어제 생성된 리포트의 카카오 발송이 모두 정상 기록되었습니다."),
        ("발송 성공 기록 없음(어제", "리포트는 만들어졌지만 카카오 알림이 나간 기록이 없습니다 — 전달 구간 점검이 필요합니다: "),
        ("카카오 발송 실패 기록(어제): ", "어제 카카오 발송이 실패한 기록이 있습니다: "),
        ("카카오 토큰 만료 임박 — ", "카카오 알림 토큰이 곧 만료됩니다 — GitHub Secret(KAKAO_REFRESH_TOKEN) 교체가 필요합니다: "),
        ("routine 자동 머지 충돌(최근 3일): ", "루틴 산출물이 main 에 자동 머지되지 못하고 브랜치에 남아 있습니다 — 수동 검토가 필요합니다: "),
    ]
    if clean.startswith("latest daily report:"):
        return f"최신 데일리 리포트를 확인했습니다: {clean.split(':', 1)[1].strip()}"
    for needle, text in translations:
        if needle in clean:
            if ":" in clean and needle == "weekly target gap from portfolio equity":
                amount = clean.split(":", 1)[1].strip().replace(" KRW", "원").replace("KRW", "원")
                return f"{text} 현재 부족분: {amount}"
            # 번역문이 ': ' 로 끝나면 원문 디테일을 이어붙인다 —
            # 디테일이 떨어져 나가 "이상한 항목을 발견했습니다: " 처럼 빈 경고가 되는 버그 방지.
            if text.endswith(": "):
                detail = clean.split(needle, 1)[1].strip()
                return text + detail if detail else text.rstrip(": ") + "."
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


def build_report(now: datetime, fixes: list[str], output: str, lines: list[str], returncode: int = 0) -> tuple[str, dict[str, Any]]:
    status, ok, warn, fail = classify(lines, returncode)
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
    if status == "ERROR":
        body.append("- 감사 스크립트가 비정상 종료되어 오늘 점검이 수행되지 않았습니다. 위 상세 로그의 에러를 먼저 고쳐야 합니다.")
    elif fail:
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
    output, lines, returncode = run_audit()

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"{now.strftime('%Y-%m-%d')}-audit.md"

    report, log = build_report(now, fixes, output, lines, returncode)
    report_path.write_text(report, encoding="utf-8")

    log_path = ROOT / "state" / "audit_log.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    print(f"wrote {report_path.relative_to(ROOT)} status={log['status']} auto_fixed={log['auto_fixed']}")
    return 1 if (log["fail"] or log["status"] == "ERROR") else 0


if __name__ == "__main__":
    raise SystemExit(main())
