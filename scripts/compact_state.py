#!/usr/bin/env python3
"""콘텍스트 압축 — 핫패스 config 의 무한 누적 필드를 archive 로 이관한다 (의존성 0, 멱등).

배경(2026-06-12 진단, docs/plan_context_compaction.md): 평일 routine 의무 적재가 ~500KB
(≈200K+ 토큰)에 도달. watchlist 1,945줄(Read 캡 2,000 임박)·watch_items 52개·
portfolio.history 33건·policy.changelog 22건이 매 routine 콘텍스트를 잠식했다.

원칙 — 자기보완 루프 보존:
- 학습 재료는 **삭제하지 않는다**. git 히스토리 + archive 파일에 전문 보존, 핫패스에서만 뺀다.
- 의사결정 신호(보유 종목 최근 코멘트·열린 watch_items·최근 history)는 그대로 둔다.
- 청산 종목을 candidates.json 에 자동 추가하지 않는다 — 정리 작업이 진입 경로를 다시 열어
  매매 행동을 바꾸면 안 된다. 재발굴은 universe.json → screen_universe 경로가 담당한다.

수행 항목:
1. watchlist.stocks — 비보유(청산) 종목은 통째로 state/watchlist_archive.json 이관,
   보유 종목 comments 는 최근 KEEP_COMMENTS 개만 유지(이전분 archive).
2. weekly_plan.watch_items — 최신 KEEP_WATCH_ITEMS 개 유지, 초과분 state/watch_items_archive.jsonl.
3. portfolio.history — 전체를 state/portfolio_history.jsonl 에 merge(날짜 dedup) 후
   config 에는 최근 KEEP_HISTORY 개 유지.
4. policy.changelog — 전체를 docs/policy_changelog.md 에 누적 기록 후 최근 KEEP_CHANGELOG 개 유지.

P0 커버리지 확장 (2026-08-13, docs/plan_removal_exclusion.md §5-A — 매매 행동 무변경):
5. pending_orders — 종결 상태(expired/filled/cancelled/resolved_*) 주문 중 기준일이
   KEEP_TERMINAL_ORDER_DAYS 를 지난 것 + 오래된 날짜형 _meta 키를 archive 로 이관.
   check_intraday_alerts(status active 만 평가)·sync_pending_orders(active SELL 만) 무영향.
6. catalysts.manual_events — 이벤트일이 KEEP_PAST_CATALYST_DAYS 를 지난 과거분 이관.
   estimate_target_price 의 과거 촉매 사용창(days_until < -7 스킵)과 정확히 정렬.
7. watchlist 상위 comments·cross_check_notes — 최근 KEEP_TOP_NOTES 건 유지(초과분 archive).
   stocks[].comments 와 동일 원칙 — 종전엔 상위 필드가 미커버 성장원이었다.
8. weekly_plan.weekend_review — 날짜 키(saturday_review_YYYY_MM_DD 류)가
   KEEP_WEEKEND_REVIEW_DAYS 를 지난 것 이관 (5주+ 주차 키 누적 실측).
9. inference_log — 채점 완료(outcome hit/partial/miss) + INFERENCE_LOG_KEEP_DAYS 경과
   예측·결과 라인 이관. target_estimate_log 90일 보존창과 동일 관례(스코어카드는 롤링창).
   미채점·형식 위반 라인은 보존(채점·보정 표면 유지).

lessons.md 자동 이관 (2026-10-25 — 880KB·예산 14.7× 해소, 이전엔 ✅codify 마커가 있어야만 이관):
10. 누적 패턴 카운터 줄의 '[이전 기록]' 체인 → lessons_archive.md (건수·최신 기록 유지).
11. 날짜 헤딩(`## `·`### `) 항목 중 LESSONS_KEEP_DAYS 창 밖 + 예산 초과분 → lessons_archive.md 원문 이관.
    미해결 마커(check_lessons_applied 와 같은 판정)·미만료 (expiry) 룰 줄은 '이관 스텁'으로 남는다.

실행: 매일 19:00 KST weekly_compact.yml(일간 승격) + 일요일 21시 sunday_archive routine §0-B + 수동.
`--dry-run` 으로 변경량만 미리 본다. 표준 라이브러리만 사용.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_lessons_applied import (  # noqa: E402  — 미해결 판정은 감사와 같은 계약을 쓴다
    EXPIRY_RE,
    REPEAT_MARKERS,
    UNRESOLVED_MARKERS,
    build_haystack,
    extract_signals,
    signal_in_haystack,
)

KEEP_COMMENTS = 12        # 보유 종목당 최근 코멘트 (≈ 2~3일 × 4~5슬롯)
KEEP_WATCH_ITEMS = 15     # "내일 이어받을 트리거"로서 유효한 분량 (≈ 1주)
KEEP_HISTORY = 10         # 주말 사후분석(1주+)에 충분
KEEP_CHANGELOG = 5        # 최근 정책 변경 맥락 (전문은 docs/policy_changelog.md)

WATCHLIST = ROOT / "config" / "watchlist.json"
PORTFOLIO = ROOT / "config" / "portfolio.json"
WEEKLY_PLAN = ROOT / "config" / "weekly_plan.json"
POLICY = ROOT / "config" / "policy.json"
WATCHLIST_ARCHIVE = ROOT / "state" / "watchlist_archive.json"
WATCH_ITEMS_ARCHIVE = ROOT / "state" / "watch_items_archive.jsonl"
PORTFOLIO_HISTORY = ROOT / "state" / "portfolio_history.jsonl"
CHANGELOG_DOC = ROOT / "docs" / "policy_changelog.md"
TARGET_LOG = ROOT / "state" / "target_estimate_log.jsonl"
TARGET_LOG_ARCHIVE = ROOT / "state" / "target_estimate_log_archive.jsonl"
# score_target_estimates 의 60거래일 채점 지평(≈88 캘린더일)을 덮는 보존 창 — 초과분만 이관.
TARGET_LOG_KEEP_DAYS = 90
LESSONS = ROOT / "state" / "lessons.md"
LESSONS_ARCHIVE = ROOT / "state" / "lessons_archive.md"
# lessons.md "최종 갱신" 라인의 "이전 갱신:" 체인 보존 개수 — 무압축 시 한 줄이 ~10KB 까지
# 자라던 무한 누적원 (2026-07-08 진단). 초과분은 lessons_archive.md 전문 보존.
KEEP_UPDATE_CHAIN = 2
# lessons.md 항목 본문 보존 창(캘린더일) — 토 사후분석·일 리뷰가 보는 한 주.
# (2026-10-25 진단) 이관을 '✅codify 마커'에 묶은 §1-6 설계는 마커를 다는 단계가 재량이라
# 유입(자동·매일)을 못 따라가 880KB(예산 14.7×)·73일 연속 초과를 만들었다 → codify 무관 자동 이관.
LESSONS_KEEP_DAYS = 7
# 일일 유입이 3~10KB 로 출렁여(2026-08~10 실측) 날짜 창만으론 예산을 못 지킨다 — 창 안이라도
# lessons_max_bytes × 이 비율을 넘으면 오래된 항목부터 추가 이관(다음 압축까지의 유입 여유).
LESSONS_TARGET_RATIO = 0.85
# 오늘·어제 항목은 예산 초과여도 이관하지 않는다 — inference_checklist 의 최신 룰 입력 보존.
LESSONS_FLOOR_DAYS = 1
# 이관 항목 중 미해결 마커(반영 안 됨)·미만료 (expiry) 룰 줄만 남긴 스텁의 식별 태그.
LESSONS_STUB_TAG = "이관 스텁"

# --- P0 커버리지 확장 (2026-08-13, docs/plan_removal_exclusion.md §5-A) ---
PENDING_ORDERS = ROOT / "state" / "pending_orders.json"
PENDING_ARCHIVE = ROOT / "state" / "pending_orders_archive.jsonl"
CATALYSTS = ROOT / "config" / "catalysts.json"
CATALYSTS_ARCHIVE = ROOT / "state" / "catalysts_archive.jsonl"
WEEKLY_PLAN_ARCHIVE = ROOT / "state" / "weekly_plan_archive.jsonl"
INFERENCE_LOG = ROOT / "state" / "inference_log.jsonl"
INFERENCE_LOG_ARCHIVE = ROOT / "state" / "inference_log_archive.jsonl"
# 종결 주문 보존 일수 — 0900 만료 정리·리포트 회고가 보는 단기 창을 덮는다.
KEEP_TERMINAL_ORDER_DAYS = 7
# 과거 촉매 보존 일수 — estimate_target_price.catalyst 가 days_until < -7 을 스킵하므로
# 이 값은 7 미만으로 줄이면 안 된다(소비자 계약).
KEEP_PAST_CATALYST_DAYS = 7
# watchlist 상위 comments·cross_check_notes 보존 건수 — stocks[].comments(12)와 동일.
KEEP_TOP_NOTES = 12
# weekend_review 날짜 키 보존 일수 — 현재 주 + 직전 주.
KEEP_WEEKEND_REVIEW_DAYS = 14
# inference_log 채점 완료분 보존 일수 — TARGET_LOG_KEEP_DAYS(90)와 동일 관례.
# 스코어카드(score_inferences)는 이 보존창의 롤링 통계가 된다(target_estimate 선례와 동일).
INFERENCE_LOG_KEEP_DAYS = 90
TERMINAL_ORDER_STATUSES = ("expired", "filled", "cancelled")


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data, dry: bool) -> None:
    if dry:
        return
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_archive() -> dict:
    if WATCHLIST_ARCHIVE.exists():
        return read_json(WATCHLIST_ARCHIVE)
    return {
        "version": 1,
        "purpose": "watchlist 핫패스에서 이관된 청산 종목 전체 기록 + 보유 종목의 오래된 코멘트. "
                   "routine 은 읽지 않는다(복기·사후분석용). 재발굴은 universe.json → screen_universe.",
        "last_updated": None,
        "evicted_stocks": [],
        "trimmed_comments": {},
    }


def compact_watchlist(dry: bool) -> dict:
    watchlist = read_json(WATCHLIST)
    portfolio = read_json(PORTFOLIO)
    held = {p.get("ticker") for p in portfolio.get("positions", [])}
    archive = load_archive()

    kept_stocks = []
    evicted = []
    trimmed_total = 0
    for stock in watchlist.get("stocks", []):
        ticker = stock.get("ticker")
        if ticker in held:
            comments = stock.get("comments") or []
            if len(comments) > KEEP_COMMENTS:
                overflow = comments[:-KEEP_COMMENTS]
                stock["comments"] = comments[-KEEP_COMMENTS:]
                bucket = archive["trimmed_comments"].setdefault(ticker, [])
                # 코멘트에 dict 가 아닌 평문 문자열이 섞이면(2026-07 실데이터) .get 크래시 —
                # 문자열 항목은 그대로 이관하고 dict 만 ts 로 dedup 한다 (2026-07-14 보강)
                seen_ts = {c.get("ts") for c in bucket if isinstance(c, dict)}
                bucket.extend(
                    c for c in overflow
                    if not isinstance(c, dict) or c.get("ts") not in seen_ts
                )
                trimmed_total += len(overflow)
            kept_stocks.append(stock)
        else:
            evicted.append(stock)
            archive["evicted_stocks"].append({
                "evicted_at": now_kst(),
                "reason": "보유 청산 종목 — 핫패스 콘텍스트 절약 (전체 기록 보존)",
                "stock": stock,
            })

    # P0 A-3: 상위(파일 최상위) comments·cross_check_notes 도 동일 원칙으로 최근분만 유지.
    # 두 배열 모두 최신이 뒤(append) — stocks[].comments 와 같은 방향. 소비자는 LLM 콘텍스트뿐
    # (스크립트 reader 없음 — send_kakao 는 stocks[].comments 만 읽는다).
    top_trimmed = 0
    for field, bucket_key in (("comments", "trimmed_top_comments"),
                              ("cross_check_notes", "trimmed_cross_check_notes")):
        items = watchlist.get(field)
        if not isinstance(items, list) or len(items) <= KEEP_TOP_NOTES:
            continue
        overflow, watchlist[field] = items[:-KEEP_TOP_NOTES], items[-KEEP_TOP_NOTES:]
        bucket = archive.setdefault(bucket_key, [])
        seen_ts = {c.get("ts") for c in bucket if isinstance(c, dict)}
        for c in overflow:
            if isinstance(c, dict):
                if c.get("ts") not in seen_ts:
                    bucket.append(c)
            elif c not in bucket:  # 평문 문자열 항목 (상위 comments 실데이터)
                bucket.append(c)
        top_trimmed += len(overflow)

    if evicted or trimmed_total or top_trimmed:
        watchlist["stocks"] = kept_stocks
        watchlist["last_updated"] = now_kst()
        archive["last_updated"] = now_kst()
        write_json(WATCHLIST, watchlist, dry)
        write_json(WATCHLIST_ARCHIVE, archive, dry)
    return {
        "evicted_stocks": [s.get("ticker") for s in evicted],
        "trimmed_comments": trimmed_total,
        "trimmed_top_notes": top_trimmed,
        "kept_stocks": len(kept_stocks),
    }


def compact_watch_items(dry: bool) -> dict:
    plan = read_json(WEEKLY_PLAN)
    items = plan.get("watch_items") or []
    if len(items) <= KEEP_WATCH_ITEMS:
        return {"archived": 0, "kept": len(items)}
    # watch_items 는 최신이 앞 (routine 이 prepend) — 앞 N 개 유지.
    kept, overflow = items[:KEEP_WATCH_ITEMS], items[KEEP_WATCH_ITEMS:]
    plan["watch_items"] = kept
    write_json(WEEKLY_PLAN, plan, dry)
    if not dry:
        with WATCH_ITEMS_ARCHIVE.open("a", encoding="utf-8") as f:
            for item in overflow:
                f.write(json.dumps({
                    "archived_at": now_kst(),
                    "week_id": plan.get("week_id"),
                    "item": item,
                }, ensure_ascii=False) + "\n")
    return {"archived": len(overflow), "kept": len(kept)}


def compact_portfolio_history(dry: bool) -> dict:
    portfolio = read_json(PORTFOLIO)
    history = portfolio.get("history") or []
    if not history:
        return {"merged": 0, "kept": 0}

    existing: dict[str, dict] = {}
    if PORTFOLIO_HISTORY.exists():
        for line in PORTFOLIO_HISTORY.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(entry.get("date"))
            existing[key] = entry
    merged = 0
    for entry in history:
        key = str(entry.get("date"))
        if key not in existing:
            existing[key] = entry
            merged += 1
    if not dry:
        ordered = [existing[k] for k in sorted(existing)]
        PORTFOLIO_HISTORY.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in ordered),
            encoding="utf-8",
        )
    if len(history) > KEEP_HISTORY:
        portfolio["history"] = history[-KEEP_HISTORY:]
        write_json(PORTFOLIO, portfolio, dry)
    return {"merged": merged, "kept": min(len(history), KEEP_HISTORY), "jsonl_total": len(existing)}


def compact_policy_changelog(dry: bool) -> dict:
    policy = read_json(POLICY)
    changelog = policy.get("changelog") or []
    if len(changelog) <= KEEP_CHANGELOG:
        return {"archived": 0, "kept": len(changelog)}

    existing_text = CHANGELOG_DOC.read_text(encoding="utf-8") if CHANGELOG_DOC.exists() else ""
    lines: list[str] = []
    if not existing_text:
        lines.append("# policy.json changelog 전문 (compact_state.py 가 이관·누적)\n")
        lines.append("> 핫패스 콘텍스트 절약을 위해 policy.json 에는 최근 "
                     f"{KEEP_CHANGELOG}건만 남긴다. 전체 이력은 이 파일 + git 히스토리.\n")
    appended = 0
    # changelog 는 최신이 앞 — 문서에는 오래된 것부터 누적되도록 역순으로 붙인다.
    for entry in reversed(changelog):
        text = entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)
        if text in existing_text or any(text in l for l in lines):
            continue
        lines.append(f"- {text}\n")
        appended += 1
    if not dry and (lines or appended):
        with CHANGELOG_DOC.open("a", encoding="utf-8") as f:
            f.writelines(lines)
    policy["changelog"] = changelog[:KEEP_CHANGELOG]
    write_json(POLICY, policy, dry)
    return {"archived_to_doc": appended, "kept": KEEP_CHANGELOG}


def compact_target_estimate_log(dry: bool) -> dict:
    """target_estimate_log.jsonl 보존창(90일) 초과분을 archive 로 이관 (plan Phase 1-6).

    이 원장은 0900/1200/1800 슬롯마다 append 되어 일 ~19KB 씩 무한 성장하는데(진단 P13),
    소비자(score_target_estimates)의 채점 지평은 60거래일이라 그 밖은 핫패스에 필요 없다.
    멱등 — archive 에는 동일 라인을 중복 적재하지 않는다.
    """
    if not TARGET_LOG.exists():
        return {"skipped": "missing"}
    cutoff = (datetime.now(KST).date() - timedelta(days=TARGET_LOG_KEEP_DAYS)).isoformat()
    keep: list[str] = []
    move: list[str] = []
    for raw in TARGET_LOG.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
            stamp = str(entry.get("date") or entry.get("as_of") or "")[:10]
        except json.JSONDecodeError:
            keep.append(raw)  # 파싱 불가 라인은 이관하지 않고 보존(데이터 훼손 방지)
            continue
        (move if stamp and stamp < cutoff else keep).append(raw)
    if move and not dry:
        existing: set[str] = set()
        if TARGET_LOG_ARCHIVE.exists():
            existing = set(TARGET_LOG_ARCHIVE.read_text(encoding="utf-8").splitlines())
        with TARGET_LOG_ARCHIVE.open("a", encoding="utf-8") as fh:
            for raw in move:
                if raw not in existing:
                    fh.write(raw + "\n")
        TARGET_LOG.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    return {"entries": len(keep) + len(move), "kept": len(keep), "moved": len(move), "cutoff": cutoff}


def compact_lessons_update_chain(dry: bool) -> dict:
    """lessons.md '최종 갱신' 라인의 '이전 갱신:' 무한 체인을 압축한다.

    라인 형식: `_(최종 갱신: <현재 엔트리> 이전 갱신: <엔트리> 이전 갱신: <엔트리> ...)_`
    현재 + 최근 KEEP_UPDATE_CHAIN 개만 남기고, 초과분 전문은 lessons_archive.md 에 이관.
    """
    if not LESSONS.exists():
        return {"skipped": "lessons.md 부재"}
    text = LESSONS.read_text(encoding="utf-8")
    lines = text.splitlines()
    target_idx = next((i for i, l in enumerate(lines) if l.startswith("_(최종 갱신:")), None)
    if target_idx is None:
        return {"skipped": "최종 갱신 라인 없음"}
    line = lines[target_idx]
    if not line.endswith(")_"):
        return {"skipped": "라인 꼬리 형식 상이 — 수동 확인 필요"}
    inner = line[len("_("):-len(")_")]
    parts = inner.split(" 이전 갱신: ")
    if len(parts) <= 1 + KEEP_UPDATE_CHAIN:
        return {"chain_entries": len(parts), "archived": 0, "line_bytes": len(line.encode("utf-8"))}
    keep, overflow = parts[: 1 + KEEP_UPDATE_CHAIN], parts[1 + KEEP_UPDATE_CHAIN:]
    new_line = "_(" + " 이전 갱신: ".join(keep) + " — 이전 체인은 lessons_archive.md 이관)_"
    if not dry:
        stamp = now_kst()
        block = [f"\n## 최종 갱신 체인 이관 ({stamp})\n"]
        block += [f"- 이전 갱신: {p}" for p in overflow]
        with LESSONS_ARCHIVE.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(block) + "\n")
        lines[target_idx] = new_line
        LESSONS.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return {
        "chain_entries": len(parts),
        "archived": len(overflow),
        "line_bytes_before": len(line.encode("utf-8")),
        "line_bytes_after": len(new_line.encode("utf-8")),
    }


COUNTER_PREV_RE = re.compile(r"\s*\*{0,2}\[이전 기록\]\*{0,2}")


def _trim_counter_chains(lines: list[str]) -> tuple[list[str], list[str], int, int] | None:
    """(새 줄 목록, archive 로 옮길 체인 줄, 원래 바이트, 압축 후 바이트). 카운터 섹션 없으면 None."""
    start = next((i for i, l in enumerate(lines) if l.startswith("## 누적 패턴 카운터")), None)
    if start is None:
        return None
    lines = list(lines)
    moved: list[str] = []
    before = after = 0
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("#"):
            break
        if not line.startswith("- "):
            continue
        m = COUNTER_PREV_RE.search(line)
        if not m:
            continue
        head, chain = line[: m.start()].rstrip(), line[m.start():].strip()
        name = head[2:].split(":", 1)[0].strip().strip("*").strip()
        new_line = head + " — 이전 기록은 lessons_archive.md 이관)"
        moved.append(f"- {name}: {chain}")
        before += len(line.encode("utf-8"))
        after += len(new_line.encode("utf-8"))
        lines[i] = new_line
    return lines, moved, before, after


def compact_lessons_counter_chains(dry: bool) -> dict:
    """누적 패턴 카운터 각 줄의 '[이전 기록]' 체인을 압축한다.

    18시가 카운터를 갱신할 때 직전 기록 앞에 '[이전 기록]' 을 붙여 줄 뒤로 밀어내므로 줄당
    5~14KB 까지 자랐다(2026-10-25 실측 6줄 51KB). 건수(`- 이름: **N건**`)와 최신 기록은 남기고
    첫 '[이전 기록]' 이후 체인 전문만 lessons_archive.md 로 옮긴다 — 카운터 파서 계약 무변경.
    """
    if not LESSONS.exists():
        return {"skipped": "lessons.md 부재"}
    text = LESSONS.read_text(encoding="utf-8")
    trimmed = _trim_counter_chains(text.splitlines())
    if trimmed is None:
        return {"skipped": "누적 패턴 카운터 섹션 없음"}
    lines, moved, before, after = trimmed
    if moved and not dry:
        block = [f"\n## 누적 패턴 카운터 이전 기록 이관 ({now_kst()})\n"] + moved
        with LESSONS_ARCHIVE.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(block) + "\n")
        LESSONS.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return {"counters_compacted": len(moved), "bytes_before": before, "bytes_after": after}


LESSON_HEAD_RE = re.compile(r"^(#{2,3})\s+(.+)$")
LESSON_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _split_lesson_units(lines: list[str]) -> list[dict]:
    """lessons.md 를 순서 보존 단위로 나눈다.

    kind — pre: 첫 헤딩 앞(제목·설명) / struct: 날짜 없는 `## `(분류 체계·카운터 등)과 여러 줄
    HTML 주석(작성 템플릿 — 안의 `###` 는 헤딩이 아니다) / entry: 날짜가 든 `## `·`### ` 헤딩.
    09시·사후분석이 하단에 `## 날짜` 로 붙인 항목도 entry 다(파서들이 `###` 만 보던 사각).
    """
    units: list[dict] = [{"kind": "pre", "date": None, "lines": []}]
    in_comment = False
    for raw in lines:
        if in_comment:
            units[-1]["lines"].append(raw)
            in_comment = "-->" not in raw
            continue
        if raw.lstrip().startswith("<!--") and "-->" not in raw:
            units.append({"kind": "struct", "date": None, "lines": [raw]})
            in_comment = True
            continue
        m = LESSON_HEAD_RE.match(raw)
        if m:
            dm = LESSON_DATE_RE.search(m.group(2))
            if dm or m.group(1) == "###":
                units.append({"kind": "entry", "date": dm.group(1) if dm else None, "lines": [raw]})
            else:
                units.append({"kind": "struct", "date": None, "lines": [raw]})
            continue
        units[-1]["lines"].append(raw)
    return units


def _lesson_stub(unit: dict, haystack: str, today: str, stamp_date: str) -> list[str] | None:
    """이관 항목에서 핫패스에 남겨야 할 줄만 추린 스텁. 남길 줄이 없으면 None.

    남기는 줄: ①미해결 마커 줄 중 반영 신호(strong)가 policy/prompts 에 아직 없는 것
    (check_lessons_applied 와 같은 판정 — 반영되면 다음 압축에서 스텁이 자동 소멸)
    ②만료일이 오늘 이후인 (expiry: …) 룰 줄(일몰 전 임시 룰은 아직 유효).
    """
    head, body = unit["lines"][0], unit["lines"][1:]
    keep: list[str] = []
    for line in body:
        if LESSONS_STUB_TAG in line:
            continue
        if any(mk in line for mk in UNRESOLVED_MARKERS):
            strong, _ = extract_signals(line)
            if not any(signal_in_haystack(s, haystack) for s in strong):
                keep.append(line)
                continue
        em = EXPIRY_RE.search(line)
        if em and em.group(1) >= today:
            keep.append(line)
    if not keep:
        return None
    if any(LESSONS_STUB_TAG in l for l in body):
        return unit["lines"]  # 이미 스텁 — 원문은 앞선 이관에서 archive 에 있다
    stub = [head]
    cat = next((l for l in body if re.match(r"^\s*[-*]?\s*\*{0,2}(?:원인\s*)?분류\*{0,2}\s*[:：]", l)), None)
    if cat and cat not in keep:
        stub.append(cat)
    stub += keep
    # 원 섹션의 반복/재발 여부를 보존해 감사의 hard/soft 분류가 이관으로 바뀌지 않게 한다.
    if any(rm in "\n".join(body) for rm in REPEAT_MARKERS) and not any(
            rm in "\n".join(stub) for rm in REPEAT_MARKERS):
        stub.append("- (원 섹션에 반복·재발 마커 있음)")
    stub.append(f"- {LESSONS_STUB_TAG}: 전문은 state/lessons_archive.md ({stamp_date} 이관) "
                "— 미해결 마커·미만료 룰 줄만 남김")
    stub.append("")
    return stub


def compact_lessons_sections(dry: bool) -> dict:
    """lessons.md 항목 본문을 보존 창 밖이면 lessons_archive.md 로 원문 이관한다.

    ①날짜가 오늘-LESSONS_KEEP_DAYS 보다 이전인 항목 이관 ②그래도 lessons_max_bytes ×
    LESSONS_TARGET_RATIO 를 넘으면 창 안 항목도 오래된 순으로 추가 이관(오늘·어제 제외)
    ③이관 항목의 미해결·미만료 줄은 스텁으로 제자리에 남긴다. 날짜 없는 항목·구조 블록·카운터는
    건드리지 않는다. archive 를 먼저 쓰고 lessons.md 를 쓴다(중단 시 중복은 있어도 유실은 없다).
    """
    if not LESSONS.exists():
        return {"skipped": "lessons.md 부재"}
    text = LESSONS.read_text(encoding="utf-8")
    units = _split_lesson_units(text.splitlines())
    today_d = datetime.now(KST).date()
    today = today_d.isoformat()
    cutoff = (today_d - timedelta(days=LESSONS_KEEP_DAYS)).isoformat()
    floor = (today_d - timedelta(days=LESSONS_FLOOR_DAYS)).isoformat()
    max_bytes = int(((read_json(POLICY).get("context_budget") or {}).get("audit_thresholds") or {})
                    .get("lessons_max_bytes", 60000))
    target = int(max_bytes * LESSONS_TARGET_RATIO)
    haystack, _ = build_haystack()
    # 아직 안 깎인 카운터 체인 바이트 — 실제 실행에선 앞 단계가 이미 깎아 0, --dry-run 에서만
    # 남는다. 크기 추정에서 빼 dry-run 이 이관량을 과대 보고하지 않게 한다(출력엔 반영 안 함).
    trimmed = _trim_counter_chains(text.splitlines())
    pending_counter_bytes = (trimmed[2] - trimmed[3]) if trimmed else 0

    stubs: dict[int, list[str] | None] = {}

    def archive(i: int) -> None:
        stubs[i] = _lesson_stub(units[i], haystack, today, today)

    def render() -> list[str]:
        out: list[str] = []
        for i, u in enumerate(units):
            if i in stubs:
                out += stubs[i] or []
            else:
                out += u["lines"]
        return out

    def size(lines: list[str]) -> int:
        return len(("\n".join(lines) + "\n").encode("utf-8")) - pending_counter_bytes

    for i, u in enumerate(units):
        if u["kind"] == "entry" and u["date"] and u["date"] < cutoff:
            archive(i)
    window_moved = sum(1 for i in stubs if not any(LESSONS_STUB_TAG in l for l in units[i]["lines"]))
    window_count = len(stubs)
    # 예산 초과분 — 남은 항목을 오래된 날짜부터(동일 날짜는 파일 뒤쪽부터) 추가 이관.
    extra = sorted((u["date"], -i, i) for i, u in enumerate(units)
                   if i not in stubs and u["kind"] == "entry" and u["date"] and u["date"] < floor)
    for _, _, i in extra:
        if size(render()) <= target:
            break
        archive(i)

    moved = [i for i in stubs if not any(LESSONS_STUB_TAG in l for l in units[i]["lines"])]
    new_lines = render()
    result = {
        "entries": sum(u["kind"] == "entry" for u in units),
        "moved": len(moved),
        "moved_by_window": window_moved,
        "moved_by_budget": len(stubs) - window_count,
        "stubs_kept": sum(1 for i in stubs if stubs[i]),
        "cutoff": cutoff,
        "bytes_before": len(text.encode("utf-8")),
        "bytes_after": size(new_lines),
        "target_bytes": target,
    }
    if dry or new_lines == text.splitlines():
        return result
    if moved:
        block = [f"\n## 항목 이관 ({now_kst()}, compact_state 자동 — 보존 창 {LESSONS_KEEP_DAYS}일·"
                 f"목표 {target:,}B)\n"]
        for i in sorted(moved):
            block += units[i]["lines"]
        with LESSONS_ARCHIVE.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(block).rstrip("\n") + "\n")
    LESSONS.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return result


def parse_ymd(value) -> str:
    """값에서 YYYY-MM-DD 를 뽑는다. 실패 시 '' (보수적 — 날짜 불명은 이관하지 않는 쪽으로)."""
    s = str(value or "")[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return ""


def append_jsonl_dedup(path: Path, records: list[dict], dry: bool) -> int:
    """records 를 path 에 1줄 1건 append. 동일 라인은 중복 적재하지 않는다(멱등)."""
    if not records or dry:
        return len(records)
    existing: set[str] = set()
    if path.exists():
        existing = set(path.read_text(encoding="utf-8").splitlines())
    appended = 0
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            line = json.dumps(rec, ensure_ascii=False)
            if line not in existing:
                fh.write(line + "\n")
                appended += 1
    return appended


def compact_pending_orders(dry: bool) -> dict:
    """P0 A-1 — 종결 상태 주문·오래된 날짜형 _meta 키를 archive 로 이관.

    실측(2026-08-13): orders 101건 중 종결 91건(90%)이 잔존해 131KB. 소비자 계약:
    check_intraday_alerts 는 status ∈ (None, active) 만 평가, sync_pending_orders 는
    active SELL 만 갱신, 0900 프롬프트 만료 정리는 당일 valid_until 만 본다 — 종결 7일+
    주문은 어떤 소비자도 읽지 않는다.
    """
    if not PENDING_ORDERS.exists():
        return {"skipped": "missing"}
    data = read_json(PENDING_ORDERS)
    orders = data.get("orders")
    if not isinstance(orders, list):
        return {"skipped": "orders 리스트 부재"}
    cutoff = (datetime.now(KST).date() - timedelta(days=KEEP_TERMINAL_ORDER_DAYS)).isoformat()
    stamp = now_kst()

    kept, moved = [], []
    for order in orders:
        if not isinstance(order, dict):
            kept.append(order)
            continue
        status = str(order.get("status") or "")
        terminal = status in TERMINAL_ORDER_STATUSES or status.startswith("resolved")
        # 기준일: valid_until → id(po-YYYYMMDD-n) 순. 날짜 불명 종결 주문은 보수적으로 보존.
        ref = parse_ymd(order.get("valid_until"))
        if not ref:
            oid = str(order.get("id") or "")
            if len(oid) >= 11 and oid.startswith("po-"):
                raw = oid[3:11]
                ref = parse_ymd(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
        if terminal and ref and ref < cutoff:
            moved.append({"archived_at": stamp, "kind": "order", "order": order})
        else:
            kept.append(order)

    # 날짜형 메타 키(_meta_0600_YYYYMMDD 류) — 보존창 지난 것 이관.
    meta_moved = []
    for key in list(data.keys()):
        if not key.startswith("_meta_"):
            continue
        tail = key.rsplit("_", 1)[-1]
        ref = parse_ymd(f"{tail[:4]}-{tail[4:6]}-{tail[6:8]}") if len(tail) == 8 and tail.isdigit() else ""
        if ref and ref < cutoff:
            meta_moved.append({"archived_at": stamp, "kind": "meta", "key": key, "value": data.pop(key)})

    if moved or meta_moved:
        data["orders"] = kept
        append_jsonl_dedup(PENDING_ARCHIVE, moved + meta_moved, dry)
        write_json(PENDING_ORDERS, data, dry)
    return {"orders_total": len(orders), "kept": len(kept), "moved": len(moved),
            "meta_keys_moved": len(meta_moved), "cutoff": cutoff}


def compact_catalysts_manual(dry: bool) -> dict:
    """P0 A-2 — manual_events 의 과거 이벤트를 archive 로 이관.

    실측(2026-08-13): 42건 중 과거일 33건(79%) 잔존. 보존창 7일은 소비자 계약과 정렬:
    estimate_target_price 는 days_until < -7 이벤트를 스킵하고(진짜 하한), D-day 경보·
    진입 보류·earnings_preview D+1 채점은 모두 그보다 짧은 창을 쓴다. generated_events 는
    fetch_catalysts 가 매주 재생성(스크립트 소유)하므로 대상 아님.
    """
    if not CATALYSTS.exists():
        return {"skipped": "missing"}
    data = read_json(CATALYSTS)
    events = data.get("manual_events")
    if not isinstance(events, list):
        return {"skipped": "manual_events 리스트 부재"}
    cutoff = (datetime.now(KST).date() - timedelta(days=KEEP_PAST_CATALYST_DAYS)).isoformat()
    stamp = now_kst()

    kept, moved = [], []
    for ev in events:
        ref = parse_ymd(ev.get("date")) if isinstance(ev, dict) else ""
        if ref and ref < cutoff:
            moved.append({"archived_at": stamp, "kind": "manual_event", "event": ev})
        else:
            kept.append(ev)  # 날짜 불명·미래·보존창 내 이벤트는 보존

    if moved:
        data["manual_events"] = kept
        append_jsonl_dedup(CATALYSTS_ARCHIVE, moved, dry)
        write_json(CATALYSTS, data, dry)
    return {"manual_total": len(events), "kept": len(kept), "moved": len(moved), "cutoff": cutoff}


def compact_weekend_review(dry: bool) -> dict:
    """P0 A-4 — weekly_plan.weekend_review 의 날짜 키 누적을 이관.

    실측(2026-08-13): saturday_review_2026_07_04 부터 5주+ 주차 키가 누적.
    week_id·last_completed·required_outputs 등 비날짜 키와 최근 2주분은 보존.
    weekend_review 는 check_state_schema 의 weekly_plan 필수 키가 아니다.
    """
    plan = read_json(WEEKLY_PLAN)
    review = plan.get("weekend_review")
    if not isinstance(review, dict):
        return {"skipped": "weekend_review dict 아님"}
    cutoff = (datetime.now(KST).date() - timedelta(days=KEEP_WEEKEND_REVIEW_DAYS)).isoformat()
    stamp = now_kst()

    moved = []
    for key in list(review.keys()):
        m = key.rsplit("_", 3)  # <이름>_YYYY_MM_DD 꼬리 날짜 추출
        ref = parse_ymd("-".join(m[-3:])) if len(m) == 4 else ""
        if ref and ref < cutoff:
            moved.append({"archived_at": stamp, "kind": "weekend_review",
                          "week_id": plan.get("week_id"), "key": key, "value": review.pop(key)})

    if moved:
        append_jsonl_dedup(WEEKLY_PLAN_ARCHIVE, moved, dry)
        write_json(WEEKLY_PLAN, plan, dry)
    return {"keys_total": len(review) + len(moved), "kept": len(review), "moved": len(moved),
            "cutoff": cutoff}


def compact_inference_log(dry: bool) -> dict:
    """P0 A-5 — 채점 완료 + 보존창(90일) 경과 예측·결과 라인을 archive 로 이관.

    target_estimate_log 와 동일 관례(TARGET_LOG_KEEP_DAYS=90). 스코어카드는 보존창의
    롤링 통계가 된다(min_samples 가드 유지). 이관 조건은 보수적으로:
    - 예측 라인(prediction 보유)이 outcome ∈ {hit, partial, miss} 로 확정됐고
      (자체 필드 또는 같은 id 의 결과 라인), ts/id 날짜가 cutoff 이전일 때만
      예측 라인 + 해당 id 의 결과 라인을 함께 이관한다.
    - 미채점·형식 위반·shadow(realized 전용)·_meta 라인은 전부 보존
      (채점·보정 표면 유지 — check_state_schema 의 수리 대상을 숨기지 않는다).
    """
    if not INFERENCE_LOG.exists():
        return {"skipped": "missing"}
    cutoff = (datetime.now(KST).date() - timedelta(days=INFERENCE_LOG_KEEP_DAYS)).isoformat()
    stamp = now_kst()
    raw_lines = [l for l in INFERENCE_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]

    parsed: list[tuple[str, dict | None]] = []
    for line in raw_lines:
        try:
            rec = json.loads(line)
            parsed.append((line, rec if isinstance(rec, dict) else None))
        except json.JSONDecodeError:
            parsed.append((line, None))

    # id → 종결 outcome 여부 (예측 자체 필드 + 결과 라인 병합 — score_inferences 매칭 규칙과 동일)
    terminal_outcomes = {"hit", "partial", "miss"}
    scored_ids: set[str] = set()
    for _, rec in parsed:
        if rec and rec.get("id") and rec.get("outcome") in terminal_outcomes:
            scored_ids.add(str(rec["id"]))

    def pred_date(rec: dict) -> str:
        ref = parse_ymd(rec.get("ts"))
        if ref:
            return ref
        rid = str(rec.get("id") or "")
        if rid.startswith("inf-") and len(rid) >= 12:
            raw = rid[4:12]
            return parse_ymd(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
        return ""

    # 이관 대상 예측 id 확정 (예측 라인 기준으로만 판단)
    move_ids: set[str] = set()
    for _, rec in parsed:
        if not rec or "prediction" not in rec:
            continue
        rid = str(rec.get("id") or "")
        if rid and rid in scored_ids:
            ref = pred_date(rec)
            if ref and ref < cutoff:
                move_ids.add(rid)

    kept_lines, moved_records = [], []
    for line, rec in parsed:
        rid = str(rec.get("id")) if rec and rec.get("id") else ""
        is_pair_line = rec is not None and rid in move_ids and (
            "prediction" in rec or "outcome" in rec or "realized" in rec)
        if is_pair_line:
            moved_records.append({"archived_at": stamp, "kind": "inference", "line": rec})
        else:
            kept_lines.append(line)

    if moved_records and not dry:
        append_jsonl_dedup(INFERENCE_LOG_ARCHIVE, moved_records, dry)
        INFERENCE_LOG.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""),
                                 encoding="utf-8")
    return {"lines_total": len(parsed), "kept": len(kept_lines), "moved": len(moved_records),
            "moved_predictions": len(move_ids), "cutoff": cutoff}


def main() -> int:
    parser = argparse.ArgumentParser(description="핫패스 config 누적 필드 압축 (archive 이관)")
    parser.add_argument("--dry-run", action="store_true", help="변경량만 출력하고 파일은 건드리지 않음")
    args = parser.parse_args()

    summary = {
        "as_of": now_kst(),
        "dry_run": args.dry_run,
        "watchlist": compact_watchlist(args.dry_run),
        "watch_items": compact_watch_items(args.dry_run),
        "portfolio_history": compact_portfolio_history(args.dry_run),
        "policy_changelog": compact_policy_changelog(args.dry_run),
        "target_estimate_log": compact_target_estimate_log(args.dry_run),
        "lessons_update_chain": compact_lessons_update_chain(args.dry_run),
        "lessons_counter_chains": compact_lessons_counter_chains(args.dry_run),
        "lessons_sections": compact_lessons_sections(args.dry_run),
        # P0 커버리지 확장 (2026-08-13, docs/plan_removal_exclusion.md §5-A)
        "pending_orders": compact_pending_orders(args.dry_run),
        "catalysts_manual": compact_catalysts_manual(args.dry_run),
        "weekend_review": compact_weekend_review(args.dry_run),
        "inference_log": compact_inference_log(args.dry_run),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
