#!/usr/bin/env python3
"""정책 동결 게이트 (Stage 0 — reports/2026-09-02-pipeline-review.md §6-1 D-1).

목적: 검증 표본(왕복 매매)이 쌓이기 전에 전략 파라미터가 바뀌는 것을 **원칙이 아니라 게이트로** 막는다.
105일 동안 policy v1.0→v2.36(37회) vs 왕복 19건 — 패치 동결 '원칙'(v2.22)은 반복 우회됐다.

동작:
- state/policy_freeze.json 의 baseline_sha256 와 현재 config/policy.json 의 정규화 해시를 비교한다.
  정규화 = `changelog`·`last_updated` 키 제거(compact_state.py 가 changelog 를 매일 이관하므로 제외).
  `version` 은 비교 대상에 포함 — 동결 중 버전 bump 자체가 패치 신호다.
- 동결 활성(active=true) 상태에서 해시가 다르면 exit 1 (CI 차단). 어떤 최상위 키가 바뀌었는지 출력.
- 동결 해제·재설정은 사람이 `--init --reason "..."` 로만 한다(루틴 자동 갱신 금지).
- `--status` 는 판정만 출력하고 exit 0 (감사 리포트용).

표준 라이브러리만 사용. 네트워크 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config" / "policy.json"
FREEZE = ROOT / "state" / "policy_freeze.json"
KST = timezone(timedelta(hours=9))
EXCLUDED_KEYS = ("changelog", "last_updated")


def normalized_policy() -> dict:
    pol = json.load(open(POLICY, encoding="utf-8"))
    return {k: v for k, v in pol.items() if k not in EXCLUDED_KEYS}


def digest(obj) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def top_level_diff(baseline_keys: dict, current: dict) -> list[str]:
    """키별 해시(baseline 에 저장)와 현재 키별 해시를 대조해 바뀐 최상위 키를 찾는다."""
    changed = []
    cur_keys = {k: digest(v) for k, v in current.items()}
    for k in sorted(set(baseline_keys) | set(cur_keys)):
        if baseline_keys.get(k) != cur_keys.get(k):
            tag = "추가" if k not in baseline_keys else ("삭제" if k not in cur_keys else "변경")
            changed.append(f"{k}({tag})")
    return changed


def load_freeze() -> dict | None:
    if not FREEZE.exists():
        return None
    return json.load(open(FREEZE, encoding="utf-8"))


def init_freeze(reason: str, stage: str) -> dict:
    cur = normalized_policy()
    pol = json.load(open(POLICY, encoding="utf-8"))
    prev = load_freeze() or {}
    rec = {
        "active": True,
        "stage": stage,
        "since": datetime.now(KST).strftime("%Y-%m-%d"),
        "reason": reason,
        "baseline_version": pol.get("version"),
        "baseline_sha256": digest(cur),
        "baseline_key_sha256": {k: digest(v) for k, v in cur.items()},
        "excluded_keys": list(EXCLUDED_KEYS),
        "allowed_changes": [
            "scripts/*.py 의 버그 수정(정책 수치 불변)",
            "CI 게이트 강화(.github/workflows)",
            "config/policy.json 외 파일(weekly_plan·watchlist·candidates·universe)의 통상 갱신",
        ],
        "not_allowed": [
            "config/policy.json 의 어떤 파라미터·룰·버전 변경 (changelog·last_updated 제외)",
            "shadow 임계 조정·'데이터 버그' 명목의 정책 수치 변경",
        ],
        "how_to_patch_while_frozen": (
            "패치 후보는 state/policy_freeze.json.backlog 에 {date, proposer, field, current, proposed, "
            "expected_effect, required_samples, note} 로 등록만 한다. 실제 반영은 동결 해제 후 "
            "shadow 관측 → 백테스트 재실행 → 승격 순서로만."
        ),
        "lift_criteria_ref": "reports/2026-09-02-pipeline-review.md §6-2 (Stage 0→1 기준)",
        "backlog": prev.get("backlog", []),
        "history": prev.get("history", []) + [{
            "date": datetime.now(KST).strftime("%Y-%m-%d"), "action": "init", "reason": reason,
            "baseline_version": pol.get("version")}],
    }
    FREEZE.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rec


def check(status_only: bool) -> int:
    fz = load_freeze()
    if not fz:
        print("[INFO] policy freeze: state/policy_freeze.json 없음 — 동결 미설정(게이트 통과)")
        return 0
    if not fz.get("active"):
        print(f"[INFO] policy freeze: 비활성(since {fz.get('since')}) — 게이트 통과")
        return 0
    cur = normalized_policy()
    ok = digest(cur) == fz.get("baseline_sha256")
    pol_version = json.load(open(POLICY, encoding="utf-8")).get("version")
    if ok:
        print(f"[OK] policy freeze 유지 — v{pol_version} == baseline v{fz.get('baseline_version')} "
              f"(since {fz.get('since')}, stage {fz.get('stage')}, backlog {len(fz.get('backlog', []))}건)")
        return 0
    changed = top_level_diff(fz.get("baseline_key_sha256", {}), cur)
    msg = (f"policy freeze 위반 — config/policy.json 이 baseline(v{fz.get('baseline_version')}, "
           f"since {fz.get('since')}) 과 다름. 현재 v{pol_version}. 변경 키: {', '.join(changed) or '(정규화 본문)'}. "
           f"동결 중 정책 변경은 backlog 등록만 허용 — 되돌리거나 사람이 --init 으로 재설정할 것")
    if status_only:
        print(f"[FAIL] {msg}")
        return 0
    print(f"::error::{msg}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="정책 동결 게이트")
    ap.add_argument("--init", action="store_true", help="현재 policy.json 을 baseline 으로 동결 (사람 전용)")
    ap.add_argument("--reason", default="", help="--init 사유")
    ap.add_argument("--stage", default="stage0")
    ap.add_argument("--status", action="store_true", help="판정만 출력, exit 0")
    args = ap.parse_args()
    if args.init:
        if not args.reason:
            print("--init 에는 --reason 이 필요하다", file=sys.stderr)
            return 2
        rec = init_freeze(args.reason, args.stage)
        print(f"[OK] policy freeze 설정 — baseline v{rec['baseline_version']} sha {rec['baseline_sha256'][:12]} since {rec['since']}")
        return 0
    return check(args.status)


if __name__ == "__main__":
    sys.exit(main())
