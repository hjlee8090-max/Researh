#!/usr/bin/env python3
"""state/lessons.md 를 파싱해 분류별 인덱스와 '다음 적용 룰' 누적 목록을 만든다.

생성 파일: state/lessons_index.json (gitignored)
- by_category: 분류별(매크로/섹터/개별/가정오류/루틴) 항목 리스트
- next_rules: 모든 항목에서 추출한 '다음 적용 룰' / '다음 진입/점검 시 반영할 룰'
- repeat_counter: lessons.md 의 '누적 패턴 카운터' 섹션 그대로

prompts/sunday_policy_review.md 가 이 인덱스를 1차 입력으로 사용한다.
표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
LESSONS_PATH = ROOT / "state" / "lessons.md"
OUT_PATH = ROOT / "state" / "lessons_index.json"

HEADER_RE = re.compile(r"^###\s+(.+?)$")
CATEGORY_RE = re.compile(r"원인 분류[:\s]*([^\n]+)", re.IGNORECASE)
NEXT_RULE_RE = re.compile(
    r"\*{0,2}(?:다음 추론 시 고려|다음 적용 룰|다음 진입[^\n:：]*?시 반영할 룰"
    r"|다음 추천 시 반영할 교훈|다음 routine[^\n:：]*?반영할 룰)\*{0,2}[:：][ \t]*([^\n]+)",
    re.IGNORECASE,
)
NEXT_RULE_TRIGGER = (
    "다음 진입", "다음 적용 룰", "다음 추론", "다음 추천 시 반영할 교훈", "다음 routine",
)
RULE_BULLET_RE = re.compile(r"^\s*\d+\.\s+(.+?)$")
COUNTER_LINE_RE = re.compile(r"^-\s*(.+?):\s*(\d+)건")


def split_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        match = HEADER_RE.match(raw)
        if match:
            if current is not None:
                sections.append(current)
            current = {"title": match.group(1).strip(), "lines": []}
            continue
        if current is not None:
            current["lines"].append(raw)
    if current is not None:
        sections.append(current)
    return sections


def parse_section(section: dict) -> dict:
    body = "\n".join(section["lines"])
    cat_match = CATEGORY_RE.search(body)
    category_raw = cat_match.group(1).strip() if cat_match else "분류 없음"
    # 첫 키워드 매칭만 추출 (매크로 / 섹터 / 개별 / 가정오류 / 루틴)
    primary = "기타"
    for key in ("루틴", "가정오류", "개별", "섹터", "매크로"):
        if key in category_raw:
            primary = key
            break
    next_rules: list[str] = []
    for m in NEXT_RULE_RE.finditer(body):
        next_rules.append(m.group(1).strip())
    # 번호 매김 룰(예: 1. 구조적 악재... / 2. 진입 직전...) 도 별도 캡처
    capture = False
    for line in section["lines"]:
        if any(trig in line for trig in NEXT_RULE_TRIGGER):
            capture = True
            continue
        if capture:
            if not line.strip():
                # 빈 줄 만나면 캡처 중단 (단, 다음 줄이 들여쓰기된 번호면 계속)
                continue
            bm = RULE_BULLET_RE.match(line)
            if bm:
                next_rules.append(bm.group(1).strip())
            elif line.startswith("###") or line.startswith("##"):
                break
            else:
                # 새로운 bullet 가 아니면 종료
                if not line.startswith(" ") and not line.startswith("-") and not line.startswith("    "):
                    break
    # 중복 제거 (순서 보존)
    seen = set()
    dedup_rules = []
    for r in next_rules:
        if r not in seen:
            seen.add(r)
            dedup_rules.append(r)
    return {
        "title": section["title"],
        "category_raw": category_raw,
        "category": primary,
        "next_rules": dedup_rules,
    }


def parse_counter(text: str) -> dict[str, int]:
    counters: dict[str, int] = {}
    in_block = False
    for line in text.splitlines():
        if "누적 패턴 카운터" in line:
            in_block = True
            continue
        if in_block:
            if line.startswith("##") or line.startswith("###"):
                break
            m = COUNTER_LINE_RE.match(line)
            if m:
                counters[m.group(1).strip()] = int(m.group(2))
    return counters


def main() -> int:
    if not LESSONS_PATH.exists():
        print(f"{LESSONS_PATH} 없음")
        return 1
    text = LESSONS_PATH.read_text(encoding="utf-8")
    sections = split_sections(text)
    parsed = [parse_section(s) for s in sections]
    counter = parse_counter(text)

    by_category: dict[str, list[dict]] = {}
    all_rules: list[dict] = []
    for p in parsed:
        by_category.setdefault(p["category"], []).append(
            {"title": p["title"], "category_raw": p["category_raw"], "rule_count": len(p["next_rules"])}
        )
        for rule in p["next_rules"]:
            all_rules.append({"source_title": p["title"], "category": p["category"], "rule": rule})

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "total_entries": len(parsed),
        "by_category": {k: v for k, v in sorted(by_category.items())},
        "next_rules": all_rules,
        "repeat_counter": counter,
        "repeated_threshold_3_plus": {k: v for k, v in counter.items() if v >= 3},
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT_PATH.relative_to(ROOT)} entries={len(parsed)} rules={len(all_rules)} "
        f"categories={list(by_category)} repeated_3plus={list(out['repeated_threshold_3_plus'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
