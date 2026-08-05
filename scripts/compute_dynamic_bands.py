#!/usr/bin/env python3
"""동적 매수/매도 참조 밴드 산출 — 목표가 경직성 보완의 단일 소스 (의존성 0).

배경 (2026-08-05 사용자 검토 요청 — 2달 운용 관찰):
- 목표 매수/매도 금액이 주간 계획·직전 리포트의 절대가격 앵커로 고정되고, 시장이
  움직여도 routine 이 "그 틀을 유지하려는" 경향이 강하다.
  실측: 신한지주 목표 103,000 고정 상태로 목표 진행률 215%(최고 종가 109,200)까지
  도달했는데도 목표가는 8/3 하향 조정값 그대로 — 추정 기준선(118,700)과 -13% 괴리.
  rr_breach_forced_action(v2.26)은 R/R "하락" 쪽만 잡고, 목표 "초과 소진"과 매수
  밴드의 시세 이탈은 어떤 룰도 발동하지 않았다.
- 원인 구조: 매수/매도 목표가 산문(weekly_plan.watch_items 자유 서술)에만 존재해
  기계 재산정·검증이 불가능했다. 이 스크립트가 매 실행 시점 가격·ATR·레짐 tier 로
  참조 밴드를 다시 계산해 기계 판독 가능한 정본을 만든다.

원칙 (compute_exit_levels 와 동형):
- 밴드는 매 산출 시점 데이터로 재산정한다 — 직전 리포트·주초 계획의 절대가격 이월 금지.
- 참고 레이어: watchlist/portfolio 의 운용 목표가를 자동으로 덮어쓰지 않는다.
  재산정 의무(reprice_signals)만 표면화하고, 결정은 routine 이 당일 내린다
  (policy.dynamic_reprice — 자동 청산·자동 목표 변경 아님).
- 결측 보수: ATR·시세 결측 종목은 밴드를 만들지 않고 결측 사유만 남긴다(래칫 방지).

공식 (policy.dynamic_reprice 파라미터, 결측 시 아래 기본값):
- 레짐 tier 목표 배수 k: strong_bull 1.6 / bull 1.4 / neutral 1.2 / bear 1.0 / deep_bear 0.85
- 매수 참조 밴드(전 종목): 현재가 × (1 − 0.75×ATR%) ~ 현재가 × (1 + 0.25×ATR%)
  — 하단은 눌림 매수, 상단은 추격 상한. estimate 의 entry_cap 이 있으면 상단을 캡.
- 매도 목표 참조 밴드(보유): base = max(진입 후 최고 종가, 현재가),
  ref = base × (1 + k×ATR%), 밴드 = base × (1 + [0.7, 1.3]×k×ATR%).
  valuation_check 의 밸류에이션 천장이 있으면 ref·상단을 캡(cap_applied 표기).
- reprice_signals(보유):
  target_exhausted  목표 진행률 ≥ 100% — 목표가 이미 소진. (a)종가 익절 판정
                    (b)목표 재산정+trade_log REPRICE (c)트레일링 전용 전환 중 당일 택1
  target_gap        운용 목표가 ↔ ref 괴리 ≥ target_gap_warn_pct — 재산정 검토
  stop_too_wide     손절폭 > stop_max_atr_mult×ATR — 변동성 대비 과대, 상향 검토

입력: config/portfolio.json, state/market_snapshot.json(가격·ATR·regime.tier),
      state/exit_levels.json(최고 종가·진행률 — 있으면), state/target_estimate.json(entry_cap),
      state/valuation_check.json(천장), config/policy.json(dynamic_reprice)
출력: state/dynamic_bands.json
검증: --selftest 가 신한지주 2026-08-05 실측(목표 소진 방치)을 합성 재현한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "dynamic_bands.json"

# policy.dynamic_reprice 결측 시 기본값 — 정책이 있으면 정책값이 우선한다
DEFAULT_TIER_MULT = {
    "strong_bull": 1.6, "bull": 1.4, "neutral": 1.2, "bear": 1.0, "deep_bear": 0.85,
}
DEFAULT_FALLBACK_MULT = 1.2          # tier unknown/결측
DEFAULT_ENTRY_BAND_ATR = (0.75, 0.25)  # (하단 −, 상단 +) ×ATR
DEFAULT_TARGET_SPREAD = (0.7, 1.3)     # ref 대비 밴드 폭 ×(k×ATR)
DEFAULT_TARGET_GAP_WARN_PCT = 12.0
DEFAULT_STOP_MAX_ATR_MULT = 2.5


def load_json(rel: str):
    p = ROOT / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pair(v, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = _num(v[0]), _num(v[1])
        if a is not None and b is not None:
            return (a, b)
    return default


def load_params(policy: dict | None) -> dict:
    cfg = ((policy or {}).get("dynamic_reprice") or {}) if isinstance(policy, dict) else {}
    tier_mult = dict(DEFAULT_TIER_MULT)
    raw_mult = cfg.get("tier_target_atr_mult")
    if isinstance(raw_mult, dict):
        for k, v in raw_mult.items():
            if _num(v) is not None:
                tier_mult[str(k)] = float(v)
    return {
        "tier_mult": tier_mult,
        "fallback_mult": _num(cfg.get("fallback_target_atr_mult")) or DEFAULT_FALLBACK_MULT,
        "entry_band_atr": _pair(cfg.get("entry_band_atr"), DEFAULT_ENTRY_BAND_ATR),
        "target_spread": _pair(cfg.get("target_band_spread"), DEFAULT_TARGET_SPREAD),
        "gap_warn_pct": _num(cfg.get("target_gap_warn_pct")) or DEFAULT_TARGET_GAP_WARN_PCT,
        "stop_max_atr": _num(cfg.get("stop_max_atr_mult")) or DEFAULT_STOP_MAX_ATR_MULT,
    }


def build_ticker(
    ticker: str,
    snap: dict,
    params: dict,
    k_mult: float,
    position: dict | None = None,
    exit_info: dict | None = None,
    entry_cap: float | None = None,
    valuation_ceiling: float | None = None,
) -> dict:
    """1개 종목의 밴드·신호 산출. 가격/ATR 결측이면 결측 사유만 담은 dict 반환."""
    price = None
    ohlc = snap.get("today_ohlc")
    if isinstance(ohlc, dict):
        price = _num(ohlc.get("close"))
    if not price:
        price = _num(snap.get("last_close"))
    vol = snap.get("volatility")
    atr_pct = _num(vol.get("atr_pct")) if isinstance(vol, dict) else None

    out: dict = {
        "name": snap.get("name") or (position or {}).get("name"),
        "role": "holding" if position else "watch",
        "price": price,
        "atr_pct": atr_pct,
        "tier_target_mult": k_mult,
    }
    if not price or not atr_pct:
        out["note"] = "가격 또는 ATR 결측 — 밴드 산출 불가(결측 명기, 이월·손계산 금지)"
        return out

    atr_frac = atr_pct / 100.0
    ent_dn, ent_up = params["entry_band_atr"]
    entry_low = round(price * (1 - ent_dn * atr_frac))
    entry_high = round(price * (1 + ent_up * atr_frac))
    entry_basis = f"현재가 −{ent_dn}×ATR ~ +{ent_up}×ATR(추격 상한)"
    if entry_cap and entry_cap < entry_high:
        entry_high = round(entry_cap)
        entry_basis += " · estimate entry_cap 캡"
    out["entry_band"] = {"low": entry_low, "high": entry_high, "basis": entry_basis}

    if position is None:
        return out

    # ---- 보유 종목: 매도 목표 참조 밴드 + 재산정 신호 ----
    highest = _num((exit_info or {}).get("highest_close"))
    base = max(price, highest) if highest else price
    ref = base * (1 + k_mult * atr_frac)
    sp_lo, sp_hi = params["target_spread"]
    t_low = base * (1 + sp_lo * k_mult * atr_frac)
    t_high = base * (1 + sp_hi * k_mult * atr_frac)
    cap_applied = False
    if valuation_ceiling:
        if ref > valuation_ceiling:
            ref = valuation_ceiling
            cap_applied = True
        if t_high > valuation_ceiling:
            t_high = valuation_ceiling
            cap_applied = True
        t_low = min(t_low, ref)
    out["target_band"] = {
        "low": round(t_low), "ref": round(ref), "high": round(t_high),
        "base": round(base),
        "basis": f"max(최고종가, 현재가) × (1 + {k_mult}×ATR%), 폭 [{sp_lo}, {sp_hi}]"
                 + (" · 밸류에이션 천장 캡" if cap_applied else ""),
        "cap_applied": cap_applied,
    }

    entry = _num(position.get("entry_price"))
    target = _num(position.get("target_price"))
    stop = _num(position.get("stop_price"))
    progress = _num((exit_info or {}).get("target_progress_pct"))
    if progress is None and entry and target and target > entry:
        progress = round((base - entry) / (target - entry) * 100, 1)
    out["operating"] = {
        "entry_price": entry, "target_price": target, "stop_price": stop,
        "target_progress_pct": progress,
    }

    signals: list[dict] = []
    if isinstance(progress, (int, float)) and progress >= 100.0:
        signals.append({
            "code": "target_exhausted",
            "severity": "high",
            "msg": (
                f"운용 목표가 {int(target):,}원 소진(진행률 {progress:.0f}%) — 당일 18시까지 "
                "(a)종가 익절 판정 (b)목표 재산정+REPRICE 기록 (c)트레일링 전용 전환 선언 중 택1. "
                "소진된 목표가는 R/R·진행률 계산 기준으로 더 쓰지 않는다"
            ),
        })
    if target and ref:
        gap_pct = (target / ref - 1.0) * 100.0
        if abs(gap_pct) >= params["gap_warn_pct"]:
            direction = "아래" if gap_pct < 0 else "위"
            signals.append({
                "code": "target_gap",
                "severity": "medium",
                "gap_pct": round(gap_pct, 1),
                "msg": (
                    f"운용 목표가 {int(target):,}원이 동적 참조 {int(ref):,}원 대비 "
                    f"{abs(gap_pct):.1f}% {direction} — 18시 재산정 검토. 유지 시 사유를 당일 "
                    "리포트에 기록(같은 사유의 다음 신호 재사용 금지)"
                ),
            })
    if stop and price and atr_pct:
        stop_width_pct = (price - stop) / price * 100.0
        if stop_width_pct > params["stop_max_atr"] * atr_pct:
            signals.append({
                "code": "stop_too_wide",
                "severity": "medium",
                "msg": (
                    f"손절폭 {stop_width_pct:.1f}% > {params['stop_max_atr']}×ATR({atr_pct:.1f}%) — "
                    "변동성 대비 과대. 트레일링/본전 상향 검토"
                ),
            })
    out["reprice_signals"] = signals
    return out


def compute(portfolio: dict, snapshot: dict, exit_levels: dict, estimates: dict,
            valuation: dict, policy: dict) -> dict:
    params = load_params(policy)
    regime = snapshot.get("regime") if isinstance(snapshot, dict) else {}
    tier = str((regime or {}).get("tier") or "unknown")
    k_mult = params["tier_mult"].get(tier, params["fallback_mult"])

    positions = {
        str(p.get("ticker")): p
        for p in (portfolio.get("positions") or [])
        if isinstance(p, dict) and _num(p.get("shares"))
    }
    exit_tickers = (exit_levels or {}).get("tickers", {}) if isinstance(exit_levels, dict) else {}
    est_map = {
        str(e.get("ticker")): e for e in ((estimates or {}).get("estimates") or [])
        if isinstance(e, dict) and e.get("ticker")
    }
    val_tickers = (valuation or {}).get("tickers", {}) if isinstance(valuation, dict) else {}

    snap_tickers = (snapshot or {}).get("tickers", {}) if isinstance(snapshot, dict) else {}
    out_tickers: dict[str, dict] = {}
    signal_count = 0
    for ticker, snap in snap_tickers.items():
        if not isinstance(snap, dict):
            continue
        est = est_map.get(ticker) or {}
        val = val_tickers.get(ticker) or {}
        entry = build_ticker(
            ticker, snap, params, k_mult,
            position=positions.get(ticker),
            exit_info=exit_tickers.get(ticker) if isinstance(exit_tickers, dict) else None,
            entry_cap=_num(est.get("entry_cap")),
            valuation_ceiling=_num(val.get("valuation_ceiling_price")),
        )
        signal_count += len(entry.get("reprice_signals") or [])
        out_tickers[str(ticker)] = entry

    return {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "policy_ref": "policy.dynamic_reprice — 밴드·신호는 매 산출 시점 재계산 정본만 인용. "
                      "직전 리포트·주초 계획의 절대가격 이월 금지 (compute_exit_levels 동형). "
                      "운용 목표가 자동 덮어쓰기 없음 — 재산정 의무만 발동(참고 레이어 원칙).",
        "regime_tier": tier,
        "tier_target_mult": k_mult,
        "params": {
            "entry_band_atr": list(params["entry_band_atr"]),
            "target_band_spread": list(params["target_spread"]),
            "target_gap_warn_pct": params["gap_warn_pct"],
            "stop_max_atr_mult": params["stop_max_atr"],
        },
        "formula": {
            "entry_band": "현재가 × (1 − 하단×ATR%) ~ 현재가 × (1 + 상단×ATR%) — 하단 눌림 매수, 상단 추격 상한(entry_cap 캡)",
            "target_band": "max(진입 후 최고종가, 현재가) × (1 + [0.7,1.3]×k(tier)×ATR%) — 밸류에이션 천장 캡",
            "reprice_signals": "target_exhausted(진행률≥100%) / target_gap(참조 대비 괴리≥경고) / stop_too_wide(손절폭>2.5×ATR)",
        },
        "signal_count": signal_count,
        "tickers": out_tickers,
    }


def _selftest() -> int:
    """신한지주 2026-08-05 실측 재현 — 목표 103,000 고정 + 진행률 215% 방치 사례."""
    portfolio = {
        "positions": [{
            "ticker": "055550", "name": "신한지주", "shares": 5,
            "entry_price": 97_609, "stop_price": 99_831, "target_price": 103_000,
        }],
    }
    snapshot = {
        "regime": {"tier": "bull"},
        "tickers": {
            "055550": {
                "name": "신한지주",
                "last_close": 103_600.0,
                "today_ohlc": {"date": "2026-08-05", "close": 103_600.0},
                "volatility": {"atr14": 5450.0, "atr_pct": 5.26},
            },
            # 감시 종목(비보유) — entry_band 만 산출되어야 한다
            "005930": {
                "name": "삼성전자", "last_close": 249_250.0,
                "volatility": {"atr_pct": 4.0},
            },
        },
    }
    exit_levels = {"tickers": {"055550": {"highest_close": 109_200.0, "target_progress_pct": 215.0}}}
    result = compute(portfolio, snapshot, exit_levels, {}, {}, {})

    t = result["tickers"]["055550"]
    codes = {s["code"] for s in t["reprice_signals"]}
    # bull k=1.4, ATR 5.26% → ref = 109,200 × (1 + 1.4×0.0526) = 117,241
    expected_ref = round(109_200 * (1 + 1.4 * 0.0526))
    # 목표 103,000 vs ref 117,241 = -12.1% 괴리 → target_gap 도 발동
    ok_holding = (
        t["role"] == "holding"
        and t["target_band"]["ref"] == expected_ref
        and "target_exhausted" in codes
        and "target_gap" in codes
        and t["entry_band"]["low"] == round(103_600 * (1 - 0.75 * 0.0526))
        and t["entry_band"]["high"] == round(103_600 * (1 + 0.25 * 0.0526))
    )
    w = result["tickers"]["005930"]
    ok_watch = (
        w["role"] == "watch" and "target_band" not in w
        and w["entry_band"]["low"] == round(249_250 * (1 - 0.75 * 0.04))
    )
    # 결측 보수 — ATR 없는 종목은 밴드 없이 note 만
    r2 = compute({}, {"tickers": {"X": {"last_close": 1000.0}}}, {}, {}, {}, {})
    ok_missing = "note" in r2["tickers"]["X"] and "entry_band" not in r2["tickers"]["X"]
    print(json.dumps({
        "case": "신한지주 8/5 목표 소진 방치 재현 + 감시 종목 + 결측 보수",
        "expected_target_ref": expected_ref,
        "got_target_ref": t["target_band"]["ref"],
        "got_signals": sorted(codes),
        "ok_holding": ok_holding,
        "ok_watch": ok_watch,
        "ok_missing": ok_missing,
    }, ensure_ascii=False))
    return 0 if (ok_holding and ok_watch and ok_missing) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="동적 매수/매도 참조 밴드 산출")
    parser.add_argument("--selftest", action="store_true", help="신한지주 8/5 사례 재현 검증")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()

    payload = compute(
        load_json("config/portfolio.json") or {},
        load_json("state/market_snapshot.json") or {},
        load_json("state/exit_levels.json") or {},
        load_json("state/target_estimate.json") or {},
        load_json("state/valuation_check.json") or {},
        load_json("config/policy.json") or {},
    )
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({
        "written": str(OUT_PATH.relative_to(ROOT)),
        "regime_tier": payload["regime_tier"],
        "tickers": len(payload["tickers"]),
        "reprice_signals": payload["signal_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
