#!/usr/bin/env python3
"""보유·후보 종목의 thesis 카드 완성도와 무효화 조건 충족 여부를 점검한다(v2.25).

배경: policy.thesis 스키마는 오래전부터 정의돼 있었으나 2026-07-26 감사 기준 보유 3종
(079550·042700·055550) 전부 thesis 객체가 비어 있었다. 논거 층이 비면 청산 판정이
가격 규칙 하나로 축소되고, 실제로 rule_attribution 의 청산 룰 7종이 전부 가격 트리거였다.

이 스크립트가 하는 일:
1) 카드 완성도 — policy.thesis.card_gate.required_fields 누락 검사
2) 반증 가능성 — invalidation 중 measurable=true 가 최소 1건 있는지 검사
   (서술형 조건만 있으면 '영원히 intact' 로 고착된다)
3) 자동 판정 — measurable invalidation 을 fundamentals/valuation_check 실측값과 대조해
   충족 여부를 판정한다. hard 충족이면 exit_reason_class=thesis_broken 후보로 표면화한다.
4) 신선도 — last_review_ts 가 staleness_trading_days 를 넘겼는지 검사
5) 체크포인트 — 날짜가 지났는데 재검토가 없는 항목 표면화

출력: state/thesis_cards.json
종료코드: 기본 0(어드바이저리 — 하드 차단은 trade_log 게이트만 유지하는 레포 원칙).
환경변수 THESIS_ENFORCE 가 truthy 이고 hard 무효화 충족이 있으면 1.
표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "thesis_cards.json"

OPERATORS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:19], text[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=KST)
    return None


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


def trading_days_between(start: date, end: date, holiday_set: set[str]) -> int:
    """start(제외) ~ end(포함) 사이 영업일 수. 역순이면 0."""
    if end <= start:
        return 0
    count = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5 and cur.isoformat() not in holiday_set:
            count += 1
        cur += timedelta(days=1)
    return count


def catalyst_dates() -> dict[str, str]:
    """config/catalysts.json 의 {catalyst_id: date} 맵."""
    cal = load_json("config/catalysts.json", {}) or {}
    out: dict[str, str] = {}
    for key in ("generated_events", "manual_events"):
        for event in cal.get(key) or []:
            if isinstance(event, dict) and event.get("id") and event.get("date"):
                out[str(event["id"])] = str(event["date"])[:10]
    return out


def data_period_label(ticker: str, fundamentals: dict) -> str | None:
    fund = (fundamentals.get("tickers") or {}).get(ticker) or {}
    label = fund.get("period_label")
    return str(label) if label else None


def resolve_metric(source_field: str | None, metric: str | None, ticker: str,
                   fundamentals: dict, valuation: dict) -> tuple[float | None, str]:
    """measurable invalidation 의 실측값을 찾는다. (값, 출처설명) 반환."""
    # 1) source_field 가 'state/x.json a.b.c' 형태면 그 경로를 따라간다.
    if isinstance(source_field, str) and source_field.strip():
        parts = source_field.split()
        rel = parts[0]
        dotted = parts[1] if len(parts) > 1 else ""
        blob = load_json(rel, None)
        if blob is not None and dotted:
            cur: Any = blob
            for seg in dotted.split("."):
                if isinstance(cur, dict) and seg in cur:
                    cur = cur[seg]
                else:
                    cur = None
                    break
            if isinstance(cur, (int, float)):
                return float(cur), f"{rel}:{dotted}"

    # 2) 폴백 — metric 이름으로 fundamentals / valuation_check 에서 직접 찾는다.
    fund = (fundamentals.get("tickers") or {}).get(ticker) or {}
    if metric and metric in fund and isinstance(fund[metric], (int, float)):
        return float(fund[metric]), f"state/fundamentals.json:{ticker}.{metric}"
    val = (valuation.get("tickers") or {}).get(ticker) or {}
    mult = val.get("current_multiple") or {}
    if metric and metric in mult and isinstance(mult[metric], (int, float)):
        return float(mult[metric]), f"state/valuation_check.json:{ticker}.current_multiple.{metric}"
    return None, "실측값 없음"


def evaluate_card(stock: dict, cfg: dict, today: date, holiday_set: set[str],
                  fundamentals: dict, valuation: dict, catalyst_map: dict[str, str]) -> dict:
    ticker = str(stock.get("ticker") or "?")
    period_label = data_period_label(ticker, fundamentals)
    name = stock.get("name") or ticker
    card = stock.get("thesis")
    required = list(cfg.get("required_fields") or [])
    stale_days = int(cfg.get("staleness_trading_days", 5))

    entry: dict[str, Any] = {
        "ticker": ticker,
        "name": name,
        "has_card": isinstance(card, dict),
        "missing_fields": [],
        "issues": [],
        "invalidation_checks": [],
        "hard_breached": [],
        "soft_breached": [],
        "due_checkpoints": [],
        "status": None,
        "stale": None,
        "fundamentals_period": period_label,
    }

    if not isinstance(card, dict):
        entry["missing_fields"] = required
        entry["issues"].append("thesis 카드 없음 — 논거 없이 보유 중")
        return entry

    entry["status"] = card.get("status")
    entry["missing_fields"] = [f for f in required if not card.get(f)]
    if entry["missing_fields"]:
        entry["issues"].append("필수 필드 누락: " + ", ".join(entry["missing_fields"]))

    # 근거 숫자 개수
    evidence = card.get("evidence")
    if isinstance(evidence, list) and len(evidence) > 3:
        entry["issues"].append(f"evidence {len(evidence)}건 — 3건 이하로 줄일 것(논거가 흐려짐)")

    # 반증 가능성
    invalidations = card.get("invalidation") or []
    measurable = [i for i in invalidations if isinstance(i, dict) and i.get("measurable")]
    if not measurable:
        entry["issues"].append(
            "measurable invalidation 0건 — 자동 판정 가능한 반증 조건이 없어 'status=intact' 가 영구 고착된다"
        )

    # 목표가 분해
    decomp = card.get("target_decomposition")
    if isinstance(decomp, dict):
        rerating = decomp.get("rerating_share_pct")
        if isinstance(rerating, (int, float)) and rerating >= 99.0:
            entry["issues"].append(
                f"목표가 상승 여력의 {rerating:.0f}% 가 멀티플 확장 — forward 이익추정이 없어 성장 기여를 분리할 수 없다"
            )
    else:
        entry["issues"].append("target_decomposition 없음 — 목표가가 무엇의 배수인지 불명")

    # measurable invalidation 자동 판정
    for inv in measurable:
        metric = inv.get("metric")
        operator = inv.get("operator")
        threshold = inv.get("threshold")
        check: dict[str, Any] = {
            "id": inv.get("id"),
            "cond": inv.get("cond"),
            "hard": bool(inv.get("hard")),
            "metric": metric,
            "operator": operator,
            "threshold": threshold,
        }
        actual, origin = resolve_metric(inv.get("source_field"), metric, ticker, fundamentals, valuation)
        check["actual"] = actual
        check["source"] = origin
        fn = OPERATORS.get(str(operator))

        # 촉매 연동 조건은 그 촉매일이 지나기 전까지 판정하지 않는다.
        # 예: '2Q 영업이익률 40% 미만' 을 1Q 확정치로 판정하면 조건이 조기 격발된다.
        linked = inv.get("linked_catalyst")
        due_on = catalyst_map.get(str(linked)) if linked else None
        if due_on:
            check["linked_catalyst"] = linked
            check["evaluate_after"] = due_on
            try:
                pending = date.fromisoformat(due_on) > today
            except ValueError:
                pending = False
            if pending:
                check["verdict"] = "판정대기"
                check["note"] = (
                    f"{due_on} {linked} 이후 판정 — 현재 실측치는 "
                    f"{period_label or '직전 확정 기간'} 기준이라 조건 기간과 다르다"
                )
                entry["invalidation_checks"].append(check)
                continue

        if actual is None or fn is None or not isinstance(threshold, (int, float)):
            check["verdict"] = "판정불가"
            check["note"] = "실측값 또는 연산자 없음"
        elif fn(actual, float(threshold)):
            check["verdict"] = "충족"
            (entry["hard_breached"] if check["hard"] else entry["soft_breached"]).append(check["id"])
        else:
            check["verdict"] = "미충족"
        entry["invalidation_checks"].append(check)

    # 체크포인트 도래
    for cp in card.get("checkpoints") or []:
        if not isinstance(cp, dict):
            continue
        cp_date = str(cp.get("date") or "")[:10]
        try:
            parsed = date.fromisoformat(cp_date)
        except ValueError:
            continue
        if parsed <= today:
            entry["due_checkpoints"].append({
                "date": cp_date,
                "event": cp.get("event"),
                "resolves": cp.get("resolves"),
            })

    # 신선도
    reviewed = parse_ts(card.get("last_review_ts"))
    if reviewed is None:
        entry["stale"] = True
        entry["issues"].append("last_review_ts 파싱 불가")
    else:
        elapsed = trading_days_between(reviewed.astimezone(KST).date(), today, holiday_set)
        entry["stale"] = elapsed > stale_days
        entry["review_age_trading_days"] = elapsed
        if entry["stale"]:
            entry["issues"].append(f"마지막 재검토 {elapsed}영업일 경과 (상한 {stale_days})")

    return entry


def main() -> int:
    policy = load_json("config/policy.json", {}) or {}
    cfg = ((policy.get("thesis") or {}).get("card_gate") or {})
    if not cfg.get("enabled", True):
        OUT_PATH.write_text(json.dumps({"enabled": False}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[INFO] thesis.card_gate 비활성")
        return 0

    watchlist = load_json("config/watchlist.json", {}) or {}
    portfolio = load_json("config/portfolio.json", {}) or {}
    fundamentals = load_json("state/fundamentals.json", {}) or {}
    valuation = load_json("state/valuation_check.json", {}) or {}

    held = {
        str(p.get("ticker"))
        for p in (portfolio.get("positions") or [])
        if isinstance(p, dict) and (p.get("shares") or 0) > 0
    }
    stocks = [s for s in (watchlist.get("stocks") or []) if isinstance(s, dict)]
    by_ticker = {str(s.get("ticker")): s for s in stocks}
    # 보유 종목이 watchlist 에 없으면 portfolio 항목으로 대신 평가한다(카드 부재가 드러나야 한다).
    targets = []
    for tk in sorted(held):
        targets.append(by_ticker.get(tk) or {"ticker": tk, "name": tk})

    today = datetime.now(KST).date()
    holiday_set = holidays()
    catalyst_map = catalyst_dates()
    cards = [
        evaluate_card(s, cfg, today, holiday_set, fundamentals, valuation, catalyst_map)
        for s in targets
    ]

    missing_card = [c["ticker"] for c in cards if not c["has_card"]]
    no_measurable = [
        c["ticker"] for c in cards
        if c["has_card"] and any("measurable invalidation 0건" in i for i in c["issues"])
    ]
    hard_breach = [c for c in cards if c["hard_breached"]]
    stale = [c["ticker"] for c in cards if c["has_card"] and c.get("stale")]

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "policy_ref": "policy.thesis.card_gate (v2.25)",
        "mode": cfg.get("mode", "warn"),
        "held_count": len(targets),
        "summary": {
            "missing_card": missing_card,
            "no_measurable_invalidation": no_measurable,
            "hard_breached": [
                {"ticker": c["ticker"], "name": c["name"], "invalidation_ids": c["hard_breached"]}
                for c in hard_breach
            ],
            "soft_breached": [
                {"ticker": c["ticker"], "name": c["name"], "invalidation_ids": c["soft_breached"]}
                for c in cards if c["soft_breached"]
            ],
            "stale_review": stale,
        },
        "cards": cards,
        "note": (
            "hard_breached 는 exit_reason_class=thesis_broken 청산 후보다 — "
            "index_shock_stop_deferral 유예를 적용하지 않는다(policy.risk.exit_classification)."
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    lines: list[str] = []
    if missing_card:
        lines.append(f"[WARN] thesis 카드 없음(논거 없이 보유): {', '.join(missing_card)}")
    if no_measurable:
        lines.append(f"[WARN] 자동 판정 가능한 반증 조건 없음: {', '.join(no_measurable)}")
    for c in hard_breach:
        lines.append(
            f"[WARN] thesis hard 무효화 충족 — {c['name']}({c['ticker']}): "
            f"{', '.join(str(i) for i in c['hard_breached'])} → thesis_broken 청산 판정 필요"
        )
    for c in cards:
        for cp in c["due_checkpoints"]:
            lines.append(f"[INFO] 체크포인트 도래 — {c['name']}({c['ticker']}) {cp['date']} {cp['event']}")
    if stale:
        lines.append(f"[WARN] thesis 재검토 지연: {', '.join(stale)}")
    pending = [
        (c, chk) for c in cards for chk in c["invalidation_checks"]
        if chk.get("verdict") == "판정대기"
    ]
    for c, chk in pending:
        lines.append(
            f"[INFO] 무효화 판정 대기 — {c['name']}({c['ticker']}) {chk['id']}: "
            f"{chk.get('evaluate_after')} 이후"
        )
    if not any(l.startswith("[WARN]") for l in lines):
        lines.insert(0, f"[OK] thesis 카드 {len(targets)}종 정상 — hard 무효화 충족·재검토 지연 없음")
    print("\n".join(lines))

    enforce = str(os.environ.get("THESIS_ENFORCE", "")).strip().lower() in {"1", "true", "yes", "on"}
    return 1 if (enforce and hard_breach) else 0


if __name__ == "__main__":
    sys.exit(main())
