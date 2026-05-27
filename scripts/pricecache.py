#!/usr/bin/env python3
"""일별 OHLCV 가격 캐시 — 백테스트·벤치마크의 단일 데이터 소스.

레이아웃:
- data/prices/<ticker>.csv   개별 종목 일봉
- data/index/<symbol>.csv    지수 일봉 (^KS11 → _KS11.csv)

포맷: date(YYYY-MM-DD),open,high,low,close,volume — date 오름차순, 중복 date 는 upsert(최신값 우선).
표준 라이브러리(csv)만 사용 — 의존성 0. 네트워크 없음(읽기/병합 전용).

왜 캐시인가:
- fetch_market_data.py 는 매 routine 마다 ~1년치를 받아놓고 6일치만 스냅샷에 남겨 버린다.
- 데이터센터 IP 는 Yahoo/Naver 403 이라 백테스트 세션이 직접 수집 못 한다.
- → GitHub Actions(수집 가능 IP)가 이 캐시에 history 를 누적 커밋하고, 백테스트는 캐시만 읽는다.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
PRICES_DIR = ROOT / "data" / "prices"
INDEX_DIR = ROOT / "data" / "index"
FIELDS = ["date", "open", "high", "low", "close", "volume"]


def safe_symbol(symbol: str) -> str:
    """^KS11 처럼 파일명에 못 쓰는 문자를 치환한다."""
    return symbol.replace("^", "_").replace("/", "_").replace("\\", "_")


def price_path(ticker: str, base: Path | None = None) -> Path:
    return (base / "prices" if base else PRICES_DIR) / f"{ticker}.csv"


def index_path(symbol: str, base: Path | None = None) -> Path:
    return (base / "index" if base else INDEX_DIR) / f"{safe_symbol(symbol)}.csv"


def load_bars(path: Path) -> list[dict]:
    """CSV 캐시를 date 오름차순 dict 리스트로 읽는다. 파일 없으면 빈 리스트."""
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out.append({
                    "date": row["date"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0),
                })
            except (KeyError, ValueError, TypeError):
                continue
    out.sort(key=lambda b: b["date"])
    return out


def _coerce(bar: dict) -> dict | None:
    d = bar.get("date")
    if not d:
        return None
    close = bar.get("close")
    if close is None:
        return None
    try:
        c = float(close)
    except (ValueError, TypeError):
        return None

    def f(key: str) -> float:
        v = bar.get(key)
        try:
            return float(v) if v is not None else c
        except (ValueError, TypeError):
            return c

    return {
        "date": str(d),
        "open": f("open"),
        "high": f("high"),
        "low": f("low"),
        "close": c,
        "volume": (lambda v: float(v) if isinstance(v, (int, float)) else 0.0)(bar.get("volume", 0)),
    }


def upsert_bars(path: Path, bars: Iterable[dict]) -> dict:
    """기존 캐시에 bars 를 병합(같은 date 는 덮어씀)하고 정렬·저장한다.

    반환: {"added": 신규 date 수, "total": 병합 후 총 행 수}.
    """
    existing = {b["date"]: b for b in load_bars(path)}
    before = len(existing)
    for raw in bars:
        b = _coerce(raw)
        if b is not None:
            existing[b["date"]] = b
    merged = [existing[d] for d in sorted(existing)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for b in merged:
            w.writerow(b)
    return {"added": len(merged) - before, "total": len(merged)}
