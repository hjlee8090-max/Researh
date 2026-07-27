#!/usr/bin/env python3
"""선제 추론 등록 조건을 검사한다 — 행동을 바꾸지 않는 예측을 걸러낸다(v2.25).

배경: state/inference_scorecard.json 기준 채점 180건 중 손익에 연결된 예측이 1건
(pnl_linked_n=1)이었다. 179건은 맞든 틀리든 매매를 바꾸지 않았는데, lessons.md 항목의
24%(선제추론오차 23건)를 차지했다. 게다가 지수 밴드 교훈은 서로 상쇄됐다 —
2026-07-21 '상방 꼬리 포함' / 07-22 '상단 낮춰라' / 07-23 '상단 올려라' /
07-24 '하방 꼬리 포함' 네 건을 합치면 '밴드를 넓혀라'가 되어 정보량이 0이다.

검사 항목(policy.proactive_inference.inference_logging.registration_gate):
1) action_if_wrong — 예측이 빗나갔을 때 바뀌는 행동이 없으면 예측으로 등록 불가
   (kind='observation' 으로 격리해 적중률 통계·선제추론오차 카운터에서 분리)
2) index_band_cap_per_slot — 지수 밴드 예측은 슬롯당 1건 상한
3) holding_subject_floor — 슬롯마다 최소 1건은 보유·후보 종목 논거를 대상으로
4) contradiction_check — 최근 N일 내 동일 주제의 반대 방향 교훈 공존 탐지

출력: state/inference_gate.json
종료코드: 기본 0(어드바이저리). INFERENCE_ENFORCE 가 truthy 이고 위반이 있으면 1.
표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
LOG_PATH = ROOT / "state" / "inference_log.jsonl"
OUT_PATH = ROOT / "state" / "inference_gate.json"

INDEX_SUBJECTS = {"^ks11", "kospi", "kospi_close", "kospi_open_gap", "kospi_next_open",
                  "kospi_close_15h", "kospi_close_direction", "^ks200", "kosdaq"}
BAND_HINT_RE = re.compile(r"밴드|범위|갭|종가\s*[\d,]+\s*~|개장")
UP_RE = re.compile(r"상방|상단\s*(상향|올려|열)|강세 확대|반등 폭 확대|되돌림.{0,6}(접|무력)")
DOWN_RE = re.compile(r"하방|상단\s*(낮춰|하향)|되돌림 반영|반납|급락 꼬리")


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    rows: list[dict] = []
    for idx, raw in enumerate(LOG_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            row["_line"] = idx
            rows.append(row)
    return rows


def is_prediction(row: dict) -> bool:
    """예측 레코드인지 판별 — outcome/result 계열 채점 라인은 제외."""
    if row.get("kind") == "observation":
        return False
    if any(k in row for k in ("outcome", "result", "result_for", "scored_by")):
        return False
    return bool(row.get("prediction"))


def is_index_band(row: dict) -> bool:
    subject = str(row.get("subject") or "").strip().lower()
    if subject in INDEX_SUBJECTS:
        return True
    if subject.startswith("kospi") or subject == "^ks11":
        return True
    return False


def has_action_if_wrong(row: dict) -> tuple[bool, str]:
    value = row.get("action_if_wrong")
    if isinstance(value, dict):
        trigger = str(value.get("trigger") or "").strip()
        action = str(value.get("action") or "").strip()
        tier = str(value.get("tier") or "").strip().lower()
        if not (trigger and action):
            return False, "action_if_wrong 에 trigger/action 누락"
        if tier in {"", "tier0", "tier0_prepare"} and "관찰" in action:
            return False, "tier0 관찰만 — 행동이 아니다(observation 으로 격리)"
        return True, ""
    if isinstance(value, str) and value.strip():
        if "관찰" in value and "tier0" in value.lower():
            return False, "tier0 관찰만 — 행동이 아니다"
        return True, ""
    # preemptive_action 을 대체 신호로 인정(구 스키마 호환)
    prior = row.get("preemptive_action")
    if isinstance(prior, str) and prior.strip() and "관찰" not in prior:
        return True, ""
    return False, "action_if_wrong 없음"


def day_of(row: dict) -> str:
    ts = str(row.get("ts") or "")
    return ts[:10] if len(ts) >= 10 else ""


def main() -> int:
    policy = load_json("config/policy.json", {}) or {}
    logging_cfg = (((policy.get("proactive_inference") or {}).get("inference_logging")) or {})
    cfg = logging_cfg.get("registration_gate") or {}
    if not cfg.get("enabled", True):
        OUT_PATH.write_text(json.dumps({"enabled": False}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[INFO] inference registration_gate 비활성")
        return 0

    since = str(cfg.get("enforced_since") or "2026-07-27")[:10]
    band_cap = int(cfg.get("index_band_cap_per_slot", 1))
    require_holding = bool(cfg.get("holding_subject_floor"))

    portfolio = load_json("config/portfolio.json", {}) or {}
    held = {
        str(p.get("ticker"))
        for p in (portfolio.get("positions") or [])
        if isinstance(p, dict) and (p.get("shares") or 0) > 0
    }

    rows = read_log()
    predictions = [r for r in rows if is_prediction(r)]
    enforced = [r for r in predictions if day_of(r) >= since]

    violations: list[dict] = []
    observations: list[dict] = []

    # 1) action_if_wrong
    for row in enforced:
        ok, reason = has_action_if_wrong(row)
        if not ok:
            observations.append({
                "id": row.get("id"),
                "line": row.get("_line"),
                "slot": row.get("slot"),
                "subject": row.get("subject"),
                "reason": reason,
                "verdict": "observation 으로 격리 — 적중률 통계·선제추론오차 카운터 제외",
            })

    # 2) 슬롯별 지수 밴드 상한 + 3) 보유 종목 논거 예측 하한
    by_day_slot: dict[tuple[str, str], list[dict]] = {}
    for row in enforced:
        by_day_slot.setdefault((day_of(row), str(row.get("slot") or "?")), []).append(row)

    for (day, slot), group in sorted(by_day_slot.items()):
        index_rows = [r for r in group if is_index_band(r)]
        if len(index_rows) > band_cap:
            violations.append({
                "type": "index_band_cap",
                "day": day,
                "slot": slot,
                "count": len(index_rows),
                "cap": band_cap,
                "ids": [r.get("id") for r in index_rows],
                "message": (
                    f"{day} {slot} 지수 밴드 예측 {len(index_rows)}건 > 상한 {band_cap}건 — "
                    "적중률 최저·손익 연결 0건 주제가 예측 예산을 점유"
                ),
            })
        if require_holding:
            holding_rows = [r for r in group if str(r.get("subject") or "") in held]
            if not holding_rows:
                violations.append({
                    "type": "holding_subject_floor",
                    "day": day,
                    "slot": slot,
                    "ids": [r.get("id") for r in group],
                    "message": (
                        f"{day} {slot} 보유 종목 논거 예측 0건 — "
                        "지수 밴드가 예측 예산을 독점(보유 종목 checkpoint 예측 1건 이상 필요)"
                    ),
                })

    # 4) 상충 교훈 탐지 — 최근 lookback 일 내 지수 밴드 주제의 상·하방 교훈 공존
    lookback = int(cfg.get("contradiction_lookback_trading_days", 5))
    recent_days = sorted({day_of(r) for r in predictions if day_of(r)})[-lookback:]
    checklist_path = ROOT / "state" / "inference_checklist.md"
    contradictions: list[dict] = []
    if checklist_path.exists():
        text = checklist_path.read_text(encoding="utf-8")
        up_hits = [l.strip() for l in text.splitlines() if UP_RE.search(l) and BAND_HINT_RE.search(l)]
        down_hits = [l.strip() for l in text.splitlines() if DOWN_RE.search(l) and BAND_HINT_RE.search(l)]
        if up_hits and down_hits:
            contradictions.append({
                "topic": "지수 종가 밴드",
                "up_rules": up_hits[:3],
                "down_rules": down_hits[:3],
                "message": (
                    "체크리스트에 지수 밴드 상방·하방 교훈이 함께 올라 있다 — "
                    "합치면 '밴드를 넓혀라'가 되어 정보량이 0이다. 조건을 분기하거나 한쪽을 폐기할 것"
                ),
            })

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "policy_ref": "policy.proactive_inference.inference_logging.registration_gate (v2.25)",
        "enforced_since": since,
        "mode": cfg.get("mode", "warn"),
        "totals": {
            "log_rows": len(rows),
            "predictions_all_time": len(predictions),
            "predictions_enforced": len(enforced),
            "observation_isolated": len(observations),
            "violations": len(violations),
        },
        "observation_isolated": observations,
        "violations": violations,
        "contradictions": contradictions,
        "recent_days_scanned": recent_days,
        "note": (
            "observation 격리 대상은 예측이 아니라 관측이다 — inference_scorecard 적중률과 "
            "lessons.md 선제추론오차 카운터에서 제외한다."
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    lines: list[str] = []
    if observations:
        lines.append(
            f"[WARN] action_if_wrong 없는 예측 {len(observations)}건 — observation 으로 격리 "
            f"(예: {', '.join(str(o['id']) for o in observations[:3])})"
        )
    for v in violations[:6]:
        lines.append(f"[WARN] {v['message']}")
    for c in contradictions:
        lines.append(f"[WARN] 교훈 상충 — {c['topic']}: {c['message']}")
    if not lines:
        lines.append(
            f"[OK] 선제추론 등록 게이트 정상 (발효 {since} 이후 예측 {len(enforced)}건, 위반 0건)"
        )
    print("\n".join(lines))

    enforce = str(os.environ.get("INFERENCE_ENFORCE", "")).strip().lower() in {"1", "true", "yes", "on"}
    return 1 if (enforce and (violations or observations)) else 0


if __name__ == "__main__":
    sys.exit(main())
