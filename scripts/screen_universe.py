#!/usr/bin/env python3
"""종목 탐색 + 범용 섹터 로테이션 재진입 엔진(v2.7 탐색 → v2.8 섹터 로테이션).

두 가지를 한 번에 산출한다(둘 다 config 로 정의된 모든 섹터/테마에 범용 작동 — 하드코딩 없음):

1) 종목 탐색(universe screening, v2.7): config/universe.json(테마별 대형주 모집단)을
   상대강도+테마로 랭킹해 candidates 에 없는 주도주 '승격 제안'/만성 후행주 '회전아웃 제안'.

2) 섹터 로테이션 재진입(v2.8): 침체·avoid 섹터를 '5일 가격 반등'이 아니라 '호재(촉매)+시장
   몰입(자금이 실제로 도는 발자국)'으로 푼다. 이 스크립트는 '몰입'의 quant 발자국
   (rs_inflection 20일 상대강도 반등·volume_surge 거래량 급증·sector_breadth 동조·theme_heat)을
   섹터/테마 그룹별로 산출한다. **촉매(방아쇠)는 routine 이 출처 URL 로 채우고**, 이 엔진은
   **몰입 증거(안전핀)만** 계산한다(스토리≠자금 — 조선은 LNG 슈퍼사이클 스토리 내내 갖고도 3회 손실).
   출력: state/universe_screen.json.sector_rotation(전 섹터)·avoid_reentry(avoid 항목별).

입력: config/{universe,candidates,themes,policy,watchlist}.json, state/market_snapshot.json
수집: 모집단 중 스냅샷에 없는 종목만 네이버+Yahoo 로 5/20/60일 수익률·거래량 추가 수집(주 1회
전제). 차단 시 graceful degrade(데이터 없음 → 상대강도/몰입 중립).
출력: state/universe_screen.json (제안 + 랭킹 + 섹터 로테이션 + avoid 재진입 + 리포트 MD)
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# 같은 scripts/ 디렉터리의 수집·점수 헬퍼 재사용(DRY). 모듈 import 는 main 을 실행하지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_market_data import (  # noqa: E402
    compute_confidence,
    cumulative_return,
    fetch_naver,
    fetch_yahoo,
    five_day_return,
    price_structure,
    volume_ratio,
)
from score_candidates import relative_strength_score  # noqa: E402

MAX_WORKERS = 8


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def _median(xs: list[Any]) -> float | None:
    vals = sorted(x for x in xs if isinstance(x, (int, float)))
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def fundamentals_score(tk: str, funds: dict[str, Any], dir_map: dict[str, float], fcfg: dict[str, Any]) -> float | None:
    """기업가치 점수 ∈ [0,1] — 실적 방향(earnings_signal)+영업이익률+성장률. 미커버 None."""
    v = funds.get(tk)
    if not isinstance(v, dict):
        return None
    direction = float(dir_map.get(v.get("earnings_signal", "unknown"), 0.0))
    dir_comp = max(0.0, direction)  # 역성장은 완화 0(품질 가점 없음)
    margin_norm = float(fcfg.get("margin_norm_pct", 30.0)) or 30.0
    growth_norm = float(fcfg.get("growth_norm_pct", 100.0)) or 100.0
    margin = v.get("op_margin_pct")
    # 성장률: 진짜 YoY(계절성 제거) 우선, 없으면 PoP 폴백
    growth = v.get("op_growth_yoy_pct")
    if growth is None:
        growth = v.get("op_growth_pop_pct")
    margin_comp = _clamp((margin / margin_norm) if isinstance(margin, (int, float)) else 0.0, 0.0, 1.0)
    growth_comp = _clamp((growth / growth_norm) if isinstance(growth, (int, float)) else 0.0, 0.0, 1.0)
    score = (
        float(fcfg.get("dir_weight", 0.6)) * dir_comp
        + float(fcfg.get("margin_weight", 0.25)) * margin_comp
        + float(fcfg.get("growth_weight", 0.15)) * growth_comp
    )
    return round(_clamp(score, 0.0, 1.0), 3)


def news_score(tk: str, news_tickers: dict[str, Any], type_impact: dict[str, Any],
               now: datetime, decay_days: int, max_premium: float) -> float | None:
    """호재뉴스 점수 ∈ [0,1] — classified 양(+)뉴스 impact_pct × 시간감쇠, max_premium 캡. 미커버 None."""
    v = news_tickers.get(tk)
    if not isinstance(v, dict):
        return None
    classified = v.get("classified") or []
    if not classified:
        return 0.0  # 커버되나 분류뉴스 없음 → 0(완화 없음)
    premium = 0.0
    for c in classified:
        if not isinstance(c, dict):
            continue
        imp = type_impact.get(c.get("type"), {}).get("impact_pct", 0.0)
        if not isinstance(imp, (int, float)) or imp <= 0:
            continue  # 호재(양)만 가산
        pub = c.get("published")
        decay = 1.0
        if isinstance(pub, str) and decay_days > 0:
            try:
                d0 = datetime.strptime(pub[:10], "%Y-%m-%d").replace(tzinfo=KST)
                days = (now - d0).days
                decay = max(0.0, 1.0 - days / decay_days)
            except Exception:
                decay = 1.0
        premium += imp * decay
    premium = min(premium, float(max_premium))
    return round(_clamp(premium / float(max_premium or 12.0), 0.0, 1.0), 3)


def effective_excess_min(excess_60d: float | None, base_min: float, quality: float,
                         dcfg: dict[str, Any], regime_tier: str | None) -> tuple[float, float]:
    """종목별 동적 초과수익 하한 산출. 반환 (effective_min, applied_relax).

    strong_bull(설정 tier) 에서만 품질(기업가치+호재)로 음수 허용폭을 동적 부여한다.
    그 외 tier 는 base_min 엄격 적용(완화 0).
    """
    if not dcfg.get("enabled", False):
        return base_min, 0.0
    tiers = dcfg.get("applies_in_tiers", ["strong_bull"])
    if regime_tier not in tiers:
        return base_min, 0.0
    max_relax = float(dcfg.get("max_relax_pct", 50.0))
    abs_floor = float(dcfg.get("abs_floor_pct", -45.0))
    relax = max_relax * _clamp(quality, 0.0, 1.0)
    eff = max(base_min - relax, abs_floor)
    return round(eff, 2), round(relax, 2)


def fetch_returns(ticker: str) -> dict[str, Any]:
    """모집단 종목 1개의 5/20/60일 수익률·거래량비·신뢰도·종가 수집(스냅샷에 없을 때만)."""
    naver_hist = fetch_naver(ticker)
    yahoo_hist = fetch_yahoo(f"{ticker}.KS")
    # v2.18 — compute_confidence 는 동일 거래일 출처끼리만 교차검증(날짜 정렬). 출처별 마지막
    # 봉을 {name,close,date} 로 넘긴다(전일자 yahoo 를 당일 naver 와 비교해 low 로 강등하던 버그 제거).
    source_bars: list[dict[str, Any]] = []
    if naver_hist:
        source_bars.append({"name": "naver", "close": naver_hist[-1]["close"], "date": naver_hist[-1]["date"]})
    if yahoo_hist:
        source_bars.append({"name": "yahoo", "close": yahoo_hist[-1]["close"], "date": yahoo_hist[-1]["date"]})
    confidence, _gap = compute_confidence(source_bars)
    primary = naver_hist or yahoo_hist
    return {
        "ret5": five_day_return(primary) if primary else None,
        "ret20": cumulative_return(primary, 20) if primary else None,
        "ret60": cumulative_return(primary, 60) if primary else None,
        "vol_ratio": volume_ratio(primary, 20) if primary else None,
        "price_reversal": price_structure(primary)["price_reversal"] if primary else None,
        "last_close": primary[-1]["close"] if primary else None,
        "confidence": confidence,
        "data_ok": bool(primary),
    }


def reuse_from_snapshot(ts: dict[str, Any]) -> dict[str, Any]:
    """스냅샷에 이미 있는 종목은 재수집하지 않고 그 값을 재사용한다."""
    mom = ts.get("momentum", {}) if isinstance(ts, dict) else {}
    liq = ts.get("liquidity", {}) if isinstance(ts, dict) else {}
    struct = ts.get("structure", {}) if isinstance(ts, dict) else {}
    return {
        "ret5": ts.get("five_day_cumulative_return_pct"),
        "ret20": mom.get("ret_20d_pct"),
        "ret60": mom.get("ret_60d_pct"),
        "vol_ratio": liq.get("vol_ratio_20d"),
        "price_reversal": struct.get("price_reversal"),
        "last_close": ts.get("last_close"),
        "confidence": ts.get("confidence"),
        "data_ok": ts.get("last_close") is not None,
    }


def compute_immersion(
    members: list[dict[str, Any]],
    theme_strength: float | None,
    icfg: dict[str, Any],
    min_signals: int,
) -> dict[str, Any]:
    """섹터/테마 그룹의 '몰입(자금 유입)' quant 발자국을 계산한다(v2.8).

    섹터 단위 외국인/기관 수급을 직접 못 구하므로 상대강도·거래량·동조로 대체측정한다.
    members: 그룹 구성종목의 per-ticker dict(excess_60d·excess_20d·vol_ratio·ret5·data_ok).
    반환: {signals(bool dict), met(int), immersion_met(bool), members_with_data}.
    """
    valid = [m for m in members if m.get("data_ok")]
    rs_min = float(icfg.get("rs_inflection_min_pct", -10.0))
    vol_x = float(icfg.get("volume_surge_x", 1.5))
    breadth_min = int(icfg.get("breadth_min_members", 2))
    heat_min = float(icfg.get("theme_heat_min", 0.75))

    ex60 = [m.get("excess_60d") for m in valid]
    ex20 = [m.get("excess_20d") for m in valid]
    med20, med60 = _median(ex20), _median(ex60)
    rs_inflection = (
        med20 is not None and med60 is not None and med20 > med60 and med20 >= rs_min
    )
    vs_count = sum(
        1 for m in valid if isinstance(m.get("vol_ratio"), (int, float)) and m["vol_ratio"] >= vol_x
    )
    volume_surge = bool(valid) and vs_count >= max(1, len(valid) // 2)
    br_count = sum(
        1
        for m in valid
        if (isinstance(m.get("excess_20d"), (int, float)) and m["excess_20d"] > 0)
        or (isinstance(m.get("ret5"), (int, float)) and m["ret5"] > 0)
    )
    sector_breadth = br_count >= breadth_min
    pr_count = sum(1 for m in valid if m.get("price_reversal") is True)
    price_reversal = bool(valid) and pr_count >= max(1, len(valid) // 2)
    theme_heat = isinstance(theme_strength, (int, float)) and theme_strength >= heat_min

    # 집계 대상 = '자금이 실제로 도는' 발자국 + 가격구조 반등(v2.9). theme_heat 는 구조적 강도(context)라 집계 제외.
    signals = {
        "rs_inflection": rs_inflection,
        "volume_surge": volume_surge,
        "sector_breadth": sector_breadth,
        "price_reversal": price_reversal,
    }
    context = {"theme_heat": theme_heat}
    met = sum(1 for v in signals.values() if v)
    return {
        "signals": signals,
        "context": context,
        "met": met,
        "min_signals": min_signals,
        "immersion_met": met >= min_signals,
        "members_with_data": len(valid),
        "median_excess_20d": med20,
        "median_excess_60d": med60,
    }


def main() -> int:
    universe = load_json("config/universe.json", {"pool": []})
    candidates = load_json("config/candidates.json", {"candidates": []})
    themes_cfg = load_json("config/themes.json", {"themes": []})
    policy = load_json("config/policy.json", {})
    snapshot = load_json("state/market_snapshot.json", {"tickers": {}})
    watchlist = load_json("config/watchlist.json", {})
    fundamentals = load_json("state/fundamentals.json", {}).get("tickers", {})
    news_feed = load_json("state/news_feed.json", {}).get("tickers", {})
    news_impact = load_json("config/news_impact.json", {})
    now = datetime.now(KST)

    # 엔진 일원화: momentum_signal.full_ranking 를 단일 점수 권위로 로드(결측 시 상대강도 fallback).
    mom_signal = load_json("state/momentum_signal.json", {})
    mom_rank = {r.get("ticker"): r for r in mom_signal.get("full_ranking", []) if isinstance(r, dict) and r.get("ticker")}
    dg = policy.get("momentum_strategy", {}).get("discovery_gate", {}) if isinstance(policy.get("momentum_strategy"), dict) else {}
    dg_enabled = bool(dg.get("enabled", False)) and bool(mom_rank)  # 데이터 있을 때만 권위 적용
    promote_score_min = float(dg.get("promote_score_min", 30.0))
    rotate_score_max = float(dg.get("rotate_score_max", 0.0))

    theme_strength: dict[str, float] = {
        t.get("id"): float(t.get("strength", 0.0))
        for t in themes_cfg.get("themes", [])
        if isinstance(t, dict) and t.get("id")
    }
    cand_tickers = {
        c.get("ticker") for c in candidates.get("candidates", []) if isinstance(c, dict)
    }
    ef_cfg = policy.get("entry_filters", {}) if isinstance(policy.get("entry_filters"), dict) else {}
    rsw = ef_cfg.get("relative_strength_leader_widening", {}) if isinstance(ef_cfg.get("relative_strength_leader_widening"), dict) else {}
    excess_min = float(rsw.get("excess_min_pct", 10.0))
    hard_floor = float(ef_cfg.get("entry_filter_hard_floor_pct", -22.0))

    # 동적 승격 임계(강세장: 기업가치+호재로 음수 초과수익 허용폭 산출)
    dcfg = rsw.get("dynamic_excess_min", {}) if isinstance(rsw.get("dynamic_excess_min"), dict) else {}
    base_excess_min = float(dcfg.get("base_excess_min_pct", excess_min))
    qweights = dcfg.get("quality_weights", {}) if isinstance(dcfg.get("quality_weights"), dict) else {}
    w_fund = float(qweights.get("fundamentals", 0.55))
    w_news = float(qweights.get("news", 0.45))
    fund_cfg = dcfg.get("fundamentals_score", {}) if isinstance(dcfg.get("fundamentals_score"), dict) else {}
    news_cfg = dcfg.get("news_score", {}) if isinstance(dcfg.get("news_score"), dict) else {}
    dir_map = news_impact.get("earnings_signal_direction", {}) if isinstance(news_impact.get("earnings_signal_direction"), dict) else {}
    type_impact = news_impact.get("news_type_impact_pct", {}) if isinstance(news_impact.get("news_type_impact_pct"), dict) else {}
    news_decay = int(news_cfg.get("decay_days", (news_impact.get("params", {}) or {}).get("news_decay_days", 90)))
    news_max_prem = float(news_cfg.get("max_premium_pct", (news_impact.get("params", {}) or {}).get("max_news_premium_pct", 12.0)))

    # v2.8 — 섹터 로테이션 재진입 설정(몰입 신호 임계·민감도).
    srr = policy.get("sector_rotation_reentry", {}) if isinstance(policy.get("sector_rotation_reentry"), dict) else {}
    icfg = srr.get("immersion_confirmation", {}) if isinstance(srr.get("immersion_confirmation"), dict) else {}
    # v2.10 — 시장 상황(레짐 tier)에 따라 민감도 자동 조정(sensitivity_mode=auto). tier unknown·고정모드면 폴백.
    min_sig_map = icfg.get("min_signals_by_sensitivity", {"aggressive": 1, "medium": 2, "conservative": 3})
    sens_by_tier = srr.get("sensitivity_by_tier", {}) if isinstance(srr.get("sensitivity_by_tier"), dict) else {}
    sensitivity_mode = srr.get("sensitivity_mode", "auto")
    tier_for_sens = (snapshot.get("regime", {}) or {}).get("tier") if isinstance(snapshot, dict) else None
    if sensitivity_mode == "auto" and isinstance(sens_by_tier.get(tier_for_sens), str) and sens_by_tier.get(tier_for_sens) in min_sig_map:
        sensitivity = sens_by_tier[tier_for_sens]
        sensitivity_basis = f"auto(tier={tier_for_sens})"
    else:
        sensitivity = srr.get("sensitivity", "medium")
        sensitivity_basis = "fixed" if sensitivity_mode != "auto" else f"fallback(tier={tier_for_sens})"
    min_signals = int(min_sig_map.get(sensitivity, 2))

    rules = universe.get("screening_rules", {}) if isinstance(universe.get("screening_rules"), dict) else {}
    blend = rules.get("rank_blend", {"relative_strength": 0.6, "thematic": 0.4})
    w_rs = float(blend.get("relative_strength", 0.6))
    w_th = float(blend.get("thematic", 0.4))
    rotate_excess = float(rules.get("rotate_out_excess_pct", -25.0))
    promote_max = int(rules.get("promote_max_per_run", 4))

    regime = snapshot.get("regime", {}) if isinstance(snapshot, dict) else {}
    kospi_ret60 = regime.get("ret_60d_pct") if isinstance(regime, dict) else None
    kospi_ret20 = regime.get("ret_20d_pct") if isinstance(regime, dict) else None
    regime_tier = regime.get("tier") if isinstance(regime, dict) else None
    snap_tickers = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}

    pool = [p for p in universe.get("pool", []) if isinstance(p, dict) and p.get("ticker")]

    # 스냅샷에 없는 종목만 네트워크 수집(스레드풀). 있는 종목은 스냅샷 값 재사용.
    to_fetch = [p["ticker"] for p in pool if p["ticker"] not in snap_tickers]
    fetched: dict[str, dict[str, Any]] = {}
    if to_fetch:
        workers = min(len(to_fetch), MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool_ex:
            futs = {tk: pool_ex.submit(fetch_returns, tk) for tk in to_fetch}
            fetched = {tk: f.result() for tk, f in futs.items()}

    ranked: list[dict[str, Any]] = []
    by_ticker: dict[str, dict[str, Any]] = {}
    for p in pool:
        tk = p["ticker"]
        data = reuse_from_snapshot(snap_tickers[tk]) if tk in snap_tickers else fetched.get(tk, {})
        ret60 = data.get("ret60")
        ret20 = data.get("ret20")
        ret5 = data.get("ret5")
        vol_ratio = data.get("vol_ratio")
        rs_score, excess60 = relative_strength_score(ret60, kospi_ret60)
        excess20 = round(ret20 - kospi_ret20, 2) if isinstance(ret20, (int, float)) and isinstance(kospi_ret20, (int, float)) else None
        theme = p.get("theme")
        exposure = float(p.get("exposure", 0.0) or 0.0)
        strength = theme_strength.get(theme, 0.0) if theme else 0.0
        thematic = round(min(1.0, strength * exposure), 3)
        screen_score = round(w_rs * rs_score + w_th * thematic, 3)
        # 기업가치+호재 품질 → 동적 초과수익 하한(강세장 음수 허용폭)
        f_sc = fundamentals_score(tk, fundamentals, dir_map, fund_cfg)
        n_sc = news_score(tk, news_feed, type_impact, now, news_decay, news_max_prem)
        has_q = f_sc is not None or n_sc is not None
        quality = round(_clamp(w_fund * (f_sc or 0.0) + w_news * (n_sc or 0.0), 0.0, 1.0), 3) if has_q else 0.0
        eff_min, relax = effective_excess_min(excess60, base_excess_min, quality, dcfg, regime_tier)
        entry = {
            "ticker": tk,
            "name": p.get("name", ""),
            "sector": p.get("sector"),
            "theme": theme,
            "fund_score": f_sc,
            "news_score": n_sc,
            "quality": quality,
            "effective_excess_min": eff_min,
            "excess_relax_applied": relax,
            # 단일 점수 권위(momentum_signal 절대모멘텀) — 없으면 None → RS fallback
            "mom_score": (mom_rank.get(tk, {}) or {}).get("score"),
            "mom_pass_filter": (mom_rank.get(tk, {}) or {}).get("pass_filter"),
            "ret5": ret5,
            "ret20": ret20,
            "ret60": ret60,
            "excess_60d": excess60,
            "excess_20d": excess20,
            "excess_vs_kospi_pct": excess60,
            "vol_ratio": vol_ratio,
            "price_reversal": data.get("price_reversal"),
            "rs_score": rs_score,
            "thematic": thematic,
            "screen_score": screen_score,
            "confidence": data.get("confidence"),
            "data_ok": bool(data.get("data_ok")),
            "in_candidates": tk in cand_tickers,
        }
        ranked.append(entry)
        by_ticker[tk] = entry

    ranked.sort(key=lambda r: r["screen_score"], reverse=True)

    # --- v2.7 종목 탐색: 승격/회전아웃 제안 (v2.9 동적 임계: 강세장 기업가치+호재로 음수 허용) ---
    # 승격 후보 우선순위: 단일 권위(momentum score) 있으면 그 순, 없으면 상대강도 순.
    promote_pool = sorted(ranked, key=lambda r: (-(r["mom_score"] if r.get("mom_score") is not None else -999),
                                                 -(r["screen_score"] or 0)))
    promote: list[dict[str, Any]] = []
    for r in promote_pool:
        if r["in_candidates"] or not r["data_ok"]:
            continue
        if r["ret5"] is not None and r["ret5"] < hard_floor:
            continue  # 자유낙하 차단(불변)
        if dg_enabled and r.get("mom_score") is not None:
            # 일원화: momentum 이 실제 매수할 만한 종목만 승격(promote_score_min 은 매수 floor 와 정렬)
            if not r.get("mom_pass_filter") or r["mom_score"] < promote_score_min:
                continue
        else:
            # fallback: momentum 데이터 없을 때만 상대강도 동적임계 사용
            threshold = r.get("effective_excess_min", excess_min)
            if r["excess_60d"] is None or r["excess_60d"] < threshold:
                continue
        promote.append(r)
        if len(promote) >= promote_max:
            break
    # 회전아웃: 일원화 시 momentum 이 버린 종목만(절대모멘텀 소멸/추세이탈) — momentum 이 아직
    # 원하는 종목은 회전아웃 안 함(모순 제거). fallback 은 기존 상대강도+품질 보호 로직.
    rotate_out = []
    for r in ranked:
        if not r["in_candidates"]:
            continue
        if dg_enabled and r.get("mom_score") is not None:
            if (r.get("mom_pass_filter") is False) or (r["mom_score"] <= rotate_score_max):
                rotate_out.append(r)
        else:
            if (r["excess_60d"] is not None and r["excess_60d"] <= rotate_excess
                    and r["excess_60d"] < r.get("effective_excess_min", rotate_excess)):
                rotate_out.append(r)

    # --- v2.8 섹터 로테이션: theme(없으면 sector)로 그룹핑해 '몰입' 신호 산출(전 섹터 범용) ---
    groups: dict[str, dict[str, Any]] = {}
    for r in ranked:
        key = r["theme"] or f"sector:{r['sector']}"
        g = groups.setdefault(key, {"key": key, "theme": r["theme"], "members": [], "sectors": set()})
        g["members"].append(r)
        if r.get("sector"):
            g["sectors"].add(r["sector"])
    sector_rotation: list[dict[str, Any]] = []
    for key, g in groups.items():
        strength = theme_strength.get(g["theme"]) if g["theme"] else None
        imm = compute_immersion(g["members"], strength, icfg, min_signals)
        sector_rotation.append({
            "group": key,
            "theme": g["theme"],
            "theme_strength": strength,
            "sectors": sorted(g["sectors"]),
            "tickers": [m["ticker"] for m in g["members"]],
            **imm,
        })
    sector_rotation.sort(key=lambda s: (s["immersion_met"], s["met"], s.get("median_excess_20d") or -999), reverse=True)

    # --- v2.8 avoid 재진입: watchlist.avoid_sectors 의 모든 항목에 동일 적용(범용) ---
    avoid_reentry: list[dict[str, Any]] = []
    for av in watchlist.get("avoid_sectors", []) if isinstance(watchlist.get("avoid_sectors"), list) else []:
        if not isinstance(av, dict):
            continue
        av_tickers = av.get("tickers", []) or []
        members = [by_ticker[t] for t in av_tickers if t in by_ticker]
        # 그룹의 테마 강도(첫 구성종목 기준)
        strength = None
        for m in members:
            if m.get("theme"):
                strength = theme_strength.get(m["theme"])
                break
        imm = compute_immersion(members, strength, icfg, min_signals)
        avoid_reentry.append({
            "sector": av.get("sector"),
            "tickers": av_tickers,
            "effective_from": av.get("effective_from"),
            **imm,
            "catalyst": "routine 확인 필요(출처 URL+게재일 — sector_rotation_reentry.catalyst_trigger)",
            "verdict": (
                "몰입 충족 — 촉매 web_verify 후 avoid 해제·probe 진입 검토"
                if imm["immersion_met"]
                else "avoid 유지(몰입 미충족 — 자금 유입 발자국 부족)"
            ),
        })

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of") if isinstance(snapshot, dict) else None,
        "kospi_ret60_pct": kospi_ret60,
        "kospi_ret20_pct": kospi_ret20,
        "regime_tier": regime.get("tier") if isinstance(regime, dict) else None,
        "pool_size": len(pool),
        "fetched_count": len(to_fetch),
        "sensitivity": sensitivity,
        "sensitivity_basis": sensitivity_basis,
        "immersion_min_signals": min_signals,
        "rank_blend": {"relative_strength": w_rs, "thematic": w_th},
        "score_authority": {
            "unified": dg_enabled,
            "source": "state/momentum_signal.json#full_ranking.score" if dg_enabled else "relative_strength(fallback)",
            "promote_score_min": promote_score_min,
            "rotate_score_max": rotate_score_max,
            "note": "일원화 ON 시 promote/rotate 는 momentum 절대점수 권위를 따르고 상대강도·품질은 2차 랭킹/컨텍스트. momentum_signal 결측 시 상대강도로 degrade.",
        },
        "promote_threshold": {
            "base_excess_min_pct": base_excess_min,
            "dynamic_enabled": bool(dcfg.get("enabled", False)),
            "applies_in_tiers": dcfg.get("applies_in_tiers", []),
            "active_now": bool(dcfg.get("enabled", False)) and regime_tier in dcfg.get("applies_in_tiers", []),
            "max_relax_pct": dcfg.get("max_relax_pct"),
            "abs_floor_pct": dcfg.get("abs_floor_pct"),
            "quality_weights": {"fundamentals": w_fund, "news": w_news},
            "note": "강세장 promote 0 문제 해소 — 종목별 기업가치(실적)+호재뉴스 품질로 음수 초과수익 허용폭 동적 산출. 종목별 effective_excess_min 은 ranked[].effective_excess_min 참조.",
        },
        "ranked": ranked,
        "promote_suggestions": promote,
        "rotate_out_suggestions": rotate_out,
        "sector_rotation": sector_rotation,
        "avoid_reentry": avoid_reentry,
        "report_section_md": _report_md(ranked, promote, rotate_out, sector_rotation, avoid_reentry, kospi_ret60, regime, min_signals),
        "note": "촉매(방아쇠)는 routine 이 출처 URL 로 채우고 이 엔진은 몰입 증거(안전핀)만 산출. candidates/avoid 자동수정 안 함 — 제안만.",
    }
    out_path = ROOT / "state" / "universe_screen.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    n_heating = sum(1 for s in sector_rotation if s["immersion_met"])
    n_avoid_ready = sum(1 for a in avoid_reentry if a["immersion_met"])
    print(
        f"wrote {out_path.relative_to(ROOT)} pool={len(pool)} fetched={len(to_fetch)} "
        f"promote={len(promote)} rotate_out={len(rotate_out)} "
        f"heating_sectors={n_heating} avoid_reentry_ready={n_avoid_ready} "
        f"sensitivity={sensitivity}(min={min_signals})"
    )
    return 0


def _report_md(
    ranked: list[dict],
    promote: list[dict],
    rotate_out: list[dict],
    sector_rotation: list[dict],
    avoid_reentry: list[dict],
    kospi_ret60: float | None,
    regime: dict,
    min_signals: int,
) -> str:
    lines = ["### 종목 탐색 + 섹터 로테이션", ""]
    tier = regime.get("tier") if isinstance(regime, dict) else None
    lines.append(f"- 벤치마크: KOSPI 60일 {kospi_ret60}% / tier {tier} / 몰입 신호 {min_signals}개 요구")
    lines.append("")
    if promote:
        lines.append("**승격 제안 (momentum 절대점수 권위 — 매수 floor 와 정렬):**")
        for r in promote:
            ms = r.get("mom_score")
            head = f"모멘텀 {ms:+.1f}" if ms is not None else f"초과수익 {r['excess_60d']:+.1f}%p"
            q = r.get("quality", 0.0)
            qnote = f" · 품질 {q:.2f}(실적 {r.get('fund_score')}/뉴스 {r.get('news_score')})" if q else ""
            lines.append(f"- {r['name']}({r['ticker']}) · {r['sector']} — {head}, 5일 {r['ret5']}%{qnote}")
    else:
        lines.append("**승격 제안: 없음** (momentum 점수 상위 신규 주도주가 이미 모두 추적 중 — 정상)")
    if rotate_out:
        lines.append("")
        lines.append("**회전아웃 제안 (momentum 절대점수 소멸 — 단일 권위):**")
        for r in rotate_out:
            ms = r.get("mom_score")
            ms_s = f"모멘텀 {ms:+.1f}" if ms is not None else f"초과수익 {r['excess_60d']:+.1f}%p"
            lines.append(f"- {r['name']}({r['ticker']}) — {ms_s} (추세·절대모멘텀 이탈)")
    lines.append("")
    lines.append("**🔥 섹터 로테이션 — 몰입 신호 (호재는 routine 이 별도 web_verify):**")
    heating = [s for s in sector_rotation if s["immersion_met"]]
    if heating:
        for s in heating:
            on = [k for k, v in s["signals"].items() if v]
            lines.append(f"- 🔥 {s['group']} (테마강도 {s['theme_strength']}) — 몰입 {s['met']}/{min_signals} ✓ [{', '.join(on)}]")
    else:
        lines.append("- 현재 몰입 충족 섹터 없음 (자금 유입 발자국 부족 — 정상)")
    if avoid_reentry:
        lines.append("")
        lines.append("**🚫→ avoid 재진입 점검:**")
        for a in avoid_reentry:
            mark = "✅ 검토" if a["immersion_met"] else "유지"
            lines.append(f"- [{mark}] {a['sector']} — 몰입 {a['met']}/{min_signals} · {a['verdict']}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
