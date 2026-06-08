#!/usr/bin/env python3
"""보유·후보 종목의 일별 가격을 두 출처(네이버 금융, Yahoo Finance)에서 수집해 신뢰도와 5거래일 추세를 산출한다.

routine prompt 가 매 시작 시 이 스크립트를 호출하여 `state/market_snapshot.json` 을 갱신하고,
이후 가격 판단·신규 진입 추세필터·entry 차단 사유를 결정한다.

- 의존성: Python 표준 라이브러리만 사용 (urllib, json, concurrent.futures). 추가 패키지 설치 불필요.
- 성능: 종목별 2출처 + 지수 요청을 스레드풀로 동시 수집한다(I/O 바운드 → 직렬 합산이 아닌 최장 요청 수준으로 수렴).
- 네트워크: 네이버 siseJson 일별 + Yahoo Finance v8 chart JSON. 둘 중 하나만 살아 있어도 medium 신뢰도까지 산출.
- 출력: state/market_snapshot.json (신규 생성·덮어쓰기). state/audit_log 와 무관.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
# 종목별 2출처 + 지수 레짐 요청은 모두 네트워크 대기(I/O 바운드)다. 직렬로 돌리면
# (2×종목수 + 1)개 요청이 한 줄로 늘어서 전체 소요가 그 합이 되지만, 스레드풀로 동시에
# 던지면 전체 소요가 '가장 느린 요청 하나' 수준으로 수렴한다(GIL 영향 없음). 출처 부하·
# rate-limit 을 감안해 동시 요청 수에 상한을 둔다.
MAX_WORKERS = 8

logger = logging.getLogger(__name__)


def http_get(url: str, extra_headers: dict[str, str] | None = None) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if extra_headers:
        headers.update(extra_headers)
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


def fetch_naver(ticker: str) -> list[dict[str, Any]]:
    """네이버 금융 siseJson 에서 일별 종가를 수집한다.

    응답은 엄격한 JSON 이 아니라 단일따옴표 의사-JSON 이다 (날짜만 문자열, 숫자는 무인용).
    헤더 문자열에 작은따옴표가 없으므로 ' → " 치환 후 json.loads 로 안전하게 파싱한다.
    행 형식: ['날짜','시가','고가','저가','종가','거래량','외국인소진율'].
    """
    end = datetime.now(KST)
    start = end - timedelta(days=400)  # ATR·60일 모멘텀·52주 고점 산출을 위해 약 1년 확보
    url = (
        f"https://api.finance.naver.com/siseJson.naver?symbol={ticker}"
        f"&requestType=1&startTime={start:%Y%m%d}&endTime={end:%Y%m%d}&timeframe=day"
    )
    try:
        raw = http_get(url, {"Referer": "https://finance.naver.com/"}).decode(
            "utf-8", errors="replace"
        )
    except Exception as exc:  # noqa: BLE001 - we want to record any failure mode
        logger.warning("naver fetch failed for %s: %s", ticker, exc)
        return []
    try:
        rows = json.loads(raw.strip().replace("'", '"'))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("naver parse failed for %s: %s", ticker, exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows[1:]:  # 첫 행은 헤더. 행: ['날짜','시가','고가','저가','종가','거래량',...]
        try:
            d = str(r[0])
            date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            bar = {
                "date": date,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
            }
        except (IndexError, ValueError, TypeError):
            continue
        try:  # 거래량(r[5]) — 몰입(거래량 급증) 신호용. 누락/파싱 실패는 None(비치명).
            bar["volume"] = float(r[5]) if len(r) > 5 and r[5] not in (None, "") else None
        except (ValueError, TypeError):
            bar["volume"] = None
        out.append(bar)
    return out[-260:]


def fetch_yahoo(symbol: str) -> list[dict[str, Any]]:
    """Yahoo v8 chart 일봉을 수집한다. `symbol` 은 `005930.KS` 또는 지수 `^KS11` 처럼 완전한 심볼."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=1y&interval=1d"
    )
    try:
        raw = http_get(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("yahoo fetch failed for %s: %s", symbol, exc)
        return []
    try:
        payload = json.loads(raw)
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        opens, highs, lows, closes = (
            quote["open"], quote["high"], quote["low"], quote["close"],
        )
        volumes = quote.get("volume") or [None] * len(closes)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("yahoo parse failed for %s: %s", symbol, exc)
        return []
    out: list[dict[str, Any]] = []
    for t, o, h, lo, c, v in zip(timestamps, opens, highs, lows, closes, volumes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "date": d,
            "open": float(o) if o is not None else float(c),
            "high": float(h) if h is not None else float(c),
            "low": float(lo) if lo is not None else float(c),
            "close": float(c),
            "volume": float(v) if v is not None else None,
        })
    return out[-260:]


def compute_confidence(naver_last: float | None, yahoo_last: float | None) -> tuple[str, float | None]:
    if naver_last and yahoo_last:
        gap = abs(naver_last - yahoo_last) / max(naver_last, yahoo_last) * 100
        if gap <= 1.0:
            return "high", round(gap, 3)
        if gap <= 2.0:
            return "medium", round(gap, 3)
        return "low", round(gap, 3)
    if naver_last or yahoo_last:
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


def cumulative_return(history: list[dict[str, Any]], lookback: int) -> float | None:
    """lookback 거래일 전 종가 대비 최신 종가 누적 수익률(%). 데이터 부족 시 None."""
    if len(history) < lookback + 1:
        return None
    last_close = history[-1]["close"]
    base_close = history[-(lookback + 1)]["close"]
    if base_close <= 0:
        return None
    return round((last_close - base_close) / base_close * 100, 2)


def pct_of_52w_high(history: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """(현재가가 52주 고점의 몇 %인지, 52주 고점가). 윈도우는 가용 데이터(최대 ~252거래일)."""
    if len(history) < 2:
        return None, None
    window = history[-252:]
    high_52w = max(h.get("high", h["close"]) for h in window)
    if high_52w <= 0:
        return None, None
    last_close = history[-1]["close"]
    return round(last_close / high_52w * 100, 2), round(high_52w, 2)


def compute_atr(history: list[dict[str, Any]], period: int = 14) -> float | None:
    """ATR(period). True Range = max(고-저, |고-전일종가|, |저-전일종가|)의 단순평균."""
    if len(history) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(history)):
        cur, prev_close = history[i], history[i - 1]["close"]
        hi = cur.get("high", cur["close"])
        lo = cur.get("low", cur["close"])
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    return round(sum(trs[-period:]) / period, 2)


def volume_ratio(history: list[dict[str, Any]], period: int = 20) -> float | None:
    """당일 거래량 ÷ 직전 period 거래일 평균 거래량. '몰입(거래량 급증)' 신호용.

    당일 포함 직전 period+1 바가 필요. 거래량 결측이 많으면 None(비치명).
    """
    if len(history) < period + 1:
        return None
    vols = [h.get("volume") for h in history[-(period + 1):]]
    today = vols[-1]
    prior = [v for v in vols[:-1] if isinstance(v, (int, float)) and v > 0]
    if not isinstance(today, (int, float)) or len(prior) < period // 2:
        return None
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return None
    return round(today / avg, 2)


def price_structure(history: list[dict[str, Any]], ma_period: int = 5) -> dict[str, Any]:
    """'공격' 모드 가격구조 반등 신호: 5일선 회복 + higher-low (v2.9).

    above_ma5 = 종가 > 최근 5일 종가 평균(단기 흐름이 위로 꺾임).
    higher_low = 오늘 저가 > 직전 5거래일 최저가(신저점 미갱신 — 바닥 다지기).
    price_reversal = 둘 다 충족. 데이터 부족·결측이면 None.
    """
    none = {"ma5": None, "above_ma5": None, "higher_low": None, "price_reversal": None}
    if len(history) < ma_period + 1:
        return none
    window = history[-(ma_period + 1):]
    closes = [h.get("close") for h in window]
    lows = [h.get("low") for h in window]
    if any(c is None for c in closes):
        return none
    ma5 = round(sum(closes[-ma_period:]) / ma_period, 2)
    above = closes[-1] > ma5
    today_low = lows[-1]
    prior_lows = [l for l in lows[:-1] if isinstance(l, (int, float))]
    higher_low = (
        isinstance(today_low, (int, float))
        and len(prior_lows) >= ma_period
        and today_low > min(prior_lows)
    )
    return {
        "ma5": ma5,
        "above_ma5": bool(above),
        "higher_low": bool(higher_low),
        "price_reversal": bool(above and higher_low),
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def classify_tier(
    pct_vs_ma200: float | None,
    pct_vs_ma60: float | None,
    slope_pct: float | None,
    tiers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """policy.market_regime.dynamic_sizing.tiers 를 순서대로 평가해 첫 매칭 tier 를 반환한다.

    각 tier 의 gates 중 명시된 것만 검사한다(미명시 게이트는 제약 없음).
    슬로프/60일선 게이트가 있는데 해당 신호가 None 이면 그 tier 는 매칭 실패로 처리하고
    더 보수적인 다음 tier 로 폴스루한다. 마지막 tier(gates 비어 있음)는 catch-all.
    """
    for tier in tiers:
        gates = tier.get("gates", {}) or {}
        ok = True
        gmin = gates.get("price_vs_ma200_min")
        if gmin is not None and not (pct_vs_ma200 is not None and pct_vs_ma200 >= gmin):
            ok = False
        gmin = gates.get("price_vs_ma60_min")
        if ok and gmin is not None and not (pct_vs_ma60 is not None and pct_vs_ma60 >= gmin):
            ok = False
        gmin = gates.get("ma200_slope_min")
        if ok and gmin is not None and not (slope_pct is not None and slope_pct >= gmin):
            ok = False
        if ok:
            return tier
    return tiers[-1] if tiers else None


def build_regime(
    ma_window: int = 200,
    tiers: list[dict[str, Any]] | None = None,
    slope_lookback: int = 20,
) -> dict[str, Any]:
    """KOSPI 지수의 이동평균 위치·기울기로 시장 레짐과 5단계 tier 를 판정한다.

    지수는 2출처 교차검증이 불필요하므로 Yahoo `^KS11` 단일 출처를 사용한다.
    데이터 수집 실패 시 state="unknown" — 게이트는 보수적으로 풀어주되 리포트에 명시한다.

    레거시 `state`(risk_on/risk_off, score_candidates 가 사용) 와
    신규 `tier`/`target_equity_pct`(compute_allocation.py 가 사용) 를 함께 싣는다.
    """
    hist = fetch_yahoo("^KS11")
    if not hist or len(hist) < 2:
        return {
            "index": "KOSPI",
            "state": "unknown",
            "tier": "unknown",
            "reason": "지수 데이터 수집 실패(레짐 게이트 보류)",
            "source": "yahoo:^KS11",
        }
    closes = [h["close"] for h in hist]
    last = closes[-1]
    window = min(ma_window, len(closes))
    ma200 = sum(closes[-window:]) / window
    pct_vs_ma200 = round((last / ma200 - 1) * 100, 2)

    ma60 = _mean(closes[-60:]) if len(closes) >= 60 else None
    pct_vs_ma60 = round((last / ma60 - 1) * 100, 2) if ma60 else None

    # v2.5 — 섹터 로테이션(상대강도) 벤치마크: KOSPI 자체의 60일·20일 수익률.
    # score_candidates.py 가 종목 ret_60d_pct 에서 이 값을 빼 '초과수익(excess)'을 점수화한다.
    ret_60d_pct = round((last / closes[-61] - 1) * 100, 2) if len(closes) >= 61 else None
    ret_20d_pct = round((last / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None

    slope_pct: float | None = None
    if len(closes) >= window + slope_lookback:
        ma200_prev = _mean(closes[-(window + slope_lookback):-slope_lookback])
        if ma200_prev:
            slope_pct = round((ma200 / ma200_prev - 1) * 100, 2)

    above = last >= ma200
    regime: dict[str, Any] = {
        "index": "KOSPI",
        "last_close": round(last, 2),
        "ma_window": window,
        "ma_long": round(ma200, 2),
        "ma60": round(ma60, 2) if ma60 else None,
        "above_ma": above,
        "pct_vs_ma": pct_vs_ma200,
        "pct_vs_ma60": pct_vs_ma60,
        "ret_60d_pct": ret_60d_pct,
        "ret_20d_pct": ret_20d_pct,
        "ma200_slope_pct": slope_pct,
        "slope_lookback_days": slope_lookback,
        "state": "risk_on" if above else "risk_off",
        "source": "yahoo:^KS11",
        "as_of": hist[-1]["date"],
    }

    tier = classify_tier(pct_vs_ma200, pct_vs_ma60, slope_pct, tiers or [])
    if tier:
        regime["tier"] = tier.get("tier")
        regime["target_equity_pct"] = tier.get("target_equity_pct")
        regime["entry_mode"] = tier.get("entry_mode")
        regime["tier_narrative"] = tier.get("narrative")
    else:
        regime["tier"] = "unknown"
    return regime


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
) -> dict[str, Any]:
    naver_hist = fetch_naver(ticker)
    yahoo_hist = fetch_yahoo(f"{ticker}.KS")
    naver_last = naver_hist[-1]["close"] if naver_hist else None
    yahoo_last = yahoo_hist[-1]["close"] if yahoo_hist else None
    confidence, gap_pct = compute_confidence(naver_last, yahoo_last)
    primary_hist = naver_hist or yahoo_hist
    ret5 = five_day_return(primary_hist) if primary_hist else None
    # entry_filter(추세필터)는 레짐 tier·상대강도에 따라 임계가 달라지므로(v2.7 레짐 적응형),
    # 여기서는 ret5·ret60 만 산출하고 pass/threshold 판정은 main() 이 레짐 tier 확정 후
    # apply_entry_filter() 로 채운다(strong_bull 눌림목에서 주도주를 평면 -7% 로 막던 모순 해소).

    ret60 = cumulative_return(primary_hist, 60) if primary_hist else None
    high_ratio, high_52w = pct_of_52w_high(primary_hist) if primary_hist else (None, None)
    last_close = primary_hist[-1]["close"] if primary_hist else None
    atr14 = compute_atr(primary_hist, 14) if primary_hist else None
    atr_pct = (
        round(atr14 / last_close * 100, 2)
        if atr14 is not None and last_close
        else None
    )
    # v2.8 — 섹터 로테이션 '몰입' 신호용: 20일 수익률 + 거래량 급증비.
    ret20 = cumulative_return(primary_hist, 20) if primary_hist else None
    vol_ratio = volume_ratio(primary_hist, 20) if primary_hist else None
    last_volume = primary_hist[-1].get("volume") if primary_hist else None
    # v2.9 — '공격' 모드 가격구조 반등 신호(5일선 회복 + higher-low).
    structure = price_structure(primary_hist) if primary_hist else {"price_reversal": None}
    # 오늘자 OHLC(시가/고가/저가/현재가) — 웹 교차확인이 '개장/장중 고가'를 '현재가'로 오인하는 것을
    # 막기 위한 범위 맥락(policy.price_data_quality.web_verify_guard). 마지막 캔들 날짜가 오늘일 때만 채운다.
    today_kst = datetime.now(KST).date().isoformat()
    last_bar = primary_hist[-1] if primary_hist else None
    today_ohlc = (
        {
            "date": last_bar["date"],
            "open": last_bar.get("open"),
            "high": last_bar.get("high"),
            "low": last_bar.get("low"),
            "close": last_bar.get("close"),
        }
        if last_bar and last_bar.get("date") == today_kst
        else None
    )
    return {
        "name": meta.get("name", ""),
        "role": meta.get("role", "candidate"),
        "last_close": last_close,
        "today_ohlc": today_ohlc,
        "sources": [
            {
                "name": "naver",
                "last_close": naver_last,
                "last_date": naver_hist[-1]["date"] if naver_hist else None,
                "ok": bool(naver_hist),
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
        "momentum": {
            "ret_60d_pct": ret60,
            "ret_20d_pct": ret20,
            "pct_of_52w_high": high_ratio,
            "high_52w": high_52w,
        },
        "volatility": {
            "atr14": atr14,
            "atr_pct": atr_pct,
        },
        "liquidity": {
            "volume": last_volume,
            "vol_ratio_20d": vol_ratio,
        },
        "structure": structure,
        "entry_filter": {},  # main() 의 apply_entry_filter 가 레짐 tier 확정 후 채운다(v2.7)
    }


def resolve_entry_threshold(
    tier: str | None,
    stock_ret60: float | None,
    kospi_ret60: float | None,
    ef_cfg: dict[str, Any],
) -> tuple[float, str]:
    """레짐 tier·상대강도(주도주) 기반 5일 추세필터 임계(%)를 산출한다(v2.7).

    base = block_if_cumulative_return_below_pct_by_tier[tier] (없으면 평면 -7.0).
    주도주 예외: KOSPI 대비 60일 초과수익이 excess_min_pct 이상이면 extra_pct 만큼 임계를
    더 넓힌다(예 strong_bull -13→-20). 최종값은 entry_filter_hard_floor_pct 아래로는
    내려가지 않는다(진짜 자유낙하 차단). 반환: (임계_pct, 근거 문자열).
    """
    flat = float(ef_cfg.get("block_if_cumulative_return_below_pct", -7.0))
    base, basis = flat, "flat"
    by_tier = ef_cfg.get("block_if_cumulative_return_below_pct_by_tier")
    if isinstance(by_tier, dict) and tier and isinstance(by_tier.get(tier), (int, float)):
        base, basis = float(by_tier[tier]), f"tier:{tier}"
    threshold = base
    rsw = ef_cfg.get("relative_strength_leader_widening")
    if isinstance(rsw, dict) and stock_ret60 is not None and kospi_ret60 is not None:
        excess = stock_ret60 - kospi_ret60
        if excess >= float(rsw.get("excess_min_pct", 10.0)):
            threshold = base + float(rsw.get("extra_pct", -7.0))
            basis += "+rs_leader"
    floor = ef_cfg.get("entry_filter_hard_floor_pct")
    if isinstance(floor, (int, float)):
        threshold = max(threshold, float(floor))
    return round(threshold, 2), basis


def apply_entry_filter(
    ts: dict[str, Any],
    tier: str | None,
    kospi_ret60: float | None,
    ef_cfg: dict[str, Any],
) -> None:
    """종목 스냅샷(ts)의 entry_filter 를 레짐 tier 확정 후 채운다(in-place, v2.7).

    build_ticker_snapshot 는 ret5·ret60 만 산출하고, 임계 판정은 레짐(KOSPI ret60)이
    확정된 main() 에서 이 함수로 수행한다(평면 -7% → tier·상대강도 적응형).
    """
    ret5 = ts.get("five_day_cumulative_return_pct")
    stock_ret60 = (ts.get("momentum") or {}).get("ret_60d_pct")
    threshold, basis = resolve_entry_threshold(tier, stock_ret60, kospi_ret60, ef_cfg)
    passes = ret5 is not None and ret5 >= threshold
    if ret5 is None:
        reason = "데이터 부족 — 5거래일 가격 수집 실패"
    elif not passes:
        reason = f"5거래일 누적 {ret5}% < 기준 {threshold}% ({basis})"
    else:
        reason = None
    ts["entry_filter"] = {
        "passes": passes,
        "threshold_pct": threshold,
        "basis": basis,
        "reason": reason,
    }


def main() -> int:
    policy = load_json("config/policy.json")
    regime_cfg = policy.get("market_regime", {}) if isinstance(policy.get("market_regime"), dict) else {}
    ma_window = regime_cfg.get("ma_window", 200)
    dyn = regime_cfg.get("dynamic_sizing", {}) if isinstance(regime_cfg.get("dynamic_sizing"), dict) else {}
    tiers = dyn.get("tiers", []) if dyn.get("enabled", False) else []
    slope_lookback = dyn.get("slope_lookback_days", 20)

    tickers = collect_tickers()
    now = datetime.now(KST)

    # 지수 레짐(^KS11)과 종목별 스냅샷의 모든 시세 요청을 한 스레드풀에서 동시에 수집한다.
    # 작업 함수(build_regime·build_ticker_snapshot)는 공유 상태를 변경하지 않고 결과만
    # 반환하므로 별도 동기화가 필요 없다. 결과 조립·요약은 아래에서 기존 종목 순서대로
    # 수행하므로 출력(JSON) 순서·내용은 직렬 버전과 동일하다.
    max_workers = min(len(tickers) + 1, MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        regime_future = pool.submit(build_regime, ma_window, tiers, slope_lookback)
        ticker_futures = {
            ticker: pool.submit(build_ticker_snapshot, ticker, meta)
            for ticker, meta in tickers.items()
        }
        regime = regime_future.result()
        ticker_snapshots = {
            ticker: future.result() for ticker, future in ticker_futures.items()
        }

    # v2.7 — 레짐 tier·KOSPI 60일 수익률 확정 후 종목별 추세필터(레짐 적응형 임계 + 주도주
    # 예외)를 채운다. 평면 -7% 가 강세장 눌림목에서 주도주를 막던 모순을 tier 로 푼다.
    ef_cfg = policy.get("entry_filters", {}) if isinstance(policy.get("entry_filters"), dict) else {}
    regime_tier = regime.get("tier") if isinstance(regime, dict) else None
    kospi_ret60 = regime.get("ret_60d_pct") if isinstance(regime, dict) else None
    for ts in ticker_snapshots.values():
        apply_entry_filter(ts, regime_tier, kospi_ret60, ef_cfg)
    tier_base_threshold, tier_base_basis = resolve_entry_threshold(regime_tier, None, None, ef_cfg)

    snapshot: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "policy_threshold_pct": tier_base_threshold,
        "entry_threshold_basis": tier_base_basis,
        "ticker_count": len(tickers),
        "regime": regime,
        "tickers": {},
    }

    holdings_low = []
    candidates_passing = []
    candidates_failing = []
    sources_ok = 0

    for ticker, meta in tickers.items():
        ts = ticker_snapshots[ticker]
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
            # 지수(^KS11)는 별도 출처라 살아 있을 수 있다 — 레짐만은 최신화한다.
            if regime.get("state") != "unknown":
                prior["regime"] = regime
            out_path.write_text(
                json.dumps(prior, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"all sources failed — preserved prior snapshot (as_of={prior.get('as_of')}), "
                f"marked stale; regime={regime.get('state')}"
            )
            return 0

    snapshot.pop("stale", None)
    out_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {out_path.relative_to(ROOT)} tickers={len(tickers)} sources_ok={sources_ok} "
        f"pass={len(candidates_passing)} block={len(candidates_failing)} low_conf={len(holdings_low)} "
        f"regime={regime.get('state')}"
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
