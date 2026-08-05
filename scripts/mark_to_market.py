#!/usr/bin/env python3
"""보유 포지션 평가금액의 스냅샷 시세 반영(단일 소스, 의존성 0).

배경 (2026-08-05 사용자 보고 — "카톡 평가금액이 항상 똑같다"):
- 카톡 알림(send_kakao)·인덱스 헤드라인(build_html)의 평가금액은 config/portfolio.json 의
  equity 정적 필드를 그대로 읽는데, 이 필드는 routine 이 파일을 직접 수정할 때만 갱신된다.
  routine 이 한 슬롯이라도 갱신을 건너뛰면 직전 값이 그대로 재발송된다.
  실측(2026-08-05 12시): weekly_plan 메모에는 12:10 평가 4,801,548원을 적으면서
  portfolio.json 은 09:35 값 4,825,648원으로 방치 → 12:23 카톡이 09시와 같은 금액 발송.
- 시세 자체는 state/market_snapshot.json 에 매 슬롯 들어온다(fetch_prices 워크플로) —
  소비 지점이 스냅샷을 무시하고 정적 필드를 읽는 결합이 원인이다.

역할 두 가지:
1) 라이브러리 — overlay_snapshot(portfolio, snapshot) 이 포지션에 스냅샷 시세를 덮어
   평가금액·종목별 등락률을 재계산해 반환한다(파일 무변경, 순수 함수).
   send_kakao.py 와 build_html.py 가 임포트해 발송/렌더 "시점" 값으로 쓴다 —
   routine 의 portfolio.json 갱신 여부와 무관하게 카톡·인덱스가 항상 최신 시세를 싣는다.
2) CLI — config/portfolio.json 의 시세 파생 표시 필드(current_price_approx·
   market_value_approx·equity·unrealized_pnl·cumulative_return_pct·as_of)를 스냅샷
   기준으로 다시 쓴다. fetch_prices 워크플로가 스냅샷 수집 직후 호출해 커밋한다 —
   routine 이 갱신을 잊어도 파일 자체가 낡지 않는다.

불변 원칙: cash·shares·entry_price·realized_pnl·trade_count·history 등 원장 사실은
절대 건드리지 않는다(그건 trade_log 와 reconcile_portfolio 의 영역). 스냅샷에 없는
종목은 기존 평가값을 보존한다(결측이 평가를 0 으로 무너뜨리는 래칫 방지).
검증: --selftest 가 합성 포트폴리오로 equity/괴리 계산을 재현한다. --dry-run 지원.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

PORTFOLIO_PATH = ROOT / "config" / "portfolio.json"
SNAPSHOT_PATH = ROOT / "state" / "market_snapshot.json"


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def snap_price(snap_ticker: dict) -> tuple[float | None, str | None]:
    """스냅샷 1종목에서 (평가에 쓸 가격, 가격 일자) — 당일 OHLC 종가 우선, 없으면 last_close."""
    if not isinstance(snap_ticker, dict):
        return None, None
    ohlc = snap_ticker.get("today_ohlc")
    if isinstance(ohlc, dict):
        close = _num(ohlc.get("close"))
        if close:
            return close, str(ohlc.get("date") or "") or None
    close = _num(snap_ticker.get("last_close"))
    if close:
        for src in snap_ticker.get("sources") or []:
            if isinstance(src, dict) and src.get("ok") and src.get("last_date"):
                return close, str(src["last_date"])
        return close, None
    return None, None


def overlay_snapshot(portfolio: dict, snapshot: dict) -> dict:
    """포지션에 스냅샷 시세를 덮어 평가 요약을 재계산한다 (순수 함수 — 파일 무변경).

    반환: {
      equity, cash, unrealized_pnl, cumulative_return_pct,   # 재계산 합계
      price_as_of,          # 스냅샷 기준 시각(ISO) — 없으면 None
      marked, total,        # 스냅샷 시세가 실제로 덮인 종목 수 / 전체 보유 수
      positions: [{ticker, name, shares, entry_price, price, price_source,
                   market_value, cost_basis, unrealized_pnl, pct_from_entry, tier}]
    }
    스냅샷에 없는 종목은 portfolio 기존 평가(current_price → current_price_approx →
    entry_price)로 폴백하고 price_source 로 구분한다.
    """
    snap_tickers = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(snap_tickers, dict):
        snap_tickers = {}
    cash = _num(portfolio.get("cash")) or 0.0
    initial = _num(portfolio.get("initial_capital")) or 0.0

    positions_out: list[dict] = []
    mv_sum = 0.0
    upnl_sum = 0.0
    marked = 0
    for p in portfolio.get("positions", []):
        if not isinstance(p, dict):
            continue
        shares = _num(p.get("shares")) or 0.0
        if shares <= 0:
            continue
        ticker = str(p.get("ticker", ""))
        price, _price_date = snap_price(snap_tickers.get(ticker, {}))
        if price:
            source = "snapshot"
            marked += 1
        else:
            price = _num(p.get("current_price")) or _num(p.get("current_price_approx"))
            source = "portfolio"
            if not price:
                price = _num(p.get("entry_price")) or 0.0
                source = "entry"
        mv = shares * price
        cost = _num(p.get("cost_basis"))
        if cost is None:
            cost = _num(p.get("cost_basis_total"))
        if cost is None:
            entry = _num(p.get("entry_price")) or 0.0
            cost = shares * entry
        pnl = mv - cost if cost else 0.0
        entry_price = _num(p.get("entry_price")) or (cost / shares if shares else 0.0)
        pct = (price / entry_price - 1.0) * 100.0 if entry_price else None
        mv_sum += mv
        upnl_sum += pnl
        positions_out.append({
            "ticker": ticker,
            "name": p.get("name"),
            "shares": int(shares),
            "entry_price": entry_price,
            "price": price,
            "price_source": source,
            "market_value": round(mv),
            "cost_basis": round(cost),
            "unrealized_pnl": round(pnl),
            "pct_from_entry": round(pct, 2) if pct is not None else None,
            "tier": p.get("tier"),
        })

    equity = cash + mv_sum
    cum_pct = (equity / initial - 1.0) * 100.0 if initial else None
    return {
        "equity": round(equity),
        "cash": round(cash),
        "unrealized_pnl": round(upnl_sum),
        "cumulative_return_pct": round(cum_pct, 3) if cum_pct is not None else None,
        "price_as_of": snapshot.get("as_of") if isinstance(snapshot, dict) else None,
        "marked": marked,
        "total": len(positions_out),
        "positions": positions_out,
    }


def load_marked(root: Path = ROOT) -> dict | None:
    """portfolio + snapshot 를 읽어 overlay 요약을 반환 (소비자 편의 — 실패 시 None)."""
    try:
        portfolio = json.loads((root / "config" / "portfolio.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        snapshot = json.loads((root / "state" / "market_snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        snapshot = {}
    return overlay_snapshot(portfolio, snapshot)


def apply_mark(portfolio: dict, marked: dict) -> bool:
    """overlay 결과를 portfolio dict 의 시세 파생 표시 필드에 반영. 변경 여부 반환.

    스냅샷이 덮지 못한 종목(price_source != snapshot)은 기존 필드를 보존한다.
    """
    changed = False
    by_ticker = {pos["ticker"]: pos for pos in marked.get("positions", [])}
    for p in portfolio.get("positions", []):
        if not isinstance(p, dict):
            continue
        m = by_ticker.get(str(p.get("ticker", "")))
        if not m or m["price_source"] != "snapshot":
            continue
        if p.get("current_price_approx") != m["price"]:
            p["current_price_approx"] = m["price"]
            changed = True
        if p.get("market_value_approx") != m["market_value"]:
            p["market_value_approx"] = m["market_value"]
            changed = True
    for key in ("equity", "unrealized_pnl", "cumulative_return_pct"):
        val = marked.get(key)
        if val is not None and portfolio.get(key) != val:
            portfolio[key] = val
            changed = True
    if changed:
        price_as_of = marked.get("price_as_of")
        portfolio["as_of"] = price_as_of or datetime.now(KST).isoformat(timespec="seconds")
    return changed


def _selftest() -> int:
    portfolio = {
        "initial_capital": 5_000_000,
        "cash": 2_448_748,
        "positions": [
            # 스냅샷이 덮는 종목 — today_ohlc 종가 103,600 으로 재평가되어야 한다
            {"ticker": "055550", "name": "신한지주", "shares": 5,
             "entry_price": 97_609, "cost_basis_total": 488_045,
             "current_price_approx": 104_700.0, "market_value_approx": 523_500},
            # 스냅샷 결측 종목 — 기존 평가 811,000 보존 (결측 래칫 방지)
            {"ticker": "079550", "name": "LIG넥스원", "shares": 1,
             "entry_price": 738_585, "cost_basis_total": 738_585,
             "current_price_approx": 811_000.0, "market_value_approx": 811_000},
        ],
        "equity": 4_825_648,
    }
    snapshot = {
        "as_of": "2026-08-05T14:21:03+09:00",
        "tickers": {
            "055550": {"last_close": 103_600.0,
                       "today_ohlc": {"date": "2026-08-05", "close": 103_600.0},
                       "sources": [{"name": "naver", "ok": True, "last_date": "2026-08-05"}]},
        },
    }
    m = overlay_snapshot(portfolio, snapshot)
    # 기대: equity = 2,448,748 + 5×103,600 + 1×811,000 = 3,777,748... (계산: 518,000+811,000=1,329,000 → 3,777,748)
    expected_equity = 2_448_748 + 5 * 103_600 + 811_000
    expected_pct = round((expected_equity / 5_000_000 - 1.0) * 100.0, 3)
    ok_overlay = (
        m["equity"] == expected_equity
        and m["marked"] == 1 and m["total"] == 2
        and m["cumulative_return_pct"] == expected_pct
        and m["positions"][0]["price_source"] == "snapshot"
        and m["positions"][1]["price_source"] == "portfolio"
        and m["positions"][0]["pct_from_entry"] == round((103_600 / 97_609 - 1) * 100, 2)
    )
    changed = apply_mark(portfolio, m)
    ok_apply = (
        changed
        and portfolio["equity"] == expected_equity
        and portfolio["positions"][0]["current_price_approx"] == 103_600.0
        and portfolio["positions"][0]["market_value_approx"] == 518_000
        and portfolio["positions"][1]["current_price_approx"] == 811_000.0  # 보존
        and portfolio["as_of"] == "2026-08-05T14:21:03+09:00"
    )
    # 재적용 멱등성 — 같은 스냅샷이면 변경 없음(불필요 커밋 방지)
    ok_idempotent = not apply_mark(portfolio, overlay_snapshot(portfolio, snapshot))
    print(json.dumps({
        "case": "2026-08-05 12시 무갱신 재현 — 스냅샷 오버레이/부분 결측/멱등",
        "expected_equity": expected_equity,
        "got_equity": m["equity"],
        "ok_overlay": ok_overlay,
        "ok_apply": ok_apply,
        "ok_idempotent": ok_idempotent,
    }, ensure_ascii=False))
    return 0 if (ok_overlay and ok_apply and ok_idempotent) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="portfolio.json 평가 필드를 스냅샷 시세로 갱신")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 변경 요약만 출력")
    parser.add_argument("--selftest", action="store_true", help="합성 데이터로 계산 검증")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"portfolio.json 로드 실패: {exc}"}, ensure_ascii=False))
        return 1
    try:
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        snapshot = {}

    marked = overlay_snapshot(portfolio, snapshot)
    before_equity = portfolio.get("equity")
    changed = apply_mark(portfolio, marked)
    summary = {
        "price_as_of": marked.get("price_as_of"),
        "marked_positions": f'{marked["marked"]}/{marked["total"]}',
        "equity_before": before_equity,
        "equity_after": portfolio.get("equity"),
        "changed": changed,
        "written": False,
    }
    if changed and not args.dry_run:
        PORTFOLIO_PATH.write_text(
            json.dumps(portfolio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        summary["written"] = True
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
