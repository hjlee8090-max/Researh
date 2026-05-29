#!/usr/bin/env python3
"""시장 레짐 tier 기반 목표 주식 비중과 현재 포트폴리오 비중을 비교해 배치/축소 권고를 낸다.

입력:
- state/market_snapshot.json — regime.tier (fetch_market_data.py 가 산출)
- config/portfolio.json — cash, positions(market_value_approx)
- config/policy.json — market_regime.dynamic_sizing.tiers, position_sizing.min_cash_weight_pct
- state/allocation.json (직전) — prev_tier (히스테리시스용)

출력: state/allocation.json
- current_stock_pct / target band / 권고(action, KRW) / entry_mode

tier 가 비어있거나 unknown(구버전 snapshot·지수 수집 실패)이면 어드바이저리로만 출력하고 권고는 보류한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# tier 보수성 순서(강세 → 약세). 히스테리시스 인접 판정에 사용.
TIER_ORDER = ["strong_bull", "bull", "neutral", "bear", "deep_bear"]


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def portfolio_equity(portfolio: dict) -> tuple[float, float, float]:
    """(equity, cash, stock_value) 를 반환. stock_value 는 market_value_approx 합(폴백: shares×현재가)."""
    cash = float(portfolio.get("cash", 0) or 0)
    stock_value = 0.0
    for pos in portfolio.get("positions", []):
        mv = pos.get("market_value_approx")
        if mv is None:
            shares = pos.get("shares") or 0
            price = pos.get("current_price_approx") or pos.get("entry_price") or 0
            mv = shares * price
        stock_value += float(mv or 0)
    equity = cash + stock_value
    if equity <= 0:
        equity = float(portfolio.get("equity", 0) or 0)
    return equity, cash, stock_value


def find_tier(name: str | None, tiers: list[dict]) -> dict | None:
    for t in tiers:
        if t.get("tier") == name:
            return t
    return None


def apply_hysteresis(
    raw_tier: str | None,
    prev_tier: str | None,
    pct_vs_ma200: float | None,
    tiers: list[dict],
    hysteresis_pct: float,
) -> tuple[str | None, bool]:
    """직전 tier 와 1단계 차이고 통제신호(200일선 대비 %)가 경계 ±hysteresis 안이면 직전 tier 유지.

    경계값은 두 tier 중 더 강세 쪽의 price_vs_ma200_min 게이트를 사용한다(주 신호 기준 근사).
    slope 로만 갈리는 strong_bull↔bull 전환은 가격 경계가 같아 히스테리시스가 적용되지 않는다.
    """
    if not raw_tier or not prev_tier or raw_tier == prev_tier:
        return raw_tier, False
    if raw_tier not in TIER_ORDER or prev_tier not in TIER_ORDER:
        return raw_tier, False
    if abs(TIER_ORDER.index(raw_tier) - TIER_ORDER.index(prev_tier)) != 1:
        return raw_tier, False
    if pct_vs_ma200 is None:
        return raw_tier, False
    bullish = raw_tier if TIER_ORDER.index(raw_tier) < TIER_ORDER.index(prev_tier) else prev_tier
    gate = (find_tier(bullish, tiers) or {}).get("gates", {}).get("price_vs_ma200_min")
    if gate is None:
        return raw_tier, False
    if abs(pct_vs_ma200 - gate) < hysteresis_pct:
        return prev_tier, True
    return raw_tier, False


def main() -> int:
    snapshot = load_json("state/market_snapshot.json", {})
    portfolio = load_json("config/portfolio.json", {})
    policy = load_json("config/policy.json", {})
    prev_alloc = load_json("state/allocation.json", {})

    regime = snapshot.get("regime", {}) if isinstance(snapshot, dict) else {}
    regime_cfg = policy.get("market_regime", {}) if isinstance(policy, dict) else {}
    dyn = regime_cfg.get("dynamic_sizing", {}) if isinstance(regime_cfg.get("dynamic_sizing"), dict) else {}
    tiers = dyn.get("tiers", [])
    hysteresis_pct = float(dyn.get("hysteresis_pct", 1.0))
    pos_cfg = policy.get("position_sizing", {}) if isinstance(policy.get("position_sizing"), dict) else {}
    min_cash_pct = float(pos_cfg.get("min_cash_weight_pct", 5.0))
    max_positions = int(pos_cfg.get("max_positions", 4))
    max_pos_weight_pct = float(pos_cfg.get("max_position_weight_pct", 35.0))
    n_positions = len([p for p in portfolio.get("positions", []) if p.get("ticker")])
    vacant_slots = max(0, max_positions - n_positions)

    equity, cash, stock_value = portfolio_equity(portfolio)
    stock_pct = round(stock_value / equity * 100, 1) if equity > 0 else None
    cash_pct = round(cash / equity * 100, 1) if equity > 0 else None

    raw_tier = regime.get("tier")
    pct_vs_ma200 = regime.get("pct_vs_ma")
    stale = bool(snapshot.get("stale"))

    # v2.1 — 스냅샷 나이(age) 계산: 수집 시각(as_of) vs 현재. freshness 등급 산출.
    # stale 키(직접 수집 실패)와 별개로, GitHub Actions 가 성공 수집한 가격도 routine
    # 시점엔 최대 1시간 묵을 수 있으므로 age 를 명시해 다운스트림(프롬프트)이 보정하게 한다.
    now = datetime.now(KST)
    snap_as_of = snapshot.get("as_of")
    age_min: int | None = None
    if snap_as_of:
        try:
            collected = datetime.fromisoformat(snap_as_of)
            age_min = round((now - collected).total_seconds() / 60)
        except (ValueError, TypeError):
            age_min = None
    fresh_cfg = (
        policy.get("price_data_quality", {}).get("data_freshness", {})
        if isinstance(policy.get("price_data_quality", {}).get("data_freshness"), dict)
        else {}
    )
    fresh_max = float(fresh_cfg.get("fresh_max_min", 20))
    intraday_max = float(fresh_cfg.get("intraday_acceptable_max_min", 75))
    if age_min is None:
        freshness = "unknown"
    elif age_min <= fresh_max:
        freshness = "fresh"
    elif age_min <= intraday_max:
        freshness = "acceptable"
    else:
        freshness = "stale_intraday"

    out: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of"),
        "snapshot_stale": stale,
        "snapshot_age_min": age_min,
        "freshness": freshness,
        "current": {
            "equity_krw": round(equity),
            "cash_krw": round(cash),
            "stock_value_krw": round(stock_value),
            "stock_pct": stock_pct,
            "cash_pct": cash_pct,
        },
        "signals": {
            "pct_vs_ma200": pct_vs_ma200,
            "pct_vs_ma60": regime.get("pct_vs_ma60"),
            "ma200_slope_pct": regime.get("ma200_slope_pct"),
            "legacy_state": regime.get("state"),
        },
    }

    if not raw_tier or raw_tier == "unknown" or not tiers:
        out["tier"] = "unknown"
        out["recommendation"] = {
            "action": "advisory_only",
            "note": "regime tier 미확정(구버전 snapshot·지수 수집 실패·dynamic_sizing 비활성) — 동적 비중 권고 보류. 정책 default 사이징 사용.",
        }
        _write(out)
        print(f"allocation: tier=unknown stock_pct={stock_pct} — advisory only")
        return 0

    prev_tier = prev_alloc.get("effective_tier") or prev_alloc.get("tier")
    eff_tier, held = apply_hysteresis(raw_tier, prev_tier, pct_vs_ma200, tiers, hysteresis_pct)
    tier_def = find_tier(eff_tier, tiers) or {}
    band = tier_def.get("target_equity_pct", [None, None])
    band_min, band_max = (band + [None, None])[:2] if isinstance(band, list) else (None, None)
    entry_mode = tier_def.get("entry_mode")

    out["tier"] = raw_tier
    out["effective_tier"] = eff_tier
    out["hysteresis_hold"] = held
    out["prev_tier"] = prev_tier
    out["target_equity_pct"] = band
    out["entry_mode"] = entry_mode
    out["tier_narrative"] = tier_def.get("narrative")

    if band_min is None or band_max is None or stock_pct is None:
        out["recommendation"] = {"action": "hold", "note": "밴드·비중 산출 불가"}
        _write(out)
        print(f"allocation: tier={eff_tier} stock_pct={stock_pct} — band 미산출")
        return 0

    midpoint = (band_min + band_max) / 2
    # 배치 시 현금 하한(min_cash_pct) 아래로는 내려가지 않도록 배치 가능액을 제한한다.
    deployable_cash = max(0.0, cash - min_cash_pct / 100 * equity)

    if stock_pct < band_min:
        target_pct = min(midpoint, 100 - min_cash_pct)
        want_krw = (target_pct - stock_pct) / 100 * equity
        krw = round(min(want_krw, deployable_cash))
        action = "deploy" if krw > 0 else "hold"
        note = (
            f"주식 비중 {stock_pct}% < 목표 하한 {band_min}% → 약 {krw:,}원 추가 배치 권고"
            f"(목표 중앙 {midpoint:.0f}%, 현금 하한 {min_cash_pct:.0f}% 준수)."
            if action == "deploy"
            else f"목표 하한 미달이나 배치 가능 현금 부족(현금 하한 {min_cash_pct:.0f}% 준수)."
        )
    elif stock_pct > band_max:
        krw = round((stock_pct - midpoint) / 100 * equity)
        action = "trim"
        note = (
            f"주식 비중 {stock_pct}% > 목표 상한 {band_max}% → 약 {krw:,}원 축소 권고"
            f"(목표 중앙 {midpoint:.0f}%). 익절·트레일링스톱 우선 종목부터."
        )
    else:
        krw = 0
        action = "hold"
        note = f"주식 비중 {stock_pct}% 가 목표 밴드 {band_min}~{band_max}% 안 — 유지."

    # v2.0 — 신규 진입 1종목당 배분액. deploy 권고 KRW 를 빈 슬롯 수로 나누되 종목당 비중 상한으로 캡.
    # 프롬프트가 이 값 ÷ 진입가 = 목표 수량으로 변환해 '1주만 사는' 과소 사이징을 방지한다.
    per_pos_cap = round(equity * max_pos_weight_pct / 100)
    if action == "deploy":
        # 빈 슬롯이 있으면 신규 1종목당 배분액 = deploy krw / 빈 슬롯 수(종목당 상한 캡).
        # 빈 슬롯이 없으면 기존 보유 추가매수(scale-in)로 전액 배정한다.
        per_new = round(min(krw / vacant_slots, per_pos_cap)) if vacant_slots > 0 else krw
    else:
        per_new = 0
    out["recommendation"] = {
        "action": action,
        "krw": krw,
        "vacant_slots": vacant_slots,
        "per_new_position_krw": per_new,
        "max_position_krw": per_pos_cap,
        "target_midpoint_pct": round(midpoint, 1),
        "deployable_cash_krw": round(deployable_cash),
        "note": note,
    }
    out["reconcile_note"] = (
        "weekly_recovery_plan(누적손실 단계)·entry_filter 와 함께 '더 보수적인 쪽'을 최종 적용한다. "
        "deep_bear/entry_mode=block 이면 신규 진입 중단이 비중 배치보다 우선."
    )
    _write(out)
    print(
        f"allocation: tier={eff_tier}{'(hold)' if held else ''} stock_pct={stock_pct} "
        f"target={band_min}~{band_max}% action={action} krw={krw} "
        f"freshness={freshness}(age={age_min}m)"
    )
    return 0


def _write(out: dict) -> None:
    path = ROOT / "state" / "allocation.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
