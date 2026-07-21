#!/usr/bin/env python3
"""추정 기대수익(target_estimate)의 후보 랭킹 틸트 편입 백테스트 (의존성 0).

배경 (2026-07-21 정렬 진단 — v2.24 후속):
- score_candidates.final_score 는 모멘텀·상대강도·테마·신뢰도·thesis 5축이고 추정 기대수익의
  가중치는 0 이다. 실측(7/20): 기대수익 +1.0% 종목이 tradable 1위, +47.1% 종목이 tradable
  꼴찌 — '한발 앞선 기준선'의 크기 정보가 매수 우선순위에 전혀 반영되지 않는다.
- 다만 추정 수치는 상방 낙관 편향(estimate_scorecard 5td 중앙오차 -10.4%p)이 실측돼 있어
  '크기'가 아니라 '순위(횡단면)' 정보가 있는지부터 검증해야 한다. 레포 규칙: 점수 가중
  변경은 백테스트 근거 필수(policy 2.12 공격 트리거 보류와 동일 원칙).

무엇을 검증하나:
  Q1 (IC) — 같은 날 추정 기대수익의 '순위'가 이후 5/20거래일 수익률 순위를 예측하는가?
       날짜별 Spearman 순위상관(IC)의 평균·양(+)일 비율. A/B 등급(틸트 적용 대상) 별도.
  Q2 (스프레드) — 기대수익 상위 1/3 vs 하위 1/3 의 이후 수익 차이.
  Q3 (재랭킹) — 실전 유사 프록시 점수(모멘텀 0.30 + 상대강도 0.20, score_candidates 의
       실제 밴드 함수 재사용)에 틸트(w×밴드)를 더했을 때 top-1/top-2 픽의 이후 수익이
       개선되는가? 픽이 바뀐 날만 떼어 한계 효과도 본다. w 그리드 {0.02, 0.05, 0.08}.

한계 (정직 고지):
- 표본 창이 짧다(추정 로그 2026-06-11~, 거래일 ~25일) — 5/20거래일 창이 겹쳐 표본이
  독립이 아니며, 단일 시장 국면(강세 후 조정)만 포함한다. 통계적 유의 주장 금지.
- 프록시 점수는 테마·신뢰도·thesis 축을 재현하지 않는다(설정 파일이 기간 중 변해 소급
  재구성이 look-ahead 오염). 모멘텀+상대강도 = 실제 블렌드의 50%로 순위 근사.
- 진입 필터(5일 급락 tier 임계)·비중캡은 재현하지 않는다. A/B 음수 기대수익 종목은
  estimate_gate 가 차단하므로 픽 시뮬레이션 후보에서 제외해 실전과 정합.

판정 기준 (사전 등록 — 결과 보고 후 바꾸지 않는다):
  C1: A/B IC(fwd5) 평균 > 0 이고 양(+)일 비율 ≥ 55%
  C2: 픽 시뮬레이션에서 어떤 w 로도 top-1 fwd5 평균이 베이스라인 대비 악화되지 않고,
      최소 1개 w 에서 top-1·top-2 fwd5 평균이 동시 개선
  C3: 픽이 바뀐 날의 한계 효과(틸트픽 − 베이스픽 fwd5 평균) ≥ 0
  세 기준 모두 충족 → 최소 w 로 배선 권고(wire). 하나라도 미달 → 보류(hold, 표본 누적 후
  sunday_policy_review 재상정). 20거래일 지평은 참고(표본 더 적음 — 단독 탈락 사유 아님).

Q4 (타이브레이크 변형 — 1차 실행에서 가산 틸트가 hold 로 판정된 뒤 추가 사전 등록):
  1차 실측이 'IC 는 양(+)인데 소폭 가산은 점수 격차를 못 넘어 픽 변경 0일'을 보여
  가산이 아닌 **동점권 타이브레이커**(점수 최상위와 margin 이내 후보 중 A/B 기대수익
  최대를 선택)를 같은 하니스로 검증한다. margin 그리드 {0.03, 0.05}. 가산 틸트의
  C1~C3 판정은 그대로 두고(사후 변경 없음), 타이브레이크는 자기 기준으로만 심사:
  T1: 전 margin top-1 fwd5 무악화 + 최소 1개 margin 에서 개선
  T2: 픽 변경일 한계 효과(fwd5) ≥ 0 (전 margin)
  T3: top-1 fwd20 열화가 전 margin 에서 0.5%p 이내
  T1~T3 모두 충족 → 통과한 최소 margin 으로 배선 권고(wire_tiebreak). 아니면 hold.

입력: state/target_estimate_log.jsonl(날짜별 마지막 행 — score_target_estimates 동일 규약),
      state/price_history.json(종목·지수 일봉)
출력: state/backtest_estimate_tilt.json + stdout 요약
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
sys.path.insert(0, str(ROOT / "scripts"))
import score_candidates as sc  # noqa: E402 — 실제 점수 밴드 함수 재사용(단일 출처)

WEIGHT_GRID = [0.02, 0.05, 0.08]
TIEBREAK_MARGINS = [0.03, 0.05]
# 틸트 밴드 — FUND_TILT(±0.05)와 동형의 소폭 확신 틸트. A/B 등급만, C/결측 0.
# ≥15% 는 강한 상방(추세게이트·캡 통과 후에도 큰 여력), <0% 는 게이트 차단 대상(음수 확인용).
def tilt_band(ret: float | None, grade: str | None) -> float:
    if ret is None or grade not in ("A", "B"):
        return 0.0
    if ret >= 15.0:
        return 1.0
    if ret >= 5.0:
        return 0.4
    if ret >= 0.0:
        return 0.0
    return -1.0


def load_json(rel: str, default):
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def last_record_per_date() -> dict[str, dict]:
    """target_estimate_log 의 날짜별 마지막 행 {date: record}."""
    out: dict[str, dict] = {}
    p = ROOT / "state" / "target_estimate_log.jsonl"
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("date"):
                out[rec["date"]] = rec  # 뒤가 최신 — 자연 덮어쓰기
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman 순위상관 (동순위 평균랭크). n<4 면 None."""
    n = len(xs)
    if n < 4 or n != len(ys):
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx * vy) ** 0.5


def summarize(vals: list[float]) -> dict:
    if not vals:
        return {"n_days": 0}
    s = sorted(vals)
    return {
        "n_days": len(vals),
        "mean": round(sum(vals) / len(vals), 3),
        "median": round(s[len(s) // 2], 3),
        "positive_share": round(sum(1 for v in vals if v > 0) / len(vals), 3),
    }


def main() -> int:
    hist = load_json("state/price_history.json", {})
    idx_dates = [b["date"] for b in (hist.get("index") or {}).get("bars") or []]
    closes: dict[str, dict[str, float]] = {}
    for t, v in (hist.get("tickers") or {}).items():
        closes[t] = {
            b["date"]: float(b["close"]) for b in v.get("bars") or []
            if isinstance(b, dict) and b.get("close")
        }
    if not idx_dates or not closes:
        print("price_history 부재 — 백테스트 불가")
        return 1
    pos = {d: i for i, d in enumerate(idx_dates)}
    idx_close = {b["date"]: float(b["close"]) for b in (hist.get("index") or {}).get("bars") or []}

    def t0_of(date: str) -> str | None:
        """추정일 → 기준 거래일(그 이하 마지막 거래일)."""
        cand = [d for d in idx_dates if d <= date]
        return cand[-1] if cand else None

    def fwd(t: str, d0: str, k: int) -> float | None:
        i = pos.get(d0)
        if i is None or i + k >= len(idx_dates):
            return None
        d1 = idx_dates[i + k]
        c = closes.get(t, {})
        if d0 not in c or d1 not in c:
            return None
        return round((c[d1] / c[d0] - 1.0) * 100.0, 2)

    def hist_ret(t: str, d0: str, k: int) -> float | None:
        i = pos.get(d0)
        if i is None or i - k < 0:
            return None
        db = idx_dates[i - k]
        c = closes.get(t, {}) if t != "^KS11" else idx_close
        if d0 not in c or db not in c:
            return None
        return (c[d0] / c[db] - 1.0) * 100.0

    def pct52(t: str, d0: str) -> float | None:
        i = pos.get(d0)
        if i is None:
            return None
        c = closes.get(t, {})
        window = [c[d] for d in idx_dates[max(0, i - 251): i + 1] if d in c]
        if not window or d0 not in c or max(window) <= 0:
            return None
        return c[d0] / max(window) * 100.0

    # ---- 표본 구성: t0(기준 거래일)별 마지막 추정 스냅샷 ----
    recs = last_record_per_date()
    by_t0: dict[str, dict] = {}
    for d in sorted(recs):
        t0 = t0_of(d)
        if t0:
            by_t0[t0] = recs[d]  # 주말 로그는 금요일 t0 로 병합(뒤 날짜가 최신)

    ic5_all, ic20_all, ic5_ab, ic20_ab = [], [], [], []
    spread5, spread20 = [], []
    base_ic5, base_ic5_n = [], 0
    picks_base: list[dict] = []
    picks_tilt: dict[float, list[dict]] = {w: [] for w in WEIGHT_GRID}
    picks_tb: dict[float, list[dict]] = {m: [] for m in TIEBREAK_MARGINS}
    day_rows = []

    for t0, rec in sorted(by_t0.items()):
        samples = []
        for e in rec.get("estimates", []) or []:
            if not isinstance(e, dict) or not e.get("ticker"):
                continue
            ret = e.get("expected_return_pct")
            if not isinstance(ret, (int, float)):
                continue
            f5, f20 = fwd(e["ticker"], t0, 5), fwd(e["ticker"], t0, 20)
            if f5 is None:
                continue
            samples.append({
                "ticker": e["ticker"], "exp": float(ret), "grade": e.get("grade"),
                "f5": f5, "f20": f20,
            })
        if len(samples) < 5:
            continue

        # Q1 — IC (전 등급 / A/B 만)
        r = spearman([s["exp"] for s in samples], [s["f5"] for s in samples])
        if r is not None:
            ic5_all.append(r)
        s20 = [s for s in samples if s["f20"] is not None]
        r = spearman([s["exp"] for s in s20], [s["f20"] for s in s20]) if len(s20) >= 5 else None
        if r is not None:
            ic20_all.append(r)
        ab = [s for s in samples if s["grade"] in ("A", "B")]
        r = spearman([s["exp"] for s in ab], [s["f5"] for s in ab]) if len(ab) >= 5 else None
        if r is not None:
            ic5_ab.append(r)
        ab20 = [s for s in ab if s["f20"] is not None]
        r = spearman([s["exp"] for s in ab20], [s["f20"] for s in ab20]) if len(ab20) >= 5 else None
        if r is not None:
            ic20_ab.append(r)

        # Q2 — 상/하위 1/3 스프레드 (전 등급, 기대수익 기준)
        srt = sorted(samples, key=lambda s: s["exp"], reverse=True)
        k = max(1, len(srt) // 3)
        top, bot = srt[:k], srt[-k:]
        spread5.append(sum(s["f5"] for s in top) / k - sum(s["f5"] for s in bot) / k)
        t20 = [s for s in top if s["f20"] is not None]
        b20 = [s for s in bot if s["f20"] is not None]
        if t20 and b20:
            spread20.append(sum(s["f20"] for s in t20) / len(t20) - sum(s["f20"] for s in b20) / len(b20))

        # Q3 — 프록시 재랭킹. 후보 = A/B 음수(estimate_gate 차단 대상) 제외, C 는 잔류(게이트 미적용).
        kospi60 = hist_ret("^KS11", t0, 60)
        pool = []
        for s in samples:
            if s["grade"] in ("A", "B") and s["exp"] < 0.0:
                continue  # 실전 estimate_gate 차단과 정합
            ret5, ret60 = hist_ret(s["ticker"], t0, 5), hist_ret(s["ticker"], t0, 60)
            p52 = pct52(s["ticker"], t0)
            if ret5 is None or ret60 is None:
                continue
            m, _ = sc.momentum_score(ret5, ret60, p52)
            rs, _ = sc.relative_strength_score(ret60, kospi60)
            base = 0.30 * m + 0.20 * rs
            pool.append({**s, "base": base})
        if len(pool) < 3:
            continue
        pool.sort(key=lambda s: s["base"], reverse=True)
        base_top = pool[:2]
        picks_base.append({
            "t0": t0, "top1": base_top[0]["ticker"], "top1_f5": base_top[0]["f5"],
            "top1_f20": base_top[0]["f20"],
            "top2_f5": sum(p["f5"] for p in base_top) / len(base_top),
        })
        r = spearman([p["base"] for p in pool], [p["f5"] for p in pool])
        if r is not None:
            base_ic5.append(r)
        for w in WEIGHT_GRID:
            tilted = sorted(pool, key=lambda s: s["base"] + w * tilt_band(s["exp"], s["grade"]), reverse=True)
            tt = tilted[:2]
            picks_tilt[w].append({
                "t0": t0, "top1": tt[0]["ticker"], "top1_f5": tt[0]["f5"], "top1_f20": tt[0]["f20"],
                "top2_f5": sum(p["f5"] for p in tt) / len(tt),
                "changed": tt[0]["ticker"] != base_top[0]["ticker"],
                "base_top1_f5": base_top[0]["f5"],
            })
        # Q4 — 동점권 타이브레이크: 최상위 base 점수와 margin 이내 후보 중 A/B 기대수익 최대 선택.
        # top1 교체 룰만 검증한다(top2 비교 없음 — 실전 배선 형태도 deploy 1순위 선택 규칙).
        for m in TIEBREAK_MARGINS:
            near = [p for p in pool if base_top[0]["base"] - p["base"] <= m]
            pick = max(
                near,
                key=lambda p: (p["exp"] if p["grade"] in ("A", "B") else float("-inf"), p["base"]),
            )
            picks_tb[m].append({
                "t0": t0, "top1": pick["ticker"], "top1_f5": pick["f5"], "top1_f20": pick["f20"],
                "changed": pick["ticker"] != base_top[0]["ticker"],
                "base_top1_f5": base_top[0]["f5"],
                "base_top1_f20": base_top[0]["f20"],
            })
        day_rows.append({"t0": t0, "n": len(samples), "n_ab": len(ab), "n_pool": len(pool)})

    def pick_stats(rows: list[dict]) -> dict:
        if not rows:
            return {"n_days": 0}
        f20 = [r["top1_f20"] for r in rows if r.get("top1_f20") is not None]
        return {
            "n_days": len(rows),
            "top1_f5_mean": round(sum(r["top1_f5"] for r in rows) / len(rows), 2),
            "top2_f5_mean": round(sum(r["top2_f5"] for r in rows) / len(rows), 2),
            "top1_f20_mean": round(sum(f20) / len(f20), 2) if f20 else None,
        }

    out_pick = {"baseline": pick_stats(picks_base)}
    criteria: dict[str, dict] = {}
    for w in WEIGHT_GRID:
        rows = picks_tilt[w]
        stats = pick_stats(rows)
        changed = [r for r in rows if r["changed"]]
        stats["changed_days"] = len(changed)
        if changed:
            stats["changed_marginal_f5"] = round(
                sum(r["top1_f5"] - r["base_top1_f5"] for r in changed) / len(changed), 2
            )
            stats["changed_examples"] = [
                {"t0": r["t0"], "tilt_pick": r["top1"], "tilt_f5": r["top1_f5"], "base_f5": r["base_top1_f5"]}
                for r in changed[:6]
            ]
        out_pick[f"w={w}"] = stats

    # Q4 — 타이브레이크 통계·판정 (T1~T3, 사전 등록)
    out_tb: dict[str, dict] = {}
    for m in TIEBREAK_MARGINS:
        rows = picks_tb[m]
        if not rows:
            out_tb[f"margin={m}"] = {"n_days": 0}
            continue
        f20 = [r["top1_f20"] for r in rows if r.get("top1_f20") is not None]
        changed = [r for r in rows if r["changed"]]
        st = {
            "n_days": len(rows),
            "top1_f5_mean": round(sum(r["top1_f5"] for r in rows) / len(rows), 2),
            "top1_f20_mean": round(sum(f20) / len(f20), 2) if f20 else None,
            "changed_days": len(changed),
        }
        if changed:
            st["changed_marginal_f5"] = round(
                sum(r["top1_f5"] - r["base_top1_f5"] for r in changed) / len(changed), 2
            )
            c20 = [
                (r["top1_f20"], r["base_top1_f20"]) for r in changed
                if r.get("top1_f20") is not None and r.get("base_top1_f20") is not None
            ]
            if c20:
                st["changed_marginal_f20"] = round(sum(a - b for a, b in c20) / len(c20), 2)
            st["changed_examples"] = [
                {"t0": r["t0"], "tb_pick": r["top1"], "tb_f5": r["top1_f5"], "base_f5": r["base_top1_f5"]}
                for r in changed[:8]
            ]
        out_tb[f"margin={m}"] = st

    ic = {
        "all_grades": {"fwd5": summarize(ic5_all), "fwd20": summarize(ic20_all)},
        "ab_only": {"fwd5": summarize(ic5_ab), "fwd20": summarize(ic20_ab)},
        "baseline_proxy_fwd5": summarize(base_ic5),
    }
    spread = {"fwd5": summarize(spread5), "fwd20": summarize(spread20)}

    # ---- 사전 등록 판정 ----
    c1 = bool(ic["ab_only"]["fwd5"].get("n_days") and ic["ab_only"]["fwd5"]["mean"] > 0
              and ic["ab_only"]["fwd5"]["positive_share"] >= 0.55)
    base5 = out_pick["baseline"].get("top1_f5_mean")
    no_harm = all(
        out_pick[f"w={w}"].get("top1_f5_mean") is not None and base5 is not None
        and out_pick[f"w={w}"]["top1_f5_mean"] >= base5
        for w in WEIGHT_GRID
    )
    any_improve = any(
        base5 is not None
        and out_pick[f"w={w}"]["top1_f5_mean"] > base5
        and out_pick[f"w={w}"]["top2_f5_mean"] > out_pick["baseline"]["top2_f5_mean"]
        for w in WEIGHT_GRID
    )
    c2 = bool(no_harm and any_improve)
    c3 = all(
        out_pick[f"w={w}"].get("changed_days", 0) == 0
        or out_pick[f"w={w}"].get("changed_marginal_f5", -1) >= 0
        for w in WEIGHT_GRID
    )
    criteria = {
        "C1_ic_ab_fwd5_positive": {"pass": c1, "rule": "A/B IC(fwd5) 평균>0 & 양(+)일 ≥55%"},
        "C2_pick_no_harm_and_improve": {"pass": c2, "rule": "전 w top1 fwd5 무악화 + 최소 1개 w 에서 top1·top2 동시 개선"},
        "C3_changed_days_marginal": {"pass": c3, "rule": "픽 변경일 한계 효과(fwd5) ≥ 0 (전 w)"},
    }
    verdict = "wire" if (c1 and c2 and c3) else "hold"

    # 타이브레이크 판정 (T1~T3)
    def tb_stat(m: float, key: str):
        return out_tb.get(f"margin={m}", {}).get(key)

    t1 = base5 is not None and all(
        isinstance(tb_stat(m, "top1_f5_mean"), (int, float)) and tb_stat(m, "top1_f5_mean") >= base5
        for m in TIEBREAK_MARGINS
    ) and any(tb_stat(m, "top1_f5_mean") > base5 for m in TIEBREAK_MARGINS)
    t2 = all(
        tb_stat(m, "changed_days") in (0, None) or (tb_stat(m, "changed_marginal_f5") or -1) >= 0
        for m in TIEBREAK_MARGINS
    )
    base20 = out_pick["baseline"].get("top1_f20_mean")
    t3 = base20 is None or all(
        tb_stat(m, "top1_f20_mean") is None or tb_stat(m, "top1_f20_mean") >= base20 - 0.5
        for m in TIEBREAK_MARGINS
    )
    tb_pass_margins = [
        m for m in TIEBREAK_MARGINS
        if base5 is not None and isinstance(tb_stat(m, "top1_f5_mean"), (int, float))
        and tb_stat(m, "top1_f5_mean") > base5
    ]
    criteria_tb = {
        "T1_top1_no_harm_and_improve": {"pass": bool(t1), "rule": "전 margin top1 fwd5 무악화 + 최소 1개 margin 개선"},
        "T2_changed_days_marginal": {"pass": bool(t2), "rule": "픽 변경일 한계 효과(fwd5) ≥ 0 (전 margin)"},
        "T3_fwd20_guard": {"pass": bool(t3), "rule": "top1 fwd20 열화 ≤ 0.5%p (전 margin)"},
    }
    tb_verdict = "wire_tiebreak" if (t1 and t2 and t3 and tb_pass_margins) else "hold"
    tb_recommended_margin = min(tb_pass_margins) if tb_verdict == "wire_tiebreak" else None

    # 반쪽 분할(전/후반) 안정성 — 참고용
    halves = {}
    if len(ic5_ab) >= 8:
        h = len(ic5_ab) // 2
        halves = {"ic5_ab_first_half": summarize(ic5_ab[:h]), "ic5_ab_second_half": summarize(ic5_ab[h:])}

    payload = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "window": {
            "t0_first": day_rows[0]["t0"] if day_rows else None,
            "t0_last": day_rows[-1]["t0"] if day_rows else None,
            "n_days": len(day_rows),
        },
        "params": {
            "tilt_bands": "≥+15%:+1.0 / +5~15:+0.4 / 0~5:0.0 / <0:-1.0 (A/B 만, C·결측 0) × w",
            "weight_grid": WEIGHT_GRID,
            "proxy_score": "momentum(0.30)+relative_strength(0.20) — score_candidates 실제 밴드 함수 재사용",
            "pool_rule": "A/B 음수 기대수익 제외(estimate_gate 차단 정합), C 잔류",
        },
        "ic": ic,
        "tercile_spread_pct": spread,
        "pick_simulation": out_pick,
        "tiebreak_simulation": out_tb,
        "split_half": halves,
        "criteria": criteria,
        "verdict": verdict,
        "criteria_tiebreak": criteria_tb,
        "tiebreak_verdict": tb_verdict,
        "tiebreak_recommended_margin": tb_recommended_margin,
        "limitations": [
            "표본 창 ~25거래일 · 겹치는 fwd 창(비독립) · 단일 국면 — 유의성 주장 불가, 방향 판단용",
            "프록시 점수는 실제 블렌드의 모멘텀+상대강도 50%만 재현(테마·신뢰도·thesis 소급 불가)",
            "진입필터(5일 급락 tier 임계)·비중캡 미재현",
        ],
        "disclaimer": "학습·시뮬레이션 목적 — 투자 권유 아님.",
    }
    dest = ROOT / "state" / "backtest_estimate_tilt.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)} days={len(day_rows)} verdict={verdict} tiebreak={tb_verdict}")
    print(json.dumps({"ic_ab_fwd5": ic["ab_only"]["fwd5"], "ic_ab_fwd20": ic["ab_only"]["fwd20"],
                      "baseline_proxy_ic5": ic["baseline_proxy_fwd5"],
                      "spread5": spread["fwd5"], "picks": out_pick,
                      "tiebreak": out_tb,
                      "criteria": {k: v["pass"] for k, v in criteria.items()},
                      "criteria_tiebreak": {k: v["pass"] for k, v in criteria_tb.items()},
                      "verdict": verdict, "tiebreak_verdict": tb_verdict,
                      "tiebreak_recommended_margin": tb_recommended_margin}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
