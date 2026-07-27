#!/usr/bin/env python3
"""동일 경보가 며칠 연속 반복됐는지 세고, 강제 결정 대상을 표면화한다(v2.25).

배경: lessons.md 45번 항목의 자기진단 —
  "R/R 하한 미달 경보가 매일 뜨는데도 '목표 근접에 따른 자연 압축'이라는 동일한 설명만
   반복하고 실제 재조정이 이뤄지지 않는다. 신한지주 R/R 미달 5거래일 연속, 한미반도체
   재검토 의무 7거래일 연속. 경보가 있어도 결론이 항상 '유지'라면 그 경보의 실효성
   자체를 재점검해야 한다."

이 스크립트가 하는 일:
1) reports/YYYY-MM-DD-audit.md 의 [WARN]/[FAIL] 라인을 날짜별로 수집한다.
2) 경보를 정규화한 키로 묶는다(종목코드·숫자·바이트수 등 변동부를 제거해 같은 경보로 인식).
3) 최근 연속 발생 영업일 수를 센다.
4) consecutive_trading_days_to_force 이상이면 강제 결정 대상으로 올린다.
5) state/alert_decisions.jsonl 에 기록된 결정(재조정/청산/예외승인/경보폐기)을 대조해
   미결정 경보만 남긴다. 만료일 지난 예외승인은 다시 미결정으로 되돌린다.

결정 기록 형식(state/alert_decisions.jsonl, 한 줄 1건):
  {"ts": "...", "alert_key": "...", "decision": "예외승인",
   "basis": "...", "expires_on": "2026-08-14"}

출력: state/alert_expiry.json
종료코드: 항상 0(어드바이저리). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "alert_expiry.json"
DECISIONS_PATH = ROOT / "state" / "alert_decisions.jsonl"
REPORTS_DIR = ROOT / "reports"

AUDIT_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-audit\.md$")
ALERT_LINE_RE = re.compile(r"^\[(WARN|FAIL)\]\s*(.+?)\s*$")

# 경보 본문에서 날마다 바뀌는 부분을 지워 같은 경보로 묶는다.
NORMALIZERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "<date>"),
    (re.compile(r"\b\d{6}\b"), "<ticker>"),
    (re.compile(r"[\d,]+B\b"), "<bytes>"),
    (re.compile(r"[-+]?[\d,]+\.\d+"), "<num>"),
    (re.compile(r"[-+]?[\d,]{2,}"), "<num>"),
    (re.compile(r"\s+"), " "),
]


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def normalize(message: str) -> str:
    """경보 본문 → 안정적인 비교 키. 콜론 앞 제목부를 우선 사용한다."""
    head = message.split(":")[0] if ":" in message else message
    # 제목부가 너무 짧으면(예: '요약') 본문 전체를 쓴다.
    text = head if len(head) >= 8 else message
    for pattern, repl in NORMALIZERS:
        text = pattern.sub(repl, text)
    return text.strip()[:160]


def holidays() -> set[str]:
    cal = load_json("config/market_calendar.json", {}) or {}
    out: set[str] = set()
    for key, value in cal.items():
        if not key.startswith("holidays_"):
            continue
        if isinstance(value, dict):
            out.update(str(k)[:10] for k in value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    out.add(item[:10])
                elif isinstance(item, dict) and item.get("date"):
                    out.add(str(item["date"])[:10])
    return out


def collect_history() -> dict[str, dict[str, Any]]:
    """{alert_key: {"dates": [...], "sample": "...", "level": "WARN"}}"""
    history: dict[str, dict[str, Any]] = {}
    for path in sorted(REPORTS_DIR.glob("*-audit.md")):
        match = AUDIT_NAME_RE.match(path.name)
        if not match:
            continue
        day = match.group(1)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        seen_today: set[str] = set()
        for raw in text.splitlines():
            line_match = ALERT_LINE_RE.match(raw.strip())
            if not line_match:
                continue
            level, body = line_match.group(1), line_match.group(2)
            key = normalize(body)
            if not key or key in seen_today:
                continue
            seen_today.add(key)
            entry = history.setdefault(key, {"dates": [], "sample": body, "level": level})
            entry["dates"].append(day)
            entry["sample"] = body  # 가장 최근 원문을 남긴다
            if level == "FAIL":
                entry["level"] = "FAIL"
    return history


def audit_days() -> list[str]:
    days = []
    for path in REPORTS_DIR.glob("*-audit.md"):
        match = AUDIT_NAME_RE.match(path.name)
        if match:
            days.append(match.group(1))
    return sorted(days)


def consecutive_streak(dates: list[str], all_days: list[str]) -> int:
    """감사가 실제로 돈 날 기준으로, 가장 최근 감사일부터 연속 발생 일수를 센다."""
    if not dates or not all_days:
        return 0
    present = set(dates)
    streak = 0
    for day in reversed(all_days):
        if day in present:
            streak += 1
        else:
            break
    return streak


def load_decisions() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not DECISIONS_PATH.exists():
        return out
    for raw in DECISIONS_PATH.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        key = str(row.get("alert_key") or "")
        if key:
            out.setdefault(key, []).append(row)
    return out


def decision_state(rows: list[dict], today: date, cfg: dict) -> dict[str, Any]:
    """가장 최근 결정의 유효성을 판정한다."""
    if not rows:
        return {"decided": False, "reason": "결정 기록 없음"}
    latest = sorted(rows, key=lambda r: str(r.get("ts") or ""))[-1]
    decision = str(latest.get("decision") or "")
    valid_enum = set(cfg.get("forced_decision_enum") or [])
    if decision not in valid_enum:
        return {"decided": False, "reason": f"결정값 '{decision}' 이 enum 밖", "latest": latest}
    if decision == "예외승인":
        expires = str(latest.get("expires_on") or "")[:10]
        if not expires:
            return {"decided": False, "reason": "예외승인에 만료일(expires_on) 없음 — 미결정 처리", "latest": latest}
        try:
            if date.fromisoformat(expires) < today:
                return {"decided": False, "reason": f"예외승인 만료({expires})", "latest": latest}
        except ValueError:
            return {"decided": False, "reason": f"만료일 형식 오류({expires})", "latest": latest}
        if not str(latest.get("basis") or "").strip():
            return {"decided": False, "reason": "예외승인에 근거(basis) 없음", "latest": latest}
    return {"decided": True, "decision": decision, "latest": latest}


def main() -> int:
    policy = load_json("config/policy.json", {}) or {}
    cfg = policy.get("alert_expiry") or {}
    if not cfg.get("enabled", True):
        OUT_PATH.write_text(json.dumps({"enabled": False}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[INFO] alert_expiry 비활성")
        return 0

    threshold = int(cfg.get("consecutive_trading_days_to_force", 3))
    prefixes = [str(p) for p in (cfg.get("tracked_alert_prefixes") or [])]
    today = datetime.now(KST).date()

    history = collect_history()
    all_days = audit_days()
    decisions = load_decisions()

    tracked: list[dict] = []
    for key, entry in history.items():
        sample = entry["sample"]
        # tracked_alert_prefixes 가 비어 있으면 전체를 본다.
        if prefixes and not any(p in sample or p in key for p in prefixes):
            continue
        streak = consecutive_streak(entry["dates"], all_days)
        if streak <= 0:
            continue
        state = decision_state(decisions.get(key, []), today, cfg)
        tracked.append({
            "alert_key": key,
            "level": entry["level"],
            "sample": sample,
            "streak_audit_days": streak,
            "total_occurrences": len(entry["dates"]),
            "first_seen": entry["dates"][0],
            "last_seen": entry["dates"][-1],
            "forced": streak >= threshold,
            "decision_state": state,
            "needs_decision": streak >= threshold and not state.get("decided"),
        })

    tracked.sort(key=lambda r: (-r["streak_audit_days"], r["alert_key"]))
    pending = [r for r in tracked if r["needs_decision"]]

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "policy_ref": "policy.alert_expiry (v2.25)",
        "threshold_consecutive_days": threshold,
        "audit_days_scanned": len(all_days),
        "tracked_count": len(tracked),
        "needs_decision_count": len(pending),
        "needs_decision": pending,
        "tracked": tracked,
        "how_to_resolve": (
            "state/alert_decisions.jsonl 에 한 줄 추가한다 — "
            '{"ts":"<ISO>","alert_key":"<위 alert_key 그대로>","decision":"재조정|청산|예외승인|경보폐기",'
            '"basis":"<근거>","expires_on":"<예외승인일 때 필수>"}'
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    lines: list[str] = []
    for row in pending:
        lines.append(
            f"[WARN] 경보 {row['streak_audit_days']}회 연속 미결정 — {row['sample'][:90]} "
            f"→ 강제 결정 필요(재조정/청산/예외승인/경보폐기)"
        )
    if not lines:
        lines.append(
            f"[OK] 반복 경보 강제 결정 대기 0건 (추적 {len(tracked)}건, 임계 {threshold}회 연속)"
        )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
