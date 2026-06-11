#!/usr/bin/env python3
"""score_target_estimates — 목표주가 추정 vs 실현 주간 채점 + 뉴스 키워드 보강 점검 (v1.0).

자기보완 루프의 목표가 오차 분석(18시 routine)과 동일 패턴을 추정 레이어에 적용한다.
sunday_policy_review(일 20시)가 0-C 단계에서 실행해 산출물을 패치 리뷰의 입력으로 쓴다.

입력: state/target_estimate_log.jsonl (estimate_target_price 가 실행마다 적재),
      state/price_history.json·state/market_snapshot.json (실현 가격),
      state/news_feed.json (unclassified·분류 현황 — 키워드 보강 재료)
출력: state/estimate_scorecard.json — 채점 통계 + 리뷰 체크리스트 + 리포트 MD 섹션

채점 방식:
  - 로그의 날짜별 마지막 추정을 표본으로, 추정일로부터 5/20/60거래일 후 실현 수익률을
    추정 기대수익률과 대조한다(부족한 호라이즌은 '진행 중' — 마지막 가용가로 잠정).
  - 방향 적중(부호 일치)·실현/기대 비율·평균 부호 오차를 등급(A/B/C)·게이트별로 집계.
  - 표본 < min_samples(5)면 채점 보류를 명시하고 통계를 내지 않는다(소표본 과신 방지).
뉴스 루프 점검:
  - news_feed 의 unclassified 누적(키워드 구멍 후보)·유형별 분류 분포를 요약하고,
    sunday_policy_review 가 검토할 체크리스트(승격/키워드 보강/오분류 교정)를 생성한다.
의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "estimate_scorecard.json"
LOG_PATH = ROOT / "state" / "target_estimate_log.jsonl"
HORIZONS_TD = [5, 20, 60]  # 거래일
MIN_SAMPLES = 5


def load_json(rel: str, default: Any) -> Any:
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_log() -> dict[str, dict]:
    """날짜별 마지막 추정 레코드."""
    by_date: dict[str, dict] = {}
    if not LOG_PATH.exists():
        return by_date
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("date"):
            by_date[rec["date"]] = rec
    return by_date


def price_lookup() -> tuple[list[str], dict[str, dict[str, float]]]:
    """거래일 리스트 + ticker→date→close. price_history 1순위, 스냅샷 last_close 보강."""
    hist = load_json("state/price_history.json", {})
    closes: dict[str, dict[str, float]] = {}
    dates: set[str] = set()
    for t, v in (hist.get("tickers") or {}).items():
        m = {b["date"]: float(b["close"]) for b in v.get("bars") or [] if b.get("close")}
        closes[t] = m
        dates.update(m)
    snap = load_json("state/market_snapshot.json", {})
    snap_date = (snap.get("as_of") or "")[:10]
    for t, v in (snap.get("tickers") or {}).items():
        if isinstance(v, dict) and v.get("last_close") and snap_date:
            closes.setdefault(t, {})[snap_date] = float(v["last_close"])
            dates.add(snap_date)
    return sorted(dates), closes


def score_estimates(by_date: dict[str, dict], dates: list[str], closes: dict) -> dict:
    date_idx = {d: i for i, d in enumerate(dates)}
    rows: list[dict] = []
    for d, rec in sorted(by_date.items()):
        i0 = date_idx.get(d)
        if i0 is None:  # 휴장일 추정 → 다음 거래일 기준
            later = [x for x in dates if x > d]
            if not later:
                continue
            i0 = date_idx[later[0]]
        for e in rec.get("estimates", []):
            cur, est, exp = e.get("current_price"), e.get("estimate"), e.get("expected_return_pct")
            if not cur or not est or exp is None:
                continue
            row = {
                "date": d, "ticker": e["ticker"], "name": e.get("name"),
                "expected_return_pct": exp, "grade": e.get("grade"),
                "trend_gate": e.get("trend_gate"),
            }
            tcl = closes.get(e["ticker"], {})
            for h in HORIZONS_TD:
                j = i0 + h
                if j < len(dates) and dates[j] in tcl:
                    row[f"realized_{h}td_pct"] = round((tcl[dates[j]] / cur - 1) * 100, 2)
            # 진행 중 표시: 마지막 가용 종가 기준 잠정 실현
            avail = [dd for dd in tcl if dd > d]
            if avail:
                last_d = max(avail)
                row["interim_pct"] = round((tcl[last_d] / cur - 1) * 100, 2)
                row["interim_days"] = (date_idx.get(last_d, i0) - i0)
            rows.append(row)

    def agg(h: int) -> dict:
        pairs = [
            (r["expected_return_pct"], r[f"realized_{h}td_pct"])
            for r in rows if r.get(f"realized_{h}td_pct") is not None
        ]
        if len(pairs) < MIN_SAMPLES:
            return {"n": len(pairs), "status": f"표본 부족(<{MIN_SAMPLES}) — 채점 보류"}
        hit = sum(1 for x, y in pairs if x * y > 0) / len(pairs)
        return {
            "n": len(pairs),
            "hit_rate": round(hit, 3),
            "mean_expected": round(statistics.mean(x for x, _ in pairs), 2),
            "mean_realized": round(statistics.mean(y for _, y in pairs), 2),
            "median_realized_minus_expected": round(
                statistics.median(y - x for x, y in pairs), 2
            ),
        }

    return {"samples": rows, "by_horizon": {f"{h}td": agg(h) for h in HORIZONS_TD}}


def gate_cost(by_date: dict[str, dict], dates: list[str], closes: dict) -> dict:
    """estimate_gate(v2.12) 손익 채점 — '게이트가 차단한 종목이 그 뒤에 올랐는가'.

    게이트 차단 조건(등급 A/B·기대수익<임계)에 해당했던 추정을 로그에서 재구성해
    이후 5/20거래일 실현 수익을 추적한다. 차단 종목의 fwd20 중앙값 ≥ +3% 또는
    양(+)수익 비율 ≥ 60%(n≥5)면 '게이트가 알파를 차단' 경보 → 임계 완화 후보
    (policy.entry_filters.estimate_gate.weekly_gate_scoring).
    """
    eg = load_json("config/policy.json", {}).get("entry_filters", {}).get("estimate_gate", {})
    thr = float(eg.get("block_if_expected_return_below_pct", 0.0))
    grades = eg.get("allowed_grades") or ["A", "B"]
    date_idx = {d: i for i, d in enumerate(dates)}
    rows: list[dict] = []
    for d, rec in sorted(by_date.items()):
        i0 = date_idx.get(d)
        if i0 is None:
            later = [x for x in dates if x > d]
            if not later:
                continue
            i0 = date_idx[later[0]]
        for e in rec.get("estimates", []):
            cur = e.get("current_price")
            if not cur or e.get("grade") not in grades:
                continue
            exp = e.get("expected_return_pct")
            if not isinstance(exp, (int, float)) or exp >= thr:
                continue
            row = {"date": d, "ticker": e["ticker"], "name": e.get("name"),
                   "expected_return_pct": exp}
            tcl = closes.get(e["ticker"], {})
            for h in (5, 20):
                j = i0 + h
                if j < len(dates) and dates[j] in tcl:
                    row[f"fwd_{h}td_pct"] = round((tcl[dates[j]] / cur - 1) * 100, 2)
            rows.append(row)
    f20 = [r["fwd_20td_pct"] for r in rows if r.get("fwd_20td_pct") is not None]
    out: dict[str, Any] = {"n_blocked_samples": len(rows), "n_scored_20td": len(f20),
                           "threshold_pct": thr, "samples": rows[-30:]}
    if len(f20) >= MIN_SAMPLES:
        med = statistics.median(f20)
        pos = sum(1 for x in f20 if x > 0) / len(f20)
        out.update({
            "fwd20_median_pct": round(med, 2),
            "fwd20_positive_rate": round(pos, 3),
            "alpha_block_alert": bool(med >= 3.0 or pos >= 0.6),
            "verdict": ("⚠️ 게이트가 알파를 차단 중 — 임계 완화 후보 상정"
                        if (med >= 3.0 or pos >= 0.6)
                        else "게이트 유효 — 차단 종목이 평균적으로 부진(차단 정당)"),
        })
    else:
        out["status"] = f"표본 부족(<{MIN_SAMPLES}) — 채점 보류"
    return out


def news_loop_review() -> dict:
    feed = load_json("state/news_feed.json", {})
    type_dist: dict[str, int] = {}
    uncls_samples: list[dict] = []
    for t, v in (feed.get("tickers") or {}).items():
        for c in v.get("classified", []):
            type_dist[c.get("type", "?")] = type_dist.get(c.get("type", "?"), 0) + 1
        for u in (v.get("unclassified") or [])[:3]:
            uncls_samples.append({"ticker": t, "name": v.get("name"),
                                  "published": u.get("published"), "title": u.get("title")})
    g_dist: dict[str, int] = {}
    for g in feed.get("global", []) or []:
        g_dist[g.get("type", "?")] = g_dist.get(g.get("type", "?"), 0) + 1
    impact_types = set(load_json("config/news_impact.json", {}).get("news_type_impact_pct", {}))
    silent_types = sorted(impact_types - set(type_dist))
    return {
        "feed_as_of": feed.get("as_of"),
        "classified_total": feed.get("classified_total"),
        "unclassified_total": feed.get("unclassified_total"),
        "global_total": feed.get("global_total"),
        "type_distribution": dict(sorted(type_dist.items(), key=lambda x: -x[1])),
        "global_type_distribution": g_dist,
        "silent_types": silent_types,
        "silent_types_note": "한 번도 매칭되지 않은 유형 — 키워드 구멍이거나 해당 뉴스가 없던 것. unclassified 표본과 대조해 판단.",
        "unclassified_samples": uncls_samples[:15],
        "review_checklist": [
            "unclassified 표본 중 주가 관련 실질 뉴스가 있으면: ①manual_news 승격(출처 URL+게재일) 또는 ②news_keywords 보강",
            "type_distribution 에서 특정 유형 과다(도배) 시 키워드가 너무 넓은지 점검",
            "silent_types 는 unclassified 와 대조 — 구멍이면 키워드 추가, 뉴스 부재면 무시",
            "오분류(방향 반대) 발견 시 exclude 키워드 추가 — '관세 환급'·'Exempts Autos' 패턴 참조",
        ],
    }


def build_md(score: dict, news: dict, as_of: str, log_days: int, gate: dict | None = None) -> str:
    lines = ["### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)", "",
             f"- 기준: {as_of} · 추정 로그 {log_days}일 / 채점 표본 {len(score['samples'])}건"]
    for h, a in score["by_horizon"].items():
        if a.get("status"):
            lines.append(f"- {h}: {a['status']} (n={a['n']})")
        else:
            lines.append(
                f"- {h}: 적중률 {a['hit_rate']:.0%} · 기대 {a['mean_expected']:+.1f}% vs 실현 "
                f"{a['mean_realized']:+.1f}% · 중앙오차 {a['median_realized_minus_expected']:+.1f}%p (n={a['n']})"
            )
    if gate is not None:
        if gate.get("status"):
            lines.append(f"- estimate_gate 손익: 차단표본 {gate['n_blocked_samples']}건 — {gate['status']}")
        else:
            lines.append(
                f"- estimate_gate 손익: 차단표본 {gate['n_scored_20td']}건 · fwd20 중앙값 "
                f"{gate['fwd20_median_pct']:+.1f}% · 양수율 {gate['fwd20_positive_rate']:.0%} → {gate['verdict']}"
            )
    lines += ["",
              f"- 뉴스 피드: 분류 {news.get('classified_total')}건 / 미분류 {news.get('unclassified_total')}건 / 해외 {news.get('global_total')}건",
              f"- 무음 유형(미매칭): {', '.join(news.get('silent_types') or []) or '없음'}",
              "- 검토 의무: unclassified 표본 → manual_news 승격 또는 키워드 보강 (estimate_scorecard.json 의 review_checklist)"]
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(KST)
    by_date = load_log()
    dates, closes = price_lookup()
    score = score_estimates(by_date, dates, closes)
    gate = gate_cost(by_date, dates, closes)
    news = news_loop_review()
    as_of = now.isoformat(timespec="seconds")
    out = {
        "as_of": as_of,
        "log_days": sorted(by_date),
        "scoring": score,
        "gate_cost": gate,
        "news_loop": news,
        "report_section_md": build_md(score, news, as_of, len(by_date), gate),
        "policy_link": "sunday_policy_review §1-5 — 적중률·오차가 2주 연속 악화하거나 무음 유형/오분류가 누적되면 news_impact·news_keywords·estimate 파라미터 패치 후보로 상정한다. 모델 파라미터(틸트·게이트·전이계수) 변경은 backtest 재실행 근거 필수.",
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out["report_section_md"])
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
