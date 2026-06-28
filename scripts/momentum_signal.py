#!/usr/bin/env python3
"""모멘텀 로테이션 실거래 신호 생성기 — 백테스트로 검증된 전략을 매 리밸런스 시점의
'오늘 목표 포트폴리오'로 변환한다. routine prompt(09/18시)가 읽어 진입/회전 판단의 1차 입력으로 쓴다.

전략(backtest_strategy.py 에서 walk-forward 로 검증·고정):
  - 유니버스: state/price_history.json 의 대형주(KRX 시총 상위) 30종목.
  - 신호: 점수 = 0.5×60일수익률 + 0.5×120일수익률, 단 가격>MA200(추세) AND 절대모멘텀>0 통과분만.
  - 보유: 점수 상위 10종목 동일가중(통과 종목<10 이면 잔여 현금 — 추세 없는 시장엔 강제 배치 금지).
  - 리밸런스 주기: 약 1개월(21거래일). 저회전으로 거래비용·휩쏘 억제.

설계 원칙(현 파이프라인의 패배 원인 교정):
  - 강세장에서 현금 보유가 최대 적 → '추세가 살아있는 한 항시투자'를 기본값으로.
  - 단, 개별 추세필터(가격>MA200)로 하락 종목은 자동 배제 → 무차별 buy&hold 가 아님.
  - 데이터 신뢰도가 낮으면(가격 결측) 신호를 보류하고 직전 목표를 유지(stale 가격 추격 금지).

산출: state/momentum_signal.json (목표 바스켓 + 진입/이탈 변경분 + 종목별 점수).
의존성: Python 표준 라이브러리만. 네트워크 0(레포 내 price_history.json 사용 — Actions 가 갱신).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# 검증된 권장 파라미터(backtest_strategy.json.recommended_config 와 일치)
TOP_N = 10
MOM_FAST = 60
MOM_SLOW = 120
TREND_MA = 200


def load():
    d = json.load(open(ROOT / "state" / "price_history.json"))
    tickers = {}
    for tk, v in d["tickers"].items():
        bars = [b for b in (v.get("bars") or []) if b.get("close")]
        if len(bars) < TREND_MA + 5:
            continue
        bars.sort(key=lambda b: b["date"])
        tickers[tk] = {"name": v.get("name", tk),
                       "dates": [b["date"] for b in bars],
                       "closes": [float(b["close"]) for b in bars]}
    return tickers, d.get("as_of")


def score_ticker(closes):
    cur = closes[-1]
    p_fast = closes[-1 - MOM_FAST]
    p_slow = closes[-1 - MOM_SLOW]
    ma = sum(closes[-TREND_MA:]) / TREND_MA
    mom_fast = (cur / p_fast - 1) * 100
    mom_slow = (cur / p_slow - 1) * 100
    score = 0.5 * mom_fast + 0.5 * mom_slow
    in_uptrend = cur >= ma
    return {
        "close": round(cur, 1),
        "ma200": round(ma, 1),
        "mom60_pct": round(mom_fast, 1),
        "mom120_pct": round(mom_slow, 1),
        "score": round(score, 2),
        "in_uptrend": in_uptrend,
        "pct_vs_ma200": round((cur / ma - 1) * 100, 1),
    }


def executable_allocation(eligible, equity, min_cash_pct=10.0, per_name_cap_pct=30.0):
    """백테스트 바스켓을 '이 계좌 크기'의 정수주 매수 주문으로 변환한다.

    제약: 종목당 비중 ≤ per_name_cap_pct(1주가 상한 초과면 제외 — 예: 초고가주),
    현금 최소 min_cash_pct 확보, 점수 상위부터 ~동일가중으로 정수주 배분.
    """
    deployable = equity * (1 - min_cash_pct / 100.0)
    cap_krw = equity * per_name_cap_pct / 100.0
    # 1주조차 종목당 상한을 넘는 초고가주는 제외(분산·상한 준수)
    cand = [r for r in eligible if r["close"] <= cap_krw]
    n = min(TOP_N, len(cand))
    if n == 0:
        return [], equity, 0.0
    per_name = deployable / n
    orders, spent = [], 0.0
    for r in cand[:n]:
        shares = round(per_name / r["close"])
        # 종목당 상한 준수
        while shares * r["close"] > cap_krw and shares > 0:
            shares -= 1
        # 잔여 예산 준수
        while shares * r["close"] > (deployable - spent) and shares > 0:
            shares -= 1
        # 점수 통과 종목은 최소 1주는 담되, 예산·상한 둘 다 허용할 때만
        if shares == 0 and r["close"] <= (deployable - spent) and r["close"] <= cap_krw:
            shares = 1
        if shares <= 0:
            continue
        cost = shares * r["close"]
        spent += cost
        orders.append({"ticker": r["ticker"], "name": r["name"], "shares": shares,
                       "price": r["close"], "cost": round(cost),
                       "weight_pct": round(cost / equity * 100, 1), "score": r["score"]})
    cash_left = equity - spent
    return orders, round(cash_left), round(cash_left / equity * 100, 1)


def main():
    tickers, data_as_of = load()
    ranked = []
    for tk, v in tickers.items():
        s = score_ticker(v["closes"])
        s["ticker"] = tk
        s["name"] = v["name"]
        s["pass_filter"] = bool(s["in_uptrend"] and s["score"] > 0)
        ranked.append(s)

    eligible = sorted([r for r in ranked if r["pass_filter"]],
                      key=lambda r: -r["score"])
    target = eligible[:TOP_N]
    target_tickers = [r["ticker"] for r in target]
    weight = round(1.0 / TOP_N, 4)
    cash_weight = round(1.0 - weight * len(target), 4)

    # 직전 신호와 비교해 진입/이탈 변경분 산출
    prev_path = ROOT / "state" / "momentum_signal.json"
    prev_target = []
    if prev_path.exists():
        try:
            prev_target = [h["ticker"] for h in json.load(open(prev_path)).get("target_basket", [])]
        except Exception:
            prev_target = []
    enters = [t for t in target_tickers if t not in prev_target]
    exits = [t for t in prev_target if t not in target_tickers]

    # 실거래 정수주 배분 — portfolio.json 의 현재 equity 기준
    equity = 5_000_000.0
    try:
        equity = float(json.load(open(ROOT / "config" / "portfolio.json")).get("equity", equity))
    except Exception:
        pass
    exec_orders, cash_left, cash_left_pct = executable_allocation(eligible, equity)

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "data_as_of": data_as_of,
        "strategy": "dual-momentum rotation Top10, monthly rebalance, MA200 trend filter, always-invested",
        "config": {"top_n": TOP_N, "mom_fast": MOM_FAST, "mom_slow": MOM_SLOW, "trend_ma": TREND_MA},
        "executable_allocation": {
            "equity": round(equity),
            "constraints": {"min_cash_pct": 10.0, "per_name_cap_pct": 30.0,
                            "excluded_too_expensive": [r["ticker"] for r in eligible
                                                       if r["close"] > equity * 0.30][:TOP_N]},
            "orders": exec_orders,
            "cash_left": cash_left,
            "cash_left_pct": cash_left_pct,
            "note": "data_as_of 가격 기준 지시적 수량 — 실제 체결 routine 이 개장 fresh 가격으로 종목당 상한 내 재산정.",
        },
        "equal_weight_pct": round(weight * 100, 2),
        "cash_weight_pct": round(cash_weight * 100, 2),
        "n_eligible": len(eligible),
        "target_basket": [
            {"ticker": r["ticker"], "name": r["name"], "weight_pct": round(weight * 100, 2),
             "score": r["score"], "mom60_pct": r["mom60_pct"], "mom120_pct": r["mom120_pct"],
             "close": r["close"], "pct_vs_ma200": r["pct_vs_ma200"]}
            for r in target
        ],
        "rebalance_changes": {"enter": enters, "exit": exits},
        "full_ranking": sorted(ranked, key=lambda r: -r["score"]),
        "caveats": [
            "data_as_of 가 오래됐으면(주말/공휴일/Actions 미실행) stale — 18시·09시 routine 은 fresh 가격 확인 후 적용.",
            "리밸런스 주기는 약 21거래일. 매일 강제 회전 금지(거래비용·휩쏘).",
            "학습·시뮬레이션 목적. 미래 수익 보장 아님.",
        ],
    }
    prev_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"데이터 기준일: {data_as_of}")
    print(f"적격(추세+모멘텀 통과) 종목: {len(eligible)}개 / 전체 {len(ranked)}개")
    print(f"목표 바스켓 Top{TOP_N} (각 {weight*100:.1f}%, 현금 {cash_weight*100:.1f}%):")
    for r in target:
        print(f"  {r['name']:<12}({r['ticker']}) score {r['score']:+7.1f} | "
              f"60d {r['mom60_pct']:+6.1f}% 120d {r['mom120_pct']:+6.1f}% | vsMA200 {r['pct_vs_ma200']:+.1f}%")
    if enters or exits:
        print(f"\n변경분 — 신규진입: {enters or '없음'} / 이탈: {exits or '없음'}")
    print(f"\n=== 실행 가능 정수주 배분 (equity {equity:,.0f}원) ===")
    for o in exec_orders:
        print(f"  {o['name']:<12}({o['ticker']}) {o['shares']:>2}주 × {o['price']:>10,.0f} = "
              f"{o['cost']:>11,.0f}원 ({o['weight_pct']:.1f}%)")
    print(f"  현금잔여: {cash_left:,.0f}원 ({cash_left_pct:.1f}%)")
    print(f"\n저장: state/momentum_signal.json")


if __name__ == "__main__":
    main()
