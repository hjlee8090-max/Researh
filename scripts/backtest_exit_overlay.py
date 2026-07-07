#!/usr/bin/env python3
"""청산 오버레이 백테스트 — 라이브 청산 룰(ATR 하드스톱·트레일링·부분익절)이 검증된
월간 리밸런스 듀얼모멘텀 전략에 가치를 더하는지/파괴하는지 동일 과거 데이터로 정량화한다.

배경 (2026-07-06 감사 처방②):
- 실현 매매 9건 전부가 청산 오버레이(ATR 손절·트레일링·orange/red 단계 경보)로 집행됐지만,
  전략의 근거인 검증 백테스트(scripts/backtest_strategy.py → state/backtest_strategy.json)는
  '월간 리밸런스·월중 매도 없음'만 검증했고 청산 룰은 한 번도 시뮬레이션된 적이 없다.
- 실측: 스톱 청산 7건 중 6건이 휩쏘(청산 후 15일 내 +8~16% 회복). 오버레이가 검증 전략의
  성과를 갉아먹고 있을 가설을 백테스트로 판정한다.

설계 (backtest_strategy.py 관례 승계 — __main__ 가드가 있어 함수 직접 import):
- 데이터: state/price_history.json (610 거래일 2024-01-02~2026-07-06, 종목별 OHLCV + 지수).
- 비용: COST_BUY=0.002 / COST_SELL=0.0038 (backtest_strategy 와 동일).
- 룩어헤드 차단: t 종가 정보로 신호 → t 종가 체결(close-to-close). 라이브
  risk.exit_execution.close_trigger_fill_rule(종가 트리거 → 당일 확정 종가 체결)과 일치.
- 선정 로직: backtest_strategy 의 듀얼모멘텀(0.5×60일+0.5×120일, 가격>MA200, 절대모멘텀>0,
  Top-N 동일가중, 고정 분모)을 pct_return/sma import 로 그대로 재현. 단 엔진은 청산 오버레이에
  진입가·최고종가·부분익절 상태가 필요해 '비중 벡터'가 아닌 '포지션 단위'로 재구현했다
  (backtest_strategy.backtest 는 비중만 추적해 포지션별 스톱 레벨을 표현할 수 없음).

3개 변형 (동일 진입, 청산만 다름):
- A. baseline    — 월간 리밸런스만, 월중 청산 없음 (backtest_strategy 권장 전략 그대로).
- B. overlay_full— A + 일별 종가 평가: ①하드 ATR 스톱(진입가 − 2.0×진입시 ATR14%, 종가 이탈)
                   ②트레일링(compute_exit_levels.trail_levels 동일 공식 — 1차선 최고종가×
                   (1−max(3.0,1.5×ATR%)/100) 이탈 시 50% 부분익절, 잔여 샹들리에 최고종가×
                   (1−2.0×ATR%/100) 이탈 시 잔여 전량). 활성화 = 목표 진행률 ≥ 70%
                   (단순 목표 = 진입가×1.10 → 최고종가 ≥ 진입가×1.07).
- C. stop_only   — 하드 ATR 스톱만 (휩쏘를 유발하는 컴포넌트 분리).
스톱아웃 현금은 다음 월간 리밸런스까지 대기(라이브 재진입 규율과 일치).

단순화 (명시):
- 목표가: 라이브 dynamic_exit_model(변동성·저항선·밸류에이션 반영)은 복잡해 policy
  risk.target_return_pct=10% 단순 목표(진입가×1.10)로 대체 → 활성화 문턱 = +7%.
- ATR14%: TR(고가-저가, |고가-전종가|, |저가-전종가| 최댓값) 14일 '단순평균'/당일종가×100
  (Wilder 지수평활 아님 — 라이브 스냅샷 atr_pct 와 산식 계열 동일, 값은 근사).
- 하드 스톱의 ATR 은 진입 시점 고정, 트레일링의 ATR 은 평가일 롤링(라이브 snapshot 관례).
- orange/red 단계 경보(원인 분류 조건부)는 재량 판단이 섞여 기계 재현 불가 — 하드 스톱·
  트레일링 두 기계 룰만 오버레이한다. 리밸런스 당일은 리밸런스가 청산을 대신한다.

산출: state/backtest_exit_overlay.json + 표준출력 한국어 마크다운(룰 채점 rule_attribution 양식).
휩쏘 정의: 스톱 청산 후 10거래일 내 종가가 청산가 대비 +5% 이상 회복.
학습·시뮬레이션 목적 — 과거 성과는 미래 수익을 보장하지 않는다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_strategy as bts  # noqa: E402  (__main__ 가드 확인 — import 안전)
import compute_exit_levels as cel  # noqa: E402 (trail_levels 단일 소스)

KST = timezone(timedelta(hours=9))
COST_BUY = bts.COST_BUY    # 0.002
COST_SELL = bts.COST_SELL  # 0.0038

# ── 청산 룰 파라미터 (policy.risk.volatility_sizing / trailing_stop + compute_exit_levels 사본)
STOP_ATR_MULT = 2.0                 # 하드 스톱 = 진입가 − 2.0×ATR14%(진입 시점)
FLOOR_PCT = cel.FLOOR_PCT           # 3.0
FIRST_MULT = cel.FIRST_MULT         # 1.5
RESID_MULT = cel.RESID_MULT         # 2.0
ACTIVATE_PROGRESS_PCT = 70.0        # trailing_stop.activate_at_target_progress_pct
TARGET_RETURN_PCT = 10.0            # 단순 목표(진입가×1.10) — dynamic_exit_model 단순화
ATR_PERIOD = 14
WHIPSAW_RECOVER_PCT = 5.0           # 휩쏘: 청산 후 10거래일 내 종가 ≥ 청산가×1.05
WHIPSAW_WINDOW_DAYS = 10
RECENT_WINDOW_START = "2026-01-01"

# 시뮬레이션 대상 설정 — ①backtest_strategy 권장(검증 원본) ②라이브 momentum_strategy.config
CONFIGS = [
    ("권장 Top10·월간리밸 (backtest_strategy 검증 설정)",
     dict(top_n=10, rebal_days=42, mom_fast=60, mom_slow=120, trend_ma=200)),
    ("라이브 Top6·21일리밸 (policy momentum_strategy 설정)",
     dict(top_n=6, rebal_days=21, mom_fast=60, mom_slow=120, trend_ma=200)),
]


def atr_pct_by_date(bars: list[dict]) -> dict[str, float]:
    """일자별 ATR14%(단순평균 TR / 당일 종가 × 100). Wilder 평활 아님(docstring 참조)."""
    seq = sorted((b for b in bars if b.get("close")), key=lambda b: b["date"])
    out: dict[str, float] = {}
    trs: list[float] = []
    prev_close = None
    for b in seq:
        c = float(b["close"])
        h = float(b.get("high") or c)
        low = float(b.get("low") or c)
        tr = (h - low) if prev_close is None else max(h - low, abs(h - prev_close), abs(low - prev_close))
        trs.append(tr)
        if len(trs) >= ATR_PERIOD and c > 0:
            out[b["date"]] = sum(trs[-ATR_PERIOD:]) / ATR_PERIOD / c * 100.0
        prev_close = c
    return out


def load_history_ohlc():
    """backtest_strategy.load_history 와 동일 규약(종가 시리즈·지수 날짜 그리드) + ATR% 사전계산."""
    d = json.load(open(ROOT / "state" / "price_history.json"))
    tickers = {}
    for tk, v in d["tickers"].items():
        bars = v.get("bars") or []
        if len(bars) < 200:  # backtest_strategy 와 동일 필터
            continue
        tickers[tk] = {
            "name": v.get("name", tk),
            "series": {b["date"]: float(b["close"]) for b in bars if b.get("close")},
            "atr_pct": atr_pct_by_date(bars),
        }
    index_series = {b["date"]: float(b["close"]) for b in d["index"]["bars"] if b.get("close")}
    dates = sorted(index_series.keys())
    return tickers, index_series, dates


def select_topn(tickers, dates, i, cfg) -> list[str]:
    """backtest_strategy.backtest 의 선정 블록 재현 — 0.5×fast+0.5×slow, 가격>MA, 절대모멘텀>0."""
    d = dates[i]
    scored = []
    for tk, v in tickers.items():
        s = v["series"]
        cur = s.get(d)
        if not cur:
            continue
        mf = bts.pct_return(s, dates, i, cfg["mom_fast"])
        ms = bts.pct_return(s, dates, i, cfg["mom_slow"])
        ma = bts.sma(s, dates, i, cfg["trend_ma"])
        if mf is None or ms is None or ma is None:
            continue
        score = 0.5 * mf + 0.5 * ms
        if score > 0 and cur >= ma:
            scored.append((score, tk))
    scored.sort(reverse=True)
    return [tk for _, tk in scored[: cfg["top_n"]]]


def atr_at(tickers, tk, dates, i) -> float | None:
    """평가일(또는 직전 10거래일 내 최근) ATR%."""
    ap = tickers[tk]["atr_pct"]
    for j in range(i, max(-1, i - 10), -1):
        v = ap.get(dates[j])
        if v is not None:
            return v
    return None


def simulate(tickers, dates, cfg, variant, start_idx, end_idx):
    """포지션 단위 시뮬레이션. variant ∈ {baseline, stop_only, overlay_full}.

    관례: 리밸런스일 종가에 회전(이탈 매도→신규 매수, 유지 종목은 무비용 재조정 —
    backtest_strategy 의 '유지 종목 비용 없음'과 동일). 비리밸런스일에는 오버레이 변형만
    종가 기준 청산 룰 평가 → 당일 종가 체결. 스톱아웃 현금은 다음 리밸런스까지 대기.
    """
    cash = 1.0
    positions: dict[str, dict] = {}
    last_price: dict[str, float] = {}
    curve: list[tuple[str, float]] = []
    events: list[dict] = []
    n_trades = 0
    turnover_x = 0.0  # Σ 체결대금/체결시점 equity (편도 합산)

    def mark_equity() -> float:
        return cash + sum(p["units"] * last_price[t] for t, p in positions.items())

    for i in range(start_idx, end_idx + 1):
        d = dates[i]
        for tk, v in tickers.items():
            p = v["series"].get(d)
            if p:
                last_price[tk] = p

        is_rebal = (i - start_idx) % cfg["rebal_days"] == 0
        if is_rebal:
            equity = mark_equity()
            target = select_topn(tickers, dates, i, cfg)
            for tk in list(positions):  # 회전 이탈 매도
                if tk not in target:
                    value = positions[tk]["units"] * last_price[tk]
                    cash += value * (1.0 - COST_SELL)
                    turnover_x += value / equity
                    n_trades += 1
                    del positions[tk]
            equity = mark_equity()
            w = 1.0 / cfg["top_n"]  # 고정 분모 — 후보<top_n 이면 잔여 현금(backtest_strategy 동일)
            for tk in target:
                p = tickers[tk]["series"].get(d)
                if not p:
                    continue
                tv = w * equity
                if tk in positions:  # 유지 종목 — 무비용 재조정(baseline 관례), 청산 상태 승계
                    cash -= tv - positions[tk]["units"] * p
                    positions[tk]["units"] = tv / p
                    # 리밸런스 당일 종가도 최고종가 추적에 반영 — 누락 시 트레일 레벨이
                    # 그날의 신고가를 놓쳐 한 박자 늦게/느슨하게 잡힌다(2026-07-08 검증
                    # 감사 발견: 143건 중 1건 영향, 051910 잔여선 370,455 vs 정정 372,676).
                    positions[tk]["highest"] = max(positions[tk]["highest"], p)
                else:  # 신규 진입 — 진입가·ATR 고정 스톱·트레일 상태 초기화
                    atr0 = atr_at(tickers, tk, dates, i) or FLOOR_PCT
                    cash -= tv * (1.0 + COST_BUY)
                    turnover_x += tv / equity
                    n_trades += 1
                    positions[tk] = {
                        "units": tv / p, "entry": p, "atr_entry": atr0,
                        "stop": p * (1.0 - STOP_ATR_MULT * atr0 / 100.0),
                        "highest": p, "activated": False, "partial_done": False,
                    }
        elif variant != "baseline":
            equity = mark_equity()
            for tk in list(positions):
                pos = positions[tk]
                c = tickers[tk]["series"].get(d)
                if not c:
                    continue
                pos["highest"] = max(pos["highest"], c)
                if c <= pos["stop"]:  # ① 하드 ATR 스톱 — 종가 이탈 → 당일 종가 전량 체결
                    value = pos["units"] * c
                    cash += value * (1.0 - COST_SELL)
                    turnover_x += value / equity
                    n_trades += 1
                    events.append({"date": d, "i": i, "ticker": tk, "name": tickers[tk]["name"],
                                   "rule": "hard_atr_stop", "exit_price": c, "entry": pos["entry"],
                                   "ret_pct": round((c / pos["entry"] - 1) * 100, 2)})
                    del positions[tk]
                    continue
                if variant != "overlay_full":
                    continue
                # ② 트레일링 — 활성화(목표 진행률 ≥70%, 단순 목표 +10% ⇒ 최고종가 ≥ 진입가×1.07)
                target_price = pos["entry"] * (1.0 + TARGET_RETURN_PCT / 100.0)
                progress = (pos["highest"] - pos["entry"]) / (target_price - pos["entry"]) * 100.0
                if progress >= ACTIVATE_PROGRESS_PCT:
                    pos["activated"] = True
                if not pos["activated"]:
                    continue
                atr_now = atr_at(tickers, tk, dates, i) or pos["atr_entry"]
                first_lv, resid_lv = cel.trail_levels(pos["highest"], atr_now)
                if not pos["partial_done"] and c <= first_lv:  # 1차선 이탈 → 50% 부분익절
                    value = 0.5 * pos["units"] * c
                    cash += value * (1.0 - COST_SELL)
                    turnover_x += value / equity
                    n_trades += 1
                    pos["units"] *= 0.5
                    pos["partial_done"] = True
                    events.append({"date": d, "i": i, "ticker": tk, "name": tickers[tk]["name"],
                                   "rule": "trail_first_partial_50", "exit_price": c, "entry": pos["entry"],
                                   "ret_pct": round((c / pos["entry"] - 1) * 100, 2)})
                if pos["partial_done"] and c <= resid_lv:  # 잔여 샹들리에 이탈 → 잔여 전량
                    value = pos["units"] * c
                    cash += value * (1.0 - COST_SELL)
                    turnover_x += value / equity
                    n_trades += 1
                    events.append({"date": d, "i": i, "ticker": tk, "name": tickers[tk]["name"],
                                   "rule": "trail_residual_exit", "exit_price": c, "entry": pos["entry"],
                                   "ret_pct": round((c / pos["entry"] - 1) * 100, 2)})
                    del positions[tk]

        curve.append((d, mark_equity()))
    return curve, events, n_trades, turnover_x


def annotate_whipsaws(events, tickers, dates):
    """전량 청산(하드스톱·잔여트레일) 후 10거래일 내 종가 ≥ 청산가×1.05 → 휩쏘(진단용 사후 관찰)."""
    for e in events:
        if e["rule"] == "trail_first_partial_50":
            e["whipsaw"] = None  # 부분익절은 잔여가 추세를 계속 타므로 휩쏘 판정 제외
            continue
        s = tickers[e["ticker"]]["series"]
        thr = e["exit_price"] * (1.0 + WHIPSAW_RECOVER_PCT / 100.0)
        e["whipsaw"] = any(
            (s.get(dates[j]) or 0) >= thr
            for j in range(e["i"] + 1, min(e["i"] + 1 + WHIPSAW_WINDOW_DAYS, len(dates)))
        )


def variant_summary(curve, events, n_trades, turnover_x, base_total=None):
    m = bts.metrics(curve)
    hard = [e for e in events if e["rule"] == "hard_atr_stop"]
    partial = [e for e in events if e["rule"] == "trail_first_partial_50"]
    resid = [e for e in events if e["rule"] == "trail_residual_exit"]
    out = {
        "total_return_pct": m["total_return_pct"],
        "cagr_pct": m["cagr_pct"],
        "sharpe": m["sharpe"],
        "max_drawdown_pct": m["max_drawdown_pct"],
        "n_trades": n_trades,
        "turnover_x": round(turnover_x, 2),
        "intra_month_exits": {
            "hard_atr_stop": len(hard),
            "trail_first_partial_50": len(partial),
            "trail_residual_exit": len(resid),
        },
        "whipsaw": {
            "hard_atr_stop": sum(1 for e in hard if e.get("whipsaw")),
            "trail_residual_exit": sum(1 for e in resid if e.get("whipsaw")),
            "definition": f"전량 청산 후 {WHIPSAW_WINDOW_DAYS}거래일 내 종가 ≥ 청산가×{1 + WHIPSAW_RECOVER_PCT / 100:.2f}",
        },
    }
    if base_total is not None:
        out["delta_vs_baseline_pp"] = round(m["total_return_pct"] - base_total, 1)
    return out


def run_window(tickers, dates, cfg, start_idx, end_idx):
    res = {}
    events_by_variant = {}
    for key, variant in [("A_baseline", "baseline"), ("B_overlay_full", "overlay_full"),
                         ("C_stop_only", "stop_only")]:
        curve, events, ntr, tov = simulate(tickers, dates, cfg, variant, start_idx, end_idx)
        annotate_whipsaws(events, tickers, dates)
        base_total = res.get("A_baseline", {}).get("total_return_pct")
        res[key] = variant_summary(curve, events, ntr, tov,
                                   base_total=None if key == "A_baseline" else base_total)
        events_by_variant[key] = events
    # 컴포넌트 분해: C−A = 하드스톱 기여, B−C = 트레일링(+부분익절) 추가 기여
    res["attribution_pp"] = {
        "hard_stop_component": round(res["C_stop_only"]["total_return_pct"]
                                     - res["A_baseline"]["total_return_pct"], 1),
        "trailing_component": round(res["B_overlay_full"]["total_return_pct"]
                                    - res["C_stop_only"]["total_return_pct"], 1),
        "overlay_total": round(res["B_overlay_full"]["total_return_pct"]
                               - res["A_baseline"]["total_return_pct"], 1),
    }
    res["exit_events_overlay_full"] = [
        {k: v for k, v in e.items() if k != "i"} for e in events_by_variant["B_overlay_full"]]
    res["exit_events_stop_only"] = [
        {k: v for k, v in e.items() if k != "i"} for e in events_by_variant["C_stop_only"]]
    return res


def render_markdown(label, window_label, period, res) -> str:
    lines = [
        f"#### {label} — {window_label} ({period})",
        "| 변형 | 총수익 | CAGR | Sharpe | MDD | Δ vs A(%p) | 하드스톱 | 휩쏘 | 부분익절 | 잔여청산 | 거래 | 회전배수 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, name in [("A_baseline", "A 월간리밸(청산 없음)"), ("B_overlay_full", "B 오버레이 전체"),
                      ("C_stop_only", "C 하드스톱만")]:
        r = res[key]
        ie, wh = r["intra_month_exits"], r["whipsaw"]
        delta = "—" if "delta_vs_baseline_pp" not in r else f"{r['delta_vs_baseline_pp']:+.1f}"
        lines.append(
            f"| {name} | {r['total_return_pct']:+.1f}% | {r['cagr_pct']:+.1f}% | {r['sharpe']} | "
            f"{r['max_drawdown_pct']:.1f}% | {delta} | {ie['hard_atr_stop']} | "
            f"{wh['hard_atr_stop'] + wh['trail_residual_exit']} | {ie['trail_first_partial_50']} | "
            f"{ie['trail_residual_exit']} | {r['n_trades']} | {r['turnover_x']} |")
    a = res["attribution_pp"]
    lines.append(f"> 기여 분해(%p): 하드스톱(C−A) {a['hard_stop_component']:+.1f} · "
                 f"트레일링 추가(B−C) {a['trailing_component']:+.1f} · "
                 f"오버레이 합계(B−A) {a['overlay_total']:+.1f}")
    return "\n".join(lines)


def build_verdict(results) -> str:
    parts = []
    for label, windows in results.items():
        for wlabel, res in windows.items():
            a = res["attribution_pp"]
            b = res["B_overlay_full"]
            whip = b["whipsaw"]["hard_atr_stop"] + b["whipsaw"]["trail_residual_exit"]
            stops = (b["intra_month_exits"]["hard_atr_stop"]
                     + b["intra_month_exits"]["trail_residual_exit"])
            mdd_gain = res["A_baseline"]["max_drawdown_pct"] - b["max_drawdown_pct"]
            parts.append(
                f"[{label} · {wlabel}] 오버레이 B−A {a['overlay_total']:+.1f}%p"
                f"(하드스톱 {a['hard_stop_component']:+.1f} / 트레일링 {a['trailing_component']:+.1f}), "
                f"MDD 개선 {-mdd_gain:+.1f}%p, 전량청산 {stops}건 중 휩쏘 {whip}건")
    total_pps = [res["attribution_pp"]["overlay_total"]
                 for windows in results.values() for res in windows.values()]
    destroyed = sum(1 for x in total_pps if x < 0)
    if destroyed == len(total_pps):
        head = ("판정: 청산 오버레이는 모든 설정·구간에서 가치를 파괴했다 — 이 강세장 데이터에서 "
                "월중 스톱·트레일링은 검증된 월간 리밸런스 대비 수익을 깎는 순비용이다. ")
    elif destroyed == 0:
        head = "판정: 청산 오버레이는 모든 설정·구간에서 가치를 더했다. "
    else:
        head = (f"판정: 혼재 — {len(total_pps)}개 설정·구간 중 {destroyed}개에서 오버레이가 "
                "가치를 파괴했다(구간·설정 의존). ")
    return head + " / ".join(parts)


def main():
    tickers, index_series, dates = load_history_ohlc()
    n = len(dates)
    warmup = 201  # backtest_strategy.main 과 동일
    recent_idx = next(i for i, d in enumerate(dates) if d >= RECENT_WINDOW_START)
    windows = [
        ("full", warmup, n - 1),
        ("recent_2026", recent_idx, n - 1),
    ]

    print(f"### 청산 오버레이 백테스트 (backtest_exit_overlay — 2026-07-06 감사 처방②)")
    print(f"- 데이터: {len(tickers)}종목 × {n}거래일 ({dates[0]} ~ {dates[-1]}) · "
          f"비용 매수 {COST_BUY*100:.2f}%/매도 {COST_SELL*100:.2f}%")
    print(f"- 룰: 하드스톱 진입가−{STOP_ATR_MULT}×ATR14%(진입시 고정) · 트레일 1차 "
          f"최고종가×(1−max({FLOOR_PCT},{FIRST_MULT}×ATR%)/100)→50% 부분익절 · "
          f"잔여 샹들리에 ×(1−{RESID_MULT}×ATR%/100) · 활성화 목표진행 ≥{ACTIVATE_PROGRESS_PCT:.0f}%"
          f"(단순 목표 +{TARGET_RETURN_PCT:.0f}% ⇒ +7%) · 종가 트리거→당일 종가 체결")
    print(f"- ATR14%: TR 14일 단순평균/당일종가 (Wilder 아님) · 휩쏘: 청산 후 "
          f"{WHIPSAW_WINDOW_DAYS}거래일 내 +{WHIPSAW_RECOVER_PCT:.0f}% 회복\n")

    results: dict[str, dict] = {}
    for label, cfg in CONFIGS:
        results[label] = {}
        for wlabel, s, e in windows:
            res = run_window(tickers, dates, cfg, s, e)
            res["period"] = f"{dates[s]}~{dates[e]}"
            results[label][wlabel] = res
            print(render_markdown(label, wlabel, res["period"], res))
            print()

    verdict = build_verdict(results)
    print("### 판정")
    print(verdict)

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "purpose": "2026-07-06 감사 처방② — 라이브 청산 오버레이(ATR 스톱·트레일링·부분익절)가 "
                   "검증된 월간 리밸런스 듀얼모멘텀 대비 가치를 더하는지/파괴하는지 정량화",
        "data_window": {"start": dates[0], "end": dates[-1], "trading_days": n},
        "params": {
            "cost_buy": COST_BUY, "cost_sell": COST_SELL,
            "stop_atr_mult": STOP_ATR_MULT, "floor_pct": FLOOR_PCT,
            "first_mult": FIRST_MULT, "resid_mult": RESID_MULT,
            "activate_at_target_progress_pct": ACTIVATE_PROGRESS_PCT,
            "simple_target_return_pct": TARGET_RETURN_PCT,
            "activation_effective_gain_pct": TARGET_RETURN_PCT * ACTIVATE_PROGRESS_PCT / 100.0,
            "atr_period": ATR_PERIOD,
            "atr_method": "TR(고저·전종가 갭 최대) 14일 단순평균 / 당일 종가 ×100 — Wilder 평활 아님",
            "whipsaw_definition": f"전량 청산 후 {WHIPSAW_WINDOW_DAYS}거래일 내 종가 ≥ 청산가×"
                                  f"{1 + WHIPSAW_RECOVER_PCT / 100:.2f}",
            "fill_rule": "종가 트리거 → 당일 종가 체결(risk.exit_execution.close_trigger_fill_rule)",
            "reentry_discipline": "스톱아웃 현금은 다음 월간 리밸런스까지 대기(라이브 규율 일치)",
            "simplifications": [
                "목표가 = 진입가×1.10 고정(dynamic_exit_model 미재현) — 활성화 문턱 +7%",
                "orange/red 단계 경보(재량 원인분류)는 기계 재현 불가로 제외 — 하드스톱·트레일링만",
                "트레일 ATR 은 평가일 롤링, 하드스톱 ATR 은 진입 시점 고정",
                "리밸런스 당일은 리밸런스가 청산을 대신(동일 종가 이중 체결 방지)",
                "'라이브 Top6' 설정은 policy momentum_strategy 의 min_score=30·tracked_only 필터를 생략(score>0 전체 유니버스) — 라벨 충실도 한계, B−A 변형 간 비교는 동일 조건이라 유효",
                "기말 보유 포지션은 종가 마킹만(매도비용 0.38% 미차감) — 완전투자 상태인 A 에 최대 ~1-2%p 유리, 오버레이 손상 추정을 보수적으로 만드는 방향",
            ],
            "configs": {label: cfg for label, cfg in CONFIGS},
        },
        "variants_legend": {
            "A_baseline": "월간 리밸런스만 — backtest_strategy 권장 전략(월중 청산 없음)",
            "B_overlay_full": "A + 하드 ATR 스톱 + 트레일링(1차 50% 부분익절→잔여 샹들리에)",
            "C_stop_only": "A + 하드 ATR 스톱만(트레일링 없음 — 휩쏘 컴포넌트 분리)",
        },
        "results": results,
        "verdict": verdict,
        "baseline_cross_check": "A_baseline(권장 Top10·42일, full)은 backtest_strategy.json "
                                "strategies_full '★권장'(+304.3%)과 같은 로직의 포지션 단위 재구현 — "
                                "방향·규모가 일치해야 정상",
        "note": "학습·시뮬레이션 목적. 과거 성과는 미래 수익을 보장하지 않는다.",
    }
    dest = ROOT / "state" / "backtest_exit_overlay.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n저장: state/backtest_exit_overlay.json")


if __name__ == "__main__":
    main()
