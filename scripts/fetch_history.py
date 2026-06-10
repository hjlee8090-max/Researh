#!/usr/bin/env python3
"""fetch_history — 백테스트용 장기 일봉 수집 (one-shot/주간).

fetch_market_data.py 가 routine 용 5일 스냅샷만 남기는 것과 달리, 목표주가 추정식
백테스트(backtest_target_model.py)가 쓰는 ~2.5년 일봉 전체를 state/price_history.json 에
저장한다. 네트워크 차단된 웹 세션 대신 GitHub Actions 러너(fetch_history.yml)에서 실행.

소스: naver siseJson(1차) → yahoo v8 chart(폴백). 지수는 naver symbol=KOSPI → yahoo ^KS11.
의존성 0(표준 라이브러리).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "price_history.json"
HTTP_TIMEOUT = 20
START = "20240101"

TICKERS = {
    "005930": {"name": "삼성전자", "yahoo": "005930.KS"},
    "005380": {"name": "현대차", "yahoo": "005380.KS"},
}
INDEX = {"naver": "KOSPI", "yahoo": "^KS11", "name": "KOSPI"}


def http_get(url: str, extra_headers: dict[str, str] | None = None) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; research-pipeline/1.0)"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_naver(symbol: str) -> list[dict[str, Any]]:
    end = datetime.now(KST)
    url = (
        f"https://api.finance.naver.com/siseJson.naver?symbol={symbol}"
        f"&requestType=1&startTime={START}&endTime={end:%Y%m%d}&timeframe=day"
    )
    try:
        raw = http_get(url, {"Referer": "https://finance.naver.com/"}).decode("utf-8", errors="replace")
        rows = json.loads(raw.strip().replace("'", '"'))
    except Exception as exc:  # noqa: BLE001
        print(f"  naver {symbol} 실패: {exc}")
        return []
    out: list[dict[str, Any]] = []
    for r in rows[1:]:
        try:
            d = str(r[0])
            out.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[5]) if len(r) > 5 and r[5] not in (None, "") else None,
            })
        except (IndexError, ValueError, TypeError):
            continue
    return out


def fetch_yahoo(symbol: str) -> list[dict[str, Any]]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=3y&interval=1d&includeAdjustedClose=false"
    )
    try:
        data = json.loads(http_get(url).decode("utf-8", errors="replace"))
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
    except Exception as exc:  # noqa: BLE001
        print(f"  yahoo {symbol} 실패: {exc}")
        return []
    out: list[dict[str, Any]] = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        out.append({
            "date": datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d"),
            "open": q["open"][i], "high": q["high"][i], "low": q["low"][i], "close": c,
            "volume": q["volume"][i],
        })
    return out


def collect(naver_symbol: str, yahoo_symbol: str, name: str) -> dict[str, Any]:
    bars = fetch_naver(naver_symbol)
    source = "naver"
    if len(bars) < 100:  # 결손이면 yahoo 폴백(더 길면 교체)
        ybars = fetch_yahoo(yahoo_symbol)
        if len(ybars) > len(bars):
            bars, source = ybars, "yahoo"
    print(f"  {name}: {len(bars)} bars ({source}) {bars[0]['date'] if bars else '—'}~{bars[-1]['date'] if bars else '—'}")
    return {"name": name, "source": source, "bars": bars}


def main() -> int:
    now = datetime.now(KST)
    out: dict[str, Any] = {"as_of": now.isoformat(timespec="seconds"), "start_requested": START, "tickers": {}}
    print("fetch_history:")
    for t, meta in TICKERS.items():
        out["tickers"][t] = collect(t, meta["yahoo"], meta["name"])
    out["index"] = collect(INDEX["naver"], INDEX["yahoo"], INDEX["name"])
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(len(v["bars"]) for v in out["tickers"].values()) + len(out["index"]["bars"])
    print(f"wrote {OUT_PATH.relative_to(ROOT)} total_bars={total}")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
