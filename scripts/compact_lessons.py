#!/usr/bin/env python3
"""lessons.md 를 구조 인식 방식으로 압축한다 (콘텍스트 압축 v2 Phase 2).

배경(2026-07-27 실측): lessons.md 128KB 로 예산(60KB)의 2배가 넘는다. 원인은 개수가 아니라
크기다 — 섹션 65개 중 하나가 11,470B, 카운터 블록의 한 줄이 6,582B(갱신 서사)·6,866B(선제추론오차)다.

**단순 바이트 절단을 하지 않는 이유**: 이 파일은 두 스크립트가 파싱한다.
- build_lessons_index — `- 분류:` 와 `다음 추론 시 고려 / 다음 적용 룰 / 다음 추천 시 반영할 교훈`
  라인을 추출해 주간 정책 리뷰의 1차 입력을 만든다.
- check_lessons_applied — `✅ codify` 마커와 미해결 마커로 교훈 반영 여부를 판정한다.
꼬리를 자르면 이 라인들이 먼저 날아간다(대개 섹션 끝에 있다). 그래서 **기계가 읽는 라인은
전량 보존하고 서사만 걷어낸다.**

수행:
1. 오래된 섹션(cutoff 이전) → 스텁화. 분류·요약·"다음 ~" 룰·codify·신뢰도만 남기고
   전문은 lessons_archive.md 로 이관. 기존 관행(`- 전문: state/lessons_archive.md (날짜 이관)`)과 동일 형식.
2. 최근 섹션이 상한 초과 → 서사 라인(상황/사유/예측·실제/영향/미흡했던 부분)만 줄이고
   기계 판독 라인은 손대지 않는다.
3. 카운터 블록의 초장문 라인 → 앞부분만 남기고 상세는 archive 로.

멱등: 이미 스텁(`전문: state/lessons_archive.md` 포함)인 섹션은 건너뛴다.
출력 없음(파일 직접 수정). `--dry-run` 으로 변경량만 본다. 표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
LESSONS = ROOT / "state" / "lessons.md"
ARCHIVE = ROOT / "state" / "lessons_archive.md"

SECTION_RE = re.compile(r"(?m)^(### .+)$")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
STUB_MARKER = "전문: state/lessons_archive.md"

# 기계가 읽는 라인 — 절대 줄이지 않는다.
KEEP_PATTERNS = (
    # "- 분류:" 와 "- 원인 분류:" 두 표기가 섞여 있다(build_lessons_index CATEGORY_RE 와 동일 범위).
    # "원인 " 접두를 빠뜨리면 그 섹션의 분류가 '기타'로 떨어진다.
    re.compile(r"^\s*-\s*\*{0,2}(?:원인\s*)?분류\s*(?:신뢰도)?\*{0,2}\s*[:：]"),
    re.compile(r"다음\s*(추론\s*시\s*고려|적용\s*룰|진입|추천\s*시\s*반영할\s*교훈|routine)"),
    re.compile(r"✅\s*\*{0,2}\s*codify"),
    re.compile(r"^\s*-\s*\*{0,2}요약\*{0,2}\s*[:：]"),
    re.compile(re.escape(STUB_MARKER)),
)
# 서사 라인 — 요약 대상.
NARRATIVE_RE = re.compile(
    r"^\s*-\s*\*{0,2}(상황|사유\s*요약|예측/실제|예측|실제|영향|미흡했던\s*부분|오류의\s*본질"
    r"|조치|선제\s*액션\s*결과|근거|원인)\*{0,2}\s*[:：]"
)
# build_lessons_index 는 "다음 ~" 트리거 라인 **뒤에 이어지는 번호 매김 불릿**도 룰로 수집한다
# (RULE_BULLET_RE). 트리거 라인만 남기고 이어지는 불릿을 버리면 룰이 통째로 사라진다 —
# 2026-06-08 섹션에서 실제로 3건이 유실되는 것을 확인하고 보강했다.
CONTINUATION_RE = re.compile(r"^\s+(?:\d+\.|[-*①-⑨])\s+")
SUFFIX = " …(전문 archive)"


def blen(text: str) -> int:
    return len(text.encode("utf-8"))


def is_keep(line: str) -> bool:
    return any(p.search(line) for p in KEEP_PATTERNS)


def shrink_line(line: str, limit: int) -> str:
    if blen(line) <= limit:
        return line
    budget = max(40, limit - blen(SUFFIX))
    return line.encode("utf-8")[:budget].decode("utf-8", "ignore").rstrip() + SUFFIX


def section_date(title: str) -> str:
    m = DATE_RE.search(title)
    return m.group(0) if m else "9999-99-99"


def summarize_body(body: str, narrative_limit: int) -> tuple[str, bool]:
    """서사 라인만 줄이고 기계 판독 라인(과 그 연속 불릿)은 그대로 둔다. (새 본문, 변경여부)"""
    out, changed = [], False
    in_keep_block = False
    for line in body.splitlines():
        if not line.strip():
            out.append(line)
            continue
        if is_keep(line):
            in_keep_block = True
            out.append(line)
            continue
        if in_keep_block and CONTINUATION_RE.match(line):
            out.append(line)  # 룰 불릿 — 보존
            continue
        in_keep_block = False
        if NARRATIVE_RE.match(line) or blen(line) > narrative_limit:
            new = shrink_line(line, narrative_limit)
            changed = changed or (new != line)
            out.append(new)
            continue
        out.append(line)
    return "\n".join(out), changed


def stub_body(body: str, today: str, summary_limit: int) -> str:
    """스텁 = 분류 + 요약 + '다음 ~' 룰(연속 불릿 포함) + codify + 신뢰도 + 전문 포인터."""
    kept: list[str] = []
    summary_src = ""
    in_keep_block = False
    for line in body.splitlines():
        if is_keep(line):
            in_keep_block = True
            kept.append(shrink_line(line, summary_limit) if blen(line) > summary_limit else line)
            continue
        if in_keep_block and CONTINUATION_RE.match(line):
            kept.append(shrink_line(line, summary_limit) if blen(line) > summary_limit else line)
            continue
        in_keep_block = False
        if NARRATIVE_RE.match(line) and not summary_src:
            summary_src = line
    if summary_src and not any("요약" in k for k in kept):
        text = re.sub(r"^\s*-\s*\*{0,2}[^:：]+[:：]\s*", "", summary_src).strip()
        kept.insert(1 if kept else 0, "- 요약: " + shrink_line(text, summary_limit))
    kept.append(f"- {STUB_MARKER} ({today} 이관)")
    return "\n" + "\n".join(kept) + "\n"


def compact_counter_block(head: str, limit: int, overflow: list[str]) -> tuple[str, int]:
    """카운터 블록의 초장문 라인을 줄이고 원문을 overflow 에 모은다."""
    out, cut = [], 0
    for line in head.splitlines():
        if blen(line) > limit:
            overflow.append(line)
            out.append(shrink_line(line, limit))
            cut += 1
        else:
            out.append(line)
    return "\n".join(out), cut


def main() -> int:
    parser = argparse.ArgumentParser(description="lessons.md 구조 인식 압축")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not LESSONS.exists():
        print(json.dumps({"skipped": "lessons.md 부재"}, ensure_ascii=False))
        return 0

    policy = json.loads((ROOT / "config" / "policy.json").read_text(encoding="utf-8"))
    ret = ((policy.get("context_budget") or {}).get("retention") or {})
    cutoff = str(ret.get("lessons_stub_before_date", "2026-07-10"))[:10]
    section_limit = int(ret.get("lessons_section_max_bytes", 1200))
    counter_limit = int(ret.get("lessons_counter_line_max_bytes", 800))
    summary_limit = int(ret.get("lessons_stub_summary_max_bytes", 320))

    text = LESSONS.read_text(encoding="utf-8")
    before = blen(text)
    today = datetime.now(KST).date().isoformat()

    parts = SECTION_RE.split(text)
    head = parts[0]
    sections = [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]

    overflow_lines: list[str] = []
    new_head, counter_cut = compact_counter_block(head, counter_limit, overflow_lines)

    archived_full: list[tuple[str, str]] = []
    new_sections, stubbed, shrunk = [], 0, 0
    for title, body in sections:
        if STUB_MARKER in body:
            new_sections.append((title, body))  # 이미 스텁 — 멱등
            continue
        if section_date(title) < cutoff:
            archived_full.append((title, body))
            new_sections.append((title, stub_body(body, today, summary_limit)))
            stubbed += 1
            continue
        if blen(body) > section_limit:
            new_body, changed = summarize_body(body, section_limit // 3)
            if changed:
                archived_full.append((title, body))
                shrunk += 1
            new_sections.append((title, new_body))
            continue
        new_sections.append((title, body))

    rebuilt = new_head + "".join(f"{t}{b}" for t, b in new_sections)
    after = blen(rebuilt)

    summary = {
        "cutoff": cutoff,
        "sections_total": len(sections),
        "stubbed": stubbed,
        "shrunk": shrunk,
        "counter_lines_cut": counter_cut,
        "archived_sections": len(archived_full),
        "bytes_before": before,
        "bytes_after": after,
        "bytes_saved": before - after,
    }

    if not args.dry_run and (archived_full or overflow_lines or counter_cut):
        block = [f"\n## 핫패스 압축 이관 ({datetime.now(KST).isoformat(timespec='seconds')})\n"]
        if overflow_lines:
            block.append("### 누적 패턴 카운터 — 초장문 라인 원문\n")
            block += [line for line in overflow_lines]
        for title, body in archived_full:
            block.append(f"\n{title}")
            block.append(body.rstrip())
        with ARCHIVE.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(block) + "\n")
        LESSONS.write_text(rebuilt, encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
