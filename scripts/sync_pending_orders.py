#!/usr/bin/env python3
"""pending_orders 의 트레일링 SELL 트리거값을 exit_levels 산출값과 동기화 (의존성 0).

배경 (reports/2026-07-05-pipeline-counterfactual-research.md §결론 안건②):
- po-20260702-3 이 트리거 222,117(7/2 18시 산출 시점 고정)을 들고 있는 동안
  compute_exit_levels 재산출값은 7/3 하루에만 221,880~224,647 로 표류했다.
  7/3 종가 225,000 기준 고정값이면 미체결, 09시 재산출값(224,647)이면 +353원
  차이로 체결 — 트리거 고정값과 단일 소스 산출값의 괴리가 체결 여부를 가른다.
- 이 스크립트는 트레일링 계열 SELL 사전주문의 trigger.value 를
  state/exit_levels.json 의 해당 레벨로 갱신해 괴리를 없앤다.
  실행 슬롯: 09시(compute_exit_levels 직후)·18시(EOD 갱신 직후).

동기화 대상 (보수적 — 이 외에는 손대지 않는다):
- status == "active" AND action == "SELL" AND size_hint 가 trailing 계열인 주문만.
  · size_hint startswith "trailing_first"   → trailing_first_level (50% 부분익절선)
  · size_hint startswith "trailing_residual" 또는 "chandelier" → trailing_residual_level
- 목표가(partial_profit 계열)·BUY 주문은 대상 아님 — 목표가는 정적 값이라 표류하지 않는다.
- exit_levels 에 해당 ticker 나 레벨이 없으면 그 주문은 건너뛰고 사유를 출력한다.

체결 규약과의 관계: 트리거 판정·체결은 policy.risk.exit_execution(v2.21 —
종가 판정·당일 closing_auction 체결)을 따른다. 이 스크립트는 판정 기준값만 맞춘다.

입력: state/exit_levels.json, state/pending_orders.json
출력: state/pending_orders.json 갱신(in-place) + stdout JSON 요약
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

HINT_TO_LEVEL = (
    ("trailing_first", "trailing_first_level"),
    ("trailing_residual", "trailing_residual_level"),
    ("chandelier", "trailing_residual_level"),
)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def level_key_for(size_hint: str) -> str | None:
    for prefix, key in HINT_TO_LEVEL:
        if size_hint.startswith(prefix):
            return key
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="트레일링 SELL 사전주문 트리거값을 exit_levels 와 동기화")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 변경 예정만 출력")
    args = parser.parse_args()

    exit_levels = load_json(ROOT / "state" / "exit_levels.json")
    po_path = ROOT / "state" / "pending_orders.json"
    pending = load_json(po_path)
    if not isinstance(exit_levels, dict) or not isinstance(exit_levels.get("tickers"), dict):
        print(json.dumps({"error": "state/exit_levels.json 부재/형식 오류 — compute_exit_levels.py 를 먼저 실행"}, ensure_ascii=False))
        return 1
    if not isinstance(pending, dict) or not isinstance(pending.get("orders"), list):
        print(json.dumps({"error": "state/pending_orders.json 부재/형식 오류"}, ensure_ascii=False))
        return 1

    levels = exit_levels["tickers"]
    now = datetime.now(KST).isoformat(timespec="seconds")
    changes: list[dict] = []
    skipped: list[dict] = []
    checked = 0

    for order in pending["orders"]:
        if not isinstance(order, dict):
            continue
        if order.get("status") != "active" or order.get("action") != "SELL":
            continue
        key = level_key_for(str(order.get("size_hint", "")))
        if key is None:
            continue  # 트레일링 계열이 아님 — 목표가 등은 동기화 대상 아님
        checked += 1
        ticker = str(order.get("ticker", ""))
        level_entry = levels.get(ticker)
        new_value = level_entry.get(key) if isinstance(level_entry, dict) else None
        if not isinstance(new_value, (int, float)):
            skipped.append({"id": order.get("id"), "ticker": ticker,
                            "reason": f"exit_levels 에 {key} 없음(보유 아님/레벨 산출 불가)"})
            continue
        trigger = order.get("trigger")
        if not isinstance(trigger, dict):
            skipped.append({"id": order.get("id"), "ticker": ticker, "reason": "trigger 형식 오류"})
            continue
        old_value = trigger.get("value")
        if old_value == new_value:
            continue
        trigger["value"] = int(new_value)
        order["trigger_source"] = f"exit_levels.{key}"
        order["trigger_synced_at"] = now
        changes.append({"id": order.get("id"), "ticker": ticker,
                        "level": key, "old": old_value, "new": int(new_value)})

    summary = {
        "as_of": now,
        "checked_trailing_sells": checked,
        "synced": len(changes),
        "changes": changes,
        "skipped": skipped,
        "dry_run": bool(args.dry_run),
        "policy_ref": "risk.exit_execution v2.21 — 판정·체결 규약은 정책, 이 스크립트는 판정 기준값 동기화만",
    }
    if changes and not args.dry_run:
        pending["as_of"] = now
        po_path.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
