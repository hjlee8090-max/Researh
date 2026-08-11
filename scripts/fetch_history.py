#!/usr/bin/env python3
"""fetch_history — 백테스트용 장기 일봉 수집 (one-shot/주간) v1.1.

fetch_market_data.py 가 routine 용 5일 스냅샷만 남기는 것과 달리, 목표주가 추정식
백테스트(backtest_target_model.py)가 쓰는 ~2.5년 일봉 전체를 state/price_history.json 에
저장한다. 네트워크 차단된 웹 세션 대신 GitHub Actions 러너(fetch_history.yml)에서 실행.

v1.1: 수집 범위 확장 — ①universe.json pool 전체(~30종목): 섹터값(자금 집중도) 계산에
종목별 거래대금이 섹터 단위로 필요 ②해외 심볼(yahoo): 해외뉴스→국내 주가 전이계수
실증(NVDA·SOXX·S&P500·TSM — 반도체 고객/동종/매크로 채널).

소스: naver siseJson(1차) → yahoo v8 chart(폴백). 지수는 naver symbol=KOSPI → yahoo ^KS11.
해외 심볼은 yahoo 전용. 의존성 0(표준 라이브러리).
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
# 해외 채널 심볼(yahoo 전용) — 고객(NVDA)·동종/섹터(SOXX·TSM·MU·^SOX)·매크로(^GSPC)
# (2026-08-11 P1-a) MU·^SOX 추가 — 7/16(Micron -8.02%·필라델피아반도체 -2.08%)·
# 7/8(PHLX -4.65%)·7/14(마이크론 -6.5% miss) 계열: 야간 미 반도체 확정치가 개장 전
# 슬롯(00/06/09시) 판단의 정식 입력이 된다(reports/2026-08-10-lessons-loop-data-gap-review.md 갭 #2).
GLOBALS = {
    "NVDA": "NVIDIA",
    "SOXX": "iShares Semiconductor ETF",
    "TSM": "TSMC ADR",
    "MU": "Micron",
    "^SOX": "필라델피아 반도체지수",
    "^GSPC": "S&P500",
}


def load_universe_tickers() -> dict[str, dict]:
    """universe.json pool 전체를 수집 대상으로 — 섹터값(거래대금 집중도) 계산용."""
    p = ROOT / "config" / "universe.json"
    out = dict(TICKERS)
    if not p.exists():
        return out
    try:
        pool = json.loads(p.read_text(encoding="utf-8")).get("pool", [])
    except (OSError, json.JSONDecodeError):
        return out
    for m in pool:
        if isinstance(m, dict) and m.get("ticker"):
            out.setdefault(m["ticker"], {
                "name": m.get("name", m["ticker"]),
                "yahoo": f"{m['ticker']}.KS",
                "group": m.get("theme") or m.get("sector"),
            })
    return out


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
    tickers = load_universe_tickers()
    out: dict[str, Any] = {"as_of": now.isoformat(timespec="seconds"), "start_requested": START, "tickers": {}}
    print(f"fetch_history: {len(tickers)} KR tickers + {len(GLOBALS)} global")
    for t, meta in tickers.items():
        rec = collect(t, meta["yahoo"], meta["name"])
        if meta.get("group"):
            rec["group"] = meta["group"]
        out["tickers"][t] = rec
    out["index"] = collect(INDEX["naver"], INDEX["yahoo"], INDEX["name"])
    out["global"] = {}
    for sym, name in GLOBALS.items():
        bars = fetch_yahoo(sym)
        print(f"  {name}({sym}): {len(bars)} bars (yahoo)")
        out["global"][sym] = {"name": name, "source": "yahoo", "bars": bars}
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(len(v["bars"]) for v in out["tickers"].values()) + len(out["index"]["bars"])
    print(f"wrote {OUT_PATH.relative_to(ROOT)} total_kr_bars={total}")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
