#!/usr/bin/env python3
"""state/lessons.md 를 파싱해 분류별 인덱스와 '다음 적용 룰' 누적 목록을 만든다.

생성 파일: state/lessons_index.json (gitignored)
- by_category: 분류별(매크로/섹터/개별/가정오류/루틴) 항목 리스트
- next_rules: 모든 항목에서 추출한 '다음 적용 룰' / '다음 진입/점검 시 반영할 룰'
- repeat_counter: lessons.md 의 '누적 패턴 카운터' 섹션 그대로
- rule_sunset (P1 C-1, docs/plan_removal_exclusion.md §5-C): 룰별 `(expiry: YYYY-MM-DD)`
  파싱 — 만료 도래 목록(§1-2-b 만료/승격 판정 입력)과 차단·상한 류인데 expiry 미표기인
  신규 룰 목록(2026-08-13 이후 섹션만 — 기존 룰 그랜드파더, warn 모드).
  policy.lessons_rule_sunset(v2.11)은 제도만 있고 등록이 0건이라 일몰 대상이 없었다.
- archive_candidates·throughput (P1 E): codify 30일+ 경과인데 본문이 아직 안 응축된
  섹션 목록 + 주간 유입 통계 — §1-6 '이관 ≥ 유입' 수지 균형 의무의 1차 입력.

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
# (2026-08-11 교정) 실제 lessons 항목 115/126건이 '- 분류:' 표기를 쓰는데 '원인 분류'만
# 매칭해 인덱스의 91%가 "기타"로 뭉개졌다(검토 리포트 결함 4). 두 표기 모두 + 볼드 허용.
# '분류 신뢰도:'·'분류 전환:' 같은 다른 필드는 '분류' 직후 콜론 요구로 배제된다.
CATEGORY_RE = re.compile(
    r"^\s*[-*]?\s*\*{0,2}(?:원인\s*)?분류\*{0,2}\s*[:：]\s*([^\n]+)", re.IGNORECASE | re.MULTILINE
)
NEXT_RULE_RE = re.compile(
    r"\*{0,2}(?:다음 추론 시 고려|다음 적용 룰|다음 진입[^\n:：]*?시 반영할 룰"
    r"|다음 추천 시 반영할 교훈|다음 routine[^\n:：]*?반영할 룰)\*{0,2}[:：][ \t]*([^\n]+)",
    re.IGNORECASE,
)
NEXT_RULE_TRIGGER = (
    "다음 진입", "다음 적용 룰", "다음 추론", "다음 추천 시 반영할 교훈", "다음 routine",
)
RULE_BULLET_RE = re.compile(r"^\s*\d+\.\s+(.+?)$")
# (2026-08-11 교정) 카운터가 볼드로 적히면(`- 선제추론오차: **34건**` / `- **진행 중**: 2건`)
# 종전 정규식이 미매칭 → 최대 반복 패턴(선제추론오차 34건)이 반복 임계(≥3) 판정에서
# 통째로 누락됐다(검토 리포트 결함 4 — 8/9 리뷰가 "반복 ≥3은 2개 분류뿐"으로 오보고).
COUNTER_LINE_RE = re.compile(r"^-\s*\*{0,2}(.+?)\*{0,2}\s*[:：]\s*\*{0,2}(\d[\d,]*)\s*건")
# --- P1 C-1·E (2026-08-13, docs/plan_removal_exclusion.md §5-C·E) ---
SECTION_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
EXPIRY_RE = re.compile(r"\(\s*(?:expiry|만료)\s*[:：]?\s*(\d{4}-\d{2}-\d{2})\s*\)")
# 진입 차단·비중 상한 류 판별 키워드 — policy.lessons_rule_sunset 의 일몰 대상 정의와 동일 계열.
SUNSET_KEYWORDS = ("차단", "보류", "금지", "상한", "캡", "축소", "냉각", "제한")
# expiry 표기 의무의 발효일 — 이전 섹션의 룰은 그랜드파더(소급 경고로 목록이 잠기는 것 방지).
SUNSET_MANDATE_SINCE = "2026-08-13"
# codify 후 이 일수가 지나도록 본문이 응축되지 않으면 이관 후보 (§1-6 수지 균형).
ARCHIVE_AFTER_DAYS = 30
# §1-6 응축 완료 형태는 4줄 내외 — 이보다 길면 '본문 잔존'으로 본다.
CONDENSED_MAX_LINES = 8


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
    category_raw = cat_match.group(1).strip().strip("*").strip() if cat_match else "분류 없음"
    # 첫 키워드 매칭만 추출 — 구체 분류(선제추론 계열·운영 계열)를 4대 분류보다 먼저 본다.
    primary = "기타"
    for key in (
        "선제추론오차", "기회비용오차", "사전 경보", "절차", "관측",
        "루틴", "가정오류", "개별", "섹터", "매크로",
    ):
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
                name = m.group(1).strip().strip("*").strip()
                counters[name] = int(m.group(2).replace(",", ""))
    return counters


def build_rule_sunset(parsed: list[dict], sections: list[dict], today: str) -> dict:
    """P1 C-1 — 룰 expiry 등록·만료 현황. 섹션 날짜는 헤딩의 첫 YYYY-MM-DD."""
    registered: list[dict] = []
    unregistered: list[dict] = []
    for p, s in zip(parsed, sections):
        dm = SECTION_DATE_RE.search(s["title"])
        sec_date = dm.group(1) if dm else ""
        for rule in p["next_rules"]:
            em = EXPIRY_RE.search(rule)
            if em:
                registered.append({
                    "source_title": p["title"], "rule": rule[:200], "expiry": em.group(1),
                    "expired": em.group(1) < today,
                })
            elif (any(k in rule for k in SUNSET_KEYWORDS)
                  and sec_date >= SUNSET_MANDATE_SINCE):
                unregistered.append({"source_title": p["title"], "rule": rule[:200],
                                     "section_date": sec_date})
    return {
        "mandate_since": SUNSET_MANDATE_SINCE,
        "registered": registered,
        "expired": [r for r in registered if r["expired"]],
        "unregistered": unregistered,
        "note": "expired = §1-2-b 만료/승격 판정 대상. unregistered = 발효일 이후 차단·상한 류인데 "
                "(expiry: YYYY-MM-DD) 미표기 — 기본 5거래일(policy.lessons_rule_sunset). warn 모드.",
    }


def build_archive_candidates(parsed: list[dict], sections: list[dict], today_dt: datetime) -> dict:
    """P1 E — codify 30일+ 경과 + 본문 미응축 섹션 = §1-6 이관 대상 1순위 목록."""
    cutoff = (today_dt.date() - timedelta(days=ARCHIVE_AFTER_DAYS)).isoformat()
    week_ago = (today_dt.date() - timedelta(days=7)).isoformat()
    candidates: list[dict] = []
    new_7d = 0
    for p, s in zip(parsed, sections):
        dm = SECTION_DATE_RE.search(s["title"])
        sec_date = dm.group(1) if dm else ""
        if sec_date and sec_date >= week_ago:
            new_7d += 1
        body = "\n".join(s["lines"])
        n_lines = sum(1 for l in s["lines"] if l.strip())
        codified = ("✅" in body) and ("codify" in body.lower())
        if codified and sec_date and sec_date < cutoff and n_lines > CONDENSED_MAX_LINES:
            candidates.append({"title": p["title"], "date": sec_date, "body_lines": n_lines})
    candidates.sort(key=lambda c: c["date"])
    return {
        "archive_candidates": candidates[:20],
        "archive_candidates_total": len(candidates),
        "throughput": {
            "entries_total": len(parsed),
            "new_entries_7d": new_7d,
            "note": "§1-6 수지 균형 의무 — 이번 리뷰의 이관 건수 ≥ new_entries_7d 또는 "
                    "lessons.md ≤ context_budget.lessons_max_bytes 중 하나 충족.",
        },
    }


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

    now_dt = datetime.now(KST)
    today = now_dt.date().isoformat()
    sunset = build_rule_sunset(parsed, sections, today)
    archive = build_archive_candidates(parsed, sections, now_dt)

    out = {
        "as_of": now_dt.isoformat(timespec="seconds"),
        "total_entries": len(parsed),
        "by_category": {k: v for k, v in sorted(by_category.items())},
        "next_rules": all_rules,
        "repeat_counter": counter,
        "repeated_threshold_3_plus": {k: v for k, v in counter.items() if v >= 3},
        "rule_sunset": sunset,
        **archive,
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT_PATH.relative_to(ROOT)} entries={len(parsed)} rules={len(all_rules)} "
        f"categories={list(by_category)} repeated_3plus={list(out['repeated_threshold_3_plus'])} "
        f"sunset(expired={len(sunset['expired'])} unregistered={len(sunset['unregistered'])}) "
        f"archive_candidates={archive['archive_candidates_total']} new_7d={archive['throughput']['new_entries_7d']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
