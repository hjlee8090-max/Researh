#!/usr/bin/env python3
"""estimate_target_price — 뉴스·밸류에이션·미래 테마·섹터 활발성을 결합한 목표주가 추정 (v1.3).

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

v1.3 (2026-06-10 섹터·해외 백테스트 보정 — backtest_sector_global.py, universe 30종목+해외 4심볼):
  ⑤ 연속 섹터값(sector_value) — '섹터에 자금이 몰리는 집중도'를 연속값으로 산출해 섹터
     프리미엄에 반영: sector_value = 0.7×heat + 0.3×rs.
       heat = 섹터 거래대금 점유율(20d) ÷ 자기 120d 평균 → clamp((비율-0.8)/0.8, 0, 1)
       rs   = 섹터 중앙값 20d 초과수익 → clamp((ex20+5)/15, 0, 1)
     섹터 프리미엄 = max_sector_pct × (0.5×기존 사다리 + 0.5×sector_value) 블렌드.
     근거: 8개 섹터그룹 60d 예측력 — sv 0.151 > 블렌드 0.136 > 사다리 0.096, 20d 는 블렌드
     최고(0.093). 주력 섹터에서 블렌드 최강(조선 60d 0.521·AI메모리 0.451). w_heat 0.7 이
     그리드 최적(집중도>상대모멘텀). price_history(거래량) 없으면 사다리 단독 폴백.
  ⑥ 해외뉴스 채널 전이 — news_feed.global(영어 쿼리 수집·분류)을 채널 전이계수
     (news_keywords.global_news.channel_transmission)로 할인해 국내 종목 가산점에 반영.
     실증(오버나이트 β, 큰 뉴스 |2%|+): SOXX→SK하이닉스 0.42(corr 0.55)·NVDA→SK 0.27 —
     동종(peer) 0.45·고객(customer) 0.35 로 보정. 비매핑 섹터 전이 ≈0(조선·자동차 β -0.1~0),
     매크로 0(초과수익 기반 식 — 시장 전체 충격은 지수에 흡수). 한계: 삼성전자처럼 사업이
     분산된 종목은 전이가 약함(β 0.03~0.10) — 단일 채널 계수가 과대평가할 수 있어 auto
     factor(0.6)·추세 게이트가 추가 완충.

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


def previous_estimates() -> dict[str, dict]:
    """직전 리포트(target_estimate_log.jsonl 마지막 행)의 종목별 추정 스냅샷 — 델타 산출용.

    로그에 append 하기 '전' 마지막 행이 곧 직전 routine(리포트)의 추정이다. 종목별로
    {estimate, expected_return_pct, premium_pct, news 지문, _as_of} 를 돌려준다. 없으면 {}.
    """
    path = ROOT / "state" / "target_estimate_log.jsonl"
    if not path.exists():
        return {}
    last = ""
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
    except OSError:
        return {}
    if not last:
        return {}
    try:
        rec = json.loads(last)
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict] = {}
    for e in rec.get("estimates", []) or []:
        if isinstance(e, dict) and e.get("ticker"):
            out[e["ticker"]] = {**e, "_as_of": rec.get("as_of"), "_date": rec.get("date")}
    return out


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
    # 기준가(anchor)에 쓸 수 있는 밴드 품질 화이트리스트:
    #   None/verified = 사람·일요일 루틴이 출처 검증 후 시드한 실측 5년 밴드
    #   dart_quarterly = DART 분기 자본총계 기반 실측 멀티플 시계열(fetch_valuation v1.1)
    # 그 외(approx_price_percentile·inconsistent)는 천장·가드 전용 — 밴드 중앙값이
    # '과거 평균 가격'으로 퇴화해 기준가를 왜곡한다(2026-06-11 anchor 사고).
    band_quality = val_cfg.get("band_quality")
    approx_band = (
        band_quality not in (None, "verified", "dart_quarterly")
        or "근사" in (val_cfg.get("method") or "")
    )
    metric = (val_cfg.get("preferred_metric") or "PBR").upper()
    if metric == "PBR":
        base, band = _num(val_cfg.get("bps")), val_cfg.get("pbr_band_5y")
    else:
        base, band = _num(val_cfg.get("eps_fwd")), val_cfg.get("per_band_5y")
    lo = _num(band[0]) if isinstance(band, list) and len(band) == 2 else None
    hi = _num(band[1]) if isinstance(band, list) and len(band) == 2 else None
    if base and lo is not None and hi is not None and not approx_band:
        fair = base * (lo + hi) / 2.0

    parts: list[str] = []
    values: list[float] = []
    if fair:
        values.append(fair)
        parts.append(f"{metric} 밴드 중앙값 적정가 {fair:,.0f}")
    if consensus_target:
        values.append(consensus_target)
        parts.append(f"컨센서스 목표가 {consensus_target:,.0f}")
    # 현재가도 항상 한 표 — 단일 소스(멀티플 적정가)가 기준가를 지배해 ±35~60% 극단값을
    # 만들던 왜곡 완화(2026-06-11). 시장가는 가장 유동성 높은 가치 추정치다.
    if values and current:
        values.append(current)
        parts.append(f"현재가 {current:,.0f}")
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


GROUP_FALLBACK = {"005930": "ai_memory_hbm", "005380": "humanoid_robotics"}


def sector_values_from_history() -> dict[str, dict]:
    """v1.3 ⑤ — price_history 전 종목 거래대금으로 그룹별 연속 섹터값을 산출.

    sector_value = 0.7×heat + 0.3×rs (백테스트 그리드 최적 w_heat=0.7).
    heat: 거래대금 점유율(20d) ÷ 자기 120d 평균 점유율 — '자금이 평소보다 몰리는가'.
    rs: 그룹 중앙값 20d 초과수익(KOSPI 대비). 데이터 없으면 빈 dict(→ 사다리 폴백).
    """
    hist = load_json("state/price_history.json", {})
    tickers = hist.get("tickers") or {}
    idx_bars = {b["date"]: float(b["close"]) for b in (hist.get("index") or {}).get("bars") or []}
    if not tickers or not idx_bars:
        return {}
    dates = sorted(idx_bars)
    if len(dates) < 150:
        return {}

    groups: dict[str, list[str]] = {}
    series: dict[str, dict[str, dict]] = {}
    for t, v in tickers.items():
        g = v.get("group") or GROUP_FALLBACK.get(t)
        if not g:
            continue
        bars = {b["date"]: b for b in v.get("bars") or []}
        series[t] = bars
        groups.setdefault(g, []).append(t)
    groups = {g: ms for g, ms in groups.items() if len(ms) >= 2}

    def tv20(t: str, di: int) -> float:
        """di 시점 기준 최근 20거래일 평균 거래대금."""
        seg = []
        for d in dates[max(0, di - 19): di + 1]:
            b = series[t].get(d)
            if b and b.get("volume") and b.get("close"):
                seg.append(float(b["close"]) * float(b["volume"]))
        return sum(seg) / len(seg) if len(seg) >= 7 else 0.0

    last = len(dates) - 1
    # 그룹 점유율 시계열(최근 120일, 6일 간격 샘플) — 분모는 전 추적 그룹 합
    sample_idx = list(range(max(0, last - 120), last + 1, 6)) + [last]
    share_hist: dict[str, list[float]] = {g: [] for g in groups}
    for di in sample_idx:
        tot = sum(tv20(t, di) for ms in groups.values() for t in ms)
        if not tot:
            continue
        for g, ms in groups.items():
            share_hist[g].append(sum(tv20(t, di) for t in ms) / tot)

    out: dict[str, dict] = {}
    for g, ms in groups.items():
        sh = share_hist[g]
        if len(sh) < 5:
            continue
        cur_share, base = sh[-1], sum(sh[:-1]) / len(sh[:-1])
        conc_ratio = cur_share / base if base else 1.0
        heat = max(0.0, min(1.0, (conc_ratio - 0.8) / 0.8))
        ex20 = []
        d0, d1 = dates[last - 20], dates[last]
        for t in ms:
            b0, b1 = series[t].get(d0), series[t].get(d1)
            if b0 and b1:
                ex20.append(
                    (float(b1["close"]) / float(b0["close"]) - 1) * 100
                    - (idx_bars[d1] / idx_bars[d0] - 1) * 100
                )
        if not ex20:
            continue
        ex20.sort()
        med = ex20[len(ex20) // 2]
        rs = max(0.0, min(1.0, (med + 5.0) / 15.0))
        out[g] = {
            "sector_value": round(0.7 * heat + 0.3 * rs, 3),
            "heat": round(heat, 3), "rs": round(rs, 3),
            "conc_ratio": round(conc_ratio, 2), "median_excess_20d": round(med, 2),
            "members": ms, "as_of": d1,
        }
    return out


def ticker_group(ticker: str) -> str | None:
    hist = load_json("state/price_history.json", {})
    v = (hist.get("tickers") or {}).get(ticker) or {}
    return v.get("group") or GROUP_FALLBACK.get(ticker)


def news_premium(
    ticker: str, cfg: dict, events: list[dict], earnings_signal: str | None, today: date,
    realized_since: Any = None, auto_items: list[dict] | None = None,
    global_items: list[dict] | None = None, channel_transmission: dict | None = None,
) -> tuple[float, list[dict]]:
    """뉴스(과거: manual+auto+해외)+촉매(미래) 가산점 합산. (프리미엄 %, 기여 상세) 반환."""
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

    # v1.3 ⑥ 해외뉴스 — 채널 전이계수(실증 β 기반) × auto factor 할인. 유형당 최신 1건.
    trans = channel_transmission or {}
    g_latest: dict[str, dict] = {}
    for it in global_items or []:
        if not isinstance(it, dict) or not it.get("type") or not it.get("published"):
            continue
        if ticker not in (it.get("affects_tickers") or []):
            continue
        cur = g_latest.get(it["type"])
        if cur is None or it["published"] > (cur.get("published") or ""):
            g_latest[it["type"]] = it
    for ntype, it in sorted(g_latest.items()):
        d = _parse_date(it.get("published"))
        if d is None:
            continue
        days_since = (today - d).days
        if days_since < 0 or days_since > auto_max_age:
            continue
        decay = max(0.0, 1.0 - days_since / decay_days)
        base = _num(it.get("impact_pct")) or 0.0
        tcoef = float(trans.get(it.get("channel") or "", 0.0))
        eff = base * tcoef * auto_factor  # 유효 임팩트 상한(전이·자동 할인 후)
        c = eff * decay
        realized = realized_since(it["published"]) if realized_since else None
        if realized is not None:
            c = c - realized
            c = max(0.0, min(eff, c)) if eff >= 0 else min(0.0, max(eff, c))
        c = round(c, 2)
        if c == 0.0 and tcoef == 0.0:
            continue  # macro 등 전이 0 채널은 기여 없음 — 노이즈 제거
        total += c
        contribs.append({
            "kind": "news_global", "type": ntype, "date": it.get("published"),
            "impact_pct": base, "channel": it.get("channel"), "transmission": tcoef,
            "decay": round(decay, 2), "auto_factor": auto_factor,
            "realized_since_event_pct": realized, "contrib_pct": c,
            "note": it.get("title"), "source_url": it.get("url"),
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
    ticker: str, sector_rotation: list[dict], next_catalyst: dict | None, max_pct: float,
    sv: dict | None = None,
) -> tuple[float, str, dict | None]:
    """섹터 활발성 프리미엄 + '활발성이 언제 올지' 추정. (프리미엄 %, 예상 시점, 그룹 요약) 반환.

    v1.3 ⑤ — sv(연속 섹터값: 자금 집중도 0.7 + 상대모멘텀 0.3)가 있으면
    프리미엄 = max_pct × (0.5×사다리 + 0.5×sector_value) 블렌드. 없으면 사다리 단독.
    """
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
    if group is None and sv is None:
        return 0.0, "섹터 그룹 미매핑(universe.json 미등록)" + catalyst_note, None

    excess60 = _num(group.get("median_excess_60d")) if group else None
    met = int(group.get("met", 0) or 0) if group else 0
    min_sig = max(1, int(group.get("min_signals", 1) or 1)) if group else 1
    summary = {
        "group": (group.get("group") if group else None) or (sv or {}).get("group"),
        "median_excess_60d": excess60,
        "signals_met": met, "min_signals": min_sig,
        "immersion_met": bool(group.get("immersion_met")) if group else False,
        "sector_value": sv,
    }
    if excess60 is not None and excess60 >= 10.0:
        ladder, eta = 1.0, f"현재 활발 — 주도 섹터(KOSPI 대비 60일 +{excess60:.0f}%p)"
    elif group and group.get("immersion_met"):
        ladder, eta = 0.8, "몰입 신호 충족 — 약 1~2개월 내 본격화 추정"
    elif met > 0:
        ladder, eta = 0.5, f"부분 몰입({met}/{min_sig}) — 약 2~4개월 내 회복 가능성"
    else:
        ladder, eta = 0.0, "휴면 — 자금 발자국 없음" + catalyst_note

    if sv and isinstance(sv.get("sector_value"), (int, float)):
        blended = 0.5 * ladder + 0.5 * float(sv["sector_value"])
        eta += f" · 섹터값 {sv['sector_value']:.2f}(집중도 평소 {sv.get('conc_ratio', '?')}배·heat {sv.get('heat')})"
        return round(max_pct * blended, 2), eta, summary
    return round(max_pct * ladder, 2), eta, summary


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


def build_news_target_line(r: dict) -> str:
    """리포트 종목 카드에 그대로 넣는 '뉴스 반영 추정 목표 매도가' 한 줄.

    추정 목표가 + 상승여력 + 직전 리포트 대비 델타(▲/▼) + 이번에 새로 반영된 원인 뉴스.
    """
    if not r.get("estimate"):
        return f"뉴스 반영 추정 목표가: — (기준가 산출 불가 — {r.get('anchor_basis', '')})"
    up = f"{r['expected_return_pct']:+.1f}%" if r.get("expected_return_pct") is not None else "—"
    p = r.get("premium_pct", {})
    cap = "(캡)" if abs(_num(p.get("news")) or 0) >= 12.0 else ""
    parts = [f"뉴스 반영 추정 목표 매도가 **{r['estimate']:,.0f}원**({up}, 등급 {r['grade']})"]
    d = r.get("delta_vs_prev") or {}
    dv = d.get("estimate_delta_krw")
    if dv:
        parts.append(f"직전 리포트 대비 {'▲' if dv > 0 else '▼'}{abs(dv):,.0f}원")
    elif d:
        parts.append("직전 대비 변동 없음")
    parts.append(
        f"프리미엄 테마{p.get('theme', 0):+.0f}/뉴스{p.get('news', 0):+.0f}{cap}/"
        f"섹터{p.get('sector', 0):+.0f}/모멘텀{p.get('momentum', 0):+.0f}%"
    )
    nn = r.get("new_news_since_prev") or []
    if nn:
        kind_label = {"news_auto": "자동", "news_global": "해외", "catalyst": "촉매"}
        top = sorted(nn, key=lambda x: abs(_num(x.get("contrib_pct")) or 0), reverse=True)[:2]
        causes = "; ".join(
            f"{x.get('type')}{('(' + kind_label[x['kind']] + ')') if x.get('kind') in kind_label else ''} "
            f"{_num(x.get('contrib_pct')):+.1f}%"
            for x in top
        )
        parts.append(f"📰 원인 뉴스: {causes}")
    return " · ".join(parts)


def stop_pct_fraction(atr_pct: float | None, policy: dict) -> tuple[float, str]:
    """신규 진입의 동적 손절폭(진입가 대비 분수)·basis. ATR 우선, 결측 시 정책 고정 손절%.

    policy.risk.volatility_sizing.atr_stop_multiple(2.0) × ATR% 를 3%~hard_floor(20%)로 클램프.
    """
    risk = policy.get("risk", {}) if isinstance(policy, dict) else {}
    vs = risk.get("volatility_sizing", {}) if isinstance(risk.get("volatility_sizing"), dict) else {}
    mult = float(vs.get("atr_stop_multiple", 2.0))
    fixed = abs(float(risk.get("stop_loss_pct", -10.0)))
    hard = abs(float((risk.get("tiered_alerts") or {}).get("atr_threshold_hard_floor_pct", -20.0)))
    if atr_pct and atr_pct > 0:
        sp = max(3.0, min(hard, mult * atr_pct))
        return sp / 100.0, f"ATR {atr_pct:.1f}%×{mult:.0f}≈손절 {sp:.1f}%"
    return fixed / 100.0, f"고정 손절 {fixed:.0f}%(ATR 결측)"


def regime_min_rr(tier: str | None, policy: dict) -> tuple[float, str]:
    """레짐 tier 별 신규 진입 R/R 하한(reward_risk_management.regime_adaptive_rr). 결측 시 fallback."""
    rr = (policy.get("reward_risk_management", {}) or {}).get("regime_adaptive_rr", {}) or {}
    by_tier = rr.get("min_rr_by_tier") or {}
    if tier and tier in by_tier:
        return float(by_tier[tier]), tier
    return float(rr.get("fallback_min_rr", 1.2)), f"{tier or 'unknown'}→fallback"


def entry_cap_price(estimate: float | None, min_rr: float, stop_frac: float) -> float | None:
    """뉴스 반영 목표가에서 R/R≥min_rr 를 확보하는 신규진입 상한가.

    적정가치(intrinsic value)가 아니라 리스크관리 산물 — '지금 새로 들어가도 손익비 하한이
    나오는 최대 진입가'다. R/R = (목표−진입)/(진입−손절), 손절 = 진입×(1−stop_frac) →
    진입 = 목표 / (1 + min_rr×stop_frac). 진입을 이 값 이하로 잡으면 R/R 하한이 충족된다
    (목표가가 뉴스로 오르면 상한가도 따라 오른다). 현재가보다 낮게 나오면 '상승여력 <
    R/R하한×손절폭' = 신규 진입엔 업사이드가 얇다는 신호(R/R 부족)일 뿐, 고평가 판정이 아니다.
    """
    if not estimate or stop_frac <= 0:
        return None
    return round(estimate / (1.0 + min_rr * stop_frac), -2)


def build_entry_cap_line(r: dict) -> str:
    """리포트에 넣는 '뉴스 반영 신규진입 상한가' 한 줄 — R/R 진입 상한 + 현재가 위치 + 직전 델타."""
    fb = r.get("entry_cap_price")
    cur = r.get("current_price")
    if not fb:
        note = r.get("entry_cap_note")
        return f"뉴스 반영 신규진입 상한가: — ({note})" if note else "뉴스 반영 신규진입 상한가: — (목표가 추정 불가)"
    basis = r.get("entry_cap_basis") or {}
    parts = [f"뉴스 반영 신규진입 상한가 **{fb:,.0f}원**(R/R≥{basis.get('min_rr')}·{basis.get('stop_basis', '')} 기준)"]
    if cur:
        gap = (fb / cur - 1.0) * 100.0  # +면 상한가가 현재가보다 높음 = 현재가가 진입 가능 구간
        if cur <= fb:
            parts.append(f"현재가 {cur:,.0f}원 🟢진입 가능(현재가가 상한가보다 {gap:.1f}% 낮음)")
        else:
            parts.append(f"현재가 {cur:,.0f}원 🔴신규 진입 매력 낮음(상승여력<R/R×손절 — 상한가 {-gap:.1f}% 상회)")
    fbd = (r.get("delta_vs_prev") or {}).get("entry_cap_delta_krw")
    if fbd:
        parts.append(f"직전 리포트 대비 {'▲' if fbd > 0 else '▼'}{abs(fbd):,.0f}원")
    return " · ".join(parts)


def build_report_section(rows: list[dict], as_of: str) -> str:
    lines = [
        "### 📰 뉴스 반영 매매가(목표 매도가·신규진입 상한가) 추정 (estimate_target_price v1.5 — 직전 리포트 대비 변동)",
        "",
        f"- 기준 시각: {as_of} · 추정 호라이즌 12개월 · 학습·시뮬레이션 목적(투자 권유 아님)",
        "- 식: 목표 매도가 = 기준가(밸류밴드·컨센) × (1 + 테마+뉴스/촉매+섹터+모멘텀) → 천장 캡. 신규진입 상한가 = 목표가 / (1 + 레짐 R/R하한 × 손절%).",
        "- ※ **참고 레이어**다 — watchlist 의 실제 목표가·매도/매수 트리거를 자동 대체하지 않는다(이중출처 혼란 방지). 신규진입 상한가는 신규 진입 기준(보유분 평단은 고정)이며 적정가치가 아니라 R/R 진입 상한이다.",
        "",
        "| 종목 | 현재가 | 신규진입 상한가 | 추정 목표 매도가 | 상승여력 | Δ목표(직전) | 위치 | 등급 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cur_v = r.get("current_price")
        cur = f"{cur_v:,.0f}" if cur_v else "—"
        fb = r.get("entry_cap_price")
        buy = f"{fb:,.0f}" if fb else "—"
        est = f"{r['estimate']:,.0f}" if r.get("estimate") else "—"
        up = f"{r['expected_return_pct']:+.1f}%" if r.get("expected_return_pct") is not None else "—"
        d = r.get("delta_vs_prev") or {}
        dv = d.get("estimate_delta_krw")
        delta_cell = f"{'▲' if dv > 0 else '▼'}{abs(dv):,.0f}" if dv else ("0" if d else "신규")
        if fb and cur_v:
            pos = "🟢진입가능" if cur_v <= fb else f"🔴+{(cur_v / fb - 1) * 100:.0f}% 상회"
        else:
            pos = "—"
        lines.append(
            f"| {r['name']}({r['ticker']}) | {cur} | {buy} | {est} | {up} | {delta_cell} | {pos} | {r['grade']} |"
        )
    # 직전 리포트 대비 '새 뉴스가 목표가를 움직인' 종목 — 매도 목표가 변동 풀이.
    changed = [
        r for r in rows
        if (r.get("new_news_since_prev") or (r.get("delta_vs_prev") or {}).get("estimate_delta_krw"))
    ]
    if changed:
        lines += ["", "**뉴스에 따른 목표 매도가 변동(직전 리포트 대비):**"]
        for r in changed:
            lines.append(f"- {build_news_target_line(r)}")
    # 신규진입 상한가 — 현재가 ≤ 상한가(진입 가능)이거나 상한가가 직전 대비 변한 종목.
    buy_rows = [
        r for r in rows
        if r.get("entry_cap_price") and (r.get("in_buy_zone") or (r.get("delta_vs_prev") or {}).get("entry_cap_delta_krw"))
    ]
    if buy_rows:
        lines += ["", "**신규진입 상한가(현재가 위치):**"]
        for r in buy_rows:
            lines.append(f"- {r['name']}({r['ticker']}) — {build_entry_cap_line(r)}")
    lines += [
        "",
        "> 등급: 가용 데이터 레이어 수 기준 A(5+)/B(3~4)/C(2-). C 등급은 기준가가 현재가 폴백이라 거친 추정.",
        "> 뉴스 프리미엄이 ±12%(캡)에 걸리면 추가 호재가 목표가에 더 실리지 않는다. 자동분류(자동) 뉴스는 0.6 할인·미검증.",
        "> 신규진입 상한가 = 목표가/(1+R/R하한×손절%) — 적정가치가 아니라 R/R 진입 상한(차단 게이트 아님, 진입 타이밍 참고)이다. 현재가보다 낮으면 '신규 진입엔 업사이드가 얇다'는 신호(R/R 부족·변동성 큰 종목일수록 손절폭이 넓어 더 낮게 나옴)이지 고평가 판정이 아니다. 앵커가 현재가 폴백인 종목은 상한가를 보류(—)한다. 목표가가 뉴스로 오르면 상한가도 같이 오른다(신규 진입 기준, 보유 평단은 불변).",
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
    regime_tier = (snapshot.get("regime") or {}).get("tier")  # v1.5 신규진입 상한가 R/R 하한 조회용
    policy = load_json("config/policy.json", {})
    consensus = load_json("state/consensus.json", {}).get("tickers", {})
    fundamentals = load_json("state/fundamentals.json", {}).get("tickers", {})
    val_checks = load_json("state/valuation_check.json", {}).get("tickers", {})
    sector_rotation = load_json("state/universe_screen.json", {}).get("sector_rotation", [])
    feed_all = load_json("state/news_feed.json", {})
    news_feed = feed_all.get("tickers", {})
    global_news = feed_all.get("global", [])
    channel_transmission = (
        load_json("config/news_keywords.json", {}).get("global_news", {}).get("channel_transmission", {})
    )
    sector_values = sector_values_from_history()  # v1.3 ⑤ — 그룹별 연속 섹터값(없으면 빈 dict)

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
            global_items=global_news, channel_transmission=channel_transmission,
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
        grp = ticker_group(ticker)
        sv = sector_values.get(grp) if grp else None
        if sv is not None:
            sv = {**sv, "group": grp}
        sector_pct, sector_eta, sector_summary = sector_activity(
            ticker, sector_rotation, next_cat, max_sector_pct, sv=sv
        )
        pct52 = _num(mom.get("pct_of_52w_high")) if isinstance(mom, dict) else None
        tilt_pct = momentum_tilt(excess60, pct52)

        total_premium_pct = round(theme_pct + news_pct + sector_pct + tilt_pct, 2)
        raw_estimate = anchor * (1.0 + total_premium_pct / 100.0) if anchor else None

        # 천장 캡 — policy.valuation_anchor 와 동일 위계. 결측 항은 캡을 만들지 않는다.
        caps: list[tuple[str, float]] = []
        if cons_target:
            caps.append(("컨센서스×1.15", cons_target * 1.15))
        # 천장이 현재가 이하면 캡 무효 — 랠리 종목에서 근사 밴드(가격분포 퍼센타일)의 상단이
        # 현재가 아래로 내려와 추정가를 시장가 밑으로 끌어내리는 왜곡 방지. 이때는
        # 밸류 가드 verdict(overheat_entry)가 별도로 경고를 담당한다.
        ceiling = _num((val_checks.get(ticker) or {}).get("valuation_ceiling_price"))
        if ceiling and (not current or ceiling > current):
            caps.append(("밸류에이션 천장", ceiling))
        estimate = raw_estimate
        cap_applied = None
        if estimate is not None:
            for label, cap_v in caps:
                if cap_v < estimate:
                    estimate, cap_applied = cap_v, label
            estimate = round(estimate, -2)  # 호가 단순화: 100원 단위

        expected_return = round((estimate / current - 1.0) * 100.0, 1) if estimate and current else None

        # v1.5 — 신규진입 상한가: 뉴스 반영 목표가에서 레짐 R/R 하한을 확보하는 진입 상한(신규 진입 기준).
        atr_pct = _num((ts.get("volatility") or {}).get("atr_pct"))
        stop_frac, stop_basis = stop_pct_fraction(atr_pct, policy)
        min_rr, rr_tier = regime_min_rr(regime_tier, policy)
        # v1.6 — 앵커가 현재가 폴백(밸류밴드·컨센 둘 다 결측)이면 상한가 = 현재가×(1+프리미엄)/(1+R/R×손절)
        # 로 퇴화해 '현재가에서 손절폭만 깎은 값'이 된다(정보량 0인데 현재가 대비 −10~−17% 표시가
        # 고평가로 오해됨). 이런 종목은 상한가를 보류한다 — 목표 매도가는 프리미엄 신호가 있어 유지.
        entry_cap_note = None
        if not anchor_uses_band and not cons_target:
            entry_cap = None
            entry_cap_note = "밸류·컨센 미시드(앵커=현재가 폴백) — R/R 상한가 보류, sunday_strategy 시드 필요"
        else:
            entry_cap = entry_cap_price(estimate, min_rr, stop_frac)
        in_buy_zone = current is not None and entry_cap is not None and current <= entry_cap
        entry_cap_gap_pct = round((entry_cap / current - 1.0) * 100.0, 1) if entry_cap and current else None

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
            "entry_cap_price": entry_cap,
            "entry_cap_basis": {
                "min_rr": min_rr, "min_rr_tier": rr_tier,
                "stop_frac_pct": round(stop_frac * 100, 1), "stop_basis": stop_basis,
                "formula": "목표가 / (1 + min_rr × 손절%)",
            },
            "in_buy_zone": in_buy_zone,
            "entry_cap_gap_pct": entry_cap_gap_pct,
            "entry_cap_note": entry_cap_note,
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

    # v1.4 델타 — 직전 리포트(로그 마지막 행) 대비 추정목표가·뉴스 프리미엄 변동 + '직전 이후 새/변경 뉴스'.
    # 같은 날 여러 routine 이 돌면 직전 행=직전 슬롯이므로 '리포트마다 변경값'이 자연히 산출된다.
    prev_map = previous_estimates()
    for r in results:
        prev = prev_map.get(r["ticker"])
        np_now = r["detail"]["news_parts"] or []
        prev_news = {
            (n.get("kind"), n.get("type"), n.get("date")): n.get("contrib_pct")
            for n in (prev.get("news") or [])
        } if prev else {}
        new_news = [
            n for n in np_now
            if abs(_num(n.get("contrib_pct")) or 0) >= 0.01
            and (not prev or prev_news.get((n.get("kind"), n.get("type"), n.get("date"))) != n.get("contrib_pct"))
        ]
        delta = None
        if prev:
            de = (
                r["estimate"] - prev["estimate"]
                if r.get("estimate") is not None and prev.get("estimate") is not None else None
            )
            pn_now, pn_prev = _num(r["premium_pct"].get("news")), _num((prev.get("premium_pct") or {}).get("news"))
            er_now, er_prev = _num(r.get("expected_return_pct")), _num(prev.get("expected_return_pct"))
            # prev 는 직전 로그행 — rename 이전 행은 fair_buy_price 키라 둘 다 조회(1회 전환 호환).
            fb_now = _num(r.get("entry_cap_price"))
            fb_prev = _num(prev.get("entry_cap_price")) or _num(prev.get("fair_buy_price"))
            delta = {
                "prev_estimate": prev.get("estimate"),
                "prev_as_of": prev.get("_as_of"),
                "estimate_delta_krw": round(de, -2) if de is not None else None,
                "entry_cap_delta_krw": round(fb_now - fb_prev, -2) if fb_now is not None and fb_prev is not None else None,
                "news_pct_delta": round(pn_now - pn_prev, 2) if pn_now is not None and pn_prev is not None else None,
                "expected_return_delta_pct": round(er_now - er_prev, 1) if er_now is not None and er_prev is not None else None,
            }
        r["delta_vs_prev"] = delta
        r["new_news_since_prev"] = [
            {"kind": n.get("kind"), "type": n.get("type"), "date": n.get("date"),
             "contrib_pct": n.get("contrib_pct"), "note": n.get("note"), "source_url": n.get("source_url")}
            for n in new_news
        ]
        r["news_target_line"] = build_news_target_line(r)
        r["entry_cap_line"] = build_entry_cap_line(r)

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

    # v1.4 — 추정 스냅샷 로그(jsonl 누적). score_target_estimates.py 가 '추정 vs 실현' 주간
    # 채점에 사용한다. 하루 여러 번 실행돼도 행만 쌓이고, 채점기는 날짜별 마지막 행을 쓴다.
    log_rec = {
        "as_of": as_of,
        "date": as_of[:10],
        "model": "v1.5",
        "estimates": [
            {
                "ticker": r["ticker"], "name": r["name"],
                "current_price": r["current_price"], "estimate": r["estimate"],
                "entry_cap_price": r["entry_cap_price"],
                "expected_return_pct": r["expected_return_pct"],
                "premium_pct": r["premium_pct"], "grade": r["grade"],
                "trend_gate": (r.get("trend_gate") or {}).get("factor"),
                # v1.4 — 뉴스 지문(다음 실행이 '새/변경 뉴스'를 정확히 diff 하는 근거).
                "news": [
                    {"kind": n.get("kind"), "type": n.get("type"),
                     "date": n.get("date"), "contrib_pct": n.get("contrib_pct")}
                    for n in (r["detail"]["news_parts"] or [])
                ],
            }
            for r in results
        ],
    }
    log_path = ROOT / "state" / "target_estimate_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_rec, ensure_ascii=False) + "\n")
    graded = {g: sum(1 for r in results if r["grade"] == g) for g in ("A", "B", "C")}
    print(f"wrote {OUT_PATH.relative_to(ROOT)} estimates={len(results)} grades={graded}")
    for r in results:
        est = f"{r['estimate']:,.0f}" if r.get("estimate") else "—"
        up = f"{r['expected_return_pct']:+.1f}%" if r.get("expected_return_pct") is not None else "—"
        print(f"  [{r['grade']}] {r['name']}({r['ticker']}): est {est} ({up}) premium {r['premium_pct']['total']:+.1f}% — {r['sector_activation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
