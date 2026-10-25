#!/usr/bin/env python3
"""실제 2026 약세장에서 사전 등록 레짐 필터를 검증한다 (표본외 검증).

배경: backtest_bear.py 는 약세장 데이터가 없어 합성 드리프트로만 검증했다. 2026-06-22 고점
이후 KOSPI 가 약 -39% 빠지면서 price_history.json 에 실제 약세장이 쌓였다.
state/backtest_bear.json(as_of 2026-07-01)이 기록한 regime_configs 를 그대로 쓰므로,
2026-07-01 이후 구간은 규칙이 정해진 뒤의 데이터 = 진짜 표본외다.

변형:
  - 레짐 OFF (Top6·42일 / Top10·42일 검증 권장)
  - index_ma·breadth 레짐 (사전 등록 그대로 — backtest() 가 리밸런스일에만 레짐을 확인)
  - 같은 레짐을 매일 확인하는 변형 — 사전 등록이 아닌 탐색용(메커니즘 확인, 채택 근거 금지)

마지막 봉이 장중 수집분일 수 있어 END_DATE 이전 확정 종가만 쓴다.
산출: state/backtest_bear_realdata.json + 표준출력. 학습·시뮬레이션 목적, 표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_strategy as bs  # noqa: E402

# backtest_bear.json regime_configs (2026-07-01 등록) — 바꾸면 표본외 성격이 사라진다.
INDEX_MA = dict(index_ma=200, enter_days=5, exit_days=15)
BREADTH = dict(low=0.40, high=0.55, enter_days=3, exit_days=5)
BASE = dict(top_n=6, rebal_days=42)
WINDOWS = {
    "live_since_2026-05-20": "2026-05-20",          # 라이브 첫 가동
    "oos_since_2026-07-01": "2026-07-01",           # 레짐 규칙 등록일
    "freeze_since_2026-09-02": "2026-09-02",        # 정책 동결·그림자 계좌 시작
}


def daily_regime_backtest(tickers, dates, flags, start_idx, end_idx, top_n, rebal_days):
    """탐색용 — 레짐을 매일 확인해 방어 전환 즉시 전량 현금, 복귀 즉시 재선정."""
    equity, holdings, last, curve, n_tr = 1.0, {}, {}, [], 0
    since, was_def = 0, None
    for i in range(start_idx, end_idx + 1):
        d = dates[i]
        if holdings:
            g = 0.0
            for tk, w in holdings.items():
                p, q = tickers[tk]["series"].get(d), last.get(tk)
                g += w * (p / q) if p and q else w
            equity *= g + (1.0 - sum(holdings.values()))
        for tk in tickers:
            p = tickers[tk]["series"].get(d)
            if p:
                last[tk] = p
        curve.append((d, equity))
        defensive = flags[i]
        flip = was_def is not None and defensive != was_def
        was_def = defensive
        if not (since % rebal_days == 0 or flip):
            since += 1
            continue
        since = 1 if flip else since + 1
        target = {}
        if not defensive:
            scored = []
            for tk, v in tickers.items():
                s = v["series"]
                if not s.get(d):
                    continue
                mf, ms = bs.pct_return(s, dates, i, 60), bs.pct_return(s, dates, i, 120)
                ma = bs.sma(s, dates, i, 200)
                if mf is None or ms is None or ma is None:
                    continue
                score = 0.5 * mf + 0.5 * ms
                if score > 0 and s[d] >= ma:
                    scored.append((score, tk))
            scored.sort(reverse=True)
            target = {tk: 1.0 / top_n for _, tk in scored[:top_n]}
        cost = sum(holdings[t] * bs.COST_SELL for t in set(holdings) - set(target))
        cost += sum(target[t] * bs.COST_BUY for t in set(target) - set(holdings))
        n_tr += len(set(holdings) ^ set(target))
        equity *= 1.0 - cost
        holdings = target
    return curve, n_tr


def switches(flags, dates, end_idx, since):
    out, prev = [], None
    for i, d in enumerate(dates[: end_idx + 1]):
        if d >= since and flags[i] != prev:
            out.append({"date": d, "state": "defensive" if flags[i] else "invested"})
        prev = flags[i]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="실제 약세장 레짐 필터 표본외 검증")
    ap.add_argument("--end", default="2026-10-22", help="마지막 확정 종가일 (장중 봉 제외)")
    args = ap.parse_args()

    tickers, idx, dates = bs.load_history()
    end_i = max(i for i, d in enumerate(dates) if d <= args.end)
    hflags = bs.compute_regime_hysteresis(idx, dates, **INDEX_MA)
    breadth = bs.compute_breadth(tickers, dates, 200)
    bflags = bs.compute_regime_breadth(breadth, dates, **BREADTH)

    def run(start_idx):
        rows = {"kospi_buy_hold": bs.metrics(bs.benchmark_curve(idx, dates, start_idx, end_i))}
        for key, top in (("top6_42_off", 6), ("top10_42_off", 10)):
            c, _, n = bs.backtest(tickers, idx, dates, top_n=top, rebal_days=42, start_idx=start_idx,
                                  end_idx=end_i, use_index_regime=False)
            rows[key] = {**bs.metrics(c), "n_trades": n}
        for key, fl in (("index_ma", hflags), ("breadth", bflags)):
            c, _, n = bs.backtest(tickers, idx, dates, start_idx=start_idx, end_idx=end_i,
                                  regime_flags=fl, **BASE)
            rows[f"top6_42_{key}_preregistered"] = {**bs.metrics(c), "n_trades": n}
            c, n = daily_regime_backtest(tickers, dates, fl, start_idx, end_i, **BASE)
            rows[f"top6_42_{key}_daily_exploratory"] = {**bs.metrics(c), "n_trades": n}
        return rows

    def first_at(d):
        return min(i for i, x in enumerate(dates) if x >= d)

    results = {k: run(first_at(v)) for k, v in WINDOWS.items()}
    results["full_since_warmup"] = run(201)

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "data_window": {"start": dates[0], "end": dates[end_i], "trading_days": end_i + 1},
        "method": "실데이터(합성 아님). backtest_strategy 엔진·비용 그대로, 오버레이 없음.",
        "preregistered": {"source": "state/backtest_bear.json regime_configs (2026-07-01)",
                          "index_ma": INDEX_MA, "breadth": BREADTH, "base": BASE},
        "windows": {**WINDOWS, "full_since_warmup": dates[201]},
        "results": results,
        "regime_switches_since_2026-05-01": {
            "index_ma": switches(hflags, dates, end_i, "2026-05-01"),
            "breadth": switches(bflags, dates, end_i, "2026-05-01"),
        },
        "breadth_latest": round(breadth[dates[end_i]], 3) if breadth.get(dates[end_i]) else None,
        "caveats": [
            "단일 약세 국면·5개월 표본 — 일반화 금지.",
            "daily_exploratory 는 사전 등록이 아니다. 구간에 따라 순위가 뒤집혀(경로 운) 채택 근거로 쓰지 않는다.",
            "breadth 의 재진입 지연(V자 반등을 놓칠 위험)은 이 데이터로 검증되지 않았다.",
        ],
        "note": "학습·시뮬레이션 목적. 과거 성과는 미래 수익을 보장하지 않는다.",
    }
    (ROOT / "state" / "backtest_bear_realdata.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{'구간':<26}{'KOSPI':>9}{'OFF(6)':>9}{'breadth':>9}{'index_ma':>9}")
    for k, r in results.items():
        print(f"{k:<26}{r['kospi_buy_hold']['total_return_pct']:>8}%"
              f"{r['top6_42_off']['total_return_pct']:>8}%"
              f"{r['top6_42_breadth_preregistered']['total_return_pct']:>8}%"
              f"{r['top6_42_index_ma_preregistered']['total_return_pct']:>8}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
