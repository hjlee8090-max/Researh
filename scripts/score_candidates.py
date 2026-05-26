#!/usr/bin/env python3
"""신규 진입 후보 종목을 점수화·랭킹한다.

입력:
- config/candidates.json — 후보 목록
- config/weekly_plan.json — 활성 thesis 목록
- state/market_snapshot.json — 5거래일 추세·신뢰도 (fetch_market_data.py 가 먼저 생성해야 함)
- config/policy.json — entry_filters, weekly_recovery_plan 등

출력: state/candidate_scores.json (gitignored)
- ranked candidates: 점수 내림차순 + 진입 가능 여부 + 제외 사유

점수 모델 (각 0~1 정규화):
- trend_score: 5거래일 누적 수익률 → 0% 이상 = 1.0, -2% = 0.7, -5% = 0.4, -7% = 0.0, 그 미만 = 0
- confidence_score: high=1.0 / medium=0.5 / low=0.0
- thesis_score: 활성 thesis 와 linked = 1.0 / candidate-only thesis = 0.6 / 무관 = 0.3
- bear_flag_penalty: structural_bear_flags 1개당 -0.15

final = (trend × 0.45 + confidence × 0.25 + thesis × 0.30) - bear_flag_penalty
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def trend_score(pct: float | None) -> float:
    if pct is None:
        return 0.0
    if pct >= 0:
        return 1.0
    if pct >= -2.0:
        return 0.7
    if pct >= -5.0:
        return 0.4
    if pct >= -7.0:
        return 0.1
    return 0.0


def confidence_score(level: str | None) -> float:
    return {"high": 1.0, "medium": 0.5, "low": 0.0}.get(level or "low", 0.0)


def thesis_score(thesis_id: str | None, active_thesis_ids: set[str], candidate_thesis_ids: set[str]) -> float:
    if not thesis_id:
        return 0.3
    if thesis_id in active_thesis_ids:
        return 1.0
    if thesis_id in candidate_thesis_ids:
        return 0.6
    return 0.3


def build_adopt_reasons(
    c: dict,
    ret5: float | None,
    conf: str | None,
    th_score: float,
    active_ids: set[str],
    candidate_ids: set[str],
) -> list[str]:
    """진입 가능(tradable) 후보가 '왜 채택됐는지' 를 사람이 읽을 수 있는 사유 목록으로 만든다."""
    reasons: list[str] = []
    if ret5 is not None:
        trend_word = "상승" if ret5 >= 0 else "방어"
        reasons.append(f"5거래일 누적 {ret5:+.1f}% — 추세필터 통과({trend_word})")
    conf_word = {"high": "high(2출처 일치)", "medium": "medium(단일출처)"}.get(conf or "", str(conf))
    reasons.append(f"가격 신뢰도 {conf_word}")
    tid = c.get("thesis_id")
    if tid and tid in active_ids:
        reasons.append(f"활성 thesis '{tid}' 연결")
    elif tid and tid in candidate_ids:
        reasons.append(f"후보 thesis '{tid}' 연결")
    rationale = c.get("rationale")
    if rationale:
        reasons.append(f"근거: {rationale}")
    return reasons


def build_report_section(adopted: list[dict], blocked: list[dict]) -> str:
    """리포트 MD 에 그대로 붙여 넣을 '신규 후보 채택 사유' 섹션을 생성한다."""
    lines = ["### 신규 후보 채택 사유", ""]
    if adopted:
        for r in adopted:
            name = r.get("name") or r.get("ticker")
            score = r.get("final_score")
            lines.append(f"- **{name}({r['ticker']})** — 점수 {score}")
            for reason in r.get("adopt_reasons", []):
                lines.append(f"  - {reason}")
    else:
        lines.append("- 채택 후보 없음 (진입 가능 조건을 만족한 후보 0건)")
    if blocked:
        lines.append("")
        lines.append("> 차단된 후보:")
        for r in blocked:
            name = r.get("name") or r.get("ticker")
            why = "; ".join(r.get("block_reasons", [])) or "사유 미상"
            lines.append(f"> - {name}({r['ticker']}): {why}")
    return "\n".join(lines)


def main() -> int:
    candidates_cfg = load_json("config/candidates.json", {"candidates": []})
    weekly_plan = load_json("config/weekly_plan.json", {})
    snapshot = load_json("state/market_snapshot.json", {"tickers": {}})

    theses = weekly_plan.get("weekly_thesis", []) if isinstance(weekly_plan, dict) else []
    active_ids: set[str] = set()
    candidate_ids: set[str] = set()
    for t in theses:
        if not isinstance(t, dict):
            continue
        direction = t.get("direction", "")
        tid = t.get("id")
        if not tid:
            continue
        if direction == "candidate":
            candidate_ids.add(tid)
        else:
            active_ids.add(tid)

    ts_map = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}

    ranked: list[dict] = []
    for c in candidates_cfg.get("candidates", []):
        if not isinstance(c, dict):
            continue
        ticker = c.get("ticker")
        ts = ts_map.get(ticker, {}) if isinstance(ts_map, dict) else {}
        ret5 = ts.get("five_day_cumulative_return_pct") if isinstance(ts, dict) else None
        conf = ts.get("confidence") if isinstance(ts, dict) else None
        entry_passes = (
            ts.get("entry_filter", {}).get("passes")
            if isinstance(ts, dict) and isinstance(ts.get("entry_filter"), dict)
            else False
        )
        bear_flags = c.get("structural_bear_flags", []) or []

        t_score = trend_score(ret5)
        c_score = confidence_score(conf)
        th_score = thesis_score(c.get("thesis_id"), active_ids, candidate_ids)
        penalty = 0.15 * len(bear_flags)
        final = max(0.0, t_score * 0.45 + c_score * 0.25 + th_score * 0.30 - penalty)

        block_reasons: list[str] = []
        if not entry_passes:
            block_reasons.append(
                ts.get("entry_filter", {}).get("reason") if isinstance(ts, dict) else "5거래일 추세 데이터 없음"
            )
        if conf == "low":
            block_reasons.append("가격 신뢰도 low — 신규 매매 차단")
        if bear_flags:
            block_reasons.append(f"구조적 악재 매칭: {', '.join(bear_flags)}")

        tradable = entry_passes and conf in ("high", "medium") and not bear_flags
        adopt_reasons = build_adopt_reasons(c, ret5, conf, th_score, active_ids, candidate_ids) if tradable else []
        adopt_summary = " · ".join(adopt_reasons) if adopt_reasons else None

        ranked.append({
            "ticker": ticker,
            "name": c.get("name", ""),
            "sector": c.get("sector"),
            "thesis_id": c.get("thesis_id"),
            "rationale": c.get("rationale"),
            "components": {
                "trend": t_score,
                "confidence": c_score,
                "thesis": th_score,
                "bear_penalty": penalty,
            },
            "final_score": round(final, 3),
            "data": {
                "five_day_cumulative_return_pct": ret5,
                "confidence": conf,
                "entry_filter_passes": entry_passes,
                "structural_bear_flags": bear_flags,
            },
            "tradable": tradable,
            "adopt_reasons": adopt_reasons,
            "adopt_summary": adopt_summary,
            "block_reasons": [r for r in block_reasons if r],
        })

    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    tradable = [r for r in ranked if r["tradable"]]
    blocked = [r for r in ranked if not r["tradable"]]

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of") if isinstance(snapshot, dict) else None,
        "active_thesis_ids": sorted(active_ids),
        "candidate_thesis_ids": sorted(candidate_ids),
        "ranked": ranked,
        "adopted": [
            {
                "ticker": r["ticker"],
                "name": r["name"],
                "final_score": r["final_score"],
                "summary": r["adopt_summary"],
                "reasons": r["adopt_reasons"],
            }
            for r in tradable
        ],
        "report_section_md": build_report_section(tradable, blocked),
        "summary": {
            "total": len(ranked),
            "tradable_count": len(tradable),
            "blocked_count": len(blocked),
            "top_tradable_ticker": tradable[0]["ticker"] if tradable else None,
        },
    }
    out_path = ROOT / "state" / "candidate_scores.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {out_path.relative_to(ROOT)} candidates={len(ranked)} "
        f"tradable={len(tradable)} blocked={len(blocked)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
