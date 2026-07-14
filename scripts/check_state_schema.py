#!/usr/bin/env python3
"""LLM 이 손으로 쓰는 state/config JSON 의 스키마 검증 (의존성 0, 관측 전용).

배경 (docs/plan_hourly_report_gap_fix.md Phase 1-5 · 진단 P12):
- trade_log 만 CI 하드 게이트가 있고, routine 이 직접 쓰는 inference_log.jsonl ·
  pending_orders.json · weekly_plan.json 은 검증이 없었다.
- 형식이 어긋난 예측 라인은 score_inferences.py 가 조용히 스킵하므로
  "기록했지만 채점 안 되는" 무음 실패가 된다 — 이를 표면화한다.

출력: stdout JSON 1개 {"as_of", "checked", "violations": [...]}
종료 코드: 기본 0 (관측 전용 — audit 가 WARN 으로 흡수). --strict 면 위반 시 1.
사용: python scripts/check_state_schema.py [--strict] [--tail N]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# 예측 라인(prediction 보유) 필수 필드 — prompts/0000_global.md §2-4 인라인 스키마 기준
PREDICTION_REQUIRED = ("id", "ts", "slot", "horizon", "prediction", "confidence")
# 채점 라인(outcome 보유) 필수 필드 — score_inferences.py 매칭 키
OUTCOME_REQUIRED = ("id", "outcome")
# pending_orders 주문 필수 필드 — prompts/1800_report.md §pending 적재 스키마 기준
ORDER_REQUIRED = ("id", "ticker", "action", "status", "trigger")
# weekly_plan 최상위 필수 키 — sunday_strategy.md 산출물 계약
WEEKLY_PLAN_REQUIRED = ("week_id", "objective", "weekly_thesis", "daily_bridge", "watch_items")


def check_inference_log(tail: int, violations: list[str]) -> int:
    path = ROOT / "state" / "inference_log.jsonl"
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    # tail<=0 = 전 라인 스캔. 기본 창 30줄일 때 L1~창밖 라인은 영구 무검사였다(2026-07-08 보강).
    start = max(0, len(lines) - tail) if tail > 0 else 0
    checked = 0
    for offset, raw in enumerate(lines[start:], start=start + 1):
        raw = raw.strip()
        if not raw:
            continue
        checked += 1
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            violations.append(f"inference_log L{offset}: JSON 파싱 실패")
            continue
        if not isinstance(entry, dict):
            violations.append(f"inference_log L{offset}: 객체 아님")
            continue
        if "prediction" in entry:
            # 키 존재만 보면 null 이 "정상"으로 통과한다 — 과거 WARN 라인이 confidence:null
            # "보정"으로 검사를 우회한 실사례가 있어 값 검증을 추가 (2026-07-08).
            missing = [k for k in PREDICTION_REQUIRED if entry.get(k) in (None, "")]
            if missing:
                violations.append(
                    f"inference_log L{offset}(예측 {entry.get('id', '?')}): 필수 필드 누락/null {','.join(missing)} — 채점 스킵 위험"
                )
            conf = entry.get("confidence")
            if isinstance(conf, (int, float)) and not isinstance(conf, bool):
                if not 0 <= float(conf) <= 1:
                    violations.append(
                        f"inference_log L{offset}(예측 {entry.get('id', '?')}): confidence={conf} 범위 밖(0~1)"
                    )
            elif isinstance(conf, str) and conf not in ("low", "medium", "high"):
                violations.append(
                    f"inference_log L{offset}(예측 {entry.get('id', '?')}): confidence={conf!r} — 수치(0~1) 또는 low/medium/high 만 허용"
                )
        elif "outcome" in entry:
            missing = [k for k in OUTCOME_REQUIRED if k not in entry]
            if missing:
                violations.append(
                    f"inference_log L{offset}(채점): 필수 필드 누락 {','.join(missing)}"
                )
        else:
            violations.append(
                f"inference_log L{offset}({entry.get('id', '?')}): prediction/outcome 어느 쪽도 아닌 미상 라인"
            )
    return checked


def check_pending_orders(violations: list[str]) -> int:
    path = ROOT / "state" / "pending_orders.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        violations.append("pending_orders: JSON 파싱 실패")
        return 0
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        violations.append("pending_orders: 'orders' 리스트 부재")
        return 0
    for idx, order in enumerate(orders):
        if not isinstance(order, dict):
            violations.append(f"pending_orders[{idx}]: 객체 아님")
            continue
        oid = order.get("id", f"[{idx}]")
        missing = [k for k in ORDER_REQUIRED if order.get(k) in (None, "")]
        if missing:
            violations.append(f"pending_orders {oid}: 필수 필드 누락/null {','.join(missing)}")
            continue
        if order.get("status") not in ("active", "filled", "expired", "cancelled"):
            violations.append(f"pending_orders {oid}: status={order.get('status')!r} — enum(active/filled/expired/cancelled) 밖")
        trig = order.get("trigger")
        if not isinstance(trig, dict) or not isinstance(trig.get("value"), (int, float)) or isinstance(trig.get("value"), bool):
            violations.append(f"pending_orders {oid}: trigger.value 가 수치가 아님 — 장중 트리거 평가 불가")
        vu = str(order.get("valid_until") or "")
        if vu:
            try:
                parsed = datetime.fromisoformat(vu)
                if parsed.tzinfo is None:
                    violations.append(f"pending_orders {oid}: valid_until 타임존 누락(naive) — check_intraday_alerts 비교 크래시 위험")
            except ValueError:
                violations.append(f"pending_orders {oid}: valid_until={vu!r} ISO 파싱 불가")
    return len(orders)


def check_weekly_plan(violations: list[str]) -> int:
    path = ROOT / "config" / "weekly_plan.json"
    if not path.exists():
        violations.append("weekly_plan: 파일 부재")
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        violations.append("weekly_plan: JSON 파싱 실패")
        return 0
    if not isinstance(data, dict):
        violations.append("weekly_plan: 객체 아님")
        return 0
    missing = [k for k in WEEKLY_PLAN_REQUIRED if k not in data]
    if missing:
        violations.append(f"weekly_plan: 최상위 필수 키 누락 {','.join(missing)}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="state 스키마 검증 (관측 전용)")
    parser.add_argument("--strict", action="store_true", help="위반 발견 시 종료 코드 1")
    parser.add_argument("--tail", type=int, default=0, help="inference_log 검사 라인 수 (기본 0=전 라인 — 파일이 작아 전수 스캔 비용 무시 가능)")
    args = parser.parse_args()

    violations: list[str] = []
    checked = {
        "inference_log_lines": check_inference_log(args.tail, violations),
        "pending_orders": check_pending_orders(violations),
        "weekly_plan": check_weekly_plan(violations),
    }
    print(json.dumps(
        {
            "as_of": datetime.now(KST).isoformat(timespec="seconds"),
            "checked": checked,
            "violations": violations,
        },
        ensure_ascii=False,
    ))
    return 1 if (args.strict and violations) else 0


if __name__ == "__main__":
    sys.exit(main())
