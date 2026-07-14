#!/usr/bin/env python3
"""watchlist.json 의 보유 종목 필드를 정본(portfolio.json·exit_levels.json)과 동기화한다.

배경 (2026-07-08 파이프라인 정밀 검사 B-1/B-2):
- watchlist 의 stop_price/target_price 가 6/30 지시가(indicative ±10%) 그대로 방치되어
  portfolio·exit_levels 와 6/6 종목 전부 불일치 — check_valuation_guard 등 watchlist 를
  읽는 소비자가 폐기된 "제3값"으로 판정하는 사고 토양 (정책 v2.21 ⑦ 위반 상태).
- shares_held 필드가 전 종목 결측(null) — `shares_held > 0` 로 보유를 판정하는
  fetch_news/estimate_target_price/audit_pipeline 이 보유 종목을 미보유로 오판.

동기화 규칙 (portfolio.json 이 보유의 정본, exit_levels.json 이 청산선의 정본):
- portfolio.positions(shares>0) 에 있는 종목: watchlist 항목에 shares_held·stop_price·
  target_price 를 정본 값으로 덮어쓰고 status="held" 보장.
- watchlist 에 status="held" 인데 portfolio 에 없는 종목: shares_held=0 만 기록하고
  경고 출력 (이관은 compact_state 소관 — 여기서 삭제하지 않는다).
- portfolio 에 있는데 watchlist 에 없는 종목: 경고만 (신규 항목 자동 생성은 routine 몫).

실행 슬롯: 18시(EOD 확정 후)·정합성 이슈 발견 시 수동. 멱등. --dry-run 지원.
표준 라이브러리만 사용, 의존성 0. exit 0=변경 없음/적용 완료, 2=경고 있음.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    watchlist = load("config/watchlist.json")
    portfolio = load("config/portfolio.json")
    try:
        exit_levels = load("state/exit_levels.json").get("tickers", {})
    except FileNotFoundError:
        exit_levels = {}

    positions = {
        p["ticker"]: p
        for p in portfolio.get("positions", [])
        if isinstance(p, dict) and (p.get("shares") or 0) > 0
    }
    stocks = watchlist.get("stocks", [])
    by_ticker = {s.get("ticker"): s for s in stocks if isinstance(s, dict)}

    changes: list[str] = []
    warnings: list[str] = []

    for ticker, pos in positions.items():
        stock = by_ticker.get(ticker)
        if stock is None:
            warnings.append(f"[WARN] 보유 종목 {ticker}({pos.get('name')}) 이 watchlist 에 없음 — routine 이 항목을 추가해야 함")
            continue
        # 청산선 정본: exit_levels > portfolio 순으로 채택 (둘은 원래 일치해야 한다)
        lv = exit_levels.get(ticker, {})
        authoritative = {
            "shares_held": int(pos.get("shares") or 0),
            "stop_price": lv.get("stop_price", pos.get("stop_price")),
            "target_price": lv.get("target_price", pos.get("target_price")),
            "status": "held",
        }
        if lv and pos.get("stop_price") not in (None, lv.get("stop_price")):
            warnings.append(
                f"[WARN] {ticker} stop_price 정본끼리 불일치: exit_levels {lv.get('stop_price')} vs portfolio {pos.get('stop_price')} — exit_levels 채택"
            )
        for key, val in authoritative.items():
            if val is None:
                continue
            old = stock.get(key)
            if old != val:
                changes.append(f"{ticker} {key}: {old} -> {val}")
                stock[key] = val

    for ticker, stock in by_ticker.items():
        if stock.get("status") == "held" and ticker not in positions:
            if (stock.get("shares_held") or 0) != 0:
                changes.append(f"{ticker} shares_held: {stock.get('shares_held')} -> 0 (portfolio 에 미보유)")
            stock["shares_held"] = 0
            warnings.append(f"[WARN] {ticker} status=held 이나 portfolio 미보유 — status 재확인 필요 (자동 변경 안 함)")

    if not changes:
        print("[OK] watchlist 이미 정본과 일치 — 변경 없음")
    else:
        for c in changes:
            print(f"[SYNC] {c}")
        if not args.dry_run:
            watchlist["last_updated"] = datetime.now(KST).isoformat(timespec="seconds")
            (ROOT / "config/watchlist.json").write_text(
                json.dumps(watchlist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"[OK] config/watchlist.json 갱신 ({len(changes)}건)")
        else:
            print(f"[DRY-RUN] 적용 시 {len(changes)}건 변경")

    for w in warnings:
        print(w)
    return 2 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
