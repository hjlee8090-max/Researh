#!/usr/bin/env python3
"""Run the pipeline audit and write a mobile-friendly markdown report."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


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


def main() -> int:
    now = datetime.now(KST)
    audit_script = ROOT / "scripts" / "audit_pipeline.py"
    proc = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = proc.stdout.strip()
    if proc.stderr.strip():
        output += "\n" + proc.stderr.strip()
    lines = [line for line in output.splitlines() if line.strip()]
    status, ok, warn, fail = classify(lines)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"{now.strftime('%Y-%m-%d')}-audit.md"

    body = [
        f"# 파이프라인 감사 리포트 — {now.strftime('%Y-%m-%d')}",
        "",
        "> 진행 상태: audit ✓",
        f"> 마지막 갱신: {now.strftime('%Y-%m-%d %H:%M')} KST",
        "> 본 산출물은 파이프라인 운영 점검용이며 실제 투자 권유가 아닙니다.",
        "",
        "## 요약",
        f"- 상태: {status}",
        f"- 정상: {ok}건",
        f"- 경고: {warn}건",
        f"- 실패: {fail}건",
        "",
        "## 모바일 체크",
    ]

    important = [line for line in lines if line.startswith("[FAIL]") or line.startswith("[WARN]") or line.startswith("[INFO]")]
    if important:
        body.extend(f"- {line}" for line in important[:12])
    else:
        body.append("- 조치 필요한 항목 없음")

    body.extend([
        "",
        "## 전체 감사 로그",
        "```text",
        output,
        "```",
        "",
        "## 다음 액션",
    ])
    if fail:
        body.append("- FAIL 항목을 먼저 수정하고, 수정 커밋 후 감사 workflow를 다시 실행한다.")
    elif warn:
        body.append("- WARN 항목은 다음 루틴 전까지 확인한다. 오늘 리포트 자리표시자 경고는 해당 시간대 루틴 전이면 정상일 수 있다.")
    else:
        body.append("- 파이프라인 상태 정상. 다음 루틴을 기다린다.")

    report_path.write_text("\n".join(body) + "\n", encoding="utf-8")

    log_path = ROOT / "state" / "audit_log.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    log = {
        "ts": now.isoformat(),
        "status": status,
        "ok": ok,
        "warn": warn,
        "fail": fail,
        "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    print(f"wrote {report_path.relative_to(ROOT)} status={status}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
