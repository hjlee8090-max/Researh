#!/usr/bin/env python3
"""build_inference_checklist — 다음 추론 직전 읽는 '응축 체크리스트' 생성 (Phase 1, v1.0).

자기보완 루프의 build_lessons_index.py 와 동형. lessons.md 의 선제추론오차/기회비용오차
항목에서 추출한 '다음 추론 시 고려' 룰 + inference_scorecard.json 의 반복 miss 요인을
응축해 state/inference_checklist.md 를 만든다.

이 파일은 00:00/09:00/… INFER 단계가 추론 직전 '먼저 읽는' 핫패스 입력이다
(자기보완 루프가 lessons.md 를 먼저 읽는 것과 대칭). 콘텍스트 예산 보호를 위해
policy.context_budget.audit_thresholds.inference_checklist_max_lines(기본 40) 로 캡한다.

18:00 routine 직후(당일) + 일 20시 sunday_policy_review 가 실행 → 다음날 추론이 어제
miss 를 이미 반영(학습 지연 제거, docs/plan_proactive_inference.md §10-E).
의존성: build_lessons_index.py 의 NEXT_RULE_RE 가 '다음 추론 시 고려' 를 포함해야 한다.
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
SCORECARD_PATH = ROOT / "state" / "inference_scorecard.json"
OUT_PATH = ROOT / "state" / "inference_checklist.md"

HEADER_RE = re.compile(r"^###\s+(.+?)$")
# build_lessons_index.NEXT_RULE_RE 와 동일 계약 — '다음 추론 시 고려' 포함.
NEXT_RULE_RE = re.compile(
    r"\*{0,2}(?:다음 추론 시 고려|다음 적용 룰|다음 진입[^\n:：]*?시 반영할 룰)\*{0,2}[:：][ \t]*([^\n]+)",
    re.IGNORECASE,
)
# 선제추론 루프가 만든 분류만 체크리스트로 모은다(자기보완 루프 룰과 분리).
INFERENCE_CATS = ("선제추론오차", "기회비용오차")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def max_lines() -> int:
    pol = load_json(ROOT / "config" / "policy.json", {})
    return int(
        pol.get("context_budget", {})
        .get("audit_thresholds", {})
        .get("inference_checklist_max_lines", 40)
    )


def collect_lessons_rules() -> list[str]:
    """선제추론오차/기회비용오차 항목의 '다음 추론 시 고려' 룰(최신 우선)."""
    if not LESSONS_PATH.exists():
        return []
    text = LESSONS_PATH.read_text(encoding="utf-8")
    rules: list[str] = []
    cur_body: list[str] = []
    cur_is_inf = False

    def flush():
        if cur_is_inf:
            body = "\n".join(cur_body)
            for m in NEXT_RULE_RE.finditer(body):
                rules.append(m.group(1).strip())

    for raw in text.splitlines():
        if HEADER_RE.match(raw):
            flush()
            cur_body = []
            cur_is_inf = False
            continue
        cur_body.append(raw)
        if any(c in raw for c in INFERENCE_CATS) and ("분류" in raw):
            cur_is_inf = True
    flush()
    # 최신(파일 상단)이 먼저 오도록 — lessons 는 신규가 위. 중복 제거(순서 보존).
    seen, dedup = set(), []
    for r in rules:
        if r and r not in seen:
            seen.add(r)
            dedup.append(r)
    return dedup


def collect_scorecard_factors() -> list[str]:
    sc = load_json(SCORECARD_PATH, {})
    mf = (sc.get("scoring") or {}).get("miss_factors") or {}
    return [f"반복 빗나감 요인 — {k} (지금까지 {v}회)" for k, v in mf.items()]


def main() -> int:
    cap = max_lines()
    lesson_rules = collect_lessons_rules()
    score_factors = collect_scorecard_factors()
    now = datetime.now(KST).isoformat(timespec="seconds")

    head = [
        "# 선제 추론 체크리스트 (inference_checklist.md)",
        "",
        f"> 자동 생성: build_inference_checklist.py · {now}",
        "> **추론(INFER) 직전 먼저 읽는다** — 과거 빗나간 요인을 이번 예측의 factors_considered/"
        "assumptions 에 반영하고 checklist_refs 로 증빙한다(자기보완 루프의 'lessons 먼저 읽기'와 대칭).",
        "> 항목은 lessons_rule_sunset(기본 5거래일) 대상 — 검증 안 된 선제 룰의 영구 적체 금지.",
        "",
        "## 다음 추론 시 반드시 고려할 요인",
        "",
    ]
    body: list[str] = []
    for r in score_factors:
        body.append(f"- {r}")
    for r in lesson_rules:
        body.append(f"- {r}")
    if not body:
        body.append("- (아직 누적된 선제추론 교훈 없음 — Phase 1 관측 중. 예측이 쌓이면 자동 채움)")

    # 콘텍스트 예산 캡 — 본문만 자른다(헤더 보존). 잘리면 마지막 줄에 표기.
    budget = max(1, cap - len(head))
    truncated = len(body) > budget
    if truncated:
        body = body[: budget - 1] + [f"- … (상한 {cap}줄 초과 {len(body) - (budget - 1)}건 생략 — 오래된 항목은 sunset)"]

    OUT_PATH.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} "
          f"(lesson_rules={len(lesson_rules)} score_factors={len(score_factors)} "
          f"lines={len(head) + len(body)}/{cap}{' TRUNCATED' if truncated else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
