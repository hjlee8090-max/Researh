#!/usr/bin/env python3
"""매수 매력도 지표 — 예약주문(pending_orders)의 진입가 대비 현재가 위치를 단일 수치로 산출한다(Phase 1·A).

배경: '얼마에 사면 좋은가'가 진입상한(계획가×1.05)·신규진입 상한가 두 곳에 흩어져 리포트에만
묻혀 있었다. 이 모듈은 예약주문의 limit(= trigger.price_below 값 = 진입상한)·indicative(계획가)를
기준으로 현재가 위치를 🟢/🟡/🔴 한 기호로 정규화해, **장중 알림·리포트·(향후) 대시보드가 동일
수치**를 쓰게 한다.

지표 전용이다 — 체결은 바꾸지 않는다(Phase 3에서 limit_price 가 실제 체결 트리거로 승격).
산출: state/buy_attractiveness.json (종목별 위치 + report_section_md). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "buy_attractiveness.json"

# 매력도 정렬 우선순위(낮을수록 위) — 좋은 자리부터.
TIER_RANK = {"green": 0, "yellow": 1, "red": 2, "unknown": 3}


def load_json(rel_or_path: str | Path, default: Any = None) -> Any:
    path = rel_or_path if isinstance(rel_or_path, Path) else ROOT / rel_or_path
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def classify(current: float | None, limit: float | None, indicative: float | None,
             confidence: str | None = None) -> dict:
    """현재가의 진입가 대비 위치를 단계·여력으로 정규화.

    limit      = 진입상한(계획가×1.05, 추격 방지선) — 이 위는 추격이라 매수 부적합.
    indicative = 계획가(전략이 정한 기준가) — 이 이하면 계획보다 싸게 사는 자리.
    반환: tier(green/yellow/red/unknown)·emoji·label·vs_plan_pct·room_to_limit_pct.
    """
    if (current is None or confidence == "low"
            or not isinstance(limit, (int, float)) or not isinstance(indicative, (int, float))
            or not limit or not indicative):
        return {"tier": "unknown", "emoji": "⚪", "label": "가격 미확인",
                "vs_plan_pct": None, "room_to_limit_pct": None}
    vs_plan = (current - indicative) / indicative * 100   # 음수 = 계획보다 쌈(매력)
    room = (limit - current) / limit * 100                # 양수 = 상한 아래 여력
    if current > limit:
        tier, emoji, label = "red", "🔴", "상한 초과(추격)"
    elif current <= indicative:
        tier, emoji, label = "green", "🟢", "계획가 이하(좋은 자리)"
    else:
        tier, emoji, label = "yellow", "🟡", "상한 내(추격주의)"
    return {"tier": tier, "emoji": emoji, "label": label,
            "vs_plan_pct": round(vs_plan, 1), "room_to_limit_pct": round(room, 1)}


def _current_price(ts: dict) -> float | None:
    """스냅샷 종목에서 장중 현재가 근사. today_ohlc.close 우선, 없으면 last_close."""
    ohlc = ts.get("today_ohlc") if isinstance(ts, dict) else None
    if isinstance(ohlc, dict) and isinstance(ohlc.get("close"), (int, float)):
        return float(ohlc["close"])
    lc = ts.get("last_close") if isinstance(ts, dict) else None
    return float(lc) if isinstance(lc, (int, float)) else None


def _today_low(ts: dict) -> float | None:
    ohlc = ts.get("today_ohlc") if isinstance(ts, dict) else None
    if isinstance(ohlc, dict) and isinstance(ohlc.get("low"), (int, float)):
        return float(ohlc["low"])
    return None


def build(pending: dict | None = None, snapshot: dict | None = None) -> list[dict]:
    """예약주문 BUY 건마다 매수 매력도 행을 만든다(매력 순 정렬)."""
    pending = pending if pending is not None else load_json("state/pending_orders.json", {})
    snapshot = snapshot if snapshot is not None else load_json("state/market_snapshot.json", {})
    ts_map = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    rows: list[dict] = []
    for o in pending.get("orders", []) or []:
        if not isinstance(o, dict) or o.get("action") != "BUY":
            continue
        if o.get("status") not in (None, "active"):
            continue
        ts = ts_map.get(o.get("ticker"), {}) if isinstance(ts_map, dict) else {}
        conf = ts.get("confidence") if isinstance(ts, dict) else None
        cur = _current_price(ts)
        low = _today_low(ts)
        limit = (o.get("trigger") or {}).get("value")
        indicative = o.get("indicative_price")
        info = classify(cur, limit, indicative, conf)
        touched = bool(
            cur is not None and isinstance(limit, (int, float)) and limit
            and ((low is not None and low <= limit) or cur <= limit)
        )
        rows.append({
            "ticker": o.get("ticker"), "name": o.get("name") or o.get("ticker"),
            "current": cur, "indicative": indicative, "limit": limit,
            "shares": o.get("size_shares"), "priority": o.get("momentum_score"),
            "touched_today": touched, "confidence": conf, **info,
        })
    rows.sort(key=lambda r: (TIER_RANK.get(r["tier"], 9),
                             r["vs_plan_pct"] if r["vs_plan_pct"] is not None else 999))
    return rows


def _fmt(v: Any) -> str:
    return f"{int(round(v)):,}" if isinstance(v, (int, float)) else "—"


def _pct(v: Any) -> str:
    return f"{v:+.1f}%" if isinstance(v, (int, float)) else "—"


def report_section_md(rows: list[dict]) -> str:
    """리포트 §6 옆에 붙일 마크다운 표(장중 알림과 동일 수치)."""
    if not rows:
        return ("### 🛒 매수 매력도 (예약주문 진입가 대비 현재가 위치)\n\n"
                "활성 예약주문이 없습니다.\n")
    head = (
        "### 🛒 매수 매력도 (예약주문 진입가 대비 현재가 위치)\n\n"
        "- 기준: 진입상한 = 계획가×1.05(추격 방지선). "
        "🟢 계획가 이하(좋은 자리) / 🟡 상한 내(추격주의) / 🔴 상한 초과(추격) / ⚪ 가격 미확인.\n"
        "- 지표 레이어다 — 실제 체결을 자동 대체하지 않는다(학습·시뮬레이션).\n\n"
        "| 종목 | 현재가 | 계획가 | 진입상한 | 계획대비 | 상한여력 | 위치 |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    body = "".join(
        f"| {r['name']}({r['ticker']}) | {_fmt(r['current'])} | {_fmt(r['indicative'])} | "
        f"{_fmt(r['limit'])} | {_pct(r['vs_plan_pct'])} | {_pct(r['room_to_limit_pct'])} | "
        f"{r['emoji']} {r['label']} |\n"
        for r in rows
    )
    return head + body


def write_state(rows: list[dict]) -> dict:
    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "schema": "buy_attractiveness v1 — 예약주문 진입가 대비 현재가 위치(지표 전용·체결 안 함)",
        "rows": rows,
        "report_section_md": report_section_md(rows),
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    rows = build()
    write_state(rows)
    print(f"buy_attractiveness: {len(rows)}건 산출 → {OUT_PATH.relative_to(ROOT)}")
    for r in rows:
        print(f"  {r['emoji']} {r['name']:<12}({r['ticker']}) "
              f"현재 {_fmt(r['current'])} / 계획 {_fmt(r['indicative'])} / 상한 {_fmt(r['limit'])} "
              f"| 계획대비 {_pct(r['vs_plan_pct'])} | {r['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
