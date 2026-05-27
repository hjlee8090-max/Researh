#!/usr/bin/env python3
"""기계적 룰 베이스라인 백테스트 엔진 — LLM 전진기록을 채점할 '잣대' 생성기.

전략: strategy_core(모멘텀 블렌드 + 레짐 tier 사이징 + ATR/고정 손절 + 트레일링)을 과거 일봉에
결정론적으로 적용. 룩어헤드 차단(D일 종가로 결정 → D+1 시가 체결, 손절/목표는 당일 H/L 로 체결).
비용은 policy.trading_cost(슬리피지·세금·수수료)를 그대로 반영.

비교 잣대:
- Buy&Hold KOSPI(^KS11)  — 가장 기본 벤치마크
- Equal-Weight 유니버스 Buy&Hold — 종목선택 없는 분산 기준

출력:
- state/backtest_results.json (기계용)
- reports/backtest-YYYY-MM-DD.md (사람용 — 헤드라인·연도별·거래통계·한계 명시)

데이터: data/prices/<ticker>.csv + data/index/_KS11.csv (scripts/backfill_prices.py 로 수집).
표준 라이브러리만 사용 — 의존성 0.

한계(리포트에도 명시): 가격수익(무배당) 기준 / 유니버스가 현재 구성종목이라 생존편향 존재 /
일중 틱 없이 일봉 H/L 로 손절 근사 / Yahoo 데이터 품질 한계. 실거래 전 point-in-time 구성종목·
정밀 데이터로 재검증 필요.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pricecache
import strategy_core as core

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


class Series:
    """한 종목/지수의 일봉 시계열. point-in-time 조회 전용."""

    def __init__(self, bars: list[dict]):
        self.bars = bars
        self.dates = [b["date"] for b in bars]

    def __bool__(self) -> bool:
        return bool(self.bars)

    def upto(self, d: str) -> list[dict]:
        return self.bars[: bisect_right(self.dates, d)]

    def at(self, d: str) -> dict | None:
        i = bisect_right(self.dates, d) - 1
        if i >= 0 and self.dates[i] == d:
            return self.bars[i]
        return None

    def asof(self, d: str) -> dict | None:
        i = bisect_right(self.dates, d) - 1
        return self.bars[i] if i >= 0 else None


def load_universe(data_dir: Path | None) -> tuple[dict[str, Series], Series, list[dict], str]:
    cfg = load_json("config/backtest_universe.json", {})
    index_symbol = cfg.get("index_symbol", "^KS11")
    tickers_meta = cfg.get("tickers", [])
    # 보유·후보도 포함(중복 제거)
    seen = {t.get("ticker") for t in tickers_meta}
    for src in ("config/portfolio.json", "config/candidates.json"):
        node = load_json(src, {})
        for item in node.get("positions", []) or node.get("candidates", []):
            tk = item.get("ticker")
            if tk and tk not in seen:
                tickers_meta.append({"ticker": tk, "name": item.get("name", ""), "sector": item.get("sector", "")})
                seen.add(tk)

    base = data_dir
    series: dict[str, Series] = {}
    for meta in tickers_meta:
        tk = meta.get("ticker")
        if not tk:
            continue
        bars = pricecache.load_bars(pricecache.price_path(tk, base))
        if bars:
            series[tk] = Series(bars)
    index_bars = pricecache.load_bars(pricecache.index_path(index_symbol, base))
    return series, Series(index_bars), tickers_meta, index_symbol


def trading_calendar(index: Series, series: dict[str, Series], start: str | None, end: str | None) -> list[str]:
    if index:
        dates = list(index.dates)
    else:
        alld: set[str] = set()
        for s in series.values():
            alld.update(s.dates)
        dates = sorted(alld)
    if start:
        dates = [d for d in dates if d >= start]
    if end:
        dates = [d for d in dates if d <= end]
    return dates


# ---- 비용 모델 (policy.trading_cost; 1800_report.md 컨벤션과 일치) ----

def buy_fill(open_price: float, cost: dict) -> float:
    return open_price * (1 + (cost.get("slippage_pct", 0.2) + cost.get("commission_pct", 0.015)) / 100.0)


def sell_fill(price: float, cost: dict) -> float:
    drag = cost.get("slippage_pct", 0.2) + cost.get("tax_pct", 0.18) + cost.get("commission_pct", 0.015)
    return price * (1 - drag / 100.0)


def run_backtest(
    series: dict[str, Series],
    index: Series,
    policy: dict,
    dates: list[str],
    capital: float,
    rebalance_days: int,
) -> dict[str, Any]:
    cost = policy.get("trading_cost", {})
    ps = policy.get("position_sizing", {})
    risk = policy.get("risk", {})
    max_positions = ps.get("max_positions", 4)
    min_cash_pct = ps.get("min_cash_weight_pct", 5.0)
    trail_cfg = risk.get("trailing_stop", "")
    trail_give_back = 0.03  # "-3% 트레일링"
    trail_arm_ratio = 0.70  # "목표가 70% 도달 후"

    cash = capital
    positions: dict[str, dict] = {}
    pending: list[dict] = []
    trades: list[dict] = []
    equity_curve: list[tuple[str, float]] = []
    exposure_samples: list[float] = []
    degenerate_sizing = 0  # 정수반올림으로 진입 불가했던 횟수

    def mark_value(d: str) -> float:
        v = 0.0
        for tk, pos in positions.items():
            bar = series[tk].asof(d)
            px = bar["close"] if bar else pos["entry_price"]
            v += pos["shares"] * px
        return v

    def close_position(tk: str, exit_price: float, d: str, reason: str) -> None:
        nonlocal cash
        pos = positions.pop(tk)
        eff = sell_fill(exit_price, cost)
        proceeds = pos["shares"] * eff
        cash += proceeds
        pnl = proceeds - pos["cost_basis"]
        trades.append({
            "ticker": tk,
            "entry_date": pos["entry_date"],
            "exit_date": d,
            "entry_price": round(pos["entry_price"], 1),
            "exit_price": round(eff, 1),
            "shares": pos["shares"],
            "pnl": round(pnl),
            "return_pct": round(pnl / pos["cost_basis"] * 100, 2) if pos["cost_basis"] else 0.0,
            "reason": reason,
            "hold_days": (datetime.fromisoformat(d) - datetime.fromisoformat(pos["entry_date"])).days,
        })

    for i, d in enumerate(dates):
        # 1) 직전 결정으로 대기중인 주문을 D 시가에 체결 (룩어헤드 차단)
        still_pending: list[dict] = []
        for order in pending:
            tk = order["ticker"]
            bar = series[tk].at(d) or series[tk].asof(d)
            if not bar:
                still_pending.append(order)
                continue
            if order["side"] == "buy":
                fill = buy_fill(bar.get("open", bar["close"]), cost)
                shares = order["shares"]
                cost_total = shares * fill
                while shares > 0 and cost_total > cash:  # 갭업으로 현금 초과 시 수량 축소
                    shares -= 1
                    cost_total = shares * fill
                if shares <= 0:
                    continue
                stop, target = core.stop_and_target(fill, order.get("atr14"), policy)
                cash -= cost_total
                positions[tk] = {
                    "shares": shares, "entry_price": fill, "cost_basis": cost_total,
                    "entry_date": d, "stop": stop, "target": target,
                    "trail_active": False, "peak": fill,
                }
            else:  # sell (rotation)
                if tk in positions:
                    close_position(tk, bar.get("open", bar["close"]), d, order.get("reason", "rotation"))
        pending = still_pending

        # 2) 당일 H/L 로 손절·트레일링·목표 체결 (resting order 근사)
        for tk in list(positions.keys()):
            pos = positions[tk]
            bar = series[tk].at(d)
            if not bar:
                continue
            hi, lo, op = bar["high"], bar["low"], bar.get("open", bar["close"])
            # 하드 손절 우선
            if lo <= pos["stop"]:
                fill = min(op, pos["stop"]) if op < pos["stop"] else pos["stop"]
                close_position(tk, fill, d, "stop")
                continue
            # 트레일링 활성화/갱신
            arm_price = pos["entry_price"] + trail_arm_ratio * (pos["target"] - pos["entry_price"])
            if not pos["trail_active"] and hi >= arm_price:
                pos["trail_active"] = True
                pos["peak"] = hi
            if pos["trail_active"]:
                pos["peak"] = max(pos["peak"], hi)
                trail_stop = pos["peak"] * (1 - trail_give_back)
                if lo <= trail_stop:
                    fill = min(op, trail_stop) if op < trail_stop else trail_stop
                    close_position(tk, fill, d, "trailing_stop")
                    continue
            # 고정 목표(트레일링 미활성 시에만 — 활성 후엔 추세 추종)
            elif hi >= pos["target"]:
                fill = max(op, pos["target"]) if op > pos["target"] else pos["target"]
                close_position(tk, fill, d, "target")
                continue

        # 3) 종가 마킹·기록
        stock_value = mark_value(d)
        equity = cash + stock_value
        equity_curve.append((d, equity))
        if equity > 0:
            exposure_samples.append(stock_value / equity)

        # 4) 리밸런스(주기적, 다음 시가 체결로 큐잉)
        if i % max(1, rebalance_days) == 0:
            regime = core.regime_from_index(index.upto(d), policy)
            entry_mode = regime.get("entry_mode") or "default"
            if entry_mode == "block":
                desired: list[str] = []  # deep_bear: 신규 진입 중단
            else:
                sigs: dict[str, dict] = {}
                for tk, s in series.items():
                    sub = s.upto(d)
                    if len(sub) >= 6:
                        sigs[tk] = core.signals_from_bars(sub)
                ranked = core.rank_candidates(sigs, policy)
                desired = [tk for tk, _ in ranked[:max_positions]]

            # 회전 매도: 목표에 없는 보유 → 다음 시가 매도
            for tk in list(positions.keys()):
                if tk not in desired:
                    pending.append({"ticker": tk, "side": "sell", "reason": "rotation"})

            # 신규 매수: 목표 주식비중 한도 내에서 미보유 종목 사이징
            tgt_eq_pct = core.target_equity_pct(regime, policy)
            stock_budget = equity * tgt_eq_pct / 100.0
            held_value = stock_value
            deployable = max(0.0, min(stock_budget - held_value, cash - capital * min_cash_pct / 100.0))
            for tk in desired:
                if tk in positions or deployable <= 0:
                    continue
                sig = sigs.get(tk) if entry_mode != "block" else None
                if not sig:
                    continue
                price = sig["close"]
                stop, _ = core.stop_and_target(price, sig.get("atr14"), policy)
                shares = core.position_size(equity, price, stop, policy, entry_mode)
                if shares <= 0:
                    degenerate_sizing += 1
                    continue
                est_cost = shares * buy_fill(price, cost)
                while shares > 0 and est_cost > deployable:
                    shares -= 1
                    est_cost = shares * buy_fill(price, cost)
                if shares <= 0:
                    continue
                pending.append({"ticker": tk, "side": "buy", "shares": shares, "atr14": sig.get("atr14")})
                deployable -= est_cost

    return {
        "equity_curve": equity_curve,
        "trades": trades,
        "final_equity": equity_curve[-1][1] if equity_curve else capital,
        "avg_exposure": round(statistics.fmean(exposure_samples), 4) if exposure_samples else 0.0,
        "degenerate_sizing_skips": degenerate_sizing,
    }


# ---- 벤치마크·지표 ----

def buy_hold_curve(index: Series, dates: list[str], capital: float) -> list[tuple[str, float]]:
    base = None
    out: list[tuple[str, float]] = []
    for d in dates:
        bar = index.asof(d)
        if not bar:
            continue
        if base is None:
            base = bar["close"]
        out.append((d, capital * bar["close"] / base))
    return out


def equal_weight_curve(series: dict[str, Series], dates: list[str], capital: float) -> list[tuple[str, float]]:
    if not dates or not series:
        return []
    start = dates[0]
    members = {tk: s.asof(start)["close"] for tk, s in series.items() if s.asof(start)}
    if not members:
        return []
    alloc = capital / len(members)
    shares = {tk: alloc / px for tk, px in members.items() if px > 0}
    out: list[tuple[str, float]] = []
    for d in dates:
        v = 0.0
        for tk, sh in shares.items():
            bar = series[tk].asof(d)
            if bar:
                v += sh * bar["close"]
        out.append((d, v))
    return out


def metrics(curve: list[tuple[str, float]]) -> dict[str, Any]:
    if len(curve) < 2:
        return {"total_return_pct": 0.0, "cagr_pct": 0.0, "vol_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0}
    vals = [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    total = vals[-1] / vals[0] - 1
    years = max(len(vals) / 252.0, 1e-9)
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1 if vals[0] > 0 else 0.0
    vol = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.0
    mean_daily = statistics.fmean(rets) if rets else 0.0
    sharpe = (mean_daily * 252) / vol if vol > 0 else 0.0
    peak = vals[0]
    maxdd = 0.0
    for v in vals:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1)
    return {
        "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "vol_pct": round(vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(maxdd * 100, 2),
    }


def yearly_returns(curve: list[tuple[str, float]]) -> dict[str, float]:
    by_year: dict[str, list[float]] = {}
    for d, v in curve:
        by_year.setdefault(d[:4], []).append(v)
    return {y: round((vs[-1] / vs[0] - 1) * 100, 2) for y, vs in by_year.items() if len(vs) >= 2 and vs[0] > 0}


def trade_stats(trades: list[dict]) -> dict[str, Any]:
    if not trades:
        return {"n": 0, "win_rate_pct": 0.0, "avg_win": 0, "avg_loss": 0, "avg_hold_days": 0.0, "profit_factor": 0.0}
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    return {
        "n": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "avg_win": round(gross_win / len(wins)) if wins else 0,
        "avg_loss": round(-gross_loss / len(losses)) if losses else 0,
        "avg_hold_days": round(statistics.fmean([t["hold_days"] for t in trades]), 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else 0.0,
    }


def build_report(result: dict, params: dict) -> str:
    s, b, e = result["strategy_metrics"], result["benchmark_metrics"], result["equal_weight_metrics"]
    ts = result["trade_stats"]
    alpha_total = round(s["total_return_pct"] - b["total_return_pct"], 2)
    alpha_cagr = round(s["cagr_pct"] - b["cagr_pct"], 2)
    verdict = "✅ 시장(Buy&Hold) 초과" if alpha_total > 0 else "❌ 시장(Buy&Hold) 미달 — 단순보유가 낫다"
    L = [
        f"# 백테스트 리포트 — 기계적 룰 베이스라인 ({params['start']} ~ {params['end']})",
        "",
        "> 이 백테스트는 **LLM 결정을 리플레이한 게 아니다.** policy.json 의 정량 규칙(모멘텀·레짐·사이징·",
        "> 손절)을 LLM 없이 결정론적으로 돌린 '기계적 베이스라인'이다. LLM 재량의 전진(forward) 페이퍼",
        "> 기록을 채점할 **잣대**로 쓴다. *기계 베이스라인조차 Buy&Hold 를 못 이기면, LLM 은 더 높은 바를 넘어야 한다.*",
        "",
        "## 헤드라인",
        "",
        f"- 기간: {params['start']} ~ {params['end']} · 거래일 {result['n_days']}일 · 초기자본 {params['capital']:,.0f}원",
        f"- 리밸런스: {params['rebalance_days']}거래일마다 · 유니버스 {result['n_universe']}종목 · 지수 {params['index_symbol']}",
        f"- **판정: {verdict}** (vs KOSPI 총수익 알파 {alpha_total:+.2f}%p, CAGR 알파 {alpha_cagr:+.2f}%p)",
        "",
        "| 지표 | 기계 베이스라인 | Buy&Hold KOSPI | EqualWeight 유니버스 |",
        "|---|---:|---:|---:|",
        f"| 총수익률 | {s['total_return_pct']:+.2f}% | {b['total_return_pct']:+.2f}% | {e['total_return_pct']:+.2f}% |",
        f"| CAGR | {s['cagr_pct']:+.2f}% | {b['cagr_pct']:+.2f}% | {e['cagr_pct']:+.2f}% |",
        f"| 변동성(연) | {s['vol_pct']:.2f}% | {b['vol_pct']:.2f}% | {e['vol_pct']:.2f}% |",
        f"| Sharpe | {s['sharpe']:.2f} | {b['sharpe']:.2f} | {e['sharpe']:.2f} |",
        f"| 최대낙폭(MDD) | {s['max_drawdown_pct']:.2f}% | {b['max_drawdown_pct']:.2f}% | {e['max_drawdown_pct']:.2f}% |",
        "",
        "## 거래 통계 (기계 베이스라인)",
        "",
        f"- 체결 거래: {ts['n']}건 · 승률 {ts['win_rate_pct']}% · Profit Factor {ts['profit_factor']}",
        f"- 평균 수익거래 {ts['avg_win']:,}원 / 평균 손실거래 {ts['avg_loss']:,}원 · 평균 보유 {ts['avg_hold_days']}일",
        f"- 평균 주식 노출도 {result['avg_exposure'] * 100:.1f}% · 정수반올림 진입불가 {result['degenerate_sizing_skips']}건",
        "",
        "## 연도별 수익률 (베이스라인 vs KOSPI)",
        "",
        "| 연도 | 베이스라인 | KOSPI | 알파 |",
        "|---|---:|---:|---:|",
    ]
    sy, by = result["strategy_yearly"], result["benchmark_yearly"]
    for y in sorted(set(sy) | set(by)):
        sv, bv = sy.get(y), by.get(y)
        a = round(sv - bv, 2) if sv is not None and bv is not None else None
        L.append(f"| {y} | {sv:+.2f}% | {bv:+.2f}% | {a:+.2f}%p |" if a is not None
                 else f"| {y} | {sv if sv is None else f'{sv:+.2f}%'} | {bv if bv is None else f'{bv:+.2f}%'} | - |")

    best = sorted(result["trades"], key=lambda t: t["return_pct"], reverse=True)[:3]
    worst = sorted(result["trades"], key=lambda t: t["return_pct"])[:3]
    L += ["", "## 베스트/워스트 거래", ""]
    for label, group in (("🟢 베스트", best), ("🔴 워스트", worst)):
        for t in group:
            L.append(f"- {label}: {t['ticker']} {t['entry_date']}→{t['exit_date']} "
                     f"{t['return_pct']:+.1f}% ({t['pnl']:+,}원, {t['reason']}, {t['hold_days']}일)")

    L += [
        "",
        "## ⚠️ 한계 (실거래 전 반드시 보정)",
        "",
        "1. **생존편향**: 유니버스가 *현재* 코스피 대형주라 과거 시점엔 부진주 탈락분이 빠져 수익률이 과대평가된다. → point-in-time 구성종목 필요.",
        "2. **가격수익 기준**: 배당 미반영(price return). 전략·KOSPI 모두 동일 기준이라 상대비교는 유효하나 절대 총수익은 과소.",
        "3. **체결 근사**: 일중 틱 없이 일봉 시/고/저로 체결. 갭·슬리피지·유동성·시장충격 미반영 → 실거래 괴리.",
        "4. **데이터 품질**: Yahoo 일봉 기반. 수정주가·분할·오류 가능성. 정밀 검증엔 KRX/증권사 데이터 권장.",
        "5. **파라미터 미최적화**: policy.json 기본값 그대로. 과최적화는 피했으나 민감도·워크포워드 검증은 다음 단계.",
        "",
        "> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.",
    ]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="기계적 룰 베이스라인 백테스트")
    ap.add_argument("--data-dir", default=None, help="가격 캐시 루트(기본 data/)")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--capital", type=float, default=None)
    ap.add_argument("--rebalance-days", type=int, default=5)
    ap.add_argument("--out-json", default="state/backtest_results.json")
    ap.add_argument("--out-report", default=None, help="기본 reports/backtest-<today>.md")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    policy = load_json("config/policy.json", {})
    capital = args.capital or policy.get("position_sizing", {}).get("initial_capital_krw", 5_000_000)
    data_dir = Path(args.data_dir).resolve() if args.data_dir else None

    series, index, _, index_symbol = load_universe(data_dir)
    if not series:
        print("ERROR: 가격 캐시가 비어 있다. 먼저 scripts/backfill_prices.py (GitHub Actions)로 data/ 를 채워라.")
        return 2
    dates = trading_calendar(index, series, args.start, args.end)
    if len(dates) < 30:
        print(f"ERROR: 거래일 {len(dates)}일 — 백테스트엔 데이터 부족. 백필 범위를 늘려라.")
        return 2

    bt = run_backtest(series, index, policy, dates, capital, args.rebalance_days)
    strat = bt["equity_curve"]
    bench = buy_hold_curve(index, dates, capital) if index else []
    ew = equal_weight_curve(series, dates, capital)

    result = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "params": {
            "start": dates[0], "end": dates[-1], "capital": capital,
            "rebalance_days": args.rebalance_days, "index_symbol": index_symbol,
        },
        "n_days": len(dates),
        "n_universe": len(series),
        "avg_exposure": bt["avg_exposure"],
        "degenerate_sizing_skips": bt["degenerate_sizing_skips"],
        "strategy_metrics": metrics(strat),
        "benchmark_metrics": metrics(bench) if bench else metrics(strat),
        "equal_weight_metrics": metrics(ew) if ew else {},
        "strategy_yearly": yearly_returns(strat),
        "benchmark_yearly": yearly_returns(bench) if bench else {},
        "trade_stats": trade_stats(bt["trades"]),
        "trades": bt["trades"],
        "final_equity": round(bt["final_equity"]),
    }

    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = build_report({**result, "trades": bt["trades"]}, result["params"])
    report_path = ROOT / (args.out_report or f"reports/backtest-{datetime.now(KST):%Y-%m-%d}.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    try:
        disp_path = report_path.relative_to(ROOT)
    except ValueError:
        disp_path = report_path
    if not args.quiet:
        s, b = result["strategy_metrics"], result["benchmark_metrics"]
        print(f"backtest {dates[0]}~{dates[-1]} ({len(dates)}d, {len(series)} tickers)")
        print(f"  strategy : total {s['total_return_pct']:+.2f}%  CAGR {s['cagr_pct']:+.2f}%  Sharpe {s['sharpe']}  MDD {s['max_drawdown_pct']}%")
        print(f"  KOSPI B&H: total {b['total_return_pct']:+.2f}%  CAGR {b['cagr_pct']:+.2f}%  Sharpe {b['sharpe']}  MDD {b['max_drawdown_pct']}%")
        print(f"  ALPHA    : {s['total_return_pct'] - b['total_return_pct']:+.2f}%p total / {s['cagr_pct'] - b['cagr_pct']:+.2f}%p CAGR")
        print(f"  trades {result['trade_stats']['n']} winrate {result['trade_stats']['win_rate_pct']}%  -> {disp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
