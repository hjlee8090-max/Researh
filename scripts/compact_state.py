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

실행: 일요일 21시 sunday_archive routine §0-B + 수동. `--dry-run` 으로 변경량만 미리 본다.
표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

KEEP_COMMENTS = 12        # 보유 종목당 최근 코멘트 (≈ 2~3일 × 4~5슬롯)
KEEP_WATCH_ITEMS = 15     # "내일 이어받을 트리거"로서 유효한 분량 (≈ 1주)
KEEP_HISTORY = 10         # 주말 사후분석(1주+)에 충분
KEEP_CHANGELOG = 5        # 최근 정책 변경 맥락 (전문은 docs/policy_changelog.md)
# (v2 Phase 1) watchlist 최상위 누적 배열 — compact_watchlist 는 stock.comments 만 보고
# 최상위 comments/cross_check_notes 는 한 번도 건드리지 않았다. 2026-07-27 실측에서
# comments 가 68건 80.9KB(파일의 61%)로 자라 있었다. 개수 상한과 바이트 상한을 쌍으로 둔다.
KEEP_TOPLEVEL_COMMENTS = 12    # 슬롯 코멘트 ≈ 2~3일치 (직전 슬롯 인계에 필요한 분량)
KEEP_CROSS_CHECK_NOTES = 8     # 섹터 전이 판정 근거 ≈ 1주
MAX_TOPLEVEL_ENTRY_BYTES = 1200  # 항목 하나가 무한히 자라는 것을 막는 크기 상한

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


TRUNCATE_SUFFIX = " …(archive 전문)"


def _truncate_entry(entry, limit: int) -> tuple[object, bool]:
    """항목의 최장 문자열 필드를 limit 바이트로 자른다. (새 항목, 이번에 잘렸는지) 반환.

    멱등이어야 한다 — 이미 자른 항목을 재실행이 다시 자르면 접미사가 겹쳐 붙고
    archive 에 중복 이관된다. 잘린 결과가 limit 을 넘지 않도록 접미사 길이를 미리 빼고,
    dict 는 `_truncated` 마커로 재처리를 막는다.
    """
    budget = max(1, limit - len(TRUNCATE_SUFFIX.encode("utf-8")))
    if isinstance(entry, str):
        raw = entry.encode("utf-8")
        if len(raw) <= limit or entry.endswith(TRUNCATE_SUFFIX):
            return entry, False
        return raw[:budget].decode("utf-8", "ignore") + TRUNCATE_SUFFIX, True
    if not isinstance(entry, dict):
        return entry, False
    if entry.get("_truncated"):
        return entry, False  # 이미 처리됨 — 멱등
    longest, longest_len = None, 0
    for key, value in entry.items():
        if isinstance(value, str) and len(value.encode("utf-8")) > longest_len:
            longest, longest_len = key, len(value.encode("utf-8"))
    if longest is None or longest_len <= limit:
        return entry, False
    trimmed = dict(entry)
    raw = entry[longest].encode("utf-8")
    trimmed[longest] = raw[:budget].decode("utf-8", "ignore") + TRUNCATE_SUFFIX
    trimmed["_truncated"] = True
    return trimmed, True


def compact_watchlist_toplevel(dry: bool) -> dict:
    """watchlist 최상위 누적 배열(comments·cross_check_notes)을 개수·크기 상한으로 압축한다.

    (v2 Phase 1, 2026-07-27) compact_watchlist 의 사각지대였다 — 그 함수는 stocks[] 안의
    comments 만 트림하고 파일의 61% 를 차지하는 최상위 comments 는 손대지 않았다.
    초과분 전문은 watchlist_archive.json 에 이관하므로 학습 재료는 사라지지 않는다.
    """
    if not WATCHLIST.exists():
        return {"skipped": "watchlist.json 부재"}
    watchlist = read_json(WATCHLIST)
    archive = load_archive()
    before = len(json.dumps(watchlist, ensure_ascii=False).encode("utf-8"))
    targets = (
        ("comments", KEEP_TOPLEVEL_COMMENTS, "archived_comments"),
        ("cross_check_notes", KEEP_CROSS_CHECK_NOTES, "archived_cross_check_notes"),
    )
    detail: dict[str, dict] = {}
    changed = False
    for field, keep, bucket_key in targets:
        items = watchlist.get(field)
        if not isinstance(items, list) or not items:
            detail[field] = {"kept": 0, "archived": 0, "truncated": 0}
            continue
        overflow = items[:-keep] if len(items) > keep else []
        retained = items[-keep:] if len(items) > keep else list(items)
        new_retained = []
        cut_originals = []  # 잘린 항목의 전문 — 핫패스만 줄이고 학습 재료는 보존한다.
        for item in retained:
            new_item, was_cut = _truncate_entry(item, MAX_TOPLEVEL_ENTRY_BYTES)
            if was_cut:
                cut_originals.append(item)
            new_retained.append(new_item)
        if overflow or cut_originals:
            changed = True
            bucket = archive.setdefault(bucket_key, [])
            bucket.extend(overflow)
            bucket.extend(cut_originals)
            watchlist[field] = new_retained
        detail[field] = {
            "kept": len(new_retained),
            "archived": len(overflow),
            "truncated": len(cut_originals),
        }
    if changed and not dry:
        watchlist["last_updated"] = now_kst()
        archive["last_updated"] = now_kst()
        write_json(WATCHLIST, watchlist, dry)
        write_json(WATCHLIST_ARCHIVE, archive, dry)
    after = len(json.dumps(watchlist, ensure_ascii=False).encode("utf-8"))
    return {**detail, "bytes_before": before, "bytes_after": after, "bytes_saved": before - after}


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

    if evicted or trimmed_total:
        watchlist["stocks"] = kept_stocks
        watchlist["last_updated"] = now_kst()
        archive["last_updated"] = now_kst()
        write_json(WATCHLIST, watchlist, dry)
        write_json(WATCHLIST_ARCHIVE, archive, dry)
    return {
        "evicted_stocks": [s.get("ticker") for s in evicted],
        "trimmed_comments": trimmed_total,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="핫패스 config 누적 필드 압축 (archive 이관)")
    parser.add_argument("--dry-run", action="store_true", help="변경량만 출력하고 파일은 건드리지 않음")
    args = parser.parse_args()

    summary = {
        "as_of": now_kst(),
        "dry_run": args.dry_run,
        "watchlist": compact_watchlist(args.dry_run),
        "watchlist_toplevel": compact_watchlist_toplevel(args.dry_run),
        "watch_items": compact_watch_items(args.dry_run),
        "portfolio_history": compact_portfolio_history(args.dry_run),
        "policy_changelog": compact_policy_changelog(args.dry_run),
        "target_estimate_log": compact_target_estimate_log(args.dry_run),
        "lessons_update_chain": compact_lessons_update_chain(args.dry_run),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
