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

검사 후 '보완'까지 닫는 findings 수명 관리 (2026-07-07 사용자 요청):
  경고를 보고만 하면 처분이 조용히 이월된다(감사 발견: '금요일 ORANGE 룰' 4주 방치).
  그래서 ⚠️ 항목마다 안정 ID 를 부여해 state/self_audit_findings.json 에 수명을 기록한다 —
  · 신규(open) → sunday_policy_review 가 disposition{action: patch|defer|observe, note}을 기입
  · 다음 감사가 자동 검증: 지표가 해소되면 status=resolved(보완 확인),
    'patch' 처분인데 다음 주에도 재발하면 처분을 무효화하고 재상정(효과 없는 패치 감지)
  · 처분 없이 2주(기본) 경과한 open finding = overdue — `--followup-only` 모드(AUDIT_ENFORCE=1)가
    exit 1 로 주간 워크플로를 FAIL 시킨다(방치 불가능).

출력: state/self_audit.json(히스토리) + state/self_audit_findings.json(수명·처분)
      + reports/YYYY-MM-DD-self-audit.md + stdout 요약.
종료코드: 기본 0(어드바이저리). `--followup-only` + AUDIT_ENFORCE=1 이고 overdue 존재 시 1.
표준 라이브러리만 사용. weekly_self_audit.yml(일요일 17:00 KST)이 실행하며,
sunday_policy_review 프롬프트가 이 산출을 의무 인용·처분한다.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import reconcile_portfolio as rp  # 장부 대사 재사용 (단일 출처)
import check_trade_log_gate as tlg  # 게이트 위반 집계 재사용

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
STATE_PATH = ROOT / "state" / "self_audit.json"
FINDINGS_PATH = ROOT / "state" / "self_audit_findings.json"
INCEPTION = "2026-05-20"  # 계좌 가동일 — vs KOSPI 기준점
OVERDUE_WEEKS = 2          # open + 무처분 이 주수 이상이면 overdue(강제 모드 FAIL)
DISPOSITION_STALE_DAYS = 14  # 처분 후에도 finding 이 이 일수 넘게 살아 있으면 재처분 요구


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


# ── findings 수명 관리 (검사 → 처분 → 보완 검증 닫힌 루프) ─────────────────────
def extract_findings(m: dict, prev_metrics: dict | None) -> list[dict]:
    """이번 감사에서 트리거된 finding 목록 — 안정 ID + 사람이 읽는 title + 지표 스냅샷."""
    a, c, d, e, f, g = (m[k] for k in ("ledger", "benchmark", "whipsaw", "gates",
                                       "patch_vs_validation", "deployment"))
    out: list[dict] = []
    if not a["ok"]:
        out.append({
            "id": "ledger-mismatch",
            "title": "원장 불일치 — 다른 모든 지표가 오염되므로 최우선 수정",
            "detail": "; ".join(a["reconcile_issues"] + a["pnl_mismatch_trips"]),
            "severity": "hard",
        })
    if (d.get("whipsaw_rate_pct") or 0) >= 50:
        out.append({
            "id": "whipsaw-high",
            "title": f"스톱 휩쏘율 {d.get('whipsaw_rate_pct')}% — 노이즈 저점 매도 반복",
            "detail": f"손실 스톱 t+5 일실 합계 {d.get('t5_forgone_sum_krw')}원. 오버레이 백테스트(H) 재실행·청산 룰 shadow 강등 검토.",
            "severity": "warn",
        })
    if (e.get("total") or 0) > 0:
        out.append({
            "id": "gate-violations",
            "title": f"하드 게이트 위반 {e.get('total')}건",
            "detail": f"provenance {e.get('provenance')} · timing {e.get('timing')} · chase {e.get('chase')} · shock {e.get('index_shock')} · card {e.get('decision_card')}",
            "severity": "hard",
        })
    if f.get("warning"):
        out.append({
            "id": "patch-without-validation",
            "title": "검증 표본 없는 정책 패치 — 패치 동결 규칙 발동",
            "detail": f.get("warning"),
            "severity": "warn",
        })
    if g.get("warning"):
        out.append({
            "id": "deployment-below-band",
            "title": f"주식비중 {g.get('stock_pct')}% < 목표 하한 {(g.get('target_band') or ['?'])[0]}% — 만성 미배치",
            "detail": g.get("warning"),
            "severity": "warn",
        })
    # 벤치마크 격차가 직전 감사 대비 2%p 이상 추가 악화
    prev_gap = ((prev_metrics or {}).get("benchmark") or {}).get("gap_pp")
    cur_gap = c.get("gap_pp")
    if isinstance(prev_gap, (int, float)) and isinstance(cur_gap, (int, float)) and cur_gap < prev_gap - 2:
        out.append({
            "id": "benchmark-gap-widening",
            "title": f"vs KOSPI 격차 악화 {prev_gap}%p → {cur_gap}%p",
            "detail": "미배치/휩쏘/추격 중 어느 경로인지 D·G 항목과 대조.",
            "severity": "warn",
        })
    return out


def merge_findings(triggered: list[dict], today: str) -> dict:
    """이번 트리거를 기존 findings 원장과 병합 — 수명 갱신·자동 해소·무효 패치 재상정.

    규칙:
    · 같은 id 가 다시 트리거 → last_seen/weeks_seen 갱신. 이때 기존 disposition 이
      action=patch 였다면 '패치했는데 재발'이므로 disposition 을 disposition_history 로
      밀고 재처분 요구(효과 없는 보완 감지 — 이것이 '보완 검증'의 핵심).
      defer/observe 처분도 DISPOSITION_STALE_DAYS 를 넘기면 동일하게 만료.
    · 트리거되지 않은 open finding → status=resolved (지표가 실제로 나아짐 = 보완 확인).
    """
    ledger = load_json(FINDINGS_PATH, {})
    findings: list[dict] = ledger.get("findings") or []
    by_id = {f.get("id"): f for f in findings if isinstance(f, dict)}
    triggered_ids = set()

    for t in triggered:
        triggered_ids.add(t["id"])
        cur = by_id.get(t["id"])
        if cur is None or cur.get("status") == "resolved":
            entry = {
                "id": t["id"], "title": t["title"], "detail": t.get("detail"),
                "severity": t.get("severity", "warn"),
                "first_seen": today, "last_seen": today, "weeks_seen": 1,
                "status": "open", "disposition": None, "disposition_history": (cur or {}).get("disposition_history", []),
            }
            if cur is None:
                findings.append(entry)
                by_id[t["id"]] = entry
            else:  # 해소됐다가 재발 — 새 수명으로 재오픈하되 이력 보존
                entry["disposition_history"] = cur.get("disposition_history", [])
                if cur.get("disposition"):
                    entry["disposition_history"] = entry["disposition_history"] + [cur["disposition"]]
                cur.clear()
                cur.update(entry)
            continue
        # 계속 open 인 기존 finding
        cur["title"], cur["detail"] = t["title"], t.get("detail")
        cur["last_seen"] = today
        cur["weeks_seen"] = int(cur.get("weeks_seen", 1)) + 1
        disp = cur.get("disposition")
        if isinstance(disp, dict):
            expire = False
            reason = None
            if disp.get("action") == "patch":
                expire, reason = True, "패치 처분 후에도 재발 — 보완 효과 없음, 재상정"
            else:
                d0 = str(disp.get("date") or "")[:10]
                try:
                    age = (datetime.fromisoformat(today) - datetime.fromisoformat(d0)).days
                except ValueError:
                    age = None
                if age is not None and age > DISPOSITION_STALE_DAYS:
                    expire, reason = True, f"처분 {age}일 경과에도 지속 — 재처분 요구"
            if expire:
                disp["expired"] = reason
                cur.setdefault("disposition_history", []).append(disp)
                cur["disposition"] = None

    for f in findings:
        if f.get("status") == "open" and f.get("id") not in triggered_ids:
            f["status"] = "resolved"
            f["resolved_date"] = today

    overdue = [
        f for f in findings
        if f.get("status") == "open" and not f.get("disposition")
        and int(f.get("weeks_seen", 1)) >= OVERDUE_WEEKS
    ]
    return {
        "as_of": today,
        "note": "sunday_policy_review 가 open finding 의 disposition 에 {action: patch|defer|observe, note, date} 를 기입한다. "
                "patch 처분 후 재발·처분 14일 초과 지속은 자동 만료·재상정. "
                f"무처분 {OVERDUE_WEEKS}주 이상 = overdue → weekly_self_audit 워크플로 FAIL.",
        "findings": findings,
        "open": [f["id"] for f in findings if f.get("status") == "open"],
        "overdue": [f["id"] for f in overdue],
    }


def check_followup_only() -> int:
    """--followup-only — findings 원장만 읽어 overdue 존재 시 exit 1 (AUDIT_ENFORCE=1 일 때).

    lessons-gate 와 같은 패턴: 산출은 본 실행이 하고, 강제는 별도 게이트 스텝이 한다.

    overdue 는 저장된 배열이 아니라 findings 에서 **실시간 재계산**한다 — 20시 리뷰가
    disposition 을 기입한 직후 이 모드로 확인할 때, 17시에 저장된 낡은 overdue 배열을
    읽으면 처분이 반영 안 된 것처럼 FAIL 이 나기 때문(2026-07-08 재점검에서 발견)."""
    ledger = load_json(FINDINGS_PATH, {})
    enforce = os.environ.get("AUDIT_ENFORCE", "").strip().lower() in ("1", "true", "yes", "on")
    findings = [f for f in ledger.get("findings") or [] if isinstance(f, dict)]
    open_ids = [f["id"] for f in findings if f.get("status") == "open"]
    overdue = [
        f for f in findings
        if f.get("status") == "open" and not f.get("disposition")
        and int(f.get("weeks_seen", 1)) >= OVERDUE_WEEKS
    ]
    overdue_ids = [f["id"] for f in overdue]
    for f in overdue:
        print(f"[OVERDUE 무처분] {f['id']} ({f.get('weeks_seen')}주째): {f.get('title')}")
    print(f"self_audit followup: open={len(open_ids)} overdue={len(overdue_ids)} enforce={enforce}")
    if enforce and overdue_ids:
        print(f"AUDIT_ENFORCE — 무처분 {OVERDUE_WEEKS}주 이상 finding {len(overdue_ids)}건으로 FAIL "
              "(sunday_policy_review 가 state/self_audit_findings.json 의 disposition 을 기입해야 한다)")
        return 1
    return 0


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
    ledger = m.get("findings_ledger") or {}
    open_findings = [x for x in ledger.get("findings") or [] if x.get("status") == "open"]
    resolved_now = [x for x in ledger.get("findings") or [] if x.get("resolved_date") == today]
    if open_findings:
        lines += [
            "## ⚠️ 이번 주 조치 필요 (findings — 처분 의무)",
            "",
            "> 각 항목의 처분은 `state/self_audit_findings.json` 의 `disposition` 에 기입한다"
            " (`{\"action\": \"patch|defer|observe\", \"note\": \"...\", \"date\": \"...\"}`)."
            f" 무처분 {OVERDUE_WEEKS}주 이상은 주간 워크플로 FAIL. patch 처분 후 재발은 자동 재상정.",
            "",
            "| id | 항목 | 경과 | 처분 상태 |",
            "|---|---|---|---|",
        ]
        for x in open_findings:
            disp = x.get("disposition")
            if isinstance(disp, dict):
                disp_str = f"{disp.get('action')} — {str(disp.get('note') or '')[:60]}"
            else:
                hist = x.get("disposition_history") or []
                expired = next((h.get("expired") for h in reversed(hist) if isinstance(h, dict) and h.get("expired")), None)
                disp_str = f"**무처분**{' (' + expired + ')' if expired and x.get('weeks_seen', 1) > 1 else ''}"
            overdue_mark = " 🔴overdue" if x.get("id") in (ledger.get("overdue") or []) else ""
            lines.append(f"| `{x.get('id')}` | {x.get('title')} | {x.get('weeks_seen')}주째{overdue_mark} | {disp_str} |")
        lines.append("")
    if resolved_now:
        lines += ["## ✅ 이번 주 해소 확인 (보완 검증)", ""]
        lines += [f"- `{x.get('id')}` {x.get('title')} — 지표 정상화로 자동 해소" for x in resolved_now]
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
    parser = argparse.ArgumentParser(description="주간 자기감사 — 측정 + findings 수명 관리")
    parser.add_argument(
        "--followup-only", action="store_true",
        help="findings 원장만 검사(산출물 미생성) — AUDIT_ENFORCE=1 이고 무처분 overdue 존재 시 exit 1",
    )
    args = parser.parse_args()
    if args.followup_only:
        return check_followup_only()

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

    # findings 수명 병합 — 검사가 '보완 요구'로, 다음 검사가 '보완 검증'으로 이어진다.
    today = now.date().isoformat()
    ledger = merge_findings(extract_findings(metrics, prev), today)
    FINDINGS_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics["findings_ledger"] = ledger

    history = state.get("history") or []
    history.append({k: v for k, v in metrics.items() if k != "findings_ledger"})
    STATE_PATH.write_text(
        json.dumps({"as_of": metrics["as_of"], "history": history[-26:]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = render_markdown(metrics)
    report_path = ROOT / "reports" / f"{now.date().isoformat()}-self-audit.md"
    report_path.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nself_audit → {report_path.relative_to(ROOT)} + {FINDINGS_PATH.relative_to(ROOT)} "
          f"(open {len(ledger.get('open') or [])}·overdue {len(ledger.get('overdue') or [])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
