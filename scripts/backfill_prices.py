#!/usr/bin/env python3
"""백테스트·벤치마크용 과거 일봉을 대량 백필해 data/ 캐시에 적재한다.

데이터센터 IP(웹 세션)는 Yahoo/Naver 403 이므로 이 스크립트는 **GitHub Actions**
(.github/workflows/backfill_prices.yml, 수집 가능 IP)에서 실행한다.

유니버스: config/backtest_universe.json.tickers + portfolio + candidates. 지수: ^KS11.
출처: Yahoo v8 chart(range 지정) 우선, 실패 시 Naver siseJson(start~end). 둘 다 upsert.
표준 라이브러리만 사용 — 의존성 0.

사용:
  python scripts/backfill_prices.py                 # 기본 range=10y
  python scripts/backfill_prices.py --range max
  python scripts/backfill_prices.py --naver-start 20140101
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pricecache

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 20


def http_get(url: str, extra: dict[str, str] | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
    if extra:
        headers.update(extra)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_yahoo(symbol: str, rng: str) -> list[dict[str, Any]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    try:
        payload = json.loads(http_get(url))
        result = payload["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        o, h, lo, c = q["open"], q["high"], q["low"], q["close"]
    except (urllib.error.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        print(f"  yahoo {symbol} 실패: {type(exc).__name__} {exc}")
        return []
    out: list[dict[str, Any]] = []
    for t, oo, hh, ll, cc in zip(ts, o, h, lo, c):
        if cc is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "date": d,
            "open": oo if oo is not None else cc,
            "high": hh if hh is not None else cc,
            "low": ll if ll is not None else cc,
            "close": cc,
        })
    return out


def fetch_naver(ticker: str, start: str) -> list[dict[str, Any]]:
    end = datetime.now(KST).strftime("%Y%m%d")
    url = (
        f"https://api.finance.naver.com/siseJson.naver?symbol={ticker}"
        f"&requestType=1&startTime={start}&endTime={end}&timeframe=day"
    )
    try:
        raw = http_get(url, {"Referer": "https://finance.naver.com/"}).decode("utf-8", "replace")
        rows = json.loads(raw.strip().replace("'", '"'))
    except (urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        print(f"  naver {ticker} 실패: {type(exc).__name__} {exc}")
        return []
    out: list[dict[str, Any]] = []
    for r in rows[1:]:
        try:
            d = str(r[0])
            out.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[5]) if len(r) > 5 else 0,
            })
        except (IndexError, ValueError, TypeError):
            continue
    return out


def collect_universe() -> tuple[list[str], str]:
    cfg = json.loads((ROOT / "config" / "backtest_universe.json").read_text(encoding="utf-8"))
    tickers = [t["ticker"] for t in cfg.get("tickers", []) if t.get("ticker")]
    seen = set(tickers)
    for rel in ("config/portfolio.json", "config/candidates.json"):
        p = ROOT / rel
        if not p.exists():
            continue
        node = json.loads(p.read_text(encoding="utf-8"))
        for item in node.get("positions", []) or node.get("candidates", []):
            tk = item.get("ticker")
            if tk and tk not in seen:
                tickers.append(tk)
                seen.add(tk)
    return tickers, cfg.get("index_symbol", "^KS11")


def main() -> int:
    ap = argparse.ArgumentParser(description="과거 일봉 백필 → data/ 캐시")
    ap.add_argument("--range", default="10y", help="Yahoo range (1y/2y/5y/10y/max)")
    ap.add_argument("--naver-start", default="20150101", help="Naver 폴백 시작일 YYYYMMDD")
    ap.add_argument("--sleep", type=float, default=0.4, help="요청 간 대기(초)")
    args = ap.parse_args()

    tickers, index_symbol = collect_universe()
    print(f"backfill: {len(tickers)} tickers + index {index_symbol} (range={args.range})")

    total_added = 0
    ok = 0
    for tk in tickers:
        bars = fetch_yahoo(f"{tk}.KS", args.range)
        if not bars:
            bars = fetch_naver(tk, args.naver_start)
        if bars:
            res = pricecache.upsert_bars(pricecache.price_path(tk), bars)
            total_added += res["added"]
            ok += 1
            print(f"  {tk}: +{res['added']} (total {res['total']})")
        time.sleep(args.sleep)

    idx_bars = fetch_yahoo(index_symbol, args.range)
    if idx_bars:
        res = pricecache.upsert_bars(pricecache.index_path(index_symbol), idx_bars)
        print(f"  {index_symbol}: +{res['added']} (total {res['total']})")
    else:
        print(f"  {index_symbol}: 지수 수집 실패 — 벤치마크 없이 백테스트됨")

    print(f"done: {ok}/{len(tickers)} tickers ok, +{total_added} new bars")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
