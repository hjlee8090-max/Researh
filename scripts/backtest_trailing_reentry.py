#!/usr/bin/env python3
"""4-A 검증 — 트레일링 청산 후 t+1 재진입 가설 백테스트.

가설(rule_attribution 표본 2건): 트레일링 청산의 t+1 일실이 +232,186원인데 t+5 는
-105,814원으로 부호가 뒤집힌다 → "너무 빨리 판 것"이 아니라 "판 다음 날 되사지 않은 것"이
문제다. 이 가설을 30종목 × 629거래일 백테스트 표본으로 검증한다.

검증 설계:
  - backtest_exit_overlay 의 overlay_full 시뮬레이션을 그대로 돌려 트레일링 청산 이벤트를 수집
  - 각 청산에 대해 "t+1 종가 > 청산가면 t+1 종가에 재진입" 반사실을 계산
  - 재진입 후 보유는 t+5 / t+10 / 다음 리밸런스 세 지평으로 평가
  - 왕복 비용(매수 0.20% + 매도 0.38% = 0.58%)을 전부 차감한 순효과로 판정
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, "/home/user/Researh/scripts")
import backtest_exit_overlay as bxo  # noqa: E402

REPO = Path("/home/user/Researh")
ROUNDTRIP_COST = bxo.COST_BUY + bxo.COST_SELL  # 0.0058
TRAIL_RULES = {"trail_first_partial_50", "trail_residual_exit"}


def fwd_close(series, dates, i, k):
    """i 로부터 k 거래일 뒤 종가(해당 종목 시리즈에 값이 있는 날 기준)."""
    j = i + k
    return series.get(dates[j]) if 0 <= j < len(dates) else None


def analyse(tickers, dates, cfg, start_idx, end_idx, label):
    _curve, events, _n, _t = bxo.simulate(tickers, dates, cfg, "overlay_full",
                                          start_idx, end_idx)
    bxo.annotate_whipsaws(events, tickers, dates)

    trail = [e for e in events if e["rule"] in TRAIL_RULES]
    rows = []
    for e in trail:
        s = tickers[e["ticker"]]["series"]
        i, px = e["i"], e["exit_price"]
        t1 = fwd_close(s, dates, i, 1)
        if t1 is None:
            continue
        triggered = t1 > px            # 재진입 조건: t+1 종가가 청산가 상회
        rec = {
            "ticker": e["ticker"], "date": dates[i], "rule": e["rule"],
            "exit_price": px, "t1": t1,
            "t1_vs_exit_pct": (t1 / px - 1) * 100,
            "triggered": triggered,
            "whipsaw": e.get("whipsaw"),
        }
        for k in (5, 10, 21):
            fw = fwd_close(s, dates, i, k)
            # 재진입 수익 = t+1 매수 → t+k 매도, 왕복 비용 차감
            rec[f"reentry_net_t{k}_pct"] = (
                ((fw / t1) - 1) * 100 - ROUNDTRIP_COST * 100 if (triggered and fw) else None
            )
        rows.append(rec)

    trig = [r for r in rows if r["triggered"]]
    out = {
        "window": label,
        "period": f"{dates[start_idx]}~{dates[end_idx]}",
        "trailing_exits": len(rows),
        "reentry_triggered": len(trig),
        "trigger_rate_pct": round(len(trig) / len(rows) * 100, 1) if rows else None,
        # 부분익절은 annotate_whipsaws 가 whipsaw=None 으로 판정 제외한다 —
        # None 을 분모에 넣으면 휩쏘율이 인위적으로 0 에 수렴한다(판정 대상만 분모).
        "whipsaw_scored_n": sum(1 for r in rows if r["whipsaw"] is not None),
        "whipsaw_rate_pct": (
            round(sum(1 for r in rows if r["whipsaw"]) /
                  sum(1 for r in rows if r["whipsaw"] is not None) * 100, 1)
            if any(r["whipsaw"] is not None for r in rows) else None),
    }
    for k in (5, 10, 21):
        vals = [r[f"reentry_net_t{k}_pct"] for r in trig
                if r[f"reentry_net_t{k}_pct"] is not None]
        if not vals:
            out[f"t{k}"] = {"n": 0, "status": "표본 없음"}
            continue
        vals_sorted = sorted(vals)
        out[f"t{k}"] = {
            "n": len(vals),
            "mean_net_pct": round(sum(vals) / len(vals), 2),
            "median_net_pct": round(vals_sorted[len(vals) // 2], 2),
            "win_rate_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
            "best_pct": round(max(vals), 2),
            "worst_pct": round(min(vals), 2),
            "sum_net_pct": round(sum(vals), 2),
        }
    return out, rows


def main():
    tickers, _index, dates = bxo.load_history_ohlc()
    n = len(dates)
    warmup = 201
    recent_idx = next(i for i, d in enumerate(dates) if d >= bxo.RECENT_WINDOW_START)

    report = {
        "as_of": "2026-08-03T12:30:00+09:00",
        "purpose": (
            "sunday_policy_review 후보 C — 트레일링 청산 후 t+1 재진입 규칙의 사전 검증. "
            "rule_attribution 표본 2건(t+1 일실 +232,186원 vs t+5 -105,814원)만으로는 "
            "규칙화가 불가하다는 판단에 따라 백테스트 표본으로 확대 검증."
        ),
        "design": {
            "reentry_condition": "트레일링 청산 후 t+1 종가 > 청산가",
            "entry_price": "t+1 종가",
            "exit_horizons": ["t+5", "t+10", "t+21(다음 월간 리밸 근사)"],
            "cost": f"왕복 {ROUNDTRIP_COST*100:.2f}% (매수 {bxo.COST_BUY*100:.2f}% + 매도 "
                    f"{bxo.COST_SELL*100:.2f}%) 전액 차감",
            "baseline": "현행 규칙 = 재진입 없음(현금 대기) → 수익 0%",
        },
        "data_window": {"start": dates[0], "end": dates[-1], "trading_days": n,
                        "tickers": len(tickers)},
        "results": {},
    }

    all_rows = []
    for cfg_label, cfg in bxo.CONFIGS:
        report["results"][cfg_label] = {}
        for wlabel, s, e in [("full", warmup, n - 1), ("recent_2026", recent_idx, n - 1)]:
            out, rows = analyse(tickers, dates, cfg, s, e, wlabel)
            report["results"][cfg_label][wlabel] = out
            all_rows.extend(rows)

    # ---- 판정 ----
    live_label = next((l for l in report["results"] if "policy momentum_strategy" in l),
                      bxo.CONFIGS[0][0])
    report["verdict_basis"] = (
        f"판정 기준 = '{live_label}' (실제 운용 설정). 검증용 Top10·월간리밸 설정은 참고로만 "
        "본다 — 규칙은 라이브 파라미터에서 값을 해야 채택할 수 있다.")
    prim = report["results"][live_label]["full"]
    t5, t21 = prim.get("t5", {}), prim.get("t21", {})
    n5 = t5.get("n", 0)
    if n5 < 5:
        verdict = f"채점 보류 — 표본 부족(n={n5} < 5)"
    else:
        pos = [h for h in ("t5", "t10", "t21")
               if (prim.get(h, {}).get("mean_net_pct") or 0) > 0]
        if len(pos) >= 2 and (t5.get("win_rate_pct") or 0) >= 50:
            verdict = (f"채택 후보 — {len(pos)}/3 지평에서 평균 순수익 양수, "
                       f"t+5 승률 {t5.get('win_rate_pct')}%")
        elif not pos:
            verdict = ("기각 — 전 지평에서 평균 순수익이 음수. 왕복 비용 "
                       f"{ROUNDTRIP_COST*100:.2f}% 를 넘는 반등이 나오지 않는다")
        else:
            verdict = (f"경계 — {len(pos)}/3 지평만 양수(t+5 승률 "
                       f"{t5.get('win_rate_pct')}%). 그림자 관측 권고")
    report["verdict"] = verdict

    (REPO / "state/backtest_trailing_reentry.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 출력 ----
    print("### 트레일링 청산 t+1 재진입 백테스트 (후보 C 검증)")
    print(f"- 데이터: {len(tickers)}종목 × {n}거래일 ({dates[0]} ~ {dates[-1]})")
    print(f"- 재진입 조건: 트레일링 청산 후 t+1 종가 > 청산가 · 진입가 = t+1 종가")
    print(f"- 비용: 왕복 {ROUNDTRIP_COST*100:.2f}% 전액 차감 · 기준선(현행 규칙) = 0%\n")
    for cfg_label in report["results"]:
        for wlabel, out in report["results"][cfg_label].items():
            print(f"#### {cfg_label} — {wlabel} ({out['period']})")
            wr = out['whipsaw_rate_pct']
            print(f"- 트레일링 청산 {out['trailing_exits']}건 · 재진입 트리거 "
                  f"{out['reentry_triggered']}건({out['trigger_rate_pct']}%) · "
                  f"휩쏘율 {wr}%(잔여청산 {out['whipsaw_scored_n']}건 기준)")
            print("| 보유 지평 | n | 평균 순수익 | 중앙값 | 승률 | 최고 | 최저 | 합계 |")
            print("|---|---|---|---|---|---|---|---|")
            for k in (5, 10, 21):
                h = out.get(f"t{k}", {})
                if not h.get("n"):
                    print(f"| t+{k} | 0 | 표본 없음 | | | | | |")
                    continue
                print(f"| t+{k} | {h['n']} | {h['mean_net_pct']:+.2f}% | "
                      f"{h['median_net_pct']:+.2f}% | {h['win_rate_pct']}% | "
                      f"{h['best_pct']:+.2f}% | {h['worst_pct']:+.2f}% | "
                      f"{h['sum_net_pct']:+.2f}%p |")
            print()
    print(f"**판정: {verdict}**")
    print(f"> {report['verdict_basis']}")
    print("\nwrote state/backtest_trailing_reentry.json")


if __name__ == "__main__":
    main()
