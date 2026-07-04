#!/usr/bin/env python3
"""시간대별 리포트의 형식 계약 검사 (의존성 0, 관측 전용).

단일 스펙: docs/report_contract.md — 이 스크립트의 상수는 그 문서의 기계 사본이다.
배경 (docs/plan_hourly_report_gap_fix.md Phase 1-4 · 진단 I14·I15·P4):
- 슬롯 헤더·'한눈에 보기'·시리즈 진행 줄은 카톡 추출(send_kakao)·HTML(build_html)·
  주간 응축(sunday_archive)의 파서 앵커인데, 위반이 기계 검증 없이 발행되어
  "카톡이 안 오는" 형태로만 사후 발견됐다 (07-02 이중 헤딩, ● 2개 게이지 등).

출력: stdout JSON {"as_of","files_checked","violations":[{"file","rule","detail"}]}
종료 코드: 기본 0 (관측 전용 — audit 가 WARN 으로 흡수). --strict 면 위반 시 1.
사용: python scripts/check_report_contract.py [--date YYYY-MM-DD] [--days N] [--strict]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# ---- 계약 상수 (docs/report_contract.md §1~§4 와 동기) ----
SLOT_HEADERS = {
    "00": "## 🌙 00:00 글로벌 야간 점검",
    "06": "## 🌄 06:00 미국장 마감 확정",
    "09": "## 🌅 09:00 개장 점검",
    "12": "## 🕛 12:00 장중 점검",
    "15": "## 🔔 15:00 마감 임박 점검",
    "18": "## 📊 18:00 종합·확정 리포트",
}
GLANCE_RE = re.compile(r"^###\s*한눈에 보기", re.MULTILINE)
SERIES_PREFIX = "> 시리즈 진행:"
SERIES_TOKENS = ("🌙", "🌄", "🌅", "🕛", "🔔", "📊")
DISCLAIMER_RE = re.compile(r"###\s*면책|학습·시뮬레이션")
# 본문 전체 금지 패턴 — 고정밀만 (오탐이 경보 피로를 만들면 검사 자체가 무시된다).
# '한눈에 보기' 한정의 넓은 금칙어는 audit_pipeline.GLANCE_BANNED_TOKENS 가 따로 검사한다.
BODY_BANNED_PATTERNS = [
    (re.compile(r"§"), "내부 섹션 참조(§) 노출"),
    (re.compile(r"\bv\d+\.\d+"), "정책/모델 버전 번호(vX.Y) 노출"),
    (re.compile(r"\bpo-\d{8}"), "pending_orders 트리거 ID 노출"),
]
HEADING_RE = re.compile(r"^(#{2,4})\s+(.*)$")


def check_file(path: Path, slot: str, violations: list[dict]) -> None:
    text = path.read_text(encoding="utf-8")

    def add(rule: str, detail: str) -> None:
        violations.append({"file": path.name, "rule": rule, "detail": detail})

    # 1) 슬롯 헤더 고정 문자열
    if SLOT_HEADERS[slot] not in text:
        add("slot_header", f"고정 헤더 '{SLOT_HEADERS[slot]}' 부재 — 카톡 섹션 추출 실패 위험")
    # 2) 한눈에 보기 — 존재 + 본문 첫 ### 이어야 한다 (2026-07-04 §8-1: 30초 의사결정 우선)
    if not GLANCE_RE.search(text):
        add("glance", "'### 한눈에 보기' 부재 — 카톡 요약 추출 불가")
    else:
        first_h3 = re.search(r"^###\s+(.+)$", text, re.MULTILINE)
        if first_h3 and "한눈에 보기" not in first_h3.group(1):
            add("glance_order", f"본문 첫 ### 이 '한눈에 보기'가 아님(실제: {first_h3.group(1)[:30]}) — 요약 최상단 계약(§8-1)")
    # 3) 시리즈 진행 줄 (6슬롯 전부 표기)
    series_lines = [ln for ln in text.splitlines() if ln.strip().startswith(SERIES_PREFIX)]
    if not series_lines:
        add("series_line", f"'{SERIES_PREFIX}' 줄 부재")
    else:
        missing = [tok for tok in SERIES_TOKENS if tok not in series_lines[0]]
        if missing:
            add("series_line", f"시리즈 진행 줄에 슬롯 누락: {','.join(missing)} (6슬롯 의무 — 미발행 은폐 방지)")
    # 4) 빈 섹션(연속 헤딩) — 헤딩 직후 본문 없이 같은·상위 레벨 헤딩이 오면 위반
    lines = text.splitlines()
    prev_heading: tuple[int, str, int] | None = None  # (level, title, lineno)
    content_since = True
    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            if prev_heading is not None and not content_since and level <= prev_heading[0]:
                add("empty_section", f"L{prev_heading[2]} '{prev_heading[1][:40]}' — 본문 없는 헤딩(이중 헤딩 의심)")
            prev_heading = (level, m.group(2).strip(), idx)
            content_since = False
        elif line.strip():
            content_since = True
    # 5) 본문 금지 패턴 (고정밀)
    for pattern, label in BODY_BANNED_PATTERNS:
        hits = pattern.findall(text)
        if hits:
            add("banned_token", f"{label} {len(hits)}회 (예: {str(hits[0])[:20]})")
    # 6) 게이지 — 코드펜스 안에서 ● 2개 이상인 줄 / 손절 거리 부호 반전
    in_fence = False
    for idx, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and line.count("●") >= 2:
            add("gauge", f"L{idx} 게이지 한 줄에 ● {line.count('●')}개 — 현재가 마커는 1개")
    if "손절가까지 +" in text:
        add("gauge_sign", "'손절가까지 +X%' 부호 표기 — 계약은 '-X.X%'(하락 거리) 표기")
    # 7) 면책
    if not DISCLAIMER_RE.search(text):
        add("disclaimer", "면책 문구 부재")


def main() -> int:
    parser = argparse.ArgumentParser(description="리포트 형식 계약 검사 (관측 전용)")
    parser.add_argument("--date", help="검사 기준일 YYYY-MM-DD (기본: 오늘 KST)")
    parser.add_argument("--days", type=int, default=1, help="기준일부터 과거 N일 검사 (기본 1 = 기준일만)")
    parser.add_argument("--strict", action="store_true", help="위반 발견 시 종료 코드 1")
    args = parser.parse_args()

    base = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else datetime.now(KST).date()
    )
    violations: list[dict] = []
    files_checked = 0
    for back in range(args.days):
        ds = (base - timedelta(days=back)).isoformat()
        for slot in SLOT_HEADERS:
            path = ROOT / "reports" / f"{ds}-{slot}.md"
            if path.exists():
                files_checked += 1
                check_file(path, slot, violations)
    print(json.dumps(
        {
            "as_of": datetime.now(KST).isoformat(timespec="seconds"),
            "files_checked": files_checked,
            "violations": violations,
        },
        ensure_ascii=False,
    ))
    return 1 if (args.strict and violations) else 0


if __name__ == "__main__":
    sys.exit(main())
