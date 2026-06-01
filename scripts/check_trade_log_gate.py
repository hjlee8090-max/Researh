#!/usr/bin/env python3
"""trade_log 의 모든 체결(BUY/SELL 계열) 항목이 price_source 를 기록했는지 CI 에서 강제한다.

pre_trade_gate(프롬프트 의존)를 우회해 묵은/미검증 가격으로 체결되는 것을 막는 '마지막 하드 안전장치'.
프롬프트가 무시돼도 이 게이트가 비정상 종료(exit 1)하면:
  - build_and_notify.yml 의 audit 스텝(audit_pipeline.py) 실패 → main push 빌드 FAIL(가시적)
  - auto_merge_routines.yml 의 게이트 스텝 실패 → 세션 브랜치 routine 커밋이 main 에 병합되지 못함(격리)

규칙(policy.price_data_quality.trade_provenance_gate):
  - price_source_required_since(기본 2026-06-02) 이후 ts 의 booking 만 검사(이전은 grandfather — 소급 미적용).
  - price_source ∈ allowed_price_sources(snapshot_fresh | web_verified).
  - require_verify_url_for(web_verified)면 verify_url 동반 필수.
  - EOD_EVAL/OPEN_CHECK/HOLD 등 비체결 액션은 대상 아님(BUY/SELL 계열만 — reconcile_portfolio 분류 재사용).

표준 라이브러리만. 출력: stdout JSON + exit code(0=통과, 1=위반).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import reconcile_portfolio as rp  # 같은 scripts/ — BUY/SELL 분류(_is_buy/_is_sell)·load_trade_log 재사용

ROOT = Path(__file__).resolve().parent.parent


def load_json(rel: str, default=None):
    p = ROOT / rel
    if not p.exists():
        return default if default is not None else {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default if default is not None else {}


def find_violations(entries: list[dict], gate_cfg: dict) -> tuple[list[str], int, str]:
    since = str(gate_cfg.get("price_source_required_since", "2026-06-02"))[:10]
    allowed = set(gate_cfg.get("allowed_price_sources", ["snapshot_fresh", "web_verified"]))
    need_url = set(gate_cfg.get("require_verify_url_for", ["web_verified"]))
    violations: list[str] = []
    checked = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        action = e.get("action")
        if not (rp._is_buy(action) or rp._is_sell(action)):
            continue  # 비체결 액션(EOD_EVAL/OPEN_CHECK/HOLD 등)은 대상 아님
        ts = str(e.get("ts", ""))
        if ts[:10] < since:
            continue  # grandfather — 게이트 도입 이전 체결
        checked += 1
        tag = f"{ts} {action} {e.get('ticker')}"
        ps = e.get("price_source")
        if ps not in allowed:
            violations.append(
                f"{tag}: price_source 누락/유효하지 않음(={ps!r}) — 허용 {sorted(allowed)}"
            )
            continue
        if ps in need_url and not e.get("verify_url"):
            violations.append(f"{tag}: price_source=web_verified 인데 verify_url 없음")
    return violations, checked, since


def main() -> int:
    policy = load_json("config/policy.json", {})
    pdq = policy.get("price_data_quality", {}) if isinstance(policy, dict) else {}
    gate = pdq.get("trade_provenance_gate", {}) if isinstance(pdq.get("trade_provenance_gate"), dict) else {}
    if not gate.get("enabled", True):
        print(json.dumps({"enabled": False, "violations": [], "checked": 0}, ensure_ascii=False))
        return 0
    entries = rp.load_trade_log()
    violations, checked, since = find_violations(entries, gate)
    out = {
        "enabled": True,
        "price_source_required_since": since,
        "checked": checked,
        "violations": violations,
        "ok": not violations,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))  # stdout = 순수 JSON (audit 가 subprocess 로 파싱)
    summary = (
        f"TRADE_PROVENANCE_GATE=FAIL ({len(violations)} violation) — price_source 누락 booking 차단"
        if violations
        else f"TRADE_PROVENANCE_GATE=PASS (since {since}, booking {checked}건 검증)"
    )
    print(summary, file=sys.stderr)  # 사람용 요약은 stderr 로(stdout JSON 오염 방지)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
