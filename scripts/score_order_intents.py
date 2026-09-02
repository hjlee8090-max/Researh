#!/usr/bin/env python3
"""주문 의도 채점 — 의도 대비 실제(adherence) + 거부권(veto)의 손익 (Stage 1, docs/plan_stage1.md §2).

입력: state/order_intents_log.jsonl (build_order_intents 가 upsert 보존한 과거 의도 + 루틴이 기입한 disposition),
      state/trade_log.jsonl (실제 체결), state/price_history.json (t+5 반사실).
판정(의도 1건마다):
  executed — 같은 종목·같은 방향 BUY/SELL 이 valid_until 당일 trade_log 에 있다(disposition 과 무관하게 원장이 정본).
  vetoed   — 체결 없음 + disposition.action == "vetoed" (사유 있음).
  ignored  — 체결 없음 + disposition 없음/expired 아님 → 프로토콜 위반(무기입). WARN 대상.
  expired  — disposition.action == "expired" (게이트 block 등 사유 기입).
반사실(t+5 종가, 있을 때만):
  BUY 미집행: forgone = (close_t5 − ref) × shares  (양수 = 안 사서 놓친 돈)
  SELL 미집행: avoided_loss = (ref − close_t5) × shares (양수 = 안 팔아서 손해, 음수 = 안 판 게 이득)
  → veto_pnl = 거부가 계좌에 준 효과(BUY 거부: −forgone, SELL 거부: −avoided_loss).
의도 밖 매매(off-intent): trade_log 의 BUY/SELL 중 그날 의도에 없는 것 — off_intent_reason 유무 집계.
출력: state/intent_scorecard.json. 표준 라이브러리만.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
sys.path.insert(0, str(ROOT / "scripts"))
import reconcile_portfolio as rp  # _is_buy/_is_sell/load_trade_log 재사용

OUT = ROOT / "state" / "intent_scorecard.json"


def load_log():
    p = ROOT / "state" / "order_intents_log.jsonl"
    if not p.exists():
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def price_series():
    try:
        h = json.load(open(ROOT / "state" / "price_history.json", encoding="utf-8"))
    except Exception:
        return {}, []
    idx = sorted(b["date"] for b in h["index"]["bars"] if b.get("close"))
    return {tk: {b["date"]: float(b["close"]) for b in v.get("bars", []) if b.get("close")} for tk, v in h["tickers"].items()}, idx


def close_after(series, dates, day, n):
    later = [d for d in dates if d > day]
    if len(later) < n:
        return None, None
    d = later[n - 1]
    return series.get(d), d


def main() -> int:
    intents = load_log()
    trades = [e for e in rp.load_trade_log() if rp._is_buy(e.get("action")) or rp._is_sell(e.get("action"))]
    series, dates = price_series()
    today = datetime.now(KST).date().isoformat()

    rows, off_intent = [], []
    by_day_intents = {}
    for it in intents:
        day = str(it.get("valid_until") or it.get("data_date") or "")[:10]
        if not day or day >= today:
            continue  # 오늘 의도는 아직 판정 불가
        by_day_intents.setdefault(day, set()).add((it["ticker"], it["action"]))
        side_ok = rp._is_buy if it["action"] == "BUY" else rp._is_sell
        match = [t for t in trades if t.get("ticker") == it["ticker"] and side_ok(t.get("action")) and str(t.get("ts", ""))[:10] == day]
        disp = it.get("disposition") or {}
        if match:
            verdict = "executed"
        elif disp.get("action") == "vetoed":
            verdict = "vetoed"
        elif disp.get("action") == "expired":
            verdict = "expired"
        else:
            verdict = "ignored"
        c5, d5 = close_after(series.get(it["ticker"], {}), dates, day, 5)
        ref = it.get("ref_price")
        pnl5 = None
        if c5 and ref and verdict != "executed":
            if it["action"] == "BUY":
                pnl5 = round(-(c5 - ref) * it.get("shares", 0))   # 거부/무시가 계좌에 준 효과(−forgone)
            else:
                pnl5 = round((c5 - ref) * it.get("shares", 0))    # 안 팔았을 때 보유 유지분의 t+5 손익
        rows.append({"id": it["id"], "date": day, "action": it["action"], "ticker": it["ticker"], "name": it.get("name"),
                     "shares": it.get("shares"), "rule": it.get("rule"), "ref_price": ref, "verdict": verdict,
                     "veto_reason": disp.get("reason") if verdict in ("vetoed", "expired") else None,
                     "t5_close": c5, "t5_date": d5, "veto_effect_krw_t5": pnl5,
                     "execution_owner": it.get("execution_owner")})
    # 의도 밖 매매
    for t in trades:
        day = str(t.get("ts", ""))[:10]
        if day not in by_day_intents or day >= today:
            continue
        side = "BUY" if rp._is_buy(t.get("action")) else "SELL"
        if (t.get("ticker"), side) not in by_day_intents[day]:
            off_intent.append({"date": day, "action": t.get("action"), "ticker": t.get("ticker"),
                               "off_intent_reason": t.get("off_intent_reason"), "has_reason": bool(t.get("off_intent_reason"))})

    n = len(rows)
    cnt = {k: sum(1 for r in rows if r["verdict"] == k) for k in ("executed", "vetoed", "expired", "ignored")}
    scored = [r for r in rows if r["veto_effect_krw_t5"] is not None]
    veto_rows = [r for r in scored if r["verdict"] == "vetoed"]
    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "scope": "state/order_intents_log.jsonl 중 valid_until < 오늘 인 의도",
        "counts": {"intents": n, **cnt, "off_intent_trades": len(off_intent),
                   "off_intent_without_reason": sum(1 for o in off_intent if not o["has_reason"])},
        "adherence_pct": round(cnt["executed"] / n * 100, 1) if n else None,
        "ignored_pct": round(cnt["ignored"] / n * 100, 1) if n else None,
        "veto_effect": {"n_scored_t5": len(veto_rows),
                        "sum_krw_t5": round(sum(r["veto_effect_krw_t5"] for r in veto_rows)) if veto_rows else None,
                        "positive_rate_pct": round(sum(1 for r in veto_rows if r["veto_effect_krw_t5"] > 0) / len(veto_rows) * 100, 1) if veto_rows else None,
                        "note": "양수 = 거부가 계좌를 지켰다(BUY 거부 후 하락 / SELL 거부 후 상승). 표본 ≥ 10 전에는 해석 금지."},
        "cutover_signal": {"rule": "docs/plan_stage1.md §3 — adherence ≥ 80% AND ignored 0 AND (veto 표본 ≥ 10 이면 veto 효과 합 > 0) 20거래일 유지 시 execution_owner=code 심사",
                           "adherence_ok": (cnt["executed"] / n >= 0.8) if n else None, "ignored_zero": cnt["ignored"] == 0 if n else None},
        "rows": rows, "off_intent": off_intent,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"counts": out["counts"], "adherence_pct": out["adherence_pct"], "veto_effect": out["veto_effect"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
