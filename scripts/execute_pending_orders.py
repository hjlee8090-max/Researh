#!/usr/bin/env python3
"""조건부 사전주문(pending_orders) 지정가 매칭 엔진 — Phase 2: DRY-RUN(체결 안 함).

장중 fresh 가격으로 각 BUY 주문이 '체결될 것인가'를 기계 게이트로만 판정한다.

설계 원칙(판단 ↔ 기계 분리): 종목 선정·수량·R/R·뉴스·섹터는 주문이 만들어질 때(전략/routine)
이미 통과한 '판단 게이트'다. 이 엔진은 그 위에서 *기계적으로 확인 가능한 것*만 본다:
  ① 가격이 진입가(limit = trigger.price_below)를 터치 — today_low ≤ limit
  ② 가격 신뢰도 ≥ medium  ③ 미만료(valid_until)  ④ 미체결(dedup)
  ⑤ 현금 충분  ⑥ 종목 비중 상한(equity × max_position_weight_pct) 이내  ⑦ kill switch off

체결가 = **터치 저가**(today_low, limit 로 클램프) — 사용자 선택. 동시 다발 체결은
momentum_score 우선순위로 현금이 소진될 때까지 채운다(나머지는 현금 부족으로 보류).

모드:
  --dry-run (기본): trade_log/portfolio 를 **절대 건드리지 않고** '체결될 것' 판정만
                    state/pending_fills.json 에 남긴다. Phase 2 검증용.
  --execute        : 실제 가상 체결 기록(Phase 3에서 켠다 — 지금은 안전장치로 거부).

표준 라이브러리만 사용. 출력: state/pending_fills.json + stdout 요약.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "pending_fills.json"

# scripts/ 형제 모듈(세션 판정). 단독 실행 시 sys.path[0]=scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_market_session as cms  # noqa: E402

BUY_FEE_PCT = 0.015          # 매수 수수료 0.015%(세금은 매도분 — 매수엔 미적용)
DEFAULT_CAP_PCT = 35.0       # position_sizing.max_position_weight_pct 폴백


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _price(ts: dict, key: str) -> float | None:
    ohlc = ts.get("today_ohlc") if isinstance(ts, dict) else None
    if isinstance(ohlc, dict) and isinstance(ohlc.get(key), (int, float)):
        return float(ohlc[key])
    return None


def _current(ts: dict) -> float | None:
    cur = _price(ts, "close")
    if cur is not None:
        return cur
    lc = ts.get("last_close") if isinstance(ts, dict) else None
    return float(lc) if isinstance(lc, (int, float)) else None


def evaluate(execute: bool = False) -> dict:
    policy = load_json("config/policy.json", {})
    pi = policy.get("proactive_inference", {}) if isinstance(policy.get("proactive_inference"), dict) else {}
    portfolio = load_json("config/portfolio.json", {})
    pending = load_json("state/pending_orders.json", {})
    snapshot = load_json("state/market_snapshot.json", {})
    ts_map = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}

    equity = float(portfolio.get("equity") or portfolio.get("cash") or 0.0)
    cash = float(portfolio.get("cash") or 0.0)
    cap_pct = ((policy.get("position_sizing") or {}).get("max_position_weight_pct")) or DEFAULT_CAP_PCT
    cap_krw = equity * float(cap_pct) / 100.0
    now = datetime.now(KST)

    # 세션 판정(기록용 — dry-run 은 차단하지 않고, execute 는 live 만 허용).
    cal = cms.load_calendar()
    session, mode, sess_reason, _ = cms.classify(now.date(), now.time(), cal)

    kill = (not pi.get("enabled")) or bool(pi.get("kill_switch"))

    # 종목별 기존 보유 평가액(비중 상한은 '신규 + 기존' 합산 기준).
    held_value: dict[str, float] = {}
    for p in portfolio.get("positions", []) or []:
        if isinstance(p, dict) and p.get("ticker"):
            mv = p.get("market_value")
            if not isinstance(mv, (int, float)):
                sh, cp = p.get("shares"), p.get("current_price") or p.get("entry_price")
                mv = (sh or 0) * (cp or 0) if isinstance(sh, (int, float)) and isinstance(cp, (int, float)) else 0
            held_value[p["ticker"]] = float(mv or 0)

    blocked: list[dict] = []
    eligible: list[dict] = []

    for o in pending.get("orders", []) or []:
        if not isinstance(o, dict) or o.get("action") != "BUY":
            continue
        oid = o.get("id")
        name = o.get("name") or o.get("ticker")
        shares = o.get("size_shares")
        base = {"id": oid, "ticker": o.get("ticker"), "name": name, "shares": shares}

        if kill:
            blocked.append({**base, "reason": "kill switch / proactive_inference 비활성"})
            continue
        if o.get("status") not in (None, "active"):
            blocked.append({**base, "reason": f"status={o.get('status')} (미활성·이미 처리)"})
            continue
        vu = o.get("valid_until")
        if vu:
            try:
                if datetime.fromisoformat(vu) < now:
                    blocked.append({**base, "reason": "만료(valid_until 경과)"})
                    continue
            except ValueError:
                pass
        limit = (o.get("trigger") or {}).get("value")
        if not isinstance(limit, (int, float)) or not isinstance(shares, (int, float)) or shares <= 0:
            blocked.append({**base, "reason": "limit/shares 결측"})
            continue
        ts = ts_map.get(o.get("ticker"), {}) if isinstance(ts_map, dict) else {}
        conf = ts.get("confidence") if isinstance(ts, dict) else None
        if conf not in ("high", "medium"):
            blocked.append({**base, "reason": f"가격 신뢰도 부족(confidence={conf})"})
            continue
        low = _price(ts, "low")
        cur = _current(ts)
        touch_px = min([p for p in (low, cur) if isinstance(p, (int, float))], default=None)
        if touch_px is None:
            blocked.append({**base, "reason": "가격 없음"})
            continue
        if touch_px > limit:
            blocked.append({**base, "reason": f"미터치(저가 {int(touch_px):,} > 진입가 {int(limit):,})"})
            continue
        # 체결가 = 터치 저가(진입가로 클램프 — 진입가보다 비싸게 체결하지 않음).
        fill_price = min(float(touch_px), float(limit))
        eligible.append({**base, "limit": float(limit), "fill_price": fill_price,
                         "priority": o.get("momentum_score", 0)})

    # 우선순위(momentum_score) 높은 순으로 현금·비중 상한을 적용해 순차 체결.
    eligible.sort(key=lambda r: -(r.get("priority") or 0))
    fills: list[dict] = []
    run_cash = cash
    for c in eligible:
        shares = int(c["shares"])
        cost = round(shares * c["fill_price"] * (1 + BUY_FEE_PCT / 100.0))
        cap_room = cap_krw - held_value.get(c["ticker"], 0.0)
        if shares * c["fill_price"] > cap_room:
            blocked.append({**{k: c[k] for k in ("id", "ticker", "name", "shares")},
                            "reason": f"종목 비중 상한 초과(필요 {int(shares*c['fill_price']):,} > 여유 {int(max(cap_room,0)):,})"})
            continue
        if cost > run_cash:
            blocked.append({**{k: c[k] for k in ("id", "ticker", "name", "shares")},
                            "reason": f"현금 부족(필요 {cost:,} > 잔여 {int(run_cash):,})"})
            continue
        run_cash -= cost
        fills.append({"id": c["id"], "ticker": c["ticker"], "name": c["name"],
                      "shares": shares, "limit": c["limit"], "fill_price": round(c["fill_price"]),
                      "cost": cost, "priority": c.get("priority")})

    return {
        "as_of": now.isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of"),
        "mode": "execute" if execute else "dry_run",
        "session": session,
        "execution_mode": mode,
        "session_reason": sess_reason,
        "kill_switch_active": kill,
        "equity": round(equity),
        "cash_start": round(cash),
        "cash_after_fills": round(run_cash),
        "cap_pct": cap_pct,
        "would_fill": fills,
        "blocked": blocked,
        "would_fill_count": len(fills),
        "would_fill_cost": sum(f["cost"] for f in fills),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="pending_orders 지정가 매칭 엔진(Phase 2 DRY-RUN)")
    ap.add_argument("--execute", action="store_true",
                    help="실제 가상 체결(Phase 3 전용 — 현재는 안전장치로 거부)")
    args = ap.parse_args()

    if args.execute:
        # Phase 2 안전장치: 실제 체결 경로는 아직 닫혀 있다(Phase 3에서 명시적으로 연다).
        print("❌ --execute 는 Phase 3에서 활성화된다. 지금은 DRY-RUN 만 허용(체결 차단).")
        return 2

    result = evaluate(execute=False)
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[DRY-RUN] 세션={result['session']}({result['execution_mode']}) "
          f"· 현금 {result['cash_start']:,}원 · 비중상한 {result['cap_pct']}%")
    if result["kill_switch_active"]:
        print("  ⚠️ kill switch 활성 — 전건 차단")
    print(f"  ✅ 체결예상 {result['would_fill_count']}건 (비용 {result['would_fill_cost']:,}원, "
          f"체결 후 현금 {result['cash_after_fills']:,}원):")
    for f in result["would_fill"]:
        print(f"     {f['name']}({f['ticker']}) {f['shares']}주 @ {f['fill_price']:,} "
              f"(진입가 {int(f['limit']):,}) = {f['cost']:,}원")
    print(f"  ⛔ 차단 {len(result['blocked'])}건:")
    for b in result["blocked"]:
        print(f"     {b['name']}({b['ticker']}) — {b['reason']}")
    print(f"\n저장: {OUT_PATH.relative_to(ROOT)} (체결 기록 안 함 — trade_log/portfolio 무변경)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
