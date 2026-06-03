#!/usr/bin/env python3
"""신규 진입 후보 종목을 점수화·랭킹한다.

입력:
- config/candidates.json — 후보 목록
- config/weekly_plan.json — 활성 thesis 목록
- state/market_snapshot.json — 5거래일 추세·신뢰도 (fetch_market_data.py 가 먼저 생성해야 함)
- config/policy.json — entry_filters, weekly_recovery_plan 등

출력: state/candidate_scores.json (gitignored)
- ranked candidates: 점수 내림차순 + 진입 가능 여부 + 제외 사유

점수 모델 (각 0~1 정규화):
- momentum_score: 3요소 가중 블렌드 (52주 고점 근접·60일 모멘텀·5일 추세)
  - ret5_score(34%): 단기 급락 회피 게이트 (0%↑=1.0, -2%=0.7, -5%=0.4, -7%=0.1)
  - ret60_score(33%): 중기 추세 지속 (20%↑=1.0 … -10%↓=0.1)
  - high52_score(33%): 52주 고점 근접도 (95%↑=1.0 … 50%↓=0.2) — George&Hwang 52주 고점 효과
- thematic_score: 선행 산업 메가트렌드 노출. min(1.0, Σ(theme.strength × exposure)).
  config/themes.json 의 strength × candidate.theme_exposure[].exposure. 노출 정보 없으면 0.3(중립-하).
  예: 자동차 섹터에서 현대차(humanoid_robotics 노출 0.7)는 기아(0.1)보다 thematic 점수가 높다.
- relative_strength_score: 섹터 로테이션/상대강도 (v2.5). KOSPI 대비 60일 초과수익으로
  주도 섹터를 우대한다. excess = stock.ret_60d − KOSPI.ret_60d → ≥+30%p=1.0 … <−25%p=0.05.
  '오르는 장'에서 절대 모멘텀은 후행 섹터(반도체 주도장의 조선·금융)도 양(+)이라 구분이 안 되지만,
  초과수익은 주도 섹터만 높게 준다. 지수 수익률 없으면(regime unknown) 0.5 중립 폴백.
- confidence_score: high=1.0 / medium=0.5 / low=0.0
- thesis_score: 활성 thesis 와 linked = 1.0 / candidate-only thesis = 0.6 / 무관 = 0.3
- bear_flag_penalty: structural_bear_flags 1개당 -0.15

- fundamental_tilt: IR/펀더멘털(후행)은 가중 축이 아닌 소폭 확신 틸트(±). state/fundamentals.json
  (fetch_fundamentals.py, DART 분기실적)의 earnings_signal → strong_growth +0.05 … sharp_decline -0.06.
  데이터 없으면 0(무영향).

final = (momentum × 0.30 + relative_strength × 0.20 + thematic × 0.15 + confidence × 0.15
         + thesis × 0.20) - bear_flag_penalty + fundamental_tilt
가중치는 policy.entry_filters.relative_strength.score_blend_weights 로 조정 가능(없으면 모듈 BLEND_WEIGHTS).
momentum 을 게이트(급락 회피)로 유지하므로 전망이 좋아도 추세가 깨진 종목은 entry_filter 에서 차단된다.

시장 레짐(KOSPI 200일선 risk_on/risk_off)은 snapshot.regime 에서 읽어 출력에 표기하고,
policy.market_regime.risk_off_blocks_new_entry=true 면 risk_off 일 때 tradable 을 차단한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def trend_score(pct: float | None) -> float:
    """5거래일 단기 추세 점수 (급락 회피 게이트)."""
    if pct is None:
        return 0.0
    if pct >= 0:
        return 1.0
    if pct >= -2.0:
        return 0.7
    if pct >= -5.0:
        return 0.4
    if pct >= -7.0:
        return 0.1
    return 0.0


def ret60_score(pct: float | None) -> float:
    """60거래일 중기 모멘텀 점수. 데이터 없으면 0.5(중립)."""
    if pct is None:
        return 0.5
    if pct >= 20.0:
        return 1.0
    if pct >= 10.0:
        return 0.85
    if pct >= 0.0:
        return 0.6
    if pct >= -10.0:
        return 0.35
    return 0.1


def high52_score(pct_of_high: float | None) -> float:
    """52주 고점 대비 현재가 비율 점수. 데이터 없으면 0.5(중립)."""
    if pct_of_high is None:
        return 0.5
    if pct_of_high >= 95.0:
        return 1.0
    if pct_of_high >= 85.0:
        return 0.8
    if pct_of_high >= 70.0:
        return 0.6
    if pct_of_high >= 50.0:
        return 0.4
    return 0.2


def momentum_score(ret5: float | None, ret60: float | None, pct_of_high: float | None) -> tuple[float, dict]:
    """5일·60일·52주고점 3요소 블렌드. (블렌드 점수, 구성요소 dict) 반환."""
    s5 = trend_score(ret5)
    s60 = ret60_score(ret60)
    s52 = high52_score(pct_of_high)
    blended = round(s5 * 0.34 + s60 * 0.33 + s52 * 0.33, 3)
    return blended, {"ret5": s5, "ret60": s60, "high52": s52}


def confidence_score(level: str | None) -> float:
    return {"high": 1.0, "medium": 0.5, "low": 0.0}.get(level or "low", 0.0)


def relative_strength_score(
    stock_ret60: float | None, index_ret60: float | None
) -> tuple[float, float | None]:
    """섹터 로테이션/상대강도 점수 (v2.5). KOSPI 대비 60일 초과수익으로 주도 섹터를 우대한다.

    excess = stock_ret60 − KOSPI_ret60. '오르는 장'에서 절대 모멘텀은 후행 섹터도 양(+)이라
    구분이 안 되지만, 초과수익은 지금 자금이 쏠리는 주도 섹터(반도체 등)만 높게 준다.
    지수 수익률이 없으면(regime unknown) 0.5 중립으로 폴백해 점수를 왜곡하지 않는다.

    반환: (점수 0~1, excess %p 또는 None).
    """
    if stock_ret60 is None or index_ret60 is None:
        return 0.5, None
    excess = round(stock_ret60 - index_ret60, 2)
    if excess >= 30.0:
        s = 1.0
    elif excess >= 10.0:
        s = 0.85
    elif excess >= 0.0:
        s = 0.65
    elif excess >= -10.0:
        s = 0.4
    elif excess >= -25.0:
        s = 0.2
    else:
        s = 0.05
    return s, excess


# v2.5 — score blend 가중치(합 1.0). policy.entry_filters.relative_strength.score_blend_weights 와 일치.
# momentum 은 급락 회피 게이트로 유지하되 비중을 줄이고, relative_strength(섹터 로테이션) 0.20 을 신설.
BLEND_WEIGHTS = {
    "momentum": 0.30,
    "relative_strength": 0.20,
    "thematic": 0.15,
    "confidence": 0.15,
    "thesis": 0.20,
}


def thesis_score(thesis_id: str | None, active_thesis_ids: set[str], candidate_thesis_ids: set[str]) -> float:
    if not thesis_id:
        return 0.3
    if thesis_id in active_thesis_ids:
        return 1.0
    if thesis_id in candidate_thesis_ids:
        return 0.6
    return 0.3


def thematic_score(
    theme_exposure: list[dict] | None,
    theme_strength: dict[str, float],
) -> tuple[float, list[dict]]:
    """선행 산업 메가트렌드 노출 점수. (점수 0~1, 기여도 상세) 반환.

    score = min(1.0, Σ(theme.strength × exposure)). 노출 정보가 없으면 0.3(중립-하).
    알 수 없는 theme id 는 strength 0 으로 무시한다.
    """
    if not theme_exposure:
        return 0.3, []
    total = 0.0
    parts: list[dict] = []
    for te in theme_exposure:
        if not isinstance(te, dict):
            continue
        tid = te.get("theme")
        exposure = te.get("exposure")
        if tid is None or not isinstance(exposure, (int, float)):
            continue
        strength = theme_strength.get(tid, 0.0)
        contrib = round(strength * float(exposure), 3)
        total += contrib
        parts.append({"theme": tid, "exposure": exposure, "strength": strength, "contrib": contrib})
    if not parts:
        return 0.3, []
    return round(min(1.0, total), 3), parts


# IR/펀더멘털은 후행 지표 → 가중 축이 아닌 '확신 틸트'(±, 소폭)로만 반영한다.
# state/fundamentals.json(fetch_fundamentals.py, DART) 의 earnings_signal 을 매핑. 데이터 없으면 0.
FUND_TILT = {
    "strong_growth": 0.05,
    "growth": 0.02,
    "flat": 0.0,
    "decline": -0.03,
    "sharp_decline": -0.06,
    "unknown": 0.0,
}


def build_adopt_reasons(
    c: dict,
    ret5: float | None,
    conf: str | None,
    th_score: float,
    active_ids: set[str],
    candidate_ids: set[str],
    ret60: float | None = None,
    pct_high: float | None = None,
    theme_parts: list[dict] | None = None,
    rs_excess: float | None = None,
) -> list[str]:
    """진입 가능(tradable) 후보가 '왜 채택됐는지' 를 사람이 읽을 수 있는 사유 목록으로 만든다."""
    reasons: list[str] = []
    if ret5 is not None:
        trend_word = "상승" if ret5 >= 0 else "방어"
        reasons.append(f"5거래일 누적 {ret5:+.1f}% — 추세필터 통과({trend_word})")
    if ret60 is not None:
        reasons.append(f"60일 모멘텀 {ret60:+.1f}%")
    if rs_excess is not None:
        lead_word = "주도주" if rs_excess >= 10 else ("동행" if rs_excess >= -10 else "후행주")
        reasons.append(f"상대강도: KOSPI 대비 {rs_excess:+.1f}%p ({lead_word})")
    if pct_high is not None:
        reasons.append(f"52주 고점의 {pct_high:.0f}% 수준")
    if theme_parts:
        top = sorted(theme_parts, key=lambda p: p.get("contrib", 0), reverse=True)[:2]
        label = ", ".join(f"{p['theme']}(노출 {p['exposure']})" for p in top)
        reasons.append(f"미래 테마 노출: {label}")
    conf_word = {"high": "high(2출처 일치)", "medium": "medium(단일출처)"}.get(conf or "", str(conf))
    reasons.append(f"가격 신뢰도 {conf_word}")
    tid = c.get("thesis_id")
    if tid and tid in active_ids:
        reasons.append(f"활성 thesis '{tid}' 연결")
    elif tid and tid in candidate_ids:
        reasons.append(f"후보 thesis '{tid}' 연결")
    rationale = c.get("rationale")
    if rationale:
        reasons.append(f"근거: {rationale}")
    return reasons


def build_report_section(adopted: list[dict], blocked: list[dict], regime: dict | None = None) -> str:
    """리포트 MD 에 그대로 붙여 넣을 '신규 후보 채택 사유' 섹션을 생성한다."""
    lines = ["### 신규 후보 채택 사유", ""]
    if regime and regime.get("state") and regime.get("state") != "unknown":
        st = regime["state"]
        emoji = "🟢" if st == "risk_on" else "🔴"
        pct = regime.get("pct_vs_ma")
        lines.append(
            f"- 시장 레짐: {emoji} **{st}** (KOSPI {regime.get('last_close')} / 200일선 대비 {pct:+.1f}%)"
            if isinstance(pct, (int, float))
            else f"- 시장 레짐: {emoji} **{st}**"
        )
        lines.append("")
    if adopted:
        for r in adopted:
            name = r.get("name") or r.get("ticker")
            score = r.get("final_score")
            lines.append(f"- **{name}({r['ticker']})** — 점수 {score}")
            for reason in r.get("adopt_reasons", []):
                lines.append(f"  - {reason}")
    else:
        lines.append("- 채택 후보 없음 (진입 가능 조건을 만족한 후보 0건)")
    if blocked:
        lines.append("")
        lines.append("> 차단된 후보:")
        for r in blocked:
            name = r.get("name") or r.get("ticker")
            why = "; ".join(r.get("block_reasons", [])) or "사유 미상"
            lines.append(f"> - {name}({r['ticker']}): {why}")
    return "\n".join(lines)


def main() -> int:
    candidates_cfg = load_json("config/candidates.json", {"candidates": []})
    weekly_plan = load_json("config/weekly_plan.json", {})
    snapshot = load_json("state/market_snapshot.json", {"tickers": {}})
    policy = load_json("config/policy.json", {})
    themes_cfg = load_json("config/themes.json", {"themes": []})
    theme_strength: dict[str, float] = {
        t.get("id"): float(t.get("strength", 0.0))
        for t in themes_cfg.get("themes", [])
        if isinstance(t, dict) and t.get("id")
    }
    fundamentals = load_json("state/fundamentals.json", {}).get("tickers", {})

    regime = snapshot.get("regime", {}) if isinstance(snapshot, dict) else {}
    regime_state = regime.get("state", "unknown") if isinstance(regime, dict) else "unknown"
    # v2.5 — 섹터 로테이션 벤치마크: KOSPI 60일 수익률(없으면 상대강도는 중립 폴백).
    kospi_ret60 = regime.get("ret_60d_pct") if isinstance(regime, dict) else None
    regime_cfg = policy.get("market_regime", {}) if isinstance(policy, dict) else {}
    risk_off_blocks = bool(regime_cfg.get("risk_off_blocks_new_entry", False))

    # v2.5 — score blend 가중치(policy 우선, 없으면 모듈 기본값 BLEND_WEIGHTS).
    blend_cfg = (
        policy.get("entry_filters", {}).get("relative_strength", {}).get("score_blend_weights")
        if isinstance(policy.get("entry_filters"), dict) else None
    )
    weights = {**BLEND_WEIGHTS, **blend_cfg} if isinstance(blend_cfg, dict) else dict(BLEND_WEIGHTS)

    theses = weekly_plan.get("weekly_thesis", []) if isinstance(weekly_plan, dict) else []
    active_ids: set[str] = set()
    candidate_ids: set[str] = set()
    for t in theses:
        if not isinstance(t, dict):
            continue
        direction = t.get("direction", "")
        tid = t.get("id")
        if not tid:
            continue
        if direction == "candidate":
            candidate_ids.add(tid)
        else:
            active_ids.add(tid)

    ts_map = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}

    ranked: list[dict] = []
    for c in candidates_cfg.get("candidates", []):
        if not isinstance(c, dict):
            continue
        ticker = c.get("ticker")
        ts = ts_map.get(ticker, {}) if isinstance(ts_map, dict) else {}
        ret5 = ts.get("five_day_cumulative_return_pct") if isinstance(ts, dict) else None
        conf = ts.get("confidence") if isinstance(ts, dict) else None
        mom = ts.get("momentum", {}) if isinstance(ts, dict) else {}
        ret60 = mom.get("ret_60d_pct") if isinstance(mom, dict) else None
        pct_high = mom.get("pct_of_52w_high") if isinstance(mom, dict) else None
        entry_passes = (
            ts.get("entry_filter", {}).get("passes")
            if isinstance(ts, dict) and isinstance(ts.get("entry_filter"), dict)
            else False
        )
        bear_flags = c.get("structural_bear_flags", []) or []

        m_score, m_parts = momentum_score(ret5, ret60, pct_high)
        rs_score, rs_excess = relative_strength_score(ret60, kospi_ret60)
        t_score, t_parts = thematic_score(c.get("theme_exposure"), theme_strength)
        c_score = confidence_score(conf)
        th_score = thesis_score(c.get("thesis_id"), active_ids, candidate_ids)
        fund = fundamentals.get(ticker, {}) if isinstance(fundamentals, dict) else {}
        earnings_signal = fund.get("earnings_signal")
        fund_tilt = FUND_TILT.get(earnings_signal, 0.0)
        penalty = 0.15 * len(bear_flags)
        final = max(
            0.0,
            m_score * weights["momentum"]
            + rs_score * weights["relative_strength"]
            + t_score * weights["thematic"]
            + c_score * weights["confidence"]
            + th_score * weights["thesis"]
            - penalty
            + fund_tilt,
        )

        block_reasons: list[str] = []
        if not entry_passes:
            ef_reason = ts.get("entry_filter", {}).get("reason") if isinstance(ts, dict) else None
            if not ef_reason:
                ef_reason = (
                    "스냅샷 미수집 — candidates 에 신규 추가됨, 다음 정기 수집(fetch_prices) 후 추세·신뢰도 평가"
                    if not ts else "5거래일 추세 데이터 없음"
                )
            block_reasons.append(ef_reason)
        if conf == "low":
            block_reasons.append("가격 신뢰도 low — 신규 매매 차단")
        if bear_flags:
            block_reasons.append(f"구조적 악재 매칭: {', '.join(bear_flags)}")
        if regime_state == "risk_off":
            note = f"시장 레짐 risk_off (KOSPI<200일선 {regime.get('pct_vs_ma')}%)"
            block_reasons.append(note + (" — 신규 진입 차단" if risk_off_blocks else " — 신규 진입 신중(어드바이저리)"))

        tradable = (
            entry_passes
            and conf in ("high", "medium")
            and not bear_flags
            and not (risk_off_blocks and regime_state == "risk_off")
        )
        adopt_reasons = (
            build_adopt_reasons(c, ret5, conf, th_score, active_ids, candidate_ids, ret60, pct_high, t_parts, rs_excess)
            if tradable else []
        )
        if adopt_reasons and earnings_signal in ("strong_growth", "growth"):
            g = fund.get("op_growth_pop_pct")
            adopt_reasons.append(
                f"실적 모멘텀({earnings_signal}, 영업이익 전기대비 {g:+.0f}%)" if isinstance(g, (int, float))
                else f"실적 모멘텀({earnings_signal})"
            )
        adopt_summary = " · ".join(adopt_reasons) if adopt_reasons else None

        ranked.append({
            "ticker": ticker,
            "name": c.get("name", ""),
            "sector": c.get("sector"),
            "thesis_id": c.get("thesis_id"),
            "rationale": c.get("rationale"),
            "components": {
                "momentum": m_score,
                "momentum_parts": m_parts,
                "relative_strength": rs_score,
                "rs_excess_vs_kospi_pct": rs_excess,
                "thematic": t_score,
                "thematic_parts": t_parts,
                "confidence": c_score,
                "thesis": th_score,
                "bear_penalty": penalty,
                "fundamental_tilt": fund_tilt,
                "earnings_signal": earnings_signal,
            },
            "final_score": round(final, 3),
            "data": {
                "five_day_cumulative_return_pct": ret5,
                "ret_60d_pct": ret60,
                "pct_of_52w_high": pct_high,
                "confidence": conf,
                "entry_filter_passes": entry_passes,
                "structural_bear_flags": bear_flags,
                "theme_exposure": c.get("theme_exposure", []),
                "fundamentals": {
                    "revenue": fund.get("revenue"),
                    "operating_profit": fund.get("operating_profit"),
                    "op_margin_pct": fund.get("op_margin_pct"),
                    "op_growth_pop_pct": fund.get("op_growth_pop_pct"),
                    "period_label": fund.get("period_label"),
                    "earnings_signal": earnings_signal,
                } if fund else None,
            },
            "tradable": tradable,
            "adopt_reasons": adopt_reasons,
            "adopt_summary": adopt_summary,
            "block_reasons": [r for r in block_reasons if r],
        })

    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    tradable = [r for r in ranked if r["tradable"]]
    blocked = [r for r in ranked if not r["tradable"]]

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of") if isinstance(snapshot, dict) else None,
        "regime": {"state": regime_state, "detail": regime, "blocks_new_entry": risk_off_blocks,
                   "kospi_ret_60d_pct": kospi_ret60},
        "score_blend_weights": weights,
        "active_thesis_ids": sorted(active_ids),
        "candidate_thesis_ids": sorted(candidate_ids),
        "ranked": ranked,
        "adopted": [
            {
                "ticker": r["ticker"],
                "name": r["name"],
                "final_score": r["final_score"],
                "summary": r["adopt_summary"],
                "reasons": r["adopt_reasons"],
            }
            for r in tradable
        ],
        "report_section_md": build_report_section(tradable, blocked, regime if isinstance(regime, dict) else None),
        "summary": {
            "total": len(ranked),
            "tradable_count": len(tradable),
            "blocked_count": len(blocked),
            "top_tradable_ticker": tradable[0]["ticker"] if tradable else None,
            "regime_state": regime_state,
        },
    }
    out_path = ROOT / "state" / "candidate_scores.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {out_path.relative_to(ROOT)} candidates={len(ranked)} "
        f"tradable={len(tradable)} blocked={len(blocked)} regime={regime_state}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
