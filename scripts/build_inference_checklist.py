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


def load_caps() -> tuple[int, int]:
    """policy.context_budget.audit_thresholds 의 줄·바이트 캡을 함께 읽는다.

    (2026-08-13 P0 A-6, docs/plan_removal_exclusion.md) 종전엔 줄 캡(40)만 집행해
    줄당 수백 바이트 항목이 바이트 캡(4,000B)을 구조적으로 위반했다(실측 14,644B —
    audit_context_budget 만성 WARN). 캡 단위 불일치 해소: 두 캡을 모두 집행한다.
    """
    th = (
        load_json(ROOT / "config" / "policy.json", {})
        .get("context_budget", {})
        .get("audit_thresholds", {})
    )
    return (
        int(th.get("inference_checklist_max_lines", 40)),
        int(th.get("inference_checklist_max_bytes", 4000)),
    )


SECTION_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def collect_lessons_rules() -> list[str]:
    """선제추론오차/기회비용오차 항목의 '다음 추론 시 고려' 룰 — 섹션 날짜 내림차순.

    (2026-08-11 교정) 종전엔 파일 등장 순서를 '최신이 위'로 가정했으나, lessons.md 는
    18시(상단 prepend)와 00/06시·토요 사후분석(하단 append)의 이중 삽입 지점을 가져
    하단에 붙은 최신 룰이 목록 꼬리 = 상한 절단 1순위가 됐다(검토 리포트 결함 1·2 —
    7/18 이후 룰 전량 생략 실측). 섹션 헤더의 날짜(### YYYY-MM-DD …)로 정렬해 삽입
    지점과 무관하게 최신 룰이 앞에 오도록 한다(날짜 없는 섹션은 가장 오래된 것으로 취급).
    """
    if not LESSONS_PATH.exists():
        return []
    text = LESSONS_PATH.read_text(encoding="utf-8")
    dated: list[tuple[str, str]] = []  # (date, rule)
    cur_body: list[str] = []
    cur_date = ""
    cur_is_inf = False

    def flush():
        if cur_is_inf:
            body = "\n".join(cur_body)
            for m in NEXT_RULE_RE.finditer(body):
                dated.append((cur_date, m.group(1).strip()))

    for raw in text.splitlines():
        hm = HEADER_RE.match(raw)
        if hm:
            flush()
            cur_body = []
            cur_is_inf = False
            dm = SECTION_DATE_RE.search(hm.group(1))
            cur_date = dm.group(1) if dm else ""
            continue
        cur_body.append(raw)
        if any(c in raw for c in INFERENCE_CATS) and ("분류" in raw):
            cur_is_inf = True
    flush()
    # 날짜 내림차순(안정 정렬 — 동일 날짜는 파일 등장 순서 유지) 후 중복 제거(최신 인스턴스 보존).
    dated.sort(key=lambda t: t[0], reverse=True)
    seen, dedup = set(), []
    for d, r in dated:
        if r and r not in seen:
            seen.add(r)
            dedup.append(f"[{d[5:7]}/{d[8:10]}] {r}" if d else r)
    return dedup


def collect_scorecard_factors() -> list[str]:
    """scorecard miss 요인 — 반복횟수 내림차순, 동률은 최근 발생일 내림차순.

    (2026-08-11) miss_factors_detail(정규화 클러스터 + last_seen + 최신 사례)을 우선
    사용한다. 종전 형식(전문 문장 키·삽입순 동률)은 오래된 1회짜리가 앞에 와 최신 miss 가
    상한에서 잘렸다. detail 부재 시(구버전 scorecard) 기존 형식으로 폴백.
    """
    sc = load_json(SCORECARD_PATH, {})
    scoring = sc.get("scoring") or {}
    detail = scoring.get("miss_factors_detail")
    if isinstance(detail, dict) and detail:
        rows = sorted(detail.items(), key=lambda kv: (kv[1].get("count", 0), kv[1].get("last_seen", "")), reverse=True)
        out: list[str] = []
        for label, d in rows:
            n = d.get("count", 0)
            seen = d.get("last_seen") or ""
            mmdd = f"{seen[5:7]}/{seen[8:10]}" if len(seen) >= 10 else "?"
            head = "반복 빗나감 요인" if n >= 2 else "빗나감 요인"
            line = f"{head} — {label} ({n}회·최근 {mmdd})"
            ex = (d.get("latest_example") or "").strip()
            if d.get("pattern") and ex:  # 유형 라벨엔 최신 사례 1줄을 붙여 맥락 보존
                line += f" — 최근 사례: {ex[:110]}"
            out.append(line)
        return out
    mf = scoring.get("miss_factors") or {}
    return [f"반복 빗나감 요인 — {k} (지금까지 {v}회)" for k, v in mf.items()]


def main() -> int:
    cap, cap_bytes = load_caps()
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
    # (2026-08-11 절단 방향 교정) lessons 룰(응축된 행동 지침, 최신순)을 앞에, scorecard
    # miss 요인(원재료, 빈도·최신순)을 뒤에 둔다 — 상한 절단은 목록 꼬리(빈도·최신성
    # 하위)부터 일어나므로 '최신 교훈이 잘리던' 종전 동작이 반전된다.
    body: list[str] = []
    for r in lesson_rules:
        body.append(f"- {r}")
    for r in score_factors:
        body.append(f"- {r}")
    if not body:
        body.append("- (아직 누적된 선제추론 교훈 없음 — Phase 1 관측 중. 예측이 쌓이면 자동 채움)")

    # 콘텍스트 예산 캡 — 본문만 자른다(헤더 보존). 잘리면 마지막 줄에 사실대로 표기.
    # 줄 캡과 바이트 캡을 모두 만족하는 최대 보존 건수를 찾는다(절단은 목록 꼬리 =
    # 빈도·최신성 하위부터). 통째 절단만 하고 문장 중간은 자르지 않는다(의미 훼손 방지).
    def notice(n_cut: int) -> str:
        return (f"- … (상한 {cap}줄/{cap_bytes:,}B 도달 — 빈도·최신성 하위 {n_cut}건 생략. "
                "전량은 state/inference_scorecard.json miss_factors_detail·state/lessons.md 참조)")

    def render(keep_n: int) -> str:
        kept = body[:keep_n]
        if keep_n < len(body):
            kept = kept + [notice(len(body) - keep_n)]
        return "\n".join(head + kept) + "\n"

    line_budget = max(1, cap - len(head)) - 1  # 절단 표기 줄 자리 확보
    keep_n = len(body) if len(body) <= line_budget + 1 else line_budget
    while keep_n > 0 and len(render(keep_n).encode("utf-8")) > cap_bytes:
        keep_n -= 1
    truncated = keep_n < len(body)

    text = render(keep_n)
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} "
          f"(lesson_rules={len(lesson_rules)} score_factors={len(score_factors)} "
          f"lines={text.count(chr(10))}/{cap} bytes={len(text.encode('utf-8'))}/{cap_bytes}"
          f"{' TRUNCATED' if truncated else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
