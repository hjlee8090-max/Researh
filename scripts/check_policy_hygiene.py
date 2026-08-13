#!/usr/bin/env python3
"""policy.json 위생 점검 — dead config 스캔 + 룰 원장(신규 키 등록 메타) 점검 (P1 C-2·C-3).

배경 (docs/plan_removal_exclusion.md §2-B·§5-C):
- sunday_policy_review §1-3 dead config 점검이 6주째 '식별만 반복'했다(weekly_cycle·
  rebalance_rules·disclaimers — 2026-08-09 리뷰: "수동 스캔 한계 도달, 스크립트화 필요").
  처분을 강제하는 루프가 없어 무한 이월됐다.
- policy 룰은 추가만 있는 원웨이 래칫(v1.0→v2.31 changelog 35건 전부 추가 계열).
  신규 룰부터 근거·재검토 기한 메타를 요구하는 원장(ledger) 게이트를 warn 모드로 시작한다
  (P3 원칙 — 일몰이 기본값. 기존 키는 baseline 으로 전부 그랜드파더).

점검 3종:
1. dead_configs — policy.json 최상위 키 중 prompts/*.md·scripts/*.py·.github/workflows/*.yml
   어디에도 이름이 등장하지 않는 것. `_doc` 접두 키는 문서 전용으로 면제(2026-08-09 리뷰 스킴).
2. unregistered_new_rules — baseline(state/policy_keys_baseline.json, 커밋 대상) 이후 추가된
   1·2레벨 키 중 등록 메타가 없는 것. 등록 메타 = 서브트리에 (a)날짜 근거(YYYY-MM-DD 또는
   v2.x 표기 — 기존 관례 그대로) AND (b)재검토 기한(review_by/expiry/sunset 키). warn 전용.
3. review_due — 서브트리의 review_by(YYYY-MM-DD) 가 오늘 이전인 항목(일몰 심사 도래).

소비:
- weekly_self_audit.yml 이 self_audit.py 직전에 실행 → self_audit 이 findings 로 편입해
  기존 14일 무처분 follow-up gate FAIL 루프가 처분을 강제한다(C-2 — 새 루프 신설 없음).
- sunday_policy_review §1-3 도 직접 실행해 처분 근거로 쓴다.

출력: state/policy_hygiene.json (파생물 — gitignore. baseline 만 커밋).
표준 라이브러리만 사용. 멱등 — baseline 은 부재 시 1회만 생성하고 이후 절대 자동 갱신하지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
POLICY = ROOT / "config" / "policy.json"
BASELINE = ROOT / "state" / "policy_keys_baseline.json"
OUT = ROOT / "state" / "policy_hygiene.json"

# 구조 필드 — 참조 스캔 무의미(파일 자체의 메타).
STRUCTURAL_KEYS = {"version", "last_updated", "changelog"}
DATE_EVIDENCE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}|v2\.\d+")
REVIEW_KEYS = ("review_by", "expiry", "sunset", "expires")


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def load_corpus() -> str:
    """참조 스캔 말뭉치 — prompts + scripts + workflows. policy.json 자신·본 스크립트 제외."""
    parts: list[str] = []
    for pattern, base in (("*.md", ROOT / "prompts"), ("*.py", ROOT / "scripts"),
                          ("*.yml", ROOT / ".github" / "workflows")):
        for p in sorted(base.glob(pattern)):
            if p.name == "check_policy_hygiene.py":
                continue
            try:
                parts.append(p.read_text(encoding="utf-8"))
            except OSError:
                continue
    return "\n".join(parts)


def key_paths(policy: dict, max_depth: int = 2) -> list[str]:
    """1·2레벨 키 경로 목록 (룰 원장 단위 — leaf 전수는 노이즈)."""
    paths: list[str] = []
    for k1, v1 in policy.items():
        paths.append(k1)
        if isinstance(v1, dict) and max_depth >= 2:
            paths.extend(f"{k1}.{k2}" for k2 in v1)
    return paths


def subtree(policy: dict, path: str):
    node = policy
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def has_review_meta(node) -> bool:
    """서브트리 어딘가에 재검토 기한 키가 있는가 (재귀)."""
    if isinstance(node, dict):
        if any(k in node for k in REVIEW_KEYS):
            return True
        return any(has_review_meta(v) for v in node.values())
    if isinstance(node, list):
        return any(has_review_meta(v) for v in node)
    return False


def collect_review_due(node, path: str, today: str, due: list[dict]) -> None:
    """review_by 가 오늘 이전인 항목 수집 (재귀)."""
    if isinstance(node, dict):
        rb = node.get("review_by")
        if isinstance(rb, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rb) and rb <= today:
            due.append({"path": path, "review_by": rb})
        for k, v in node.items():
            collect_review_due(v, f"{path}.{k}" if path else k, today, due)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            collect_review_due(v, f"{path}[{i}]", today, due)


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    today = datetime.now(KST).date().isoformat()

    # 1. dead config — 최상위 키 참조 스캔
    corpus = load_corpus()
    dead: list[str] = []
    for key in policy:
        if key in STRUCTURAL_KEYS or key.startswith("_doc"):
            continue
        if key not in corpus:
            dead.append(key)

    # 2. 룰 원장 — baseline 생성(1회) 또는 대조
    current_paths = key_paths(policy)
    baseline_created = False
    if not BASELINE.exists():
        BASELINE.write_text(json.dumps({
            "created": now_kst(),
            "note": "룰 원장 baseline (P1 C-3, docs/plan_removal_exclusion.md §5-C) — 이 시점의 "
                    "1·2레벨 키는 전부 그랜드파더. 이후 추가 키는 등록 메타(날짜 근거 + "
                    "review_by/expiry)를 요구한다(warn 모드). 이 파일은 자동 갱신하지 않는다.",
            "paths": sorted(current_paths),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        baseline_created = True
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    known = set(baseline.get("paths") or [])

    unregistered: list[dict] = []
    for path in current_paths:
        if path in known or path.split(".")[-1].startswith("_doc"):
            continue
        node = subtree(policy, path)
        text = json.dumps(node, ensure_ascii=False) if node is not None else ""
        missing = []
        if not DATE_EVIDENCE_RE.search(text):
            missing.append("날짜 근거(YYYY-MM-DD/v2.x)")
        if not has_review_meta(node):
            missing.append("재검토 기한(review_by/expiry)")
        if missing:
            unregistered.append({"path": path, "missing": missing})

    # 3. review_by 도래
    due: list[dict] = []
    collect_review_due(policy, "", today, due)

    out = {
        "as_of": now_kst(),
        "baseline_created": baseline_created,
        "baseline_paths": len(known),
        "current_paths": len(current_paths),
        "dead_configs": sorted(dead),
        "dead_config_note": "처분 3택: 삭제(제거) / `_doc` 접두 개명(문서 전용 선언) / 참조 배선(활성화). "
                            "self_audit findings 로 편입되어 14일 무처분 시 follow-up gate FAIL.",
        "unregistered_new_rules": unregistered,
        "review_due": due,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"policy_hygiene: dead={sorted(dead)} unregistered_new={len(unregistered)} "
          f"review_due={len(due)}{' (baseline 생성 — 기존 키 그랜드파더)' if baseline_created else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
