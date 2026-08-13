#!/usr/bin/env python3
"""주간 아카이브 기계 폴백 — 일 21시 아카이브 루틴 미발화 주의 인덱스형 아카이브 소급 생성.

배경 (P2 B-2, docs/plan_removal_exclusion.md §5-B):
- 주간 아카이브(YYYY-Www-archive.md)는 다음 주 routine 콘텍스트 절약의 핵심인데,
  생성이 일요일 21시 루틴 단일 담체에 걸려 있어 미발화 시 그대로 구멍이 났다
  (W24~W26 3주 연속 + W32 실측). 압축(compact)은 Actions 로 이중화됐지만 응축은 아니었다.
- LLM 응축을 결정적 스크립트로 재현할 수는 없으므로, 폴백은 **각 슬롯 리포트의
  '한눈에 보기' 원문을 모은 인덱스**로 한정한다(리포트 계약상 '한눈에 보기'가
  30초 의사결정 요약 = 카톡 발췌 원천이라 정보 밀도가 가장 높은 블록이다).
- 폴백 파일은 `fallback-index` 마커를 갖는다 — audit 이 이를 감지해 "루틴 미발화"
  WARN 을 유지한다(파일 존재가 미발화 신호를 침묵시키지 않는다). 다음 일요일 루틴이
  정상 발화하면 정식 응축으로 덮어써도 된다.

동작: 최근 4개 완결 주(일요일 21:30 KST 경과) 중 아카이브 부재 주를 찾아,
해당 ISO 주 평일(월~금) × 슬롯(00/06/09/12/15/18) 리포트에서 '### 한눈에 보기'
블록을 추출해 1개 파일로 합친다. 이미 있으면 건드리지 않는다(멱등).

실행: weekly_compact.yml (매일 19:00 KST) + 수동. --dry-run 지원. 표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
REPORTS = ROOT / "reports"
SLOTS = ("00", "06", "09", "12", "15", "18")
LOOKBACK_WEEKS = 4
# 한눈에 보기 블록: '### 한눈에 보기' 헤딩부터 다음 헤딩(#·##·###) 직전까지.
SUMMARY_HEAD_RE = re.compile(r"^###\s*한눈에 보기.*$", re.MULTILINE)
WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")


def extract_summary(text: str) -> str | None:
    m = SUMMARY_HEAD_RE.search(text)
    if not m:
        return None
    body_lines: list[str] = []
    for line in text[m.end():].splitlines():
        if line.startswith("#"):
            break
        body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return body or None


def build_week(sunday, dry: bool) -> dict:
    iso = sunday.isocalendar()
    name = f"{iso[0]}-W{iso[1]:02d}-archive.md"
    out_path = REPORTS / name
    if out_path.exists():
        return {"week": name, "skipped": "exists"}

    monday = sunday - timedelta(days=6)
    sections: list[str] = []
    sources: list[str] = []
    for offset in range(5):  # 월~금
        day = monday + timedelta(days=offset)
        day_parts: list[str] = []
        for slot in SLOTS:
            rel = f"{day.isoformat()}-{slot}.md"
            path = REPORTS / rel
            if not path.exists():
                continue
            sources.append(rel)
            summary = extract_summary(path.read_text(encoding="utf-8", errors="ignore"))
            if summary:
                day_parts.append(f"### 한눈에 보기 ({slot}:00) — `reports/{rel}`\n\n{summary}")
            else:
                day_parts.append(f"### ({slot}:00) — `reports/{rel}` ('한눈에 보기' 블록 없음)")
        if day_parts:
            sections.append(f"## {day.isoformat()} ({WEEKDAY_KO[day.weekday()]})\n\n" + "\n\n".join(day_parts))

    if not sources:
        return {"week": name, "skipped": "해당 주 평일 리포트 없음"}

    header = [
        f"# {iso[0]}-W{iso[1]:02d} 주간 아카이브 — 기계 폴백 인덱스",
        "",
        "<!-- fallback-index: scripts/build_week_archive_fallback.py -->",
        "",
        "> ⚠️ 일요일 21시 아카이브 루틴 미발화로 생성된 **기계 폴백**이다 — LLM 응축이 아니라",
        "> 각 슬롯 리포트의 '한눈에 보기' 원문 인덱스다. 루틴 등록 상태를 확인하라",
        "> (claude.ai/code/routines). 정식 응축이 생성되면 이 파일을 덮어써도 된다.",
        f"> 생성: {datetime.now(KST).isoformat(timespec='seconds')} · 원본 {len(sources)}개 슬롯 리포트.",
        "",
    ]
    if not dry:
        out_path.write_text("\n".join(header + sections) + "\n", encoding="utf-8")
    return {"week": name, "created": True, "source_reports": len(sources)}


def main() -> int:
    parser = argparse.ArgumentParser(description="주간 아카이브 기계 폴백 인덱스 생성 (멱등)")
    parser.add_argument("--dry-run", action="store_true", help="생성 예정만 출력")
    args = parser.parse_args()

    now = datetime.now(KST)
    results = []
    for back in range(1, LOOKBACK_WEEKS * 7 + 1):
        day = (now - timedelta(days=back)).date()
        if day.weekday() != 6:
            continue
        # 그 주 일요일 21:30 KST 가 지났을 때만 '미발화 확정'으로 본다.
        deadline = datetime(day.year, day.month, day.day, 21, 30, tzinfo=KST)
        if now < deadline:
            continue
        results.append(build_week(day, args.dry_run))
    for r in results:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
