#!/usr/bin/env python3
"""결정론적 전략 코어 — LLM 없는 '기계적 룰 베이스라인'.

목적: 백테스트로 재현 가능한 잣대를 만든다. 라이브 routine 은 LLM 재량을 유지하지만,
이 코어는 policy.json 의 정량 규칙(모멘텀 블렌드·레짐 tier·R/R·ATR 손절·사이징)만으로
포지션을 결정한다 → 과거 데이터로 리플레이 가능. "LLM이 자기 규칙을 기계적으로 따르는 것보다
나은가"를 측정하는 기준선.

라이브 규칙과 어긋나지 않도록 점수 함수는 score_candidates / fetch_market_data 의 순수 함수를
그대로 import 해서 쓴다. 네트워크·LLM·파일쓰기 없음. 입력은 '의사결정일까지의 bars'.

정량화 불가 축(thematic/thesis/fundamental_tilt/confidence)은 과거 시점에 재현 불가하므로
베이스라인에서 제외한다 → 베이스라인 = 모멘텀 + 레짐 + 리스크 규칙. LLM 이 더하는 질적 레이어는
이 베이스라인 '위'의 알파로 따로 측정한다.
"""
from __future__ import annotations

import math
from typing import Any

import fetch_market_data as fmd
import score_candidates as sc


def signals_from_bars(bars: list[dict]) -> dict[str, Any]:
    """의사결정일까지의 bars(오름차순)로 모멘텀·변동성 신호를 산출한다(point-in-time)."""
    if not bars:
        return {}
    ret5 = fmd.five_day_return(bars)
    ret60 = fmd.cumulative_return(bars, 60)
    pct_high, high52 = fmd.pct_of_52w_high(bars)
    atr = fmd.compute_atr(bars, 14)
    mom, parts = sc.momentum_score(ret5, ret60, pct_high)
    close = bars[-1]["close"]
    return {
        "close": close,
        "ret5": ret5,
        "ret60": ret60,
        "pct_of_52w_high": pct_high,
        "atr14": atr,
        "momentum": mom,
        "momentum_parts": parts,
    }


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def regime_from_index(index_bars: list[dict], policy: dict) -> dict[str, Any]:
    """지수 bars(point-in-time)로 레짐 tier 를 판정한다. fetch_market_data.build_regime 의 오프라인 판.

    fmd.classify_tier(순수 함수)를 그대로 재사용해 라이브 tier 정의와 일치시킨다.
    """
    cfg = policy.get("market_regime", {}) if isinstance(policy, dict) else {}
    ma_window = cfg.get("ma_window", 200)
    dyn = cfg.get("dynamic_sizing", {}) if isinstance(cfg.get("dynamic_sizing"), dict) else {}
    tiers = dyn.get("tiers", []) if dyn.get("enabled", False) else []
    slope_lookback = dyn.get("slope_lookback_days", 20)

    closes = [b["close"] for b in index_bars]
    if len(closes) < 2:
        return {"tier": "unknown", "state": "unknown", "pct_vs_ma200": None}

    last = closes[-1]
    window = min(ma_window, len(closes))
    ma200 = sum(closes[-window:]) / window
    pct_vs_ma200 = (last / ma200 - 1) * 100 if ma200 else None

    ma60 = _mean(closes[-60:]) if len(closes) >= 60 else None
    pct_vs_ma60 = (last / ma60 - 1) * 100 if ma60 else None

    slope_pct = None
    if len(closes) >= window + slope_lookback:
        prev = _mean(closes[-(window + slope_lookback):-slope_lookback])
        if prev:
            slope_pct = (ma200 / prev - 1) * 100

    tier = fmd.classify_tier(pct_vs_ma200, pct_vs_ma60, slope_pct, tiers)
    return {
        "tier": tier.get("tier") if tier else "unknown",
        "target_equity_pct": tier.get("target_equity_pct") if tier else None,
        "entry_mode": tier.get("entry_mode") if tier else None,
        "state": "risk_on" if (pct_vs_ma200 or 0) >= 0 else "risk_off",
        "pct_vs_ma200": round(pct_vs_ma200, 2) if pct_vs_ma200 is not None else None,
        "pct_vs_ma60": round(pct_vs_ma60, 2) if pct_vs_ma60 is not None else None,
        "ma200_slope_pct": round(slope_pct, 2) if slope_pct is not None else None,
    }


def stop_and_target(entry: float, atr14: float | None, policy: dict) -> tuple[float, float]:
    """진입가·ATR·policy 로 (손절가, 목표가)를 계산한다.

    손절 = max(entry - atr_mult×ATR, entry×(1+stop_loss_pct/100))  → -10%(red)보다 깊을 수 없음.
    ATR 없으면 고정 -10% 폴백. 목표 = entry×(1+target_return_pct/100)(고정 +10%; 동적 목표는 LLM 영역).
    """
    risk = policy.get("risk", {})
    stop_loss_pct = risk.get("stop_loss_pct", -10.0)
    target_pct = risk.get("target_return_pct", 10.0)
    vol = risk.get("volatility_sizing", {}) if isinstance(risk.get("volatility_sizing"), dict) else {}
    atr_mult = vol.get("atr_stop_multiple", 2.0)

    floor_stop = entry * (1 + stop_loss_pct / 100.0)  # 가장 깊은 손절(예: -10%)
    if atr14 and atr14 > 0:
        atr_stop = entry - atr_mult * atr14
        stop = max(atr_stop, floor_stop)  # 더 타이트한(높은) 손절 채택
    else:
        stop = floor_stop
    target = entry * (1 + target_pct / 100.0)
    return stop, target


def position_size(
    equity: float,
    price: float,
    stop: float,
    policy: dict,
    entry_mode: str = "default",
) -> int:
    """리스크 기반 사이징(정수 주). policy.position_sizing + volatility_sizing 준수.

    수량 = min(리스크기반, 비중상한기반). 둘 다 못 채우면 0(진입 불가) — 고가주 정수반올림 한계를
    그대로 드러낸다(설계 비판 지점). entry_mode=reduced 면 reduced_entry_weight_pct 로 캡.
    """
    ps = policy.get("position_sizing", {})
    risk = policy.get("risk", {})
    max_w = ps.get("max_position_weight_pct", 35.0)
    default_w = ps.get("default_entry_weight_pct", 30.0)
    reduced_w = ps.get("reduced_entry_weight_pct", 20.0)
    risk_pct = risk.get("max_single_trade_risk_pct_of_equity", 1.5)

    entry_w = reduced_w if entry_mode == "reduced" else default_w
    weight_cap_pct = min(entry_w, max_w)

    risk_per_share = price - stop
    risk_shares = 0
    if risk_per_share > 0:
        risk_budget = equity * risk_pct / 100.0
        risk_shares = math.floor(risk_budget / risk_per_share)

    weight_budget = equity * weight_cap_pct / 100.0
    weight_shares = math.floor(weight_budget / price) if price > 0 else 0

    if risk_shares <= 0:
        # ATR 손절폭이 너무 좁아 리스크기반이 0 이면 비중상한기반으로 폴백(고정 손절 폴백 상황 등)
        return max(0, weight_shares)
    return max(0, min(risk_shares, weight_shares))


def rank_candidates(
    universe_signals: dict[str, dict],
    policy: dict,
) -> list[tuple[str, dict]]:
    """진입 필터 통과 종목을 모멘텀 점수 내림차순으로 정렬해 반환한다.

    필터: 최근 5거래일 누적 ≥ block_if_cumulative_return_below_pct(=-7%). 데이터 부족 종목 제외.
    """
    ef = policy.get("entry_filters", {})
    threshold = ef.get("block_if_cumulative_return_below_pct", -7.0)
    passing: list[tuple[str, dict]] = []
    for ticker, sig in universe_signals.items():
        if not sig or sig.get("ret5") is None:
            continue
        if sig["ret5"] < threshold:
            continue
        passing.append((ticker, sig))
    passing.sort(key=lambda kv: kv[1].get("momentum", 0.0), reverse=True)
    return passing


def target_equity_pct(regime: dict, policy: dict) -> float:
    """레짐 tier 의 목표 주식비중 밴드 중앙값(%). tier 없으면 default_entry 기반 보수값."""
    band = regime.get("target_equity_pct")
    if isinstance(band, list) and len(band) == 2 and all(isinstance(x, (int, float)) for x in band):
        return (band[0] + band[1]) / 2.0
    # tier 미확정 폴백: 종목수×기본진입비중 근사, 현금하한 준수
    ps = policy.get("position_sizing", {})
    n = ps.get("max_positions", 4)
    return min(n * ps.get("default_entry_weight_pct", 30.0), 100 - ps.get("min_cash_weight_pct", 5.0))
