#!/usr/bin/env python3
"""약세장 스트레스 백테스트 — 전략의 '하방 회피' 엣지를 검증한다.

문제: state/price_history.json 은 합성 강세장(KOSPI +198%)이라 약세장 검증이 비어 있다
(docs/strategy_momentum.md 가 인정한 핵심 공백). 403 차단으로 실제 2022 하락장 수집도 불가.

해법(정직한 합성 스트레스): 실데이터의 일간 로그수익률에 '시장 드리프트'만 음(-)으로 더해
약세장 경로를 만든다. 모든 종목·지수에 같은 δ 를 더하므로 **상대강도·변동성·상관 구조는
그대로 보존**되고 절대수익·추세(MA200)만 하락장으로 바뀐다 → "추세필터(가격>MA200)와
절대모멘텀>0 게이트가 약세장에서 현금으로 빠져 자본을 지키는가"를 깨끗이 격리 검증한다.

시나리오:
  - bear_40     : 구간 총 -40% 의 지속 하락장
  - mild_bear_20: 구간 총 -20% 의 완만한 하락장
  - crash       : 중반 ~30거래일에 -35% 급락 주입(나머지 구간은 원본)
  - sideways    : 드리프트 0 + 변동성 ×1.4 (휩쏘 — 모멘텀의 약점 구간)
  - reverse     : 시계열 역전(강세장의 거울상 = 구조적 약세장)

각 시나리오에서 비교: KOSPI buy&hold vs 전략(레짐필터 ON) vs 전략(레짐 OFF=현 권장값).
핵심 질문 — 약세장에선 regime_filter 가 자본을 지키는가(강세장에선 수익을 깎았던 그 필터)?

산출: state/backtest_bear.json + 표준출력. 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_strategy import (  # noqa: E402
    backtest,
    benchmark_curve,
    load_history,
    metrics,
)


def _series_to_pricelist(series: dict, dates: list[str]) -> list[float | None]:
    """공통 날짜축 기준 가격 리스트(결측은 None)."""
    return [series.get(d) for d in dates]


def _rebuild(prices: list[float | None], new_logret: list[float | None], dates: list[str]) -> dict:
    """첫 유효가에서 시작해 조정된 로그수익률로 가격을 재구성 → {date: price}."""
    out: dict[str, float] = {}
    base = None
    prev = None
    for i, d in enumerate(dates):
        p = prices[i]
        if p is None:
            continue
        if base is None:
            base = p
            prev = p
            out[d] = p
            continue
        lr = new_logret[i]
        if lr is None:
            prev = p
            out[d] = prev  # 수익률 결측 → 보합
            continue
        prev = prev * math.exp(lr)
        out[d] = prev
    return out


def _logrets(prices: list[float | None]) -> list[float | None]:
    """인접 유효가 간 로그수익률(없으면 None). prices[i] 위치에 'i-1→i' 수익률."""
    out: list[float | None] = [None] * len(prices)
    last = None
    for i, p in enumerate(prices):
        if p is None or p <= 0:
            continue
        if last is not None and last > 0:
            out[i] = math.log(p / last)
        last = p
    return out


def _n_steps(logrets: list[float | None]) -> int:
    return sum(1 for r in logrets if r is not None)


def transform(tickers: dict, index_series: dict, dates: list[str], mode: str) -> tuple[dict, dict]:
    """시장 드리프트를 변형해 약세장 시나리오 시계열을 만든다(상대구조 보존)."""
    idx_prices = _series_to_pricelist(index_series, dates)
    idx_lr = _logrets(idx_prices)
    steps = _n_steps(idx_lr)
    orig_idx_log = sum(r for r in idx_lr if r is not None)  # 원본 지수 총 로그수익

    # 모드별 '추가 일간 드리프트 δ' 와 변동성 배수 결정
    delta = 0.0
    vol_factor = 1.0
    crash_window = None
    reverse = False
    if mode == "bear_40":
        target_log = math.log(1 - 0.40)
        delta = (target_log - orig_idx_log) / steps
    elif mode == "mild_bear_20":
        target_log = math.log(1 - 0.20)
        delta = (target_log - orig_idx_log) / steps
    elif mode == "sideways":
        target_log = math.log(1 + 0.0)  # 0
        delta = (target_log - orig_idx_log) / steps
        vol_factor = 1.4
    elif mode == "crash":
        # 중반 30거래일에 누적 -35% 주입. 나머지는 원본 드리프트.
        valid_idx = [i for i, r in enumerate(idx_lr) if r is not None]
        mid = len(valid_idx) // 2
        win = set(valid_idx[max(0, mid - 15): mid + 15])
        crash_window = win
        crash_delta = math.log(1 - 0.35) / max(1, len(win))
    elif mode == "reverse":
        reverse = True
    else:
        raise ValueError(f"unknown mode {mode}")

    def apply(prices: list[float | None]) -> dict:
        lr = _logrets(prices)
        if reverse:
            # 유효 수익률 시퀀스를 역전(거울상 약세장). 위치는 유지하되 값만 뒤집어 매핑.
            vals = [r for r in lr if r is not None]
            vals = [-v for v in reversed(vals)]
            it = iter(vals)
            new = [next(it) if r is not None else None for r in lr]
            return _rebuild(prices, new, dates)
        new: list[float | None] = []
        # 변동성 배수용 평균(유효분)
        mean_lr = (sum(r for r in lr if r is not None) / max(1, _n_steps(lr))) if vol_factor != 1.0 else 0.0
        for i, r in enumerate(lr):
            if r is None:
                new.append(None)
                continue
            if crash_window is not None:
                new.append(r + (crash_delta if i in crash_window else 0.0))
            elif vol_factor != 1.0:
                new.append(mean_lr + vol_factor * (r - mean_lr) + delta)
            else:
                new.append(r + delta)
        return _rebuild(prices, new, dates)

    new_index = apply(idx_prices)
    new_tickers = {}
    for tk, v in tickers.items():
        new_tickers[tk] = {"name": v["name"], "series": apply(_series_to_pricelist(v["series"], dates))}
    return new_tickers, new_index


def run_scenario(tickers, index_series, dates, mode):
    n = len(dates)
    warmup, end = 201, n - 1
    t2, idx2 = transform(tickers, index_series, dates, mode)
    bench = metrics(benchmark_curve(idx2, dates, warmup, end))

    # 현 권장값(레짐 OFF) vs 레짐 ON — 약세장에서 필터의 가치 검증
    cfg_off = dict(top_n=6, rebal_days=42, use_index_regime=False, trend_ma=200, mom_fast=60, mom_slow=120)
    cfg_on = dict(top_n=6, rebal_days=42, use_index_regime=True, trend_ma=200, mom_fast=60, mom_slow=120)
    c_off, _, tr_off = backtest(t2, idx2, dates, start_idx=warmup, end_idx=end, **cfg_off)
    c_on, _, tr_on = backtest(t2, idx2, dates, start_idx=warmup, end_idx=end, **cfg_on)
    m_off, m_on = metrics(c_off), metrics(c_on)
    m_off["n_trades"], m_on["n_trades"] = tr_off, tr_on
    return {"benchmark_kospi": bench, "strategy_regime_off": m_off, "strategy_regime_on": m_on}


def main():
    tickers, index_series, dates = load_history()
    print(f"원본 데이터: {len(tickers)}종목 × {len(dates)}거래일 ({dates[0]}~{dates[-1]})")
    print("약세장은 실데이터에 시장 드리프트만 음(-)으로 합성 — 상대강도·변동성 구조 보존.\n")

    scenarios = {
        "bear_40": "지속 약세 -40%",
        "mild_bear_20": "완만 약세 -20%",
        "crash": "중반 급락 -35%(30일)",
        "sideways": "횡보+휩쏘(드리프트0·변동성×1.4)",
        "reverse": "시계열 역전(강세장 거울상)",
    }
    out_scen = {}
    print(f"{'시나리오':<22}{'벤치(B&H)':>14}{'전략 레짐OFF':>20}{'전략 레짐ON':>20}")
    print("-" * 78)
    for mode, label in scenarios.items():
        r = run_scenario(tickers, index_series, dates, mode)
        out_scen[mode] = {"label": label, **r}
        b, off, on = r["benchmark_kospi"], r["strategy_regime_off"], r["strategy_regime_on"]
        print(f"{label:<22}"
              f"{b['total_return_pct']:>7.0f}%/MDD{b['max_drawdown_pct']:>5.0f}"
              f"{off['total_return_pct']:>9.0f}%/MDD{off['max_drawdown_pct']:>5.0f}"
              f"{on['total_return_pct']:>9.0f}%/MDD{on['max_drawdown_pct']:>5.0f}")

    # 핵심 판정: 약세장에서 전략(레짐ON)이 buy&hold 대비 MDD 를 얼마나 줄였나
    findings = []
    for mode, label in scenarios.items():
        b = out_scen[mode]["benchmark_kospi"]
        on = out_scen[mode]["strategy_regime_on"]
        off = out_scen[mode]["strategy_regime_off"]
        mdd_cut = round(on["max_drawdown_pct"] - b["max_drawdown_pct"], 1)  # 양수면 낙폭 더 작음(개선)
        ret_edge = round(on["total_return_pct"] - b["total_return_pct"], 1)
        regime_value = round(on["total_return_pct"] - off["total_return_pct"], 1)  # ON-OFF: 약세장 필터 가치
        findings.append({
            "scenario": mode, "label": label,
            "mdd_improvement_vs_bench_pp": mdd_cut,
            "return_edge_vs_bench_pp": ret_edge,
            "regime_filter_value_on_minus_off_pp": regime_value,
        })

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "method": "실데이터 일간 로그수익률에 시장 드리프트 δ 합성(상대강도·변동성 보존). 합성 스트레스 — 실제 약세장 아님.",
        "data_window": {"start": dates[0], "end": dates[-1], "trading_days": len(dates)},
        "config": {"top_n": 6, "rebal_days": 42, "trend_ma": 200, "mom_fast": 60, "mom_slow": 120,
                   "compared": "regime_filter ON vs OFF(현 권장값)"},
        "scenarios": out_scen,
        "findings": findings,
        "interpretation": [
            "regime_filter_value(ON-OFF) 가 약세장에서 (+)면 → 강세장에서 수익을 깎던 레짐필터가 약세장에선 자본을 지킴 → '레짐 상태에 따라 필터 ON/OFF' 동적 전환이 정답.",
            "mdd_improvement_vs_bench 가 (+)면 추세필터(가격>MA200)가 buy&hold 대비 낙폭을 줄임 = '하방 회피' 엣지 실재.",
            "sideways(휩쏘)에서 전략이 벤치보다 나쁘면 → 모멘텀의 알려진 약점(저변동·무추세 구간) 재확인 → 횡보장 진입 억제 룰 필요.",
        ],
        "note": "학습·시뮬레이션. 합성 약세장은 실제 약세장의 상관·점프·유동성 고갈을 완전히 재현하지 못한다(보수적 하한 추정).",
    }
    (ROOT / "state" / "backtest_bear.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 핵심 판정 (낙폭개선·초과수익·레짐필터가치, 모두 %p) ===")
    for f in findings:
        print(f"  {f['label']:<22} 낙폭개선 {f['mdd_improvement_vs_bench_pp']:+5.1f} | "
              f"초과수익 {f['return_edge_vs_bench_pp']:+6.1f} | 레짐필터가치(ON-OFF) {f['regime_filter_value_on_minus_off_pp']:+6.1f}")
    print(f"\n저장: state/backtest_bear.json")


if __name__ == "__main__":
    main()
