#!/usr/bin/env python3
"""보유·후보 종목의 일별 가격을 두 출처(stooq, Yahoo Finance)에서 수집해 신뢰도와 5거래일 추세를 산출한다.

routine prompt 가 매 시작 시 이 스크립트를 호출하여 `state/market_snapshot.json` 을 갱신하고,
이후 가격 판단·신규 진입 추세필터·entry 차단 사유를 결정한다.

- 의존성: Python 표준 라이브러리만 사용 (urllib, json, csv). 추가 패키지 설치 불필요.
- 네트워크: stooq.com 일별 CSV + Yahoo Finance v8 chart JSON. 둘 중 하나만 살아 있어도 medium 신뢰도까지 산출.
- 출력: state/market_snapshot.json (신규 생성·덮어쓰기). state/audit_log 와 무관.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
# 일부 데이터 출처(특히 Yahoo)는 기본/봇 User-Agent 를 403 으로 거부하므로 브라우저 UA 를 사용한다.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 12
HTTP_RETRIES = 2

logger = logging.getLogger(__name__)


def http_get(url: str) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    last_exc: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # 403/404 같은 클라이언트 거부는 재시도해도 동일하므로 즉시 포기한다.
            if exc.code in (401, 403, 404):
                raise
            last_exc = exc
        except Exception as exc:  # noqa: BLE001 - 일시적 네트워크 오류는 재시도 대상
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def fetch_stooq(ticker: str) -> list[dict[str, Any]]:
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.kr&i=d"
    try:
        raw = http_get(url).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - we want to record any failure mode
        logger.warning("stooq fetch failed for %s: %s", ticker, exc)
        return []
    if not raw.strip() or "No data" in raw:
        return []
    rows = list(csv.DictReader(io.StringIO(raw)))
    out: list[dict[str, Any]] = []
    for r in rows[-20:]:
        try:
            out.append({"date": r["Date"], "close": float(r["Close"])})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fetch_yahoo(ticker: str) -> list[dict[str, Any]]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.KS"
        "?range=1mo&interval=1d"
    )
    try:
        raw = http_get(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("yahoo fetch failed for %s: %s", ticker, exc)
        return []
    try:
        payload = json.loads(raw)
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("yahoo parse failed for %s: %s", ticker, exc)
        return []
    out: list[dict[str, Any]] = []
    for t, c in zip(timestamps, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append({"date": d, "close": float(c)})
    return out[-20:]


def compute_confidence(stooq_last: float | None, yahoo_last: float | None) -> tuple[str, float | None]:
    if stooq_last and yahoo_last:
        gap = abs(stooq_last - yahoo_last) / max(stooq_last, yahoo_last) * 100
        if gap <= 1.0:
            return "high", round(gap, 3)
        if gap <= 2.0:
            return "medium", round(gap, 3)
        return "low", round(gap, 3)
    if stooq_last or yahoo_last:
        return "medium", None
    return "low", None


def five_day_return(history: list[dict[str, Any]]) -> float | None:
    if len(history) < 6:
        return None
    last_close = history[-1]["close"]
    base_close = history[-6]["close"]
    if base_close <= 0:
        return None
    return round((last_close - base_close) / base_close * 100, 2)


def load_json(rel: str) -> dict[str, Any]:
    path = ROOT / rel
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def collect_tickers() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    portfolio = load_json("config/portfolio.json")
    for pos in portfolio.get("positions", []):
        ticker = pos.get("ticker")
        if not ticker:
            continue
        out[ticker] = {"name": pos.get("name", ""), "role": "holding"}
    candidates = load_json("config/candidates.json")
    for c in candidates.get("candidates", []):
        ticker = c.get("ticker")
        if not ticker:
            continue
        out.setdefault(ticker, {"name": c.get("name", ""), "role": "candidate"})
    return out


def build_ticker_snapshot(
    ticker: str,
    meta: dict[str, str],
    threshold_pct: float,
) -> dict[str, Any]:
    stooq_hist = fetch_stooq(ticker)
    yahoo_hist = fetch_yahoo(ticker)
    stooq_last = stooq_hist[-1]["close"] if stooq_hist else None
    yahoo_last = yahoo_hist[-1]["close"] if yahoo_hist else None
    confidence, gap_pct = compute_confidence(stooq_last, yahoo_last)
    primary_hist = stooq_hist or yahoo_hist
    ret5 = five_day_return(primary_hist) if primary_hist else None
    filter_passes = ret5 is not None and ret5 >= threshold_pct
    if ret5 is None:
        reason = "데이터 부족 — 5거래일 가격 수집 실패"
    elif not filter_passes:
        reason = f"5거래일 누적 {ret5}% < 기준 {threshold_pct}%"
    else:
        reason = None
    return {
        "name": meta.get("name", ""),
        "role": meta.get("role", "candidate"),
        "sources": [
            {
                "name": "stooq",
                "last_close": stooq_last,
                "last_date": stooq_hist[-1]["date"] if stooq_hist else None,
                "ok": bool(stooq_hist),
            },
            {
                "name": "yahoo",
                "last_close": yahoo_last,
                "last_date": yahoo_hist[-1]["date"] if yahoo_hist else None,
                "ok": bool(yahoo_hist),
            },
        ],
        "confidence": confidence,
        "price_gap_pct": gap_pct,
        "five_day_history": (primary_hist or [])[-6:],
        "five_day_cumulative_return_pct": ret5,
        "entry_filter": {
            "passes": filter_passes,
            "threshold_pct": threshold_pct,
            "reason": reason,
        },
    }


def main() -> int:
    policy = load_json("config/policy.json")
    threshold = (
        policy.get("entry_filters", {}).get("block_if_cumulative_return_below_pct", -7.0)
    )

    tickers = collect_tickers()
    now = datetime.now(KST)
    snapshot: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "policy_threshold_pct": threshold,
        "ticker_count": len(tickers),
        "tickers": {},
    }

    holdings_low = []
    candidates_passing = []
    candidates_failing = []
    sources_ok = 0

    for ticker, meta in tickers.items():
        ts = build_ticker_snapshot(ticker, meta, threshold)
        snapshot["tickers"][ticker] = ts
        sources_ok += sum(1 for s in ts["sources"] if s["ok"])
        if meta.get("role") == "holding" and ts["confidence"] == "low":
            holdings_low.append(ticker)
        if meta.get("role") == "candidate":
            if ts["entry_filter"]["passes"]:
                candidates_passing.append(ticker)
            else:
                candidates_failing.append(ticker)

    snapshot["summary"] = {
        "holdings_with_low_confidence": holdings_low,
        "candidates_passing_filter": candidates_passing,
        "candidates_blocked": candidates_failing,
    }

    out_path = ROOT / "state" / "market_snapshot.json"
    out_path.parent.mkdir(exist_ok=True)

    # 모든 출처가 실패(예: 차단된 네트워크에서 실행)했고 기존 스냅샷이 살아 있으면
    # 빈 데이터로 덮어쓰지 않는다. 이전(예: GitHub Actions 정기 수집) 결과를 보존하되
    # stale 표시를 남겨 다운스트림이 신선도를 판단할 수 있게 한다.
    if sources_ok == 0 and out_path.exists():
        prior = load_json("state/market_snapshot.json")
        if prior.get("tickers"):
            prior["stale"] = {
                "last_fetch_attempt": now.isoformat(timespec="seconds"),
                "reason": "모든 출처 수집 실패 — 직전 스냅샷 보존(덮어쓰기 생략)",
            }
            out_path.write_text(
                json.dumps(prior, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"all sources failed — preserved prior snapshot (as_of={prior.get('as_of')}), "
                "marked stale"
            )
            return 0

    snapshot.pop("stale", None)
    out_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {out_path.relative_to(ROOT)} tickers={len(tickers)} sources_ok={sources_ok} "
        f"pass={len(candidates_passing)} block={len(candidates_failing)} low_conf={len(holdings_low)}"
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
