#!/usr/bin/env python3
"""계좌 정합 백테스트 — 정수주·종목당 상한·현금 하한을 넣은 듀얼모멘텀을 파라미터 그리드로 재실행한다.

왜: policy_freeze.backlog[0] 은 top_n·min_score·유니버스 정합 결정의 전제로 "정수주 제약 포함
백테스트 재실행"을 요구한다. backtest_strategy.py 는 무제약(비율 배분)이고 min_score 를 검증한 적이
없다. 그림자 계좌 엔진(shadow_account.simulate — 정수주·상한·비용 포함, 오버레이 없음)을 그대로
빌려 같은 계좌 크기에서 어떤 (top_n, min_score, rebal_days) 가 강건한지 본다.

무엇: 창(window) × 파라미터 × 유니버스 조합을 전부 돌려 총수익·vs KOSPI·MDD·평균 주식비중·
"바스켓이 빈 날 비율"을 표로 낸다. 선택 유니버스는 --extra-history 로 ETF 등 추가 일봉을 합친다
(price_history.json 은 건드리지 않는다).

산출: state/backtest_account_fit.json + 표준출력 표. 표준 라이브러리만, 네트워크 0.
학습·시뮬레이션 목적 — 과거 성과는 미래 수익을 보장하지 않는다.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from shadow_account import KST, load_costs, load_history, load_json, metrics, simulate  # noqa: E402

OUT = ROOT / "state" / "backtest_account_fit.json"

WINDOWS = [
    # label, start, capital, note
    ("since_freeze", "2026-09-02", 4_650_961, "Stage 0 동결 이후 — 라이브 대조 구간(라이브 -1.02% @9/22)"),
    ("since_crash", "2026-06-30", 5_000_000, "7월 크래시(-20.6%) 포함 — 약세 전환 스트레스"),
    ("since_2025", "2025-01-02", 5_000_000, "장기(21개월) — 강세장 대부분 포함"),
]
GRID = {
    "top_n": [4, 6, 10],
    "min_score": [0.0, 10.0, 20.0, 30.0],
    "rebal_days": [21, 42],
}


def merge_extra(tickers, path):
    d = json.load(open(path, encoding="utf-8"))
    n = 0
    for tk, v in d.items():
        if not isinstance(v, dict):  # as_of·source·note 같은 메타 키는 건너뛴다
            continue
        bars = [b for b in (v.get("bars") or []) if b.get("close")]
        if len(bars) < 200:
            continue
        tickers[tk] = {"name": v.get("name", tk), "series": {b["date"]: float(b["close"]) for b in bars}}
        n += 1
    return n


def empty_days(curve):
    return round(sum(1 for c in curve if c["n_pos"] == 0) / len(curve) * 100, 1) if curve else None


def run(tickers, index_series, dates, costs, cap_pct, min_cash_pct, universe_label):
    rows = []
    for wlabel, start, capital, wnote in WINDOWS:
        for top_n, min_score, rebal in itertools.product(GRID["top_n"], GRID["min_score"], GRID["rebal_days"]):
            cfg = {"top_n": top_n, "min_score": min_score, "rebal_days": rebal, "trend_ma": 200,
                   "mom_fast": 60, "mom_slow": 120, "cap_pct": cap_pct, "min_cash_pct": min_cash_pct}
            res = simulate(tickers, index_series, dates, cfg, costs, start, capital)
            m = metrics(res["curve"], index_series)
            rows.append({"universe": universe_label, "window": wlabel, "start": res["start_date"],
                         "top_n": top_n, "min_score": min_score, "rebal_days": rebal,
                         "total_return_pct": m.get("total_return_pct"), "kospi_pct": m.get("kospi_pct"),
                         "vs_kospi_pp": m.get("vs_kospi_pp"), "max_drawdown_pct": m.get("max_drawdown_pct"),
                         "sharpe": m.get("sharpe_annualized"), "avg_stock_pct": m.get("avg_stock_pct"),
                         "empty_days_pct": empty_days(res["curve"]), "n_trades": len([t for t in res["trades"] if t["action"] in ("BUY", "SELL")]),
                         "costs_paid": res["costs_paid"],
                         "final_positions": [f"{p['name']}x{p['shares']}" for p in res["positions"]]})
    return rows


def table(rows, window):
    print(f"\n## window={window}")
    print("| universe | top_n | min_score | rebal | 수익% | KOSPI% | vs KOSPI | MDD% | 평균주식% | 빈날% | 체결 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted([r for r in rows if r["window"] == window], key=lambda r: (r["universe"], r["top_n"], r["min_score"], r["rebal_days"])):
        print(f"| {r['universe']} | {r['top_n']} | {r['min_score']:.0f} | {r['rebal_days']} | {r['total_return_pct']:+.2f} | {r['kospi_pct']:+.2f} | "
              f"{r['vs_kospi_pp']:+.2f} | {r['max_drawdown_pct']:.2f} | {r['avg_stock_pct']:.1f} | {r['empty_days_pct']:.1f} | {r['n_trades']} |")


def main() -> int:
    ap = argparse.ArgumentParser(description="계좌 정합(정수주) 듀얼모멘텀 그리드 백테스트")
    ap.add_argument("--extra-history", help="추가 일봉 JSON({ticker:{name,bars[]}}) — ETF 등 유니버스 보강 변형")
    ap.add_argument("--cap-pct", type=float, help="종목당 상한 %% (기본 policy.position_sizing.max_position_weight_pct)")
    ap.add_argument("--dry-run", action="store_true", help="파일 미기록")
    args = ap.parse_args()

    policy = load_json("config/policy.json", {})
    ps = policy.get("position_sizing") or {}
    cap_pct = args.cap_pct if args.cap_pct is not None else float(ps.get("max_position_weight_pct", 35.0))
    min_cash_pct = float(ps.get("min_cash_weight_pct", 5.0))
    costs = load_costs(policy)
    tickers, index_series, dates, as_of = load_history()

    rows = run(tickers, index_series, dates, costs, cap_pct, min_cash_pct, "base30")
    extra_n = 0
    if args.extra_history:
        extra_n = merge_extra(tickers, args.extra_history)
        rows += run(tickers, index_series, dates, costs, cap_pct, min_cash_pct, f"base30+etf{extra_n}")

    for wlabel, *_ in WINDOWS:
        table(rows, wlabel)

    out = {"as_of": datetime.now(KST).isoformat(timespec="seconds"), "data_as_of": as_of,
           "engine": "scripts/shadow_account.simulate (정수주·종목당 상한·현금 하한·거래비용, 오버레이 없음)",
           "cap_pct": cap_pct, "min_cash_pct": min_cash_pct, "costs": costs,
           "windows": [{"label": w[0], "start": w[1], "capital": w[2], "note": w[3]} for w in WINDOWS],
           "grid": GRID, "extra_history": args.extra_history, "extra_tickers_merged": extra_n, "rows": rows,
           "note": "학습·시뮬레이션 목적. 과거 성과는 미래 수익을 보장하지 않는다. ETF 변형은 --extra-history 로만 합친 것이며 price_history.json·universe 는 무변경."}
    if not args.dry_run:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {OUT.relative_to(ROOT)} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
