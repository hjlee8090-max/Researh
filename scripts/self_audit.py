#!/usr/bin/env python3
"""주간 자기감사 (self_audit) — 2026-07-06 수동 감사를 코드로 영구화한 정기 점검.

배경: 2026-07-06 감사가 사람 손으로 발견한 것들 — ①rule_attribution 원장 이중계상
②만성 미배치로 vs KOSPI -12%p ③손실 스톱 6건 전부 휩쏘(청산 후 8~16% 회복)
④패치 속도(주 4~5버전)가 검증 속도(청산 주 0~2건)를 압도 ⑤lessons 강제 게이트 부재 —
는 전부 '한 번' 발견됐다는 사실이 문제였다(그 전 6주간 아무도 못 봄). 이 스크립트는
그 발견 항목들을 매주 기계로 재측정해, 악화/개선을 사람이 매주 확인할 수 있게 한다.

측정 항목(A~H):
  A. 원장 정합성 — reconcile issues + rule_attribution pnl_mismatch
  B. 계좌 성과 — PF/승률/기대값 + 직전 감사 대비 델타
  C. vs KOSPI — 가동 시점(2026-05-20) 이후 누적 격차(%p)   ← 감사 처방⑥
  D. 스톱 휩쏘 — 손실 스톱 청산 중 t+5 일실 양수 비율
  E. 하드 게이트 위반 — check_trade_log_gate 6종 위반 수
  F. 패치 vs 검증 — 직전 감사 이후 policy 버전 증가 vs 신규 왕복 수
  G. 배치 — 주식비중 vs 레짐 목표 밴드, heat 잔여
  H. 청산 오버레이 백테스트 판정 — backtest_exit_overlay verdict 인용

출력: state/self_audit.json(히스토리 누적) + reports/YYYY-MM-DD-self-audit.md + stdout 요약.
종료코드: 항상 0(어드바이저리 — 하드 차단은 check_trade_log_gate/lessons-gate 몫).
표준 라이브러리만 사용. weekly_self_audit.yml(일요일 17:00 KST)이 실행하며,
sunday_policy_review 프롬프트가 이 산출을 의무 인용한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import reconcile_portfolio as rp  # 장부 대사 재사용 (단일 출처)
import check_trade_log_gate as tlg  # 게이트 위반 집계 재사용

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
STATE_PATH = ROOT / "state" / "self_audit.json"
INCEPTION = "2026-05-20"  # 계좌 가동일 — vs KOSPI 기준점


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def krw(v) -> str:
    return f"{v:+,.0f}원" if isinstance(v, (int, float)) else "?"


# ── A. 원장 정합성 ─────────────────────────────────────────────────────────────
def audit_ledger(portfolio: dict, attr: dict) -> dict:
    trade_log = rp.load_trade_log()
    expected = rp.compute_expected(trade_log, rp.num(portfolio.get("initial_capital", 5000000)))
    issues = rp.compare(expected, portfolio)
    mismatches = [tr for tr in attr.get("round_trips") or [] if tr.get("pnl_mismatch")]
    return {
        "reconcile_issues": issues,
        "pnl_mismatch_trips": [
            f"{tr.get('exit_date')} {tr.get('name')}: 로그 {tr.get('logged_realized_pnl')} vs 재계산 {tr.get('realized_pnl')}"
            for tr in mismatches
        ],
        "ok": not issues and not mismatches,
    }


# ── B. 계좌 성과 (+ 직전 감사 대비) ─────────────────────────────────────────────
def audit_performance(attr: dict, prev: dict | None) -> dict:
    acct = attr.get("account") or {}
    out = {
        "closed_exits": acct.get("closed_exits"),
        "win_rate_pct": acct.get("win_rate_pct"),
        "profit_factor": acct.get("profit_factor"),
        "net_realized": acct.get("net_realized"),
        "expectancy_per_exit": acct.get("expectancy_per_exit"),
    }
    if prev:
        p = prev.get("performance") or {}
        for k in ("closed_exits", "profit_factor", "net_realized"):
            cur, old = out.get(k), p.get(k)
            if isinstance(cur, (int, float)) and isinstance(old, (int, float)):
                out[f"delta_{k}"] = round(cur - old, 2)
    return out


# ── C. vs KOSPI 누적 격차 ─────────────────────────────────────────────────────
def audit_benchmark(portfolio: dict) -> dict:
    hist = load_json(ROOT / "state" / "price_history.json", {})
    bars = ((hist.get("index") or {}).get("bars")) or []
    closes = {b["date"]: float(b["close"]) for b in bars if isinstance(b, dict) and b.get("close")}
    dates = sorted(d for d in closes if d >= INCEPTION)
    port_pct = portfolio.get("cumulative_return_pct")
    if not dates or not isinstance(port_pct, (int, float)):
        return {"gap_pp": None, "note": "지수 이력 또는 계좌 누적 수익률 없음"}
    kospi_pct = round((closes[dates[-1]] / closes[dates[0]] - 1) * 100, 2)
    return {
        "since": dates[0],
        "as_of": dates[-1],
        "portfolio_pct": port_pct,
        "kospi_pct": kospi_pct,
        "gap_pp": round(port_pct - kospi_pct, 2),
    }


# ── D. 스톱 휩쏘 지표 ──────────────────────────────────────────────────────────
def audit_whipsaw(attr: dict) -> dict:
    stop_losses = [
        tr for tr in attr.get("round_trips") or []
        if isinstance(tr.get("realized_pnl"), (int, float)) and tr["realized_pnl"] < 0
        and any(m in str(tr.get("exit_rule", "")).upper() for m in ("STOP", "TRAILING"))
    ]
    scored, whipsaws, forgone_sum = 0, 0, 0.0
    for tr in stop_losses:
        t5 = (tr.get("post_exit") or {}).get("t5")
        if isinstance(t5, dict) and isinstance(t5.get("forgone_krw"), (int, float)):
            scored += 1
            forgone_sum += t5["forgone_krw"]
            if t5["forgone_krw"] > 0:
                whipsaws += 1
    return {
        "loss_stop_exits": len(stop_losses),
        "scored_t5": scored,
        "whipsaw_count": whipsaws,
        "whipsaw_rate_pct": round(whipsaws / scored * 100, 1) if scored else None,
        "t5_forgone_sum_krw": round(forgone_sum, 0),
        "note": "휩쏘 = 손실 스톱 청산 후 t+5 관측가가 청산가 위(팔고 올랐다). 2026-07-06 감사 실측 6/6건.",
    }


# ── E. 하드 게이트 위반 현황 ───────────────────────────────────────────────────
def audit_gates(policy: dict) -> dict:
    entries = rp.load_trade_log()
    pdq = policy.get("price_data_quality", {})
    risk = policy.get("risk", {})
    mh = policy.get("market_hours", {})
    counts = {}
    v, _, _ = tlg.find_violations(entries, pdq.get("trade_provenance_gate", {}) or {})
    counts["provenance"] = len(v)
    v, _, _ = tlg.find_timing_violations(entries, mh.get("trade_timing_gate", {}) or {})
    counts["timing"] = len(v)
    v, _, _ = tlg.find_chase_violations(entries, risk.get("chase_entry_filter", {}) or {})
    counts["chase"] = len(v)
    v, _, _ = tlg.find_index_shock_violations(entries, risk.get("index_shock_stop_deferral", {}) or {})
    counts["index_shock"] = len(v)
    v, _, _ = tlg.find_decision_card_violations(entries, pdq.get("decision_card_gate", {}) or {})
    counts["decision_card"] = len(v)
    counts["total"] = sum(counts.values())
    return counts


# ── F. 패치 vs 검증 속도 ───────────────────────────────────────────────────────
def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def audit_patch_vs_validation(policy: dict, attr: dict, prev: dict | None) -> dict:
    cur_ver = str(policy.get("version", "?"))
    prev_ver = (prev or {}).get("policy_version")
    prev_date = ((prev or {}).get("as_of") or "")[:10]
    new_trips = None
    if prev_date:
        new_trips = sum(
            1 for tr in attr.get("round_trips") or []
            if str(tr.get("exit_date") or "") > prev_date
        )
    out = {
        "policy_version": cur_ver,
        "prev_audit_version": prev_ver,
        "new_round_trips_since_prev": new_trips,
        "note": "패치(버전 증가)가 신규 왕복(검증 표본)보다 빠르면 어떤 패치가 효과였는지 영원히 알 수 없다(2026-07-06 감사: 47일간 31버전 vs 왕복 9건).",
    }
    if prev_ver and cur_ver != "?":
        bumped = _version_tuple(cur_ver) > _version_tuple(prev_ver)
        out["version_bumped_since_prev"] = bumped
        if bumped and (new_trips or 0) == 0:
            out["warning"] = "⚠️ 직전 감사 이후 정책 버전이 올라갔는데 신규 검증 표본(왕복)이 0건 — 패치 동결 검토(검증 없는 패치 누적)."
    return out


# ── G. 배치(미배치·heat) ───────────────────────────────────────────────────────
def audit_deployment(portfolio: dict, alloc: dict, policy: dict) -> dict:
    equity = rp.num(portfolio.get("equity"))
    cash = rp.num(portfolio.get("cash"))
    stock_pct = round((1 - cash / equity) * 100, 1) if equity else None
    heat = alloc.get("portfolio_heat") or {}
    tier = heat.get("budget_basis") or "?"
    tiers = ((policy.get("market_regime") or {}).get("dynamic_sizing") or {}).get("tiers") or []
    band = next((t.get("target_equity_pct") for t in tiers if isinstance(t, dict) and t.get("tier") == tier), None)
    out = {
        "stock_pct": stock_pct,
        "regime_tier": tier,
        "target_band": band,
        "heat_remaining_krw": heat.get("remaining_krw"),
        "heat_budget_krw": heat.get("budget_krw"),
    }
    if isinstance(band, (list, tuple)) and len(band) == 2 and isinstance(stock_pct, (int, float)):
        if stock_pct < band[0]:
            out["warning"] = (
                f"⚠️ 주식비중 {stock_pct}% < 목표 하한 {band[0]}% — 만성 미배치 계열"
                + (" (heat 잔여 0원이 병목이면 종목당 히트 점유 상한/래칫 승격 검토)" if not heat.get("remaining_krw") else "")
            )
    return out


# ── H. 청산 오버레이 백테스트 판정 ─────────────────────────────────────────────
def audit_overlay() -> dict:
    bt = load_json(ROOT / "state" / "backtest_exit_overlay.json", {})
    if not bt:
        return {"available": False}
    return {"available": True, "as_of": bt.get("as_of"), "verdict": bt.get("verdict")}


def render_markdown(m: dict) -> str:
    a, b, c, d, e, f, g, h = (m[k] for k in ("ledger", "performance", "benchmark", "whipsaw",
                                             "gates", "patch_vs_validation", "deployment", "overlay"))
    today = m["as_of"][:10]
    lines = [
        f"# {today} — 주간 자기감사 (self-audit, 기계 생성)",
        "",
        "> `scripts/self_audit.py` 산출 — 2026-07-06 수동 감사 항목의 정기 재측정. 수동 편집 금지.",
        "> sunday_policy_review 는 이 리포트를 의무 인용하고, ⚠️ 항목마다 조치/보류 사유를 남긴다.",
        "",
        "## 한눈에 보기",
        "",
        "| 항목 | 상태 |",
        "|---|---|",
        f"| A. 원장 정합성 | {'✅ 일치' if a['ok'] else '⚠️ ' + '; '.join(a['reconcile_issues'] + a['pnl_mismatch_trips'])} |",
        f"| B. 계좌 성과 | 왕복 {b.get('closed_exits')}건 · 승률 {b.get('win_rate_pct')}% · PF {b.get('profit_factor')} · 순실현 {krw(b.get('net_realized'))} |",
        f"| C. vs KOSPI ({c.get('since')}~) | 계좌 {c.get('portfolio_pct')}% vs KOSPI {c.get('kospi_pct')}% → **격차 {c.get('gap_pp')}%p** |",
        f"| D. 스톱 휩쏘 | 손실 스톱 {d.get('loss_stop_exits')}건 중 t+5 채점 {d.get('scored_t5')}건 · 휩쏘 {d.get('whipsaw_count')}건 ({d.get('whipsaw_rate_pct')}%) · 일실 합계 {krw(d.get('t5_forgone_sum_krw'))} |",
        f"| E. 게이트 위반 | 총 {e.get('total')}건 (provenance {e.get('provenance')} · timing {e.get('timing')} · chase {e.get('chase')} · shock {e.get('index_shock')} · card {e.get('decision_card')}) |",
        f"| F. 패치 vs 검증 | policy v{f.get('policy_version')} (직전 감사 v{f.get('prev_audit_version')}) · 신규 왕복 {f.get('new_round_trips_since_prev')}건 |",
        f"| G. 배치 | 주식 {g.get('stock_pct')}% (tier {g.get('regime_tier')}, 목표 {g.get('target_band')}) · heat 잔여 {g.get('heat_remaining_krw')}원 |",
        f"| H. 오버레이 백테스트 | {'판정 있음(아래)' if h.get('available') else '미실행'} |",
        "",
    ]
    warnings = [w for w in (
        f.get("warning"), g.get("warning"),
        None if a["ok"] else "⚠️ 원장 불일치 — 다른 모든 지표가 오염되므로 최우선 수정",
        None if (d.get("whipsaw_rate_pct") or 0) < 50 else
        f"⚠️ 휩쏘율 {d.get('whipsaw_rate_pct')}% — 스톱이 노이즈 저점에서 팔고 있다(오버레이 백테스트 H 판정과 대조할 것)",
        None if (e.get("total") or 0) == 0 else "⚠️ 하드 게이트 위반 존재 — check_trade_log_gate 출력 확인",
    ) if w]
    if warnings:
        lines += ["## ⚠️ 이번 주 조치 필요", ""]
        lines += [f"- {w}" for w in warnings]
        lines.append("")
    if h.get("available") and h.get("verdict"):
        lines += ["## H. 청산 오버레이 백테스트 판정 (요약 인용)", ""]
        v = h["verdict"]
        if isinstance(v, dict):
            lines += [f"- **{k}**: {val}" for k, val in v.items()]
        else:
            lines.append(f"- {v}")
        lines.append("")
    lines += [
        "## 참고",
        "- 판단 카드(사람이 읽는 매매 논리): `state/trade_cards.md`",
        "- 룰별 손익 채점: `state/rule_attribution.json` / 원장: `state/trade_log.jsonl`",
        "- 이 감사의 원본(수동): `reports/2026-07-06-self-reinforcement-audit.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    policy = load_json(ROOT / "config" / "policy.json", {})
    portfolio = load_json(ROOT / "config" / "portfolio.json", {})
    alloc = load_json(ROOT / "state" / "allocation.json", {})
    attr = load_json(ROOT / "state" / "rule_attribution.json", {})
    state = load_json(STATE_PATH, {})
    prev = (state.get("history") or [{}])[-1] if state.get("history") else None

    now = datetime.now(KST)
    metrics = {
        "as_of": now.isoformat(timespec="seconds"),
        "ledger": audit_ledger(portfolio, attr),
        "performance": audit_performance(attr, prev),
        "benchmark": audit_benchmark(portfolio),
        "whipsaw": audit_whipsaw(attr),
        "gates": audit_gates(policy),
        "patch_vs_validation": audit_patch_vs_validation(policy, attr, prev),
        "deployment": audit_deployment(portfolio, alloc, policy),
        "overlay": audit_overlay(),
        "policy_version": str(policy.get("version", "?")),
    }

    history = state.get("history") or []
    history.append(metrics)
    STATE_PATH.write_text(
        json.dumps({"as_of": metrics["as_of"], "history": history[-26:]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = render_markdown(metrics)
    report_path = ROOT / "reports" / f"{now.date().isoformat()}-self-audit.md"
    report_path.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nself_audit → {report_path.relative_to(ROOT)} + {STATE_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
