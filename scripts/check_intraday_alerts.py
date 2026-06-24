#!/usr/bin/env python3
"""장중(routine 4회 사이) 보유 종목의 orange/red 단계 이탈을 실시간 감지·경보한다(v2.5).

배경: lessons.md 2026-05-28·05-29 HD조선 — 장중 orange 이탈(저가 407K·405K)을
09/12/15/18 routine '사이' 시간대에 감지하지 못해 종가 후에야 확인했다.
policy.entry_filters.intraday_breach_contingency 의 잔여 갭(전면 실시간 모니터)을 채운다.
이 스크립트는 '경보'만 한다 — 실제 체결은 routine 이 한다(장중 시간 게이트 보존).

흐름:
1) state/market_snapshot.json(워크플로가 직전에 fetch_market_data.py 로 갱신)에서 보유 종목
   현재가를 읽어 진입가 대비 변동률·단계(yellow/orange/red, policy.risk.tiered_alerts)를 판정.
2) state/intraday_alert_state.json(Actions 캐시로 당일 유지)의 직전 단계와 비교해 '악화(escalation)'
   가 일어난 종목만 고른다(같은 단계 반복 경보 방지).
3) orange 이상으로 새로 악화된 종목이 있으면 카카오 경보를 보낸다(KAKAO_* 환경변수 있을 때).
   결과는 state/intraday_alert.json 에 should_notify/title/body 로 남긴다.

신뢰도 low·가격 없음은 경보하지 않는다(오탐 방지). 보유 0이면 즉시 no-op.
종료코드 0(경보 발송 실패만 비정상). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
STATE_PATH = ROOT / "state" / "intraday_alert_state.json"
OUT_PATH = ROOT / "state" / "intraday_alert.json"
PENDING_PATH = ROOT / "state" / "pending_orders.json"
PENDING_FIRED_KEY = "__pending_fired__"  # dedup 캐시 키(intraday_alert_state 에 함께 보존)

RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
EMOJI = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴"}


def load_json(rel_or_path: str | Path, default: Any = None) -> Any:
    path = rel_or_path if isinstance(rel_or_path, Path) else ROOT / rel_or_path
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def effective_threshold(fixed: float, mult: float | None, atr_pct: float | None, hard_floor: float) -> float:
    """v2.11 atr_adaptive — 유효 임계 = max(hard_floor, min(고정값, -(배수×ATR%))). 결측 시 고정값."""
    if mult is None or atr_pct is None:
        return fixed
    return max(hard_floor, min(fixed, -(float(mult) * float(atr_pct))))


def classify_tier(pct: float, alerts: dict, atr_pct: float | None = None) -> str:
    mults = alerts.get("atr_multiples", {}) if alerts.get("mode") == "atr_adaptive" else {}
    floor = float(alerts.get("atr_threshold_hard_floor_pct", -20.0))
    red = effective_threshold(float(alerts.get("red_pct", -10.0)), mults.get("red"), atr_pct, floor)
    orange = effective_threshold(float(alerts.get("orange_pct", -7.0)), mults.get("orange"), atr_pct, floor)
    yellow = effective_threshold(float(alerts.get("yellow_pct", -5.0)), mults.get("yellow"), atr_pct, floor)
    if pct <= red:
        return "red"
    if pct <= orange:
        return "orange"
    if pct <= yellow:
        return "yellow"
    return "green"


def current_price(ts: dict) -> float | None:
    """스냅샷 종목에서 장중 현재가 근사. today_ohlc.close 우선, 없으면 last_close."""
    ohlc = ts.get("today_ohlc")
    if isinstance(ohlc, dict) and isinstance(ohlc.get("close"), (int, float)):
        return float(ohlc["close"])
    lc = ts.get("last_close")
    return float(lc) if isinstance(lc, (int, float)) else None


def _order_triggered(order: dict, ts: dict) -> tuple[bool, str]:
    """조건부 사전주문의 수치 트리거를 스냅샷 가격으로 평가(장중 고가/저가 터치 포함).

    수치 트리거(price_above/below)만 자동 판정한다. condition_note(예: 'PCE 부합') 같은
    사람 검증 조건은 자동 평가 불가 — 신호에 '수동 확인 필요'로 표기해 routine 이 판단한다.
    """
    trig = order.get("trigger") or {}
    typ, val = trig.get("type"), trig.get("value")
    if not isinstance(val, (int, float)):
        return False, "수치 트리거 아님"
    cur = current_price(ts) if isinstance(ts, dict) else None
    if cur is None:
        return False, "가격 없음"
    ohlc = ts.get("today_ohlc") if isinstance(ts, dict) else None
    hi = ohlc.get("high") if isinstance(ohlc, dict) else None
    lo = ohlc.get("low") if isinstance(ohlc, dict) else None
    if typ in ("price_above", "gap_above"):
        return (cur >= val or (isinstance(hi, (int, float)) and hi >= val)), ""
    if typ in ("price_below", "gap_below"):
        return (cur <= val or (isinstance(lo, (int, float)) and lo <= val)), ""
    return False, f"알 수 없는 트리거 type={typ}"


def evaluate_pending_orders(snapshot: dict, policy: dict, prev_fired: list) -> tuple[list, list, str]:
    """조건부 사전주문(선제 커밋) 트리거 평가 — **신호만, 체결 안 함**(Phase 3).

    intraday 워크플로는 contents:read 라 trade_log/portfolio 를 쓰지 않는다. 트리거 충족은
    카톡 '예약 신호'로만 알리고, 실제 체결은 다음 09/12/15/18 routine 이 pre_trade_gate 통과
    후 수행한다. kill_switch 또는 proactive_inference 비활성이면 즉시 끈다(긴급 정지).
    """
    pi = policy.get("proactive_inference") if isinstance(policy.get("proactive_inference"), dict) else {}
    if not pi.get("enabled") or pi.get("kill_switch"):
        return [], list(prev_fired), "off"
    pend = load_json("state/pending_orders.json", {})
    orders = pend.get("orders") or []
    ts_map = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    now = datetime.now(KST)
    fired = set(prev_fired)
    signals: list[dict] = []
    for o in orders:
        if not isinstance(o, dict) or o.get("status") not in (None, "active"):
            continue
        oid = o.get("id")
        if not oid or oid in fired:
            continue
        vu = o.get("valid_until")
        if vu:
            try:
                if datetime.fromisoformat(vu) < now:
                    continue  # 만료 — 신호 안 냄(routine 이 status=expired 정리)
            except ValueError:
                pass
        ts = ts_map.get(o.get("ticker"), {}) if isinstance(ts_map, dict) else {}
        if isinstance(ts, dict) and ts.get("confidence") == "low":
            continue  # 저신뢰 가격으로 트리거 판정 금지
        hit, _ = _order_triggered(o, ts)
        if not hit:
            continue
        fired.add(oid)
        tier = o.get("tier", 1)
        approval = " (반자동: Tier2 — 카톡 승인 후 체결)" if tier == 2 else ""
        manual = f" · 수동확인: {o['condition_note']}" if o.get("condition_note") else ""
        signals.append({
            "id": oid, "ticker": o.get("ticker"), "name": o.get("name") or o.get("ticker"),
            "action": o.get("action"), "tier": tier,
            "trigger": o.get("trigger"), "current_price": current_price(ts),
            "note": f"예약 트리거 충족 — 다음 routine 이 게이트 통과 후 체결 검토{approval}{manual}",
        })
    return signals, sorted(fired), "on"


def maybe_send_kakao(title: str, body: str) -> bool:
    """KAKAO 환경변수가 있으면 send_kakao 모듈을 재사용해 경보 발송."""
    if not (os.environ.get("KAKAO_REST_API_KEY") and os.environ.get("KAKAO_REFRESH_TOKEN")):
        print("KAKAO env 없음 — 경보 미발송(상태만 기록)")
        return False
    sys.path.insert(0, str(ROOT / "scripts"))
    import send_kakao as sk  # 모듈 로드시 KAKAO_* env 읽음(위에서 존재 확인)

    res = sk.refresh_access_token()
    token = res.get("access_token")
    if not token:
        print(f"카카오 토큰 갱신 실패: {res}")
        return False
    url = os.environ.get("PAGES_URL", "").rstrip("/") or "https://github.com/hjlee8090-max/Researh"
    sk.send_kakao(token, title, body, url, "레포 열기")
    print("장중 경보 카카오 발송 완료")
    return True


def main() -> int:
    snapshot = load_json("state/market_snapshot.json", {})
    portfolio = load_json("config/portfolio.json", {})
    policy = load_json("config/policy.json", {})
    prev_state = load_json(STATE_PATH, {})

    alerts_cfg = (
        policy.get("risk", {}).get("tiered_alerts", {})
        if isinstance(policy.get("risk"), dict) else {}
    )
    orange_action = alerts_cfg.get("orange_action", "보유 비중 50% 축소 검토")
    red_action = alerts_cfg.get("red_action", "전량 청산 검토")

    ts_map = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    positions = [p for p in portfolio.get("positions", []) if isinstance(p, dict) and p.get("ticker")]

    escalations: list[dict] = []
    new_state: dict[str, str] = {}
    evaluated: list[dict] = []

    for pos in positions:
        ticker = pos.get("ticker")
        # v2.11 — portfolio.json 포지션 스키마는 avg_cost 를 쓴다(entry_price 키는 구버전). 폴백 체인으로 silent-skip 방지.
        entry = pos.get("entry_price") or pos.get("avg_cost") or pos.get("entry_price_web")
        ts = ts_map.get(ticker, {}) if isinstance(ts_map, dict) else {}
        conf = ts.get("confidence")
        cur = current_price(ts) if isinstance(ts, dict) else None
        if not isinstance(entry, (int, float)) or not entry or cur is None or conf == "low":
            # 가격/진입가 없음 또는 신뢰도 low — 경보하지 않고 직전 단계 유지(오탐 방지).
            new_state[ticker] = prev_state.get(ticker, "green")
            evaluated.append({"ticker": ticker, "skipped": True, "confidence": conf})
            continue
        atr_pct = (ts.get("volatility") or {}).get("atr_pct") if isinstance(ts.get("volatility"), dict) else None
        pct = round((cur - entry) / entry * 100, 2)
        tier = classify_tier(pct, alerts_cfg, atr_pct)
        prev = prev_state.get(ticker, "green")
        new_state[ticker] = tier
        evaluated.append({"ticker": ticker, "pct": pct, "tier": tier, "prev_tier": prev, "current_price": cur})
        # orange 이상으로 '새로 악화'된 경우만 경보(같은 단계 반복·회복은 침묵, 상태만 갱신).
        if RANK[tier] >= RANK["orange"] and RANK[tier] > RANK[prev]:
            escalations.append({
                "ticker": ticker,
                "name": pos.get("name") or ticker,
                "pct": pct,
                "tier": tier,
                "prev_tier": prev,
                "entry_price": entry,
                "current_price": cur,
                "action": red_action if tier == "red" else orange_action,
            })

    # 조건부 사전주문(선제 커밋) 트리거 평가 — 신호만(체결 안 함). dedup 은 캐시(prev_state)에 보존.
    prev_fired = prev_state.get(PENDING_FIRED_KEY, []) if isinstance(prev_state, dict) else []
    pending_signals, fired_after, pi_mode = evaluate_pending_orders(snapshot, policy, prev_fired)
    new_state[PENDING_FIRED_KEY] = fired_after

    lines: list[str] = []
    for e in escalations:
        lines.append(
            f"{EMOJI[e['tier']]} {e['name']} {e['pct']:+.1f}% "
            f"(진입 {int(e['entry_price']):,}→현재 {int(e['current_price']):,}) → {e['action']}"
        )
    for s in pending_signals:
        cp = f"현재 {int(s['current_price']):,}" if s.get("current_price") else ""
        lines.append(f"📌 [예약] {s['name']} {s.get('action','')} {cp} — {s['note']}")

    should_notify = bool(escalations) or bool(pending_signals)
    title = ""
    if should_notify:
        if escalations:
            worst = "red" if any(e["tier"] == "red" for e in escalations) else "orange"
            title = f"{EMOJI[worst]} 장중 단계 경보 — 보유 종목 {worst.upper()} 이탈"
        else:
            title = "📌 장중 예약 트리거 충족 — 체결 검토"
    as_of = snapshot.get("as_of", "")
    body = ("\n".join(lines) + (f"\n⏱ {as_of}" if as_of else "")) if should_notify else ""

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of"),
        "should_notify": should_notify,
        "title": title,
        "body": body,
        "escalations": escalations,
        "pending_signals": pending_signals,
        "pending_mode": pi_mode,
        "evaluated": evaluated,
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATE_PATH.write_text(json.dumps(new_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not positions and not pending_signals:
        print(f"보유 0·예약신호 0 — 장중 모니터 no-op (pending_mode={pi_mode})")
        return 0
    print(
        f"intraday_alerts: positions={len(positions)} escalations={len(escalations)} "
        f"pending_signals={len(pending_signals)}({pi_mode}) should_notify={should_notify}"
    )
    for e in escalations:
        print(f"  [{e['tier'].upper()}] {e['name']} {e['pct']:+.1f}% (prev={e['prev_tier']})")
    for s in pending_signals:
        print(f"  [예약] {s['name']} {s.get('action','')} tier{s['tier']} — {s['id']}")

    if should_notify:
        maybe_send_kakao(title, body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
