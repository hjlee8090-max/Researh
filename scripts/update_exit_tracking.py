#!/usr/bin/env python3
"""보유 종목의 일별 확정 종가를 state/exit_tracking.json 에 적재 (의존성 0).

배경 (reports/2026-07-05-pipeline-counterfactual-research.md §결론 안건⑩):
- exit_tracking 은 청산(exited) 종목만 담고 현 보유 종목은 미커버 — 이를 쓰는
  스크립트가 없어 LLM 수기 관리였고, compute_exit_levels 의 '진입 이후 최고 종가'가
  snapshot.five_day_history(약 6일 창) 폴백에 의존한다. 보유가 6영업일을 넘으면
  초기 고점이 창 밖으로 밀려 최고 종가 산출이 무너진다(compute_exit_levels.py 주석
  실측: 폴백만 쓰면 LS ELECTRIC 1차선 189,765 과소산출).
- 이 스크립트가 18시 EOD(fetch_market_data 직후·compute_exit_levels 직전)에
  보유 종목의 일자별 종가를 exit_tracking 에 영속 적재해 창 제약을 없앤다.

원칙:
- **기존 값 불변**: 이미 기록된 (ticker, date) 는 덮어쓰지 않는다(setdefault) —
  실제 히스토리 파일 소급 수정 금지 원칙과 동일 계열.
- confidence == "low" 종목은 당일 적재 보류(오염 방지) — 사유를 출력하고 다음 EOD 재시도.
- 확정 종가 출처는 snapshot.five_day_history 의 일자별 bar(EOD 교차확인 수집본).
  price_history.json 확정 bar 와의 사후 괴리는 policy.price_data_quality.
  settlement_close_source 의 소급 검증 규약(안건⑧)이 커버한다.

입력: config/portfolio.json, state/market_snapshot.json, state/exit_tracking.json
출력: state/exit_tracking.json 갱신 + stdout JSON 요약
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="보유 종목 일별 종가를 exit_tracking 에 적재")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 변경 예정만 출력")
    args = parser.parse_args()

    portfolio = load_json(ROOT / "config" / "portfolio.json") or {}
    snapshot = (load_json(ROOT / "state" / "market_snapshot.json") or {}).get("tickers", {})
    dest = ROOT / "state" / "exit_tracking.json"
    tracking = load_json(dest)
    if not isinstance(tracking, dict):
        tracking = {"tickers": {}, "exited_tickers": []}
    tickers = tracking.setdefault("tickers", {})

    added: dict[str, list[str]] = {}
    skipped: list[dict] = []
    for pos in portfolio.get("positions", []):
        if not isinstance(pos, dict) or not pos.get("shares"):
            continue
        ticker = str(pos.get("ticker", ""))
        snap = snapshot.get(ticker, {}) if isinstance(snapshot, dict) else {}
        if not isinstance(snap, dict):
            continue
        if snap.get("confidence") == "low":
            skipped.append({"ticker": ticker, "reason": "confidence=low — 당일 적재 보류(다음 EOD 재시도)"})
            continue
        bars = snap.get("five_day_history") or []
        entry = tickers.setdefault(ticker, {})
        if not isinstance(entry, dict):
            continue
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            d, c = bar.get("date"), bar.get("close")
            if isinstance(d, str) and isinstance(c, (int, float)) and d not in entry:
                entry[d] = float(c)
                added.setdefault(ticker, []).append(d)
        # 날짜 키 정렬 유지(가독·diff 안정)
        tickers[ticker] = dict(sorted(entry.items()))

    summary = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "held_tracked": sum(1 for p in portfolio.get("positions", []) if isinstance(p, dict) and p.get("shares")),
        "added": {t: len(ds) for t, ds in added.items()},
        "added_dates": added,
        "skipped": skipped,
        "dry_run": bool(args.dry_run),
        "note": "기존 (ticker,date) 값은 불변(setdefault) — compute_exit_levels 의 최고 종가 소스(exit_tracking ∪ five_day_history)의 영속층",
    }
    if added and not args.dry_run:
        tracking["as_of"] = summary["as_of"]
        dest.write_text(json.dumps(tracking, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
