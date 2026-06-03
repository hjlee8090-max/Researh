#!/usr/bin/env python3
"""lessons.md 의 '미반영 교훈'이 policy.json / prompts 에 실제 반영됐는지 자동 대조한다(v2.5).

배경: 자기보완 루프가 교훈을 lessons.md 에 '기록'은 하지만 policy/prompt 에 '강제'하지
못해 같은 실수가 재발했다(2026-05-29 에 등록한 '지정학 진행형 게이트' 룰이 2026-06-02 에
미적용 — lessons.md 본인이 "명문화 필요"라고 적었음에도 드롭됨). 이 스크립트는 그 갭을
매 감사·매주 정책리뷰에서 표면화한다.

탐지 방식(고정밀, 저-오탐):
1) lessons.md 에서 작성자가 직접 남긴 '미해결 마커'(명문화 필요·미적용·반영 필요·등록 필요 등)
   가 있는 줄을 찾는다 — 이건 시스템이 스스로 "아직 안 됐다"고 적은 자백이다.
2) 그 줄에서 '신호'(따옴표/꺾쇠 안 문구, 백틱 토큰, snake_case·dotted 식별자)를 추출한다.
3) policy.json + 모든 prompts/*.md 를 합친 haystack 에서 그 신호가 발견되면 '이미 반영됨'으로
   강등(append-only lessons 의 과거 마커가 영구 오탐이 되는 것을 방지), 하나도 없으면 '미반영'.
4) 같은 줄/섹션에 '반복 마커'(⚠️·연속·반복·재발·2회·3회…)가 있으면 hard(강제 대상), 아니면 soft.

출력: state/lessons_applied.json
종료코드: 기본 0(어드바이저리). 환경변수 LESSONS_ENFORCE 가 truthy 이고 hard 미반영이 있으면 1
(CI 에서 하드 차단하고 싶을 때만). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
LESSONS_PATH = ROOT / "state" / "lessons.md"
OUT_PATH = ROOT / "state" / "lessons_applied.json"

# 작성자가 "아직 policy/prompt 에 반영 안 됨"을 직접 표시한 마커(고정밀 신호).
UNRESOLVED_MARKERS = [
    "명문화 필요", "미적용", "미반영", "반영 필요", "도입 필요", "등록 필요",
    "추가 필요", "절차 필요", "개선 필요", "체계 부재", "시스템 부재",
]
# 반복/재발 신호 — 있으면 hard(우선 강제)로 승격.
REPEAT_MARKERS = ["⚠️", "연속", "반복", "재발", "2회", "3회", "4회", "2건째", "3건째", "재차", "또"]

HEADER_RE = re.compile(r"^###\s+(.+?)$")
COUNTER_LINE_RE = re.compile(r"^-\s*(.+?):\s*(\d+)건")
# 신호 추출: 따옴표/꺾쇠 안 문구, 백틱 토큰, snake_case/dotted 식별자(영문).
QUOTED_RE = re.compile(r"[\"'“”‘’「『]([^\"'“”‘’」』]{3,40})[\"'“”‘’」』]")
BACKTICK_RE = re.compile(r"`([^`]+)`")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{3,}")
# 신호로 쓰기엔 너무 흔한 토큰(오탐 유발) 제외.
STOP_SIGNALS = {
    "lessons.md", "policy.json", "prompt", "prompts", "routine", "https", "http",
    "naver", "yahoo", "kospi", "kst", "https.www", "www.tradingkey.com",
}


def split_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    current: dict = {"title": "(preamble)", "lines": []}
    for raw in text.splitlines():
        m = HEADER_RE.match(raw)
        if m:
            sections.append(current)
            current = {"title": m.group(1).strip(), "lines": []}
        else:
            current["lines"].append(raw)
    sections.append(current)
    return sections


def parse_counter(text: str) -> dict[str, int]:
    counters: dict[str, int] = {}
    in_block = False
    for line in text.splitlines():
        if "누적 패턴 카운터" in line:
            in_block = True
            continue
        if in_block:
            if line.startswith("## "):
                break
            m = COUNTER_LINE_RE.match(line)
            if m:
                counters[m.group(1).strip()] = int(m.group(2))
    return counters


def extract_signals(line: str) -> tuple[list[str], list[str]]:
    """줄에서 반영 여부 대조 신호를 뽑는다. (strong, weak) 반환.

    strong = 따옴표/꺾쇠 안 문구 + 백틱 토큰 — 룰의 '실질 내용'이라 반영 판정에 신뢰할 수 있다.
    weak   = 맨몸 식별자(예: policy_patch_review, lessons.md, Nasdaq) — 단순 상호참조일 때가 많아
             반영 판정(resolution)에 쓰면 오탐(이미 반영됨)이 생긴다. 맥락 표시용으로만 보존한다.
    """
    def _dedup(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for s in items:
            s = s.strip()
            key = s.lower()
            if not s or len(s) < 3 or key in STOP_SIGNALS or key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    strong: list[str] = []
    for rx in (QUOTED_RE, BACKTICK_RE):
        strong.extend(rx.findall(line))
    weak = IDENT_RE.findall(line)
    return _dedup(strong), _dedup(weak)


def signal_in_haystack(signal: str, haystack: str) -> bool:
    """신호가 policy+prompts 본문에 등장하는지(대소문자 무시). 식별자는 부분일치, 문구는 그대로."""
    return signal.lower() in haystack


def main() -> int:
    if not LESSONS_PATH.exists():
        print(json.dumps({"error": f"{LESSONS_PATH} 없음"}, ensure_ascii=False))
        return 1
    text = LESSONS_PATH.read_text(encoding="utf-8")

    # haystack = policy.json + 모든 prompts/*.md (소문자).
    parts: list[str] = []
    pol = ROOT / "config" / "policy.json"
    if pol.exists():
        parts.append(pol.read_text(encoding="utf-8"))
    haystack_files = ["config/policy.json"]
    for p in sorted((ROOT / "prompts").glob("*.md")):
        parts.append(p.read_text(encoding="utf-8"))
        haystack_files.append(f"prompts/{p.name}")
    haystack = "\n".join(parts).lower()

    sections = split_sections(text)
    counter = parse_counter(text)

    hard: list[dict] = []
    soft: list[dict] = []
    resolved: list[dict] = []

    for sec in sections:
        body = "\n".join(sec["lines"])
        section_has_repeat = any(rm in body for rm in REPEAT_MARKERS)
        for line in sec["lines"]:
            if not any(mk in line for mk in UNRESOLVED_MARKERS):
                continue
            strong, weak = extract_signals(line)
            # 반영 판정은 strong(따옴표/백틱 = 룰 실질 내용) 신호만 신뢰한다.
            # weak(맨몸 식별자)는 상호참조 오탐을 막기 위해 resolution 에서 제외(맥락용 보존).
            matched = [s for s in strong if signal_in_haystack(s, haystack)]
            item = {
                "section": sec["title"],
                "marker_line": line.strip()[:300],
                "strong_signals": strong,
                "weak_signals": weak,
                "matched_signals": matched,
            }
            if matched:
                # strong 신호가 policy/prompt 에 이미 존재 → 사실상 반영됨(과거 마커 잔존).
                item["status"] = "likely_applied"
                resolved.append(item)
            elif section_has_repeat or any(rm in line for rm in REPEAT_MARKERS):
                item["status"] = "unapplied_hard"
                item["why"] = "반복/재발 마커 + 미해결 마커 — policy/prompts 에 신호 미발견"
                hard.append(item)
            else:
                item["status"] = "unapplied_soft"
                item["why"] = "미해결 마커 — policy/prompts 에 신호 미발견"
                soft.append(item)

    repeated_3plus = {k: v for k, v in counter.items() if v >= 3}

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "lessons_path": "state/lessons.md",
        "haystack_files": haystack_files,
        "open_items_hard": hard,
        "open_items_soft": soft,
        "resolved_items": resolved,
        "repeated_3plus": repeated_3plus,
        "summary": {
            "hard": len(hard),
            "soft": len(soft),
            "likely_applied": len(resolved),
            "repeated_3plus": list(repeated_3plus),
        },
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"lessons_applied: hard={len(hard)} soft={len(soft)} applied={len(resolved)} "
        f"repeated_3plus={list(repeated_3plus)}"
    )
    for it in hard:
        print(f"  [HARD 미반영] {it['section']} :: {it['marker_line'][:120]}")
    for it in soft:
        print(f"  [soft 미반영] {it['section']} :: {it['marker_line'][:120]}")

    enforce = os.environ.get("LESSONS_ENFORCE", "").strip().lower() in ("1", "true", "yes", "on")
    if enforce and hard:
        print(f"LESSONS_ENFORCE — hard 미반영 {len(hard)}건으로 FAIL")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
