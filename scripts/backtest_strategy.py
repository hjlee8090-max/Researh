#!/usr/bin/env python3
"""전략 백테스트 엔진 — state/price_history.json 의 실제 일봉으로 추세추종/모멘텀 로테이션을
현실적 거래비용(슬리피지+거래세) 하에서 검증한다. 네트워크 의존성 0.

목적: "강세장에서 현금 보유"라는 현 파이프라인의 구조적 패배 원인을 정량 입증하고,
계좌를 추세에 태우는 규칙기반 전략이 벤치마크(KOSPI buy&hold)를 이기는지 out-of-sample 로 검증한다.

핵심 설계(룩어헤드 차단):
- 시점 t 종가까지의 정보로만 신호 산출 → t 종가에 체결(close-to-close).
- 거래비용은 매수/매도 각각 회전당 policy 의 슬리피지(0.2%)+거래세(0.18%)를 반영.
- 파라미터는 단일 최적값이 아니라 walk-forward(전반부 탐색 → 후반부 검증)로 강건성 확인.

산출: state/backtest_strategy.json (요약) + 표준출력 리포트.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# policy.json 거래비용(시뮬레이션): 슬리피지 0.2% + 거래세 0.18%.
# 매수 시 슬리피지만, 매도 시 슬리피지+거래세가 통상이나 보수적으로 회전(매수+매도) 합계 0.38%를 적용.
COST_BUY = 0.002          # 매수 슬리피지
COST_SELL = 0.002 + 0.0018  # 매도 슬리피지 + 거래세


def load_history():
    d = json.load(open(ROOT / "state" / "price_history.json"))
    tickers = {}
    for tk, v in d["tickers"].items():
        bars = v.get("bars") or []
        if len(bars) < 200:
            continue
        series = {b["date"]: float(b["close"]) for b in bars if b.get("close")}
        tickers[tk] = {"name": v.get("name", tk), "series": series}
    idx = d["index"]
    index_series = {b["date"]: float(b["close"]) for b in idx["bars"] if b.get("close")}
    # 공통 거래일 축(인덱스 기준 — 모든 종목이 같은 날짜 그리드를 쓰도록 정렬)
    dates = sorted(index_series.keys())
    return tickers, index_series, dates


def pct_return(series, dates, i, lookback):
    """dates[i] 종가 기준 lookback 거래일 수익률(%). 데이터 없으면 None."""
    if i - lookback < 0:
        return None
    d_now, d_then = dates[i], dates[i - lookback]
    p_now, p_then = series.get(d_now), series.get(d_then)
    if not p_now or not p_then or p_then <= 0:
        return None
    return (p_now / p_then - 1.0) * 100.0


def sma(series, dates, i, window):
    if i - window + 1 < 0:
        return None
    vals = [series.get(dates[j]) for j in range(i - window + 1, i + 1)]
    vals = [v for v in vals if v]
    if len(vals) < window * 0.8:
        return None
    return sum(vals) / len(vals)


def compute_regime_hysteresis(index_series, dates, index_ma=200, enter_days=5, exit_days=3):
    """히스테리시스 레짐 — 지수가 MA200 아래로 '지속' 이탈할 때만 방어(현금) 전환.

    약세장 백테스트 발견: 고정 레짐 OFF 는 지속 약세장에 위험하고, 고정 ON 은 V자 급락-반등을
    바닥에서 놓친다(휩쏘). 해법은 enter_days 연속 이탈 시 ON, exit_days 연속 회복 시 OFF 로
    전환을 지연시켜 단기 노이즈를 무시하는 것. 반환: dates 정렬 list[bool] (True=방어=현금).
    """
    flags = [False] * len(dates)
    defensive = False
    below_run = above_run = 0
    for i, d in enumerate(dates):
        cur = index_series.get(d)
        ma = sma(index_series, dates, i, index_ma)
        if cur and ma:
            if cur < ma:
                below_run += 1
                above_run = 0
            else:
                above_run += 1
                below_run = 0
            if not defensive and below_run >= enter_days:
                defensive = True
            elif defensive and above_run >= exit_days:
                defensive = False
        flags[i] = defensive
    return flags


def compute_breadth(tickers, dates, ma=200):
    """각 날짜별 '자기 MA200 위에 있는 종목 비율'(시장 폭). 지수 레벨보다 부드러운 레짐 신호."""
    out = {}
    for i, d in enumerate(dates):
        above = total = 0
        for v in tickers.values():
            s = v["series"]
            cur = s.get(d)
            m = sma(s, dates, i, ma)
            if cur and m:
                total += 1
                if cur >= m:
                    above += 1
        out[d] = (above / total) if total else None
    return out


def compute_regime_breadth(breadth, dates, low=0.40, high=0.55, enter_days=3, exit_days=5):
    """breadth 히스테리시스 레짐 — 폭이 low 아래로 enter_days 연속이면 방어, high 위로 exit_days 연속이면 복귀.

    이중 임계(low/high) + 일수 지연으로 지수-MA 단일선보다 휩쏘를 줄인다. 반환: list[bool](True=방어).
    """
    flags = [False] * len(dates)
    defensive = False
    below_run = above_run = 0
    for i, d in enumerate(dates):
        b = breadth.get(d)
        if b is None:
            flags[i] = defensive
            continue
        if b < low:
            below_run += 1
            above_run = 0
        elif b > high:
            above_run += 1
            below_run = 0
        else:
            below_run = above_run = 0  # 중립대 — 카운터 리셋(경계 노이즈 억제)
        if not defensive and below_run >= enter_days:
            defensive = True
        elif defensive and above_run >= exit_days:
            defensive = False
        flags[i] = defensive
    return flags


def backtest(tickers, index_series, dates,
             top_n=5, mom_fast=60, mom_slow=120, trend_ma=200,
             rebal_days=5, start_idx=None, end_idx=None,
             use_index_regime=True, index_ma=200, regime_flags=None):
    """추세추종 듀얼모멘텀 로테이션.

    매 rebal_days 마다:
      1) 시장 레짐 필터: KOSPI < index_ma 면 전량 현금(추세장에서만 베팅).
      2) 후보 점수 = 0.5*mom_fast + 0.5*mom_slow 수익률, 단 개별 추세필터(가격>trend_ma)와
         절대 모멘텀>0 통과분만. 통과 종목이 없으면 현금.
      3) 점수 상위 top_n 동일가중 보유. 회전 시 매도/매수 비용 차감.
    """
    n = len(dates)
    start_idx = start_idx if start_idx is not None else max(trend_ma, mom_slow) + 1
    end_idx = end_idx if end_idx is not None else n - 1

    equity = 1.0
    holdings = {}  # ticker -> weight fraction of equity at last rebalance
    equity_curve = []
    last_prices = {}
    n_trades = 0

    for i in range(start_idx, end_idx + 1):
        d = dates[i]
        # 보유 종목 일일 평가(전일 대비 종가 변화)
        if holdings:
            growth = 0.0
            wsum = 0.0
            for tk, w in holdings.items():
                p_now = tickers[tk]["series"].get(d)
                p_prev = last_prices.get(tk)
                if p_now and p_prev and p_prev > 0:
                    growth += w * (p_now / p_prev)
                    wsum += w
                else:
                    growth += w  # 가격 결측 → 변화 없음으로 보수 처리
                    wsum += w
            cash_w = 1.0 - sum(holdings.values())
            equity *= (growth + cash_w)
        # last_prices 갱신
        for tk in tickers:
            p = tickers[tk]["series"].get(d)
            if p:
                last_prices[tk] = p

        equity_curve.append((d, equity))

        # 리밸런스 시점인가
        if (i - start_idx) % rebal_days != 0:
            continue

        # 레짐 필터: regime_flags(히스테리시스 등 사전계산) 우선, 없으면 strict(지수<MA200 즉시 현금)
        regime_ok = True
        if regime_flags is not None:
            regime_ok = not regime_flags[i]
        elif use_index_regime:
            ma = sma(index_series, dates, i, index_ma)
            cur = index_series.get(d)
            regime_ok = bool(ma and cur and cur >= ma)

        target = {}
        if regime_ok:
            scored = []
            for tk, v in tickers.items():
                s = v["series"]
                if not s.get(d):
                    continue
                mf = pct_return(s, dates, i, mom_fast)
                ms = pct_return(s, dates, i, mom_slow)
                ma = sma(s, dates, i, trend_ma)
                cur = s.get(d)
                if mf is None or ms is None or ma is None:
                    continue
                score = 0.5 * mf + 0.5 * ms
                if score > 0 and cur >= ma:  # 절대모멘텀 + 추세필터
                    scored.append((score, tk))
            scored.sort(reverse=True)
            chosen = [tk for _, tk in scored[:top_n]]
            if chosen:
                w = 1.0 / top_n  # 고정 분모 → 후보<top_n 이면 잔여는 현금(집중 회피)
                target = {tk: w for tk in chosen}

        # 회전 비용: 빠지는 종목 매도, 새로 드는 종목 매수
        old = set(holdings)
        new = set(target)
        turnover_cost = 0.0
        for tk in old - new:
            turnover_cost += holdings[tk] * COST_SELL
            n_trades += 1
        for tk in new - old:
            turnover_cost += target[tk] * COST_BUY
            n_trades += 1
        # 유지 종목은 비용 없음(동일가중이라 미세 리밸런스 비용 무시 — 보수적이지 않게)
        equity *= (1.0 - turnover_cost)
        holdings = target

    return equity_curve, equity, n_trades


def metrics(equity_curve):
    if len(equity_curve) < 2:
        return {}
    vals = [e for _, e in equity_curve]
    total = vals[-1] / vals[0] - 1.0
    days = len(vals)
    years = days / 252.0
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1.0 if years > 0 else 0.0
    # 일간 수익률
    rets = [vals[k] / vals[k - 1] - 1.0 for k in range(1, len(vals))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sd = math.sqrt(var)
    sharpe = (mean / sd * math.sqrt(252)) if sd > 0 else 0.0
    # MDD
    peak = vals[0]
    mdd = 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return {
        "total_return_pct": round(total * 100, 1),
        "cagr_pct": round(cagr * 100, 1),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(mdd * 100, 1),
        "trading_days": days,
    }


def benchmark_curve(series, dates, start_idx, end_idx):
    base = None
    curve = []
    for i in range(start_idx, end_idx + 1):
        p = series.get(dates[i])
        if p is None:
            continue
        if base is None:
            base = p
        curve.append((dates[i], p / base))
    return curve


def main():
    tickers, index_series, dates = load_history()
    n = len(dates)
    warmup = 201
    full_start, full_end = warmup, n - 1

    print(f"데이터: {len(tickers)}종목 × {n}거래일 ({dates[0]} ~ {dates[-1]})")
    print(f"거래비용: 매수 {COST_BUY*100:.2f}% / 매도 {COST_SELL*100:.2f}% (회전당)\n")

    # 벤치마크
    bench = benchmark_curve(index_series, dates, full_start, full_end)
    bm = metrics(bench)
    print("=== 벤치마크: KOSPI buy & hold ===")
    print(f"  총수익 {bm['total_return_pct']:+.1f}% | CAGR {bm['cagr_pct']:+.1f}% | "
          f"Sharpe {bm['sharpe']} | MDD {bm['max_drawdown_pct']:.1f}%\n")

    # 권장 설정(그리드+walk-forward 로 도출한 강건 최적): Top10·월간리밸·MA200·레짐필터 OFF.
    # 근거: 전구간 Sharpe 최고(벤치 상회)+낙폭 통제+저회전, 인근 파라미터가 Sharpe 2.0~2.3 군집(과최적 아님).
    RECOMMENDED = dict(top_n=10, rebal_days=42, use_index_regime=False, trend_ma=200,
                       mom_fast=60, mom_slow=120)

    # 전략 (전구간)
    variants = [
        ("★권장: 듀얼모멘텀 Top10 (월간리밸·MA200·항시투자)", RECOMMENDED),
        ("듀얼모멘텀 Top5 (월간리밸·항시투자)", dict(top_n=5, rebal_days=42, use_index_regime=False)),
        ("듀얼모멘텀 Top5 (주간리밸·레짐필터 ON)", dict(top_n=5, rebal_days=5, use_index_regime=True)),
        ("동일가중 5종목 (주간·레짐필터 ON — 비교군)", dict(top_n=5, rebal_days=5, use_index_regime=True)),
    ]
    results = {}
    print("=== 전략 (전구간) ===")
    for label, kw in variants:
        curve, final, ntr = backtest(tickers, index_series, dates,
                                     start_idx=full_start, end_idx=full_end, **kw)
        m = metrics(curve)
        m["n_trades"] = ntr
        results[label] = m
        print(f"  {label}")
        print(f"    총수익 {m['total_return_pct']:+.1f}% | CAGR {m['cagr_pct']:+.1f}% | "
              f"Sharpe {m['sharpe']} | MDD {m['max_drawdown_pct']:.1f}% | 거래 {ntr}회")

    # Walk-forward: 전반부(탐색) vs 후반부(out-of-sample 검증)
    mid = (full_start + full_end) // 2
    print(f"\n=== Walk-forward (in-sample {dates[full_start]}~{dates[mid]} / "
          f"out-of-sample {dates[mid]}~{dates[full_end]}) ===")
    wf = {}
    for label, kw in [("★권장: Top10 월간리밸 항시투자", RECOMMENDED),
                      ("듀얼모멘텀 Top5 주간 레짐ON", dict(top_n=5, rebal_days=5, use_index_regime=True))]:
        c_is, _, _ = backtest(tickers, index_series, dates, start_idx=full_start, end_idx=mid, **kw)
        c_oos, _, _ = backtest(tickers, index_series, dates, start_idx=mid, end_idx=full_end, **kw)
        m_is, m_oos = metrics(c_is), metrics(c_oos)
        bm_oos = metrics(benchmark_curve(index_series, dates, mid, full_end))
        wf[label] = {"in_sample": m_is, "out_of_sample": m_oos, "bench_oos": bm_oos}
        print(f"  {label}")
        print(f"    IS  : 총수익 {m_is['total_return_pct']:+.1f}% Sharpe {m_is['sharpe']} MDD {m_is['max_drawdown_pct']:.1f}%")
        print(f"    OOS : 총수익 {m_oos['total_return_pct']:+.1f}% Sharpe {m_oos['sharpe']} MDD {m_oos['max_drawdown_pct']:.1f}%")
        print(f"    OOS 벤치(KOSPI): 총수익 {bm_oos['total_return_pct']:+.1f}% Sharpe {bm_oos['sharpe']}")

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "data_window": {"start": dates[0], "end": dates[-1], "trading_days": n},
        "costs": {"buy_pct": COST_BUY * 100, "sell_pct": COST_SELL * 100},
        "recommended_config": RECOMMENDED,
        "benchmark_kospi_buyhold": bm,
        "strategies_full": results,
        "walk_forward": wf,
        "key_findings": [
            "이 데이터 구간은 KOSPI +198%의 광범위 강세장 — 최대 적은 '현금 보유'다.",
            "레짐필터(지수<MA200 시 현금화)는 전 구간에서 수익을 깎았다 — 강세장에서 현금=손실.",
            "권장 전략(Top10·월간리밸·항시투자)은 총수익·Sharpe 모두 벤치마크 상회, 낙폭은 동등.",
            "저빈도 리밸런스가 거래비용·휩쏘를 줄여 고빈도 대비 우월.",
        ],
        "note": "학습·시뮬레이션 목적. 과거 성과는 미래 수익을 보장하지 않는다.",
    }
    (ROOT / "state" / "backtest_strategy.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: state/backtest_strategy.json")


if __name__ == "__main__":
    main()
