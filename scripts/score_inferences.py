#!/usr/bin/env python3
"""score_inferences — 선제적 추론 예측 vs 실측 채점기 (Phase 1, v1.0).

자기보완 루프의 목표가 채점(score_target_estimates.py)과 동형 패턴을 '상황 추론 +
선제 액션' 전체로 일반화한다. sunday_policy_review(일 20시) §0-D 가 실행하고, 18시
routine 이 당일 즉시 채점에 함께 쓴다.

입력:
  state/inference_log.jsonl   — 예측 원장(라인당 1예측, _meta·shadow 줄 포함)
  state/rule_attribution.json — 룰별 실현손익·forgone(있으면 inference_id 로 결합)
출력:
  state/inference_scorecard.json — 채점 통계 + 리포트 MD 섹션

채점 철학(docs/plan_proactive_inference.md §10-C/D):
  - 적중률(hit-rate)은 보조 지표일 뿐, 1차 지표는 '선제 액션의 실현 손익/기회비용'.
    각 예측에 결합된 trade(inference_id)의 rule_attribution round_trip 손익·forgone 을 집계.
  - 표본 < min_samples(5)면 채점 보류를 명시(소표본 과신 방지).
  - shadow(미배치 그림자) 예측은 별도 집계 — 기회비용(false negative)을 1급 오차로 본다.
의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
LOG_PATH = ROOT / "state" / "inference_log.jsonl"
OUT_PATH = ROOT / "state" / "inference_scorecard.json"
CONF_BANDS = [(0.0, 0.5, "low"), (0.5, 0.65, "mid"), (0.65, 1.01, "high")]

# ---- miss 귀속 정규화 (2026-08-11, 검토 리포트 결함 3 교정) ----------------------
# 전문 문장을 dict 키로 쓰면 같은 유형의 miss 가 1회짜리로 파편화돼 반복 임계에 오르지
# 못한다(실측: 79개 키 중 2회 이상 1건). config/miss_patterns.json 의 키워드 레지스트리로
# 유형 키에 클러스터링하고, 미매칭은 숫자 치환 정규화 문장으로 보존한다(1회성 유지).
ID_DATE_RE = re.compile(r"inf-(\d{8})-")
_NUM_RE = re.compile(r"[-+]?\d[\d,.]*\s*(?:%p|%|pt|p\b|원|조|억|건)?")


def load_miss_patterns() -> list[dict]:
    data = load_json("config/miss_patterns.json", {})
    pats = data.get("patterns") if isinstance(data, dict) else None
    return [p for p in (pats or []) if isinstance(p, dict) and p.get("keywords")]


def _fallback_key(text: str) -> str:
    t = _NUM_RE.sub("#", text)
    t = re.sub(r"\s+", " ", t).strip(" .·—-")
    return t[:80] if t else text[:80]


def normalize_miss(text: str, patterns: list[dict]) -> tuple[str, bool]:
    """(정규화 키, 패턴 매칭 여부). 레지스트리 순서대로 첫 매칭 승."""
    low = text.casefold()
    for p in patterns:
        kws = [str(k) for k in p.get("keywords", [])]
        min_hits = max(1, int(p.get("min_hits", 1)))
        if sum(1 for kw in kws if kw.casefold() in low) >= min_hits:
            return str(p.get("label") or p.get("key")), True
    return _fallback_key(text), False


def record_date(rec: dict) -> str:
    """레코드 날짜(YYYY-MM-DD) — id 의 inf-YYYYMMDD- 우선, 없으면 ts 앞 10자."""
    m = ID_DATE_RE.search(str(rec.get("id") or ""))
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    ts = str(rec.get("ts") or "")
    return ts[:10] if len(ts) >= 10 else ""


def load_json(rel: str, default: Any) -> Any:
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_records() -> list[dict]:
    """원장에서 예측·결과 레코드를 읽어 id 로 병합한다(append-only 친화).

    예측 줄: "prediction" 필드 보유. 결과 줄: "id"+"outcome"(또는 "realized")만 보유 —
    나중에 append 돼 같은 id 의 예측에 outcome/miss_attribution/realized 를 덧씌운다.
    (jsonl 은 라인 편집이 어려워 routine 이 결과를 새 줄로 append 하는 방식을 허용.)
    """
    preds: dict[str, dict] = {}
    order: list[str] = []
    results: list[dict] = []
    if not LOG_PATH.exists():
        return []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("_meta"):
            continue
        if "prediction" in rec:
            pid = rec.get("id") or f"_auto{len(order)}"
            rec.setdefault("id", pid)
            preds[pid] = rec
            order.append(pid)
        elif rec.get("id") and ("outcome" in rec or "realized" in rec):
            results.append(rec)
    # 결과 줄을 예측에 덧씌움(최신 결과 우선).
    for r in results:
        p = preds.get(r["id"])
        if not p:
            continue
        for k in ("outcome", "miss_attribution", "realized"):
            if k in r:
                p[k] = r[k]
    return [preds[pid] for pid in order]


def min_samples() -> int:
    pi = load_json("config/policy.json", {}).get("proactive_inference", {})
    return int(pi.get("min_samples", 5))


def conf_band(c: Any) -> str:
    try:
        c = float(c)
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, name in CONF_BANDS:
        if lo <= c < hi:
            return name
    return "unknown"


def subject_kind(s: Any) -> str:
    """'KOSPI_open_gap' / 'ticker:005930' / 'macro:PCE' → 종류 토큰."""
    if not isinstance(s, str) or not s:
        return "기타"
    return s.split(":", 1)[0].strip() or "기타"


def pnl_by_inference(ra: dict) -> dict[str, float]:
    """rule_attribution round_trips 에서 inference_id 별 실현손익 합산(결합 가능 시)."""
    out: dict[str, float] = {}
    for rt in ra.get("round_trips") or []:
        iid = rt.get("inference_id")
        if not iid:
            continue
        pnl = rt.get("realized_pnl") or rt.get("realized_pnl_krw") or 0
        try:
            out[iid] = out.get(iid, 0.0) + float(pnl)
        except (TypeError, ValueError):
            continue
    return out


def score(preds: list[dict], ra: dict, ms: int) -> dict:
    real = [p for p in preds if not p.get("shadow")]
    shadow = [p for p in preds if p.get("shadow")]
    scored = [p for p in real if p.get("outcome") in ("hit", "partial", "miss")]
    pnl_map = pnl_by_inference(ra)

    def hit_rate(rows: list[dict]) -> dict:
        if len(rows) < ms:
            return {"n": len(rows), "status": f"표본 부족(<{ms}) — 채점 보류"}
        hit = sum(1 for r in rows if r.get("outcome") == "hit")
        partial = sum(1 for r in rows if r.get("outcome") == "partial")
        # 결합된 실현손익(있는 것만)
        pnls = [pnl_map[r["id"]] for r in rows if r.get("id") in pnl_map]
        out = {
            "n": len(rows),
            "hit_rate": round(hit / len(rows), 3),
            "partial_rate": round(partial / len(rows), 3),
        }
        if pnls:
            wins = sum(1 for x in pnls if x > 0)
            gains = sum(x for x in pnls if x > 0)
            losses = -sum(x for x in pnls if x < 0)
            out["pnl_linked_n"] = len(pnls)
            out["realized_pnl_krw"] = round(sum(pnls))
            out["expectancy_krw"] = round(statistics.mean(pnls))
            out["profit_factor"] = round(gains / losses, 2) if losses else None
            out["win_rate_on_acted"] = round(wins / len(pnls), 3)
        else:
            out["pnl_linked_n"] = 0
            out["note_pnl"] = "결합된 체결손익 없음(Phase 1 관측 — inference_id 매칭 trade 부재)"
        return out

    # 미흡 요인(miss_attribution) 집계 — 다음 체크리스트 후보.
    # (2026-08-11) 정규화 키로 클러스터링해 반복 횟수를 누적하고, 유형별 최신 사례·최근
    # 발생일을 detail 로 보존한다. miss_factors(키→횟수)는 기존 소비처 호환 형식 유지.
    patterns = load_miss_patterns()
    detail: dict[str, dict] = {}
    for r in scored:
        if r.get("outcome") == "miss" and r.get("miss_attribution"):
            raw = str(r["miss_attribution"]).strip()
            key, matched = normalize_miss(raw, patterns)
            d = detail.setdefault(
                key, {"count": 0, "last_seen": "", "latest_example": "", "pattern": matched}
            )
            d["count"] += 1
            dt = record_date(r)
            if dt >= d["last_seen"]:
                d["last_seen"] = dt
                d["latest_example"] = raw
    ordered = sorted(detail.items(), key=lambda kv: (kv[1]["count"], kv[1]["last_seen"]), reverse=True)
    miss_factors: dict[str, int] = {k: v["count"] for k, v in ordered}

    by_slot: dict[str, dict] = {}
    for slot in sorted({r.get("slot", "?") for r in scored}):
        by_slot[slot] = hit_rate([r for r in scored if r.get("slot") == slot])
    by_kind: dict[str, dict] = {}
    for k in sorted({subject_kind(r.get("subject")) for r in scored}):
        by_kind[k] = hit_rate([r for r in scored if subject_kind(r.get("subject")) == k])
    by_conf: dict[str, dict] = {}
    for b in ("low", "mid", "high"):
        rows = [r for r in scored if conf_band(r.get("confidence")) == b]
        if rows:
            by_conf[b] = hit_rate(rows)

    # 미배치(기회비용) 그림자 채점 — forgone 합산(레짐 보정은 적재 시 risk_off 면 제외)
    shadow_scored = [s for s in shadow if isinstance(s.get("realized"), dict)]
    forgones = [
        float(s["realized"].get("forgone_krw", 0))
        for s in shadow_scored
        if s.get("realized", {}).get("regime") != "risk_off"
    ]
    opp = {"n_shadow": len(shadow), "n_scored": len(shadow_scored)}
    if len(forgones) >= ms:
        opp["forgone_total_krw"] = round(sum(forgones))
        opp["forgone_median_krw"] = round(statistics.median(forgones))
        opp["verdict"] = (
            "⚠️ 미배치로 놓친 수익 누적 — 진입 적극성 상향 후보"
            if statistics.median(forgones) > 0 else "미배치가 평균적으로 손실 회피(보류 정당)"
        )
    else:
        opp["status"] = f"표본 부족(<{ms}) — 채점 보류"

    return {
        "n_predictions": len(real),
        "n_scored": len(scored),
        "overall": hit_rate(scored),
        "by_slot": by_slot,
        "by_subject_kind": by_kind,
        "by_confidence_band": by_conf,
        "miss_factors": miss_factors,
        "miss_factors_detail": {k: v for k, v in ordered},
        "opportunity_cost": opp,
    }


def build_md(s: dict, as_of: str) -> str:
    o = s["overall"]
    lines = ["### 선제 추론 채점 (score_inferences)", "",
             f"- 기준: {as_of} · 예측 {s['n_predictions']}건 / 채점 {s['n_scored']}건"]
    if o.get("status"):
        lines.append(f"- 전체: {o['status']}")
    else:
        msg = f"- 전체: 적중률 {o['hit_rate']:.0%} (부분 {o['partial_rate']:.0%}, n={o['n']})"
        if o.get("pnl_linked_n"):
            pf = o.get("profit_factor")
            msg += (f" · 결합손익 {o['realized_pnl_krw']:+,}원 · 기대값 {o['expectancy_krw']:+,}원/건"
                    f" · PF {pf if pf is not None else 'n/a'}")
        lines.append(msg)
    if s["miss_factors"]:
        top = ", ".join(f"{k}({v})" for k, v in list(s["miss_factors"].items())[:5])
        lines.append(f"- 반복 미흡 요인(→ 체크리스트): {top}")
    opp = s["opportunity_cost"]
    if opp.get("status"):
        lines.append(f"- 미배치 그림자: {opp['n_shadow']}건 — {opp['status']}")
    elif "forgone_median_krw" in opp:
        lines.append(f"- 미배치 그림자: 놓친수익 중앙값 {opp['forgone_median_krw']:+,}원 → {opp['verdict']}")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(KST)
    ms = min_samples()
    preds = load_records()
    ra = load_json("state/rule_attribution.json", {})
    s = score(preds, ra, ms)
    as_of = now.isoformat(timespec="seconds")
    out = {
        "as_of": as_of,
        "min_samples": ms,
        "scoring": s,
        "report_section_md": build_md(s, as_of),
        "policy_link": "sunday_policy_review §0-D — confidence high 구간 적중률·결합손익(PF)·미배치 forgone 이 자격 기준. Tier2 개방은 paper expectancy>0 AND PF>1 충족 시(action_ladder). 반복 miss_factors 는 build_inference_checklist 가 다음 추론 체크리스트로 응축.",
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out["report_section_md"])
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
