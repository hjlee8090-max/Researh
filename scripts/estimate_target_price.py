#!/usr/bin/env python3
"""estimate_target_price — 뉴스·밸류에이션·미래 테마·섹터 활발성을 결합한 목표주가 추정 (v1.2).

기존 파이프라인의 흩어진 신호(PER/PBR 밴드·컨센서스·테마 레지스트리·촉매 캘린더·섹터 몰입)를
하나의 식으로 결합해 '12개월 내 도달 가능한 대략적 목표가'를 종목별로 산출한다.
점수(0~1 랭킹)가 아니라 **가격(원)** 을 내는 것이 score_candidates 와의 차이.

추정식:
  추정목표가 = 기준가(anchor) × (1 + 테마P + 뉴스P + 섹터P + 모멘텀틸트)  → 천장 캡

  1) 기준가(anchor) — 멀티플 기반 적정가와 컨센서스의 평균. 데이터 결측 시 현재가 폴백.
     - preferred_metric=PBR: BPS × PBR 5년 밴드 중앙값 / PER: 선행EPS × PER 밴드 중앙값
       (config/valuation.json — 사이클 업종은 PER 함정 때문에 PBR 우선, check_valuation_guard 동일)
     - 컨센서스 목표가(state/consensus.json)가 있으면 50:50 블렌드
  2) 테마 프리미엄(미래 산업 동향 포커스) — Σ(theme.strength × exposure × 호라이즌할인)
     × max_theme_premium_pct. 호라이즌할인 = min(1, 12개월/테마 호라이즌 중앙값) —
     '3~5년짜리 메가트렌드'는 12개월 목표가에는 일부만 반영된다.
  3) 뉴스/촉매 프리미엄 — config/news_impact.json 의 유형별 가산점 테이블.
     과거 뉴스는 90일 시간감쇠, 다가오는 촉매(catalysts.json)는 발생확률(confirmed)
     × D-day 근접가중 × 방향(earnings_signal)으로 할인. ±max_news_premium_pct 클램프.
  4) 섹터 활발성 프리미엄 — universe_screen.json 의 섹터 몰입 신호로 '활발성이 언제 올지'를
     4단계(현재 활발/1~2개월/2~4개월/촉매 대기)로 추정하고 프리미엄을 차등 반영.
  5) 모멘텀 틸트 — KOSPI 대비 60일 초과수익 + 52주 고점 근접도 기반 ±4% 보정(확신 틸트).
  6) 천장 캡 — policy.valuation_anchor 그대로: min(추정치, 컨센×1.15, 밸류에이션 천장).
     결측은 캡을 만들지 않는다(skip — 래칫 방지).

v1.1 (2026-06-10 백테스트 보정 — backtest_target_model.py, 삼성전자·현대차 2.5년·592거래일):
  ① 추세 게이트(trend_gate) — 테마 프리미엄과 양(+) 뉴스 프리미엄에 실현 계수를 곱한다:
     주도주(KOSPI 대비 60일 초과수익 ≥+10%p) 1.0 / 동행(0~10) 0.6 / 후행(<0) 0.3.
     근거: 후행주(현대차)는 상시 +프리미엄(평균 +6.0%)을 약속했지만 실현 +0.3%·60일 적중률
     25.9% — '스토리는 자금이 따라올 때만 가격이 된다'(레포 momentum-게이트 ethos 동일).
     주도주(삼성)는 corr 0.51·적중률 63%로 작동. 음(-) 뉴스는 게이트하지 않는다(후행주에서도
     악재는 지속 — 충격연구 negative persist 0.31~0.73).
  ② 뉴스 기반영분 차감(already-realized guard) — 뉴스 가산점에서 '이벤트 날짜 이후 이미
     움직인 초과수익'을 뺀다. 근거: 6/1 supply_contract_major 는 당일 +6.41%로 테이블(8%)의
     대부분이 즉시 반영 — 점프 뒤 가산점을 또 더하면 이중계상(CAR5 +0.13%, 후속 드리프트 없음).
     state/price_history.json(폴백: 스냅샷 five_day_history)으로 이벤트일 이후 실현분을 계산.
  ③ 모멘텀 틸트 재보정 — v1.0 의 '초과수익 ≥30 최대 가점'은 데이터와 반대(비단조):
     실측 fwd20 중앙값 [10,30) +9.0%/+28.3% 최고, [30,∞) +1.9%/-5.8% 둔화·역전.
     신규: ≥30 +1.0 / 10~30 +2.5 / 0~10 -1.0 / -10~0 -2.0 / <-10 0.0(낙폭 반등 중립).
     + 52주 고점 근접 항: ≥97% +1.5 / 85~97 +0.5 / 70~85 -0.5 / <70 -1.5 (합계 ±4 캡).
     ※ 당초 가설이던 '과열 댐퍼(고점 97%+ 감점)'는 기각 — 실측 fwd20 +9.2%로 강한 양(+) 신호.

v1.2 (자동 뉴스 피드 연결):
  ④ state/news_feed.json(fetch_news.py — Google News RSS+네이버 종목뉴스를 config/
     news_keywords.json 키워드로 12개 뉴스 유형에 자동 분류)을 뉴스 가산점에 반영한다.
     자동 항목은 auto_news_confidence_factor(0.6) 할인 — 자동은 후보, 확정은 검증된 manual.
     같은 유형 manual_news 가 ±5일 내 있으면 manual 우선, 유형당 최신 1건만(도배 방지),
     기반영분 차감(②)·추세 게이트(①) 동일 적용. 유형 미분류 기사는 unclassified 로 보존돼
     라우틴이 manual_news 승격 또는 키워드 보강으로 소비한다(재현율 우선).

출력: state/target_estimate.json — 종목별 추정가·프리미엄 분해·섹터 활성화 예상 시점·
신뢰등급(A/B/C, 가용 데이터 레이어 수) + 리포트용 markdown 섹션.
watchlist 의 target_price 를 자동으로 덮어쓰지 않는다 — routine 이 참고하는 추정 레이어.
의존성 0(표준 라이브러리). 학습·시뮬레이션 목적, 투자 권유 아님.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "target_estimate.json"


def load_json(rel: str, default: Any) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _parse_date(s: Any) -> date | None:
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def horizon_discount(horizon: str | None, horizon_months: int) -> float:
    """테마 호라이즌('2-4y' 등) → 추정 호라이즌(12개월) 내 실현 비율. 파싱 불가면 0.5."""
    if not isinstance(horizon, str):
        return 0.5
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", horizon)]
    if not nums:
        return 0.5
    mid_years = sum(nums) / len(nums)
    mid_months = mid_years * 12 if "y" in horizon.lower() else mid_years
    if mid_months <= 0:
        return 0.5
    return round(min(1.0, horizon_months / mid_months), 3)


def anchor_price(
    val_cfg: dict, consensus_target: float | None, current: float | None
) -> tuple[float | None, str, bool]:
    """기준가 산출. (anchor, basis 설명, 밸류 밴드 사용 여부) 반환."""
    fair = None
    metric = (val_cfg.get("preferred_metric") or "PBR").upper()
    if metric == "PBR":
        base, band = _num(val_cfg.get("bps")), val_cfg.get("pbr_band_5y")
    else:
        base, band = _num(val_cfg.get("eps_fwd")), val_cfg.get("per_band_5y")
    lo = _num(band[0]) if isinstance(band, list) and len(band) == 2 else None
    hi = _num(band[1]) if isinstance(band, list) and len(band) == 2 else None
    if base and lo is not None and hi is not None:
        fair = base * (lo + hi) / 2.0

    parts: list[str] = []
    values: list[float] = []
    if fair:
        values.append(fair)
        parts.append(f"{metric} 밴드 중앙값 적정가 {fair:,.0f}")
    if consensus_target:
        values.append(consensus_target)
        parts.append(f"컨센서스 목표가 {consensus_target:,.0f}")
    if values:
        return sum(values) / len(values), " + ".join(parts) + (" 평균" if len(values) > 1 else ""), fair is not None
    if current:
        return current, "현재가 폴백(밸류 밴드·컨센서스 미시드 — sunday_strategy 주간 시드 필요)", False
    return None, "기준가 산출 불가(현재가·밸류·컨센 전부 결측)", False


def trend_gate(excess60_pct: float | None) -> float:
    """v1.1 ① — 테마·양(+)뉴스 프리미엄의 실현 계수. '스토리는 자금이 따라올 때만 가격이 된다.'

    백테스트: 후행주(현대차, 초과수익<0)는 +프리미엄 실현 실패(60일 적중률 25.9%),
    주도주(삼성, ≥+10%p)는 작동(corr 0.51). 데이터 결측은 0.6(동행 취급 — 왜곡 최소).
    """
    if excess60_pct is None:
        return 0.6
    if excess60_pct >= 10.0:
        return 1.0
    if excess60_pct >= 0.0:
        return 0.6
    return 0.3


def realized_excess_lookup(ticker: str) -> Any:
    """이벤트일 이후 '이미 실현된 초과수익(%)'을 돌려주는 클로저 — 뉴스 이중계상 가드(v1.1 ②)용.

    1차: state/price_history.json(장기 일봉, KOSPI 보정). 폴백: 스냅샷 five_day_history
    (지수 보정 없음 — 근사). 둘 다 없으면 None(가드 미적용, 감쇠만).
    """
    hist = load_json("state/price_history.json", {})
    t_bars = ((hist.get("tickers") or {}).get(ticker) or {}).get("bars") or []
    i_bars = (hist.get("index") or {}).get("bars") or []
    t_close = {b["date"]: float(b["close"]) for b in t_bars if isinstance(b, dict)}
    i_close = {b["date"]: float(b["close"]) for b in i_bars if isinstance(b, dict)}

    snap = load_json("state/market_snapshot.json", {})
    fdh = ((snap.get("tickers") or {}).get(ticker) or {}).get("five_day_history") or []
    f_close = {b["date"]: float(b["close"]) for b in fdh if isinstance(b, dict) and b.get("close")}

    def realized(since: str) -> float | None:
        for closes, idx in ((t_close, i_close), (f_close, {})):
            if not closes:
                continue
            dates = sorted(closes)
            base_dates = [d for d in dates if d <= since]
            if not base_dates:
                continue
            d0, d1 = base_dates[-1], dates[-1]
            if d0 == d1:
                return 0.0
            stock_move = (closes[d1] / closes[d0] - 1.0) * 100.0
            if idx and d0 in idx and d1 in idx:
                stock_move -= (idx[d1] / idx[d0] - 1.0) * 100.0
            return round(stock_move, 2)
        return None

    return realized


def news_premium(
    ticker: str, cfg: dict, events: list[dict], earnings_signal: str | None, today: date,
    realized_since: Any = None, auto_items: list[dict] | None = None,
) -> tuple[float, list[dict]]:
    """뉴스(과거: manual+auto)+촉매(미래) 가산점 합산. (프리미엄 %, 기여 상세) 반환."""
    params = cfg.get("params", {})
    decay_days = int(params.get("news_decay_days", 90))
    horizon_days = int(params.get("event_horizon_days", 365))
    near_days = int(params.get("event_near_window_days", 30))
    cap = float(params.get("max_news_premium_pct", 12.0))
    p_conf = float(params.get("probability_confirmed", 0.9))
    p_unconf = float(params.get("probability_unconfirmed", 0.6))
    type_table = cfg.get("news_type_impact_pct", {})
    event_table = cfg.get("event_type_impact_pct", {})
    sig_dir = cfg.get("earnings_signal_direction", {})

    contribs: list[dict] = []
    total = 0.0
    manual_seen: list[tuple[str, date]] = []  # (type, date) — 자동 뉴스 중복 방지용

    # 과거 뉴스(manual_news) — 게재일 기준 시간감쇠. 오래된 호재는 이미 주가에 반영됐다고 본다.
    for n in cfg.get("manual_news", []) or []:
        if not isinstance(n, dict) or n.get("ticker") != ticker:
            continue
        d = _parse_date(n.get("date"))
        if d is None:
            continue
        days_since = max(0, (today - d).days)
        decay = max(0.0, 1.0 - days_since / decay_days)
        base = _num(n.get("impact_pct"))
        if base is None:
            base = _num((type_table.get(n.get("type")) or {}).get("impact_pct")) or 0.0
        c = base * decay
        # v1.1 ② 기반영분 차감 — 뉴스가 이미 가격을 움직인 만큼 가산점에서 뺀다(이중계상 방지).
        # 양(+)뉴스: [0, impact] 클램프(역행했어도 테이블 초과 금지). 음(-)뉴스: [impact, 0].
        realized = realized_since(n["date"]) if realized_since and n.get("date") else None
        if realized is not None:
            c = c - realized
            c = max(0.0, min(base, c)) if base >= 0 else min(0.0, max(base, c))
        c = round(c, 2)
        total += c
        manual_seen.append((n.get("type") or "", d))
        contribs.append({
            "kind": "news", "type": n.get("type"), "date": n.get("date"),
            "impact_pct": base, "decay": round(decay, 2),
            "realized_since_event_pct": realized, "contrib_pct": c,
            "note": n.get("note"),
        })

    # v1.2 ④ 자동 분류 뉴스(news_feed) — confidence factor 할인, manual 우선, 유형당 최신 1건.
    auto_factor = float(params.get("auto_news_confidence_factor", 0.6))
    auto_max_age = int(params.get("auto_news_max_age_days", 14))
    latest_by_type: dict[str, dict] = {}
    for it in auto_items or []:
        if not isinstance(it, dict) or not it.get("type") or not it.get("published"):
            continue
        cur = latest_by_type.get(it["type"])
        if cur is None or it["published"] > (cur.get("published") or ""):
            latest_by_type[it["type"]] = it
    for ntype, it in sorted(latest_by_type.items()):
        d = _parse_date(it.get("published"))
        if d is None:
            continue
        days_since = (today - d).days
        if days_since < 0 or days_since > auto_max_age:
            continue
        if any(t == ntype and abs((d - md).days) <= 5 for t, md in manual_seen):
            continue  # 같은 유형 manual 기록 존재 — 검증된 쪽 우선
        decay = max(0.0, 1.0 - days_since / decay_days)
        base = _num((type_table.get(ntype) or {}).get("impact_pct")) or 0.0
        c = base * decay * auto_factor
        realized = realized_since(it["published"]) if realized_since else None
        if realized is not None:
            c = c - realized
            c = max(0.0, min(base * auto_factor, c)) if base >= 0 else min(0.0, max(base * auto_factor, c))
        c = round(c, 2)
        total += c
        contribs.append({
            "kind": "news_auto", "type": ntype, "date": it.get("published"),
            "impact_pct": base, "decay": round(decay, 2), "auto_factor": auto_factor,
            "realized_since_event_pct": realized, "contrib_pct": c,
            "note": it.get("title"), "source_url": it.get("url"),
            "matched_keywords": it.get("matched_keywords"),
        })

    # 미래 촉매(catalysts) — 확률·근접가중·방향 할인. '언제 오는 이벤트인지'가 가산점 크기를 정한다.
    for ev in events:
        d = _parse_date(ev.get("date"))
        if d is None:
            continue
        days_until = (d - today).days
        if days_until < -7 or days_until > horizon_days:
            continue
        etype = ev.get("type", "")
        base = _num((event_table.get(etype) or {}).get(ev.get("importance", "medium"))) or 0.0
        if etype == "earnings_report":
            direction = float(sig_dir.get(earnings_signal or "unknown", 0.0))
        elif etype == "macro":
            direction = 0.0  # 방향 추정 불가 — 가산 없이 일정만 노출
        else:
            direction = 1.0
        time_w = 1.0 if days_until <= near_days else max(0.2, 1.0 - (days_until - near_days) / horizon_days)
        prob = p_conf if ev.get("confirmed") else p_unconf
        c = round(base * direction * time_w * prob, 2)
        total += c
        contribs.append({
            "kind": "catalyst", "type": etype, "date": ev.get("date"), "d_day": days_until,
            "impact_pct": base, "direction": direction, "time_weight": round(time_w, 2),
            "probability": prob, "contrib_pct": c, "id": ev.get("id"),
        })

    return round(max(-cap, min(cap, total)), 2), contribs


def theme_premium(
    theme_exposure: list[dict] | None, themes: dict[str, dict], max_pct: float, horizon_months: int
) -> tuple[float, list[dict]]:
    """미래 산업 테마 프리미엄. 호라이즌 할인으로 '몇 년짜리 트렌드인지'를 반영."""
    if not theme_exposure:
        return 0.0, []
    parts: list[dict] = []
    raw = 0.0
    for te in theme_exposure:
        if not isinstance(te, dict):
            continue
        th = themes.get(te.get("theme") or "")
        exposure = _num(te.get("exposure"))
        if th is None or exposure is None:
            continue
        strength = float(th.get("strength", 0.0))
        hd = horizon_discount(th.get("horizon"), horizon_months)
        contrib = strength * exposure * hd
        raw += contrib
        parts.append({
            "theme": te.get("theme"), "exposure": exposure, "strength": strength,
            "horizon": th.get("horizon"), "horizon_discount": hd,
            "contrib_pct": round(contrib * max_pct, 2),
        })
    return round(min(max_pct, raw * max_pct), 2), parts


def sector_activity(
    ticker: str, sector_rotation: list[dict], next_catalyst: dict | None, max_pct: float
) -> tuple[float, str, dict | None]:
    """섹터 활발성 프리미엄 + '활발성이 언제 올지' 추정. (프리미엄 %, 예상 시점, 그룹 요약) 반환."""
    group = None
    for g in sector_rotation or []:
        if isinstance(g, dict) and ticker in (g.get("tickers") or []):
            group = g
            break
    catalyst_note = ""
    if next_catalyst:
        dd = next_catalyst.get("d_day")
        dd_label = f"D{dd:+d}" if isinstance(dd, int) else "D?"
        catalyst_note = f" — 다음 촉매 {next_catalyst.get('date')}({next_catalyst.get('type')}, {dd_label}) 전후 재평가"
    if group is None:
        return 0.0, "섹터 그룹 미매핑(universe.json 미등록)" + catalyst_note, None

    excess60 = _num(group.get("median_excess_60d"))
    met = int(group.get("met", 0) or 0)
    min_sig = max(1, int(group.get("min_signals", 1) or 1))
    summary = {
        "group": group.get("group"), "median_excess_60d": excess60,
        "signals_met": met, "min_signals": min_sig, "immersion_met": bool(group.get("immersion_met")),
    }
    if excess60 is not None and excess60 >= 10.0:
        return max_pct, f"현재 활발 — 주도 섹터(KOSPI 대비 60일 +{excess60:.0f}%p)", summary
    if group.get("immersion_met"):
        return round(max_pct * 0.8, 2), "몰입 신호 충족 — 약 1~2개월 내 본격화 추정", summary
    if met > 0:
        return round(max_pct * 0.5, 2), f"부분 몰입({met}/{min_sig}) — 약 2~4개월 내 회복 가능성", summary
    return 0.0, "휴면 — 자금 발자국 없음" + catalyst_note, summary


def momentum_tilt(excess60_pct: float | None, pct_of_52w_high: float | None) -> float:
    """v1.1 ③ — 60일 초과수익 + 52주 고점 근접도 확신 틸트(합계 ±4 캡).

    백테스트 재보정: 초과수익은 [10,30) 구간이 최고(fwd20 중앙값 +9.0%/+28.3%)이고
    ≥30 극단은 둔화·역전(+1.9%/-5.8%) — v1.0 의 '≥30 최대 가점'을 뒤집는다.
    52주 고점 근접(≥97%)은 강한 양(+) 신호(fwd20 +9.2%) — 과열 댐퍼 가설은 기각됐다.
    """
    tilt = 0.0
    if excess60_pct is not None:
        if excess60_pct >= 30.0:
            tilt += 1.0
        elif excess60_pct >= 10.0:
            tilt += 2.5
        elif excess60_pct >= 0.0:
            tilt += -1.0
        elif excess60_pct >= -10.0:
            tilt += -2.0
        # <-10: 낙폭 과대 반등 혼재(실측 중앙값 -0.1%/+1.4%) — 0.0 중립
    if pct_of_52w_high is not None:
        if pct_of_52w_high >= 97.0:
            tilt += 1.5
        elif pct_of_52w_high >= 85.0:
            tilt += 0.5
        elif pct_of_52w_high >= 70.0:
            tilt += -0.5
        else:
            tilt += -1.5
    return max(-4.0, min(4.0, round(tilt, 2)))


def grade(layers: dict[str, bool]) -> str:
    n = sum(1 for v in layers.values() if v)
    return "A" if n >= 5 else ("B" if n >= 3 else "C")


def build_report_section(rows: list[dict], as_of: str) -> str:
    lines = [
        "### 목표주가 추정 (estimate_target_price v1.0)",
        "",
        f"- 기준 시각: {as_of} · 추정 호라이즌 12개월 · 학습·시뮬레이션 목적(투자 권유 아님)",
        "- 식: 기준가(밸류 밴드·컨센) × (1 + 테마 + 뉴스/촉매 + 섹터활발성 + 모멘텀) → 천장 캡(컨센×1.15·밸류천장)",
        "",
        "| 종목 | 현재가 | 추정 목표가 | 상승여력 | 프리미엄(테마/뉴스/섹터/모멘텀) | 섹터 활성화 예상 | 등급 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cur = f"{r['current_price']:,.0f}" if r.get("current_price") else "—"
        est = f"{r['estimate']:,.0f}" if r.get("estimate") else "—"
        up = f"{r['expected_return_pct']:+.1f}%" if r.get("expected_return_pct") is not None else "—"
        p = r.get("premium_pct", {})
        prem = f"{p.get('theme', 0):+.1f}/{p.get('news', 0):+.1f}/{p.get('sector', 0):+.1f}/{p.get('momentum', 0):+.1f}"
        lines.append(
            f"| {r['name']}({r['ticker']}) | {cur} | {est} | {up} | {prem} | {r.get('sector_activation', '—')} | {r['grade']} |"
        )
    lines += [
        "",
        "> 등급: 가용 데이터 레이어 수 기준 A(5+)/B(3~4)/C(2-). C 등급은 기준가가 현재가 폴백이라",
        "> '현재가 + 프리미엄' 수준의 거친 추정 — 밸류 밴드·컨센서스 시드 후 재산출 필요.",
    ]
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(KST)
    today = now.date()

    impact_cfg = load_json("config/news_impact.json", {})
    params = impact_cfg.get("params", {})
    horizon_months = int(params.get("estimate_horizon_months", 12))
    max_theme_pct = float(params.get("max_theme_premium_pct", 20.0))
    max_sector_pct = float(params.get("max_sector_activity_premium_pct", 8.0))

    candidates = load_json("config/candidates.json", {}).get("candidates", [])
    watchlist = load_json("config/watchlist.json", {}).get("stocks", [])
    valuation = load_json("config/valuation.json", {}).get("tickers", {})
    themes = {
        t.get("id"): t for t in load_json("config/themes.json", {}).get("themes", [])
        if isinstance(t, dict) and t.get("id")
    }
    catalysts_cfg = load_json("config/catalysts.json", {})
    all_events = (catalysts_cfg.get("generated_events", []) or []) + (catalysts_cfg.get("manual_events", []) or [])
    snapshot = load_json("state/market_snapshot.json", {})
    snap_tickers = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    kospi_ret60 = (snapshot.get("regime") or {}).get("ret_60d_pct")
    consensus = load_json("state/consensus.json", {}).get("tickers", {})
    fundamentals = load_json("state/fundamentals.json", {}).get("tickers", {})
    val_checks = load_json("state/valuation_check.json", {}).get("tickers", {})
    sector_rotation = load_json("state/universe_screen.json", {}).get("sector_rotation", [])
    news_feed = load_json("state/news_feed.json", {}).get("tickers", {})

    # 추정 대상: 후보 전체 ∪ 실보유 종목. 후보 항목이 테마 노출·섹터 정보를 가진 1차 소스.
    by_ticker: dict[str, dict] = {}
    for c in candidates:
        if isinstance(c, dict) and c.get("ticker"):
            by_ticker[c["ticker"]] = {"ticker": c["ticker"], "name": c.get("name", ""), "sector": c.get("sector"),
                                      "theme_exposure": c.get("theme_exposure")}
    for s in watchlist:
        if isinstance(s, dict) and s.get("ticker") and (s.get("shares_held") or 0) > 0:
            by_ticker.setdefault(s["ticker"], {"ticker": s["ticker"], "name": s.get("name", ""),
                                               "sector": s.get("sector"), "theme_exposure": None})

    results: list[dict] = []
    for ticker, info in by_ticker.items():
        ts = snap_tickers.get(ticker, {}) if isinstance(snap_tickers, dict) else {}
        current = _num(ts.get("last_close"))
        mom = ts.get("momentum", {}) if isinstance(ts.get("momentum"), dict) else {}
        ret60 = _num(mom.get("ret_60d_pct"))
        cons = consensus.get(ticker, {}) if isinstance(consensus, dict) else {}
        cons_target = _num(cons.get("target_price"))
        fund = fundamentals.get(ticker, {}) if isinstance(fundamentals, dict) else {}
        earnings_signal = fund.get("earnings_signal")
        val_cfg = valuation.get(ticker, {}) if isinstance(valuation, dict) else {}

        anchor, anchor_basis, anchor_uses_band = anchor_price(val_cfg, cons_target, current)

        ticker_events = [e for e in all_events if isinstance(e, dict) and e.get("ticker") == ticker]
        news_pct_raw, news_parts = news_premium(
            ticker, impact_cfg, ticker_events, earnings_signal, today,
            realized_since=realized_excess_lookup(ticker),
            auto_items=(news_feed.get(ticker) or {}).get("classified"),
        )
        theme_pct_raw, theme_parts = theme_premium(info.get("theme_exposure"), themes, max_theme_pct, horizon_months)

        # v1.1 ① 추세 게이트 — 테마·양(+)뉴스만 게이트, 음(-)뉴스는 전액 반영(악재는 후행주에서도 지속).
        excess60 = round(ret60 - _num(kospi_ret60), 2) if ret60 is not None and _num(kospi_ret60) is not None else None
        gate = trend_gate(excess60)
        theme_pct = round(theme_pct_raw * gate, 2)
        max_news = float(params.get("max_news_premium_pct", 12.0))
        news_pos = sum(p["contrib_pct"] for p in news_parts if p["contrib_pct"] > 0)
        news_neg = sum(p["contrib_pct"] for p in news_parts if p["contrib_pct"] < 0)
        news_pct = round(max(-max_news, min(max_news, news_pos * gate + news_neg)), 2)

        upcoming = sorted(
            (e for e in news_parts if e.get("kind") == "catalyst" and (e.get("d_day") or 0) >= 0),
            key=lambda e: e.get("d_day", 9999),
        )
        next_cat = upcoming[0] if upcoming else None
        sector_pct, sector_eta, sector_summary = sector_activity(ticker, sector_rotation, next_cat, max_sector_pct)
        pct52 = _num(mom.get("pct_of_52w_high")) if isinstance(mom, dict) else None
        tilt_pct = momentum_tilt(excess60, pct52)

        total_premium_pct = round(theme_pct + news_pct + sector_pct + tilt_pct, 2)
        raw_estimate = anchor * (1.0 + total_premium_pct / 100.0) if anchor else None

        # 천장 캡 — policy.valuation_anchor 와 동일 위계. 결측 항은 캡을 만들지 않는다.
        caps: list[tuple[str, float]] = []
        if cons_target:
            caps.append(("컨센서스×1.15", cons_target * 1.15))
        ceiling = _num((val_checks.get(ticker) or {}).get("valuation_ceiling_price"))
        if ceiling:
            caps.append(("밸류에이션 천장", ceiling))
        estimate = raw_estimate
        cap_applied = None
        if estimate is not None:
            for label, cap_v in caps:
                if cap_v < estimate:
                    estimate, cap_applied = cap_v, label
            estimate = round(estimate, -2)  # 호가 단순화: 100원 단위

        expected_return = round((estimate / current - 1.0) * 100.0, 1) if estimate and current else None

        layers = {
            "valuation_band": anchor_uses_band,
            "consensus_target": bool(cons_target),
            "price_snapshot": current is not None and ts.get("confidence") in ("high", "medium"),
            "theme_exposure": bool(theme_parts),
            "sector_group": sector_summary is not None,
            "earnings_signal": bool(earnings_signal and earnings_signal != "unknown"),
        }

        results.append({
            "ticker": ticker,
            "name": info.get("name") or ticker,
            "sector": info.get("sector"),
            "current_price": current,
            "anchor_price": round(anchor, -2) if anchor else None,
            "anchor_basis": anchor_basis,
            "premium_pct": {
                "theme": theme_pct, "news": news_pct, "sector": sector_pct,
                "momentum": tilt_pct, "total": total_premium_pct,
            },
            "trend_gate": {
                "factor": gate,
                "excess60_vs_kospi_pct": excess60,
                "pct_of_52w_high": pct52,
                "ungated": {"theme": theme_pct_raw, "news": round(news_pct_raw, 2)},
            },
            "raw_estimate": round(raw_estimate, -2) if raw_estimate else None,
            "cap_applied": cap_applied,
            "estimate": estimate,
            "expected_return_pct": expected_return,
            "sector_activation": sector_eta,
            "sector_signals": sector_summary,
            "grade": grade(layers),
            "data_layers": layers,
            "detail": {
                "theme_parts": theme_parts,
                "news_parts": news_parts,
                "earnings_signal": earnings_signal,
                "ret_60d_pct": ret60,
                "next_catalyst": next_cat,
            },
        })

    results.sort(key=lambda r: (r["expected_return_pct"] is None, -(r["expected_return_pct"] or 0)))
    as_of = now.isoformat(timespec="seconds")
    out = {
        "as_of": as_of,
        "snapshot_as_of": snapshot.get("as_of") if isinstance(snapshot, dict) else None,
        "horizon_months": horizon_months,
        "formula": "추정목표가 = 기준가(밸류밴드·컨센 평균, 결측 시 현재가) × (1 + 추세게이트×(테마P(호라이즌할인) + 양뉴스P(시간감쇠·확률·기반영차감)) + 음뉴스P + 섹터활발성P + 모멘텀틸트(초과수익+52주고점)) → min(컨센×1.15, 밸류천장) 캡 [v1.1 백테스트 보정]",
        "kospi_ret_60d_pct": kospi_ret60,
        "estimates": results,
        "report_section_md": build_report_section(results, as_of),
        "disclaimer": "학습·시뮬레이션 목적의 거친 추정 — 투자 권유 아님. watchlist.target_price 를 자동 갱신하지 않으며, routine 이 dynamic_exit_model 목표가 산정 시 참고 레이어로만 쓴다.",
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    graded = {g: sum(1 for r in results if r["grade"] == g) for g in ("A", "B", "C")}
    print(f"wrote {OUT_PATH.relative_to(ROOT)} estimates={len(results)} grades={graded}")
    for r in results:
        est = f"{r['estimate']:,.0f}" if r.get("estimate") else "—"
        up = f"{r['expected_return_pct']:+.1f}%" if r.get("expected_return_pct") is not None else "—"
        print(f"  [{r['grade']}] {r['name']}({r['ticker']}): est {est} ({up}) premium {r['premium_pct']['total']:+.1f}% — {r['sector_activation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
