#!/usr/bin/env python3
"""주문 의도(order intents) 생성기 — Stage 1: 체결 결정권을 LLM 에서 코드로 옮기는 첫 단계(dry-run).
(reports/2026-09-02-pipeline-review.md §6-1 Stage 1 · docs/plan_stage1.md)

무엇: 매 실행마다 '명세가 시키는 주문'을 결정론적으로 산출해 state/order_intents.json 에 쓴다.
  - 진입: state/momentum_signal.json 의 executable_allocation.orders(검증 엔진의 정수주 바스켓) 중
          미보유 종목을, 리밸런스일에만, 빈 슬롯(top_n − 보유) 수만큼. 가용 현금·종목당 상한으로 재사이징.
  - 청산(매일 종가 판정, 하드 룰 3개만): ①hard_stop — 종가 ≤ position.stop_price
          ②trend_break — 종가 < MA200 ③rebalance_rotation — 리밸런스일에 자격(추세·모멘텀>0) 이탈 또는 Top-N 초과분.
  - 그 외 청산 룰(트레일링·목표익절·orange/red·give-back·R/R 손절상향·estimate review·thesis 무효화)은
    **shadow_signals** 로 관측만 한다 — 발동했더라도 주문 의도가 아니다(청산 오버레이 백테스트가 가치 파괴로 판정).
왜: 라이브가 따른다고 선언한 명세와 실제 집행이 달랐다(P1). 코드가 의도를 먼저 쓰고 LLM 이 거부권만 행사하면
  "LLM 레이어가 더했는가 뺐는가"를 의도 대비 실제(adherence)·거부 손익으로 채점할 수 있다(score_order_intents.py).

실행 소유권(state/stage.json.execution_owner):
  - "llm"  : dry-run. 루틴이 각 의도에 disposition {action: executed|vetoed|expired, reason, by, trade_ts} 를 기입한다.
             의도 밖 매매는 trade_log 라인에 off_intent_reason 필수.
  - "code" : cutover. 의도가 곧 주문(브로커 연결은 Stage 2). 전환 기준은 plan_stage1 §3.
안전: 정책 파라미터를 읽기만 한다(동결 무관). 네트워크 0. 매 실행 직전 파일의 의도는 로그(order_intents_log.jsonl)에 upsert 보존.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT = ROOT / "state" / "order_intents.json"
LOG = ROOT / "state" / "order_intents_log.jsonl"
sys.path.insert(0, str(ROOT / "scripts"))


def load_json(rel, default=None):
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def d10(s):
    return s[:10] if isinstance(s, str) and len(s) >= 10 else ""


def trading_dates():
    """price_history 지수 봉의 거래일 축(리밸런스 그리드용)."""
    h = load_json("state/price_history.json") or {}
    return sorted(b["date"] for b in (h.get("index", {}).get("bars") or []) if b.get("close"))


def ma200_map():
    """종목별 MA200 — momentum_signal.full_ranking 이 이미 계산해 둔 값을 쓴다(단일 산식)."""
    return {}


def preserve_previous():
    """직전 order_intents.json 의 의도(disposition 포함)를 로그에 upsert — 덮어쓰기 전 보존."""
    prev = load_json("state/order_intents.json")
    if not prev or not prev.get("intents"):
        return 0
    existing = {}
    if LOG.exists():
        for line in open(LOG, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                existing[r["id"]] = r
            except Exception:
                continue
    for it in prev["intents"]:
        rec = dict(it)
        rec["built_at"] = prev.get("as_of")
        rec["data_date"] = prev.get("data_date")
        rec["execution_owner"] = prev.get("execution_owner")
        existing[rec["id"]] = rec  # 최신 disposition 이 이긴다
    LOG.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in sorted(existing.values(), key=lambda r: r["id"])),
                   encoding="utf-8")
    return len(prev["intents"])


def main() -> int:
    ap = argparse.ArgumentParser(description="주문 의도 생성(Stage 1)")
    ap.add_argument("--dry-run", action="store_true", help="파일 미기록, 결과만 출력")
    args = ap.parse_args()

    policy = load_json("config/policy.json", {})
    stage = load_json("state/stage.json", {"stage": 1, "execution_owner": "llm"})
    freeze = load_json("state/policy_freeze.json", {})
    portfolio = load_json("config/portfolio.json", {})
    signal = load_json("state/momentum_signal.json")
    snapshot = load_json("state/market_snapshot.json", {})
    exit_levels = (load_json("state/exit_levels.json", {}) or {}).get("tickers", {})
    if not signal:
        print("state/momentum_signal.json 없음 — momentum_signal.py 먼저 실행", file=sys.stderr)
        return 2

    cfg = signal.get("config") or {}
    top_n = int(cfg.get("top_n", 6))
    rebal_days = int(((policy.get("momentum_strategy") or {}).get("config") or {}).get("rebalance_days", 21))
    ps = policy.get("position_sizing") or {}
    cap_pct = float(ps.get("max_position_weight_pct", 35.0))
    min_cash_pct = float(ps.get("min_cash_weight_pct", 5.0))
    tc = policy.get("trading_cost") or {}
    buy_cost = (float(tc.get("slippage_pct", 0.2)) + float(tc.get("commission_pct", 0.015))) / 100

    data_date = d10(signal.get("effective_as_of") or signal.get("data_as_of"))
    snap_tk = snapshot.get("tickers") or {}
    ranking = {r["ticker"]: r for r in signal.get("full_ranking", [])}

    def ref_price(tk):
        st = snap_tk.get(tk) or {}
        if isinstance(st.get("last_close"), (int, float)) and st.get("confidence") != "low":
            return float(st["last_close"]), f"snapshot {d10(snapshot.get('as_of'))} ({st.get('confidence')})"
        r = ranking.get(tk)
        if r and r.get("close"):
            return float(r["close"]), f"price_history {data_date}"
        return None, "결측"

    # ── 리밸런스 그리드 ────────────────────────────────────────────────────────
    dates = trading_dates()
    anchor = stage.get("rebalance_anchor") or freeze.get("since") or data_date
    grid = [d for d in dates if d >= anchor]
    if data_date and data_date not in grid and data_date >= anchor:
        grid.append(data_date)
        grid.sort()
    days_since = grid.index(data_date) if data_date in grid else 0
    is_rebal = (days_since % rebal_days == 0)
    to_next = rebal_days - (days_since % rebal_days)

    equity = float(portfolio.get("equity") or 0)
    cash = float(portfolio.get("cash") or 0)
    positions = portfolio.get("positions") or []
    held = {p["ticker"]: p for p in positions}

    intents, shadow, notes = [], [], []
    seq = [0]
    # ── 자본 리셋(사용자 결정 2026-09-02): 보유 전량 현금화가 pending 이면 하드 룰보다 먼저, 전 종목 SELL ──
    cap_reset = ((stage.get("capital") or {}).get("reset") or {})
    reset_pending = cap_reset.get("status") == "pending"

    def new_id():
        seq[0] += 1
        return f"oi-{data_date.replace('-', '')}-{seq[0]}"

    valid_until = f"{data_date}T15:30:00+09:00"

    # ── 청산 판정(보유 종목, 종가 기준) ───────────────────────────────────────
    exiting = set()
    for tk, p in held.items():
        px, src = ref_price(tk)
        r = ranking.get(tk) or {}
        ma = r.get("ma200")
        stop = p.get("stop_price")
        rule = None
        if px is None:
            notes.append(f"{p.get('name', tk)}: 가격 결측 — 청산 판정 보류")
            continue
        if reset_pending:
            rule, why = "capital_reset", (f"사용자 결정({cap_reset.get('requested')}): 실투입 자본 = 평가금액 → 보유 전량 종가 현금화. "
                                          f"손절·목표·thesis 와 무관하게 집행(거부 불가 — 사용자 지시)")
        elif stop and px <= float(stop):
            rule, why = "hard_stop", f"종가 {px:,.0f} ≤ 손절 {float(stop):,.0f}"
        elif ma and px < float(ma):
            rule, why = "trend_break", f"종가 {px:,.0f} < MA200 {float(ma):,.0f}"
        elif is_rebal and r and not r.get("pass_filter", True):
            rule, why = "rebalance_rotation", f"리밸런스일 자격 이탈(score {r.get('score')}, MA200 {'상회' if r.get('in_uptrend') else '하회'})"
        if rule:
            exiting.add(tk)
            intents.append({"id": new_id(), "action": "SELL", "ticker": tk, "name": p.get("name", tk),
                            "shares": int(p.get("shares", 0)), "ref_price": px, "ref_price_source": src,
                            "rule": rule, "reason": why, "execution": "closing_auction 종가 청산(마감 후 신규매매 금지 원칙 동일)",
                            "valid_until": valid_until, "status": "proposed", "disposition": None})
        # shadow: 오버레이 룰이 발동했는가(관측만)
        el = exit_levels.get(tk) or {}
        tgt = p.get("target_price")
        if tgt and px >= float(tgt):
            shadow.append({"ticker": tk, "name": p.get("name", tk), "rule": "target_take_profit", "detail": f"종가 {px:,.0f} ≥ 목표 {float(tgt):,.0f}"})
        if el.get("trailing_activated") and el.get("trailing_first_level") and px < float(el["trailing_first_level"]):
            shadow.append({"ticker": tk, "name": p.get("name", tk), "rule": "trailing_first_50pct", "detail": f"종가 {px:,.0f} < 1차선 {float(el['trailing_first_level']):,.0f}"})
        if (el.get("estimate") or {}).get("review_required"):
            shadow.append({"ticker": tk, "name": p.get("name", tk), "rule": "estimate_review_required", "detail": "추정 기대수익 음수 2회 연속"})
        rr = p.get("rr_ratio")
        if isinstance(rr, (int, float)) and rr < 1.1:
            shadow.append({"ticker": tk, "name": p.get("name", tk), "rule": "rr_floor_breach", "detail": f"R/R {rr} < 1.1 (라이브 룰은 손절 상향 처방 — 의도 아님)"})
    # Top-N 초과분 회전아웃(리밸런스일, 점수 하위부터)
    if is_rebal:
        remaining = [tk for tk in held if tk not in exiting]
        if len(remaining) > top_n:
            remaining.sort(key=lambda t: (ranking.get(t) or {}).get("score", -1e9))
            for tk in remaining[: len(remaining) - top_n]:
                p = held[tk]
                px, src = ref_price(tk)
                exiting.add(tk)
                intents.append({"id": new_id(), "action": "SELL", "ticker": tk, "name": p.get("name", tk),
                                "shares": int(p.get("shares", 0)), "ref_price": px, "ref_price_source": src,
                                "rule": "rebalance_rotation", "reason": f"보유 {len(remaining)} > top_n {top_n} — 점수 하위 회전아웃",
                                "execution": "closing_auction", "valid_until": valid_until, "status": "proposed", "disposition": None})

    # ── 진입(리밸런스일에만, 빈 슬롯만) ──────────────────────────────────────
    vacant = top_n - (len(held) - len(exiting))
    entry_note = None
    if reset_pending:
        entry_note = "자본 리셋 pending — 현금화 완료(보유 0) 후 다음 리밸런스일부터 진입"
    elif not is_rebal:
        entry_note = f"리밸런스일 아님(다음 리밸런스까지 {to_next}거래일) — 신규 진입 의도 없음"
    elif vacant <= 0:
        entry_note = "빈 슬롯 없음"
    else:
        orders = [o for o in (signal.get("executable_allocation") or {}).get("orders", []) if o["ticker"] not in held]
        if not orders:
            gate = signal.get("gate") or {}
            entry_note = (f"매수 가능 종목 0 — 검증 엔진 gate: 점수하한 미달 {len(gate.get('skipped_below_floor', []))}종, "
                          f"미추적 {len(gate.get('skipped_untracked', []))}종, 상한 초과 제외 {(signal.get('executable_allocation') or {}).get('constraints', {}).get('excluded_too_expensive')}. "
                          f"(P5: 계좌 크기 대비 유니버스 주가 — 진단 리포트 §4)")
        # 현금 여력: 현금 하한 유지, 청산 예정분 매도대금은 다음 세션 재산정이므로 포함하지 않는다(보수)
        deployable = max(0.0, cash - equity * min_cash_pct / 100)
        cap_krw = equity * cap_pct / 100
        per_slot = deployable / max(1, vacant)
        for o in orders[:vacant]:
            px, src = ref_price(o["ticker"])
            if px is None:
                continue
            budget = min(per_slot, cap_krw)
            shares = int(math.floor(budget / (px * (1 + buy_cost))))
            shares = min(shares, int(o.get("shares", shares)))
            if shares <= 0:
                notes.append(f"{o['name']}: 슬롯 예산 {budget:,.0f}원 < 1주 {px:,.0f}원 — 사이징 0")
                continue
            intents.append({"id": new_id(), "action": "BUY", "ticker": o["ticker"], "name": o["name"], "shares": shares,
                            "ref_price": px, "ref_price_source": src, "rule": "momentum_basket_entry",
                            "reason": f"검증 엔진 바스켓 score {o.get('score')} · 빈 슬롯 {vacant} · 슬롯 예산 {budget:,.0f}원",
                            "execution": "정규장 fresh 가격, 진입 상한 ref×1.05(추격 방지) — 기존 §2-PRE 게이트 통과 후",
                            "valid_until": valid_until, "status": "proposed", "disposition": None})
            deployable -= shares * px * (1 + buy_cost)

    if reset_pending and not held and not args.dry_run:
        cap_reset["status"] = "done"
        cap_reset["done_date"] = data_date
        cap_reset["cash_after_reset_krw"] = cash
        stage["rebalance_anchor"] = data_date  # 현금 출발점부터 리밸런스 그리드 재시작
        (ROOT / "state" / "stage.json").write_text(json.dumps(stage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        notes.append(f"자본 리셋 완료 — 현금 {cash:,.0f}원, rebalance_anchor={data_date}")

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "data_date": data_date,
        "signal_as_of": signal.get("as_of"),
        "stage": stage.get("stage"),
        "execution_owner": stage.get("execution_owner", "llm"),
        "spec": {"engine": "state/momentum_signal.json", "top_n": top_n, "rebalance_days": rebal_days,
                 "hard_exit_rules": ["hard_stop", "trend_break", "rebalance_rotation"],
                 "sizing": {"max_position_weight_pct": cap_pct, "min_cash_weight_pct": min_cash_pct}},
        "rebalance": {"anchor": anchor, "trading_days_since_anchor": days_since, "is_rebalance_day": is_rebal,
                      "trading_days_to_next": 0 if is_rebal else to_next},
        "account": {"equity": equity, "cash": cash, "held": len(held), "vacant_slots_after_exits": max(0, vacant)},
        "capital_reset": {"status": cap_reset.get("status"), "requested": cap_reset.get("requested"), "done_date": cap_reset.get("done_date")},
        "intents": intents,
        "entry_note": entry_note,
        "shadow_signals": shadow,
        "notes": notes,
        "veto_protocol": ("execution_owner=llm: 루틴은 각 의도의 disposition 에 {action: executed|vetoed|expired, reason, by, trade_ts} 를 기입한다. "
                          "기본은 집행(§2-PRE 게이트 통과 시). 거부(vetoed)는 검증 가능한 근거(수치·출처 URL) 필수. "
                          "의도에 없는 매매는 trade_log 라인에 off_intent_reason 필수. 무기입(null)은 '무시'로 채점된다."),
    }
    summary = {"data_date": data_date, "is_rebalance_day": is_rebal, "intents": [(i["action"], i["name"], i["shares"], i["rule"]) for i in intents],
               "entry_note": entry_note, "shadow": [(s["name"], s["rule"]) for s in shadow]}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.dry_run:
        return 0
    preserved = preserve_previous()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)} (의도 {len(intents)}건, 그림자 신호 {len(shadow)}건, 직전 의도 보존 {preserved}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
