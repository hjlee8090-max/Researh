#!/usr/bin/env python3
"""trade_log.jsonl 과 portfolio.json 의 정합성을 검증한다.

검증 항목:
- 초기자본 + 모든 cash 변화의 합 = portfolio.cash
- 각 ticker 별 (BUY shares - SELL/TRAILING_STOP shares) = portfolio.positions[i].shares
- 모든 SELL/TRAILING_STOP 의 realized_pnl 합 = portfolio.realized_pnl
- trade_log 의 trade_count 추정 = portfolio.trade_count

표준 라이브러리만 사용. 의존성 0.
출력: stdout 텍스트 + exit code (0=OK, 1=불일치 발견)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# SCALE_IN(추가매수, v2.20~) 포함 — 누락 시 추가매수가 buy/sell 어느 쪽으로도 분류되지 않아
# 장부 대사와 check_trade_log_gate 전 게이트(출처·시간·추격·판단카드)를 통과 없이 우회한다
# (2026-07-08 재점검 발견 — 아직 실제 SCALE_IN 체결 0건이라 소급 영향 없음).
TRADE_ACTIONS_BUY = {"BUY", "SCALE_IN"}
TRADE_ACTIONS_SELL = {"SELL", "TRAILING_STOP", "SCALE_OUT"}


def _is_buy(action: str | None) -> bool:
    if not action:
        return False
    return action in TRADE_ACTIONS_BUY or action.startswith("BUY_")


def _is_sell(action: str | None) -> bool:
    # SELL_GIVE_BACK_STOP / SELL_TIME_STOP / SELL_TARGET 등 exit 변형도 모두 수용한다.
    if not action:
        return False
    return action in TRADE_ACTIONS_SELL or action.startswith("SELL_")


def load_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def load_trade_log() -> list[dict]:
    path = ROOT / "state" / "trade_log.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def num(v: object) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def compute_expected(trade_log: list[dict], initial_capital: float) -> dict:
    cash = initial_capital
    shares: dict[str, int] = {}
    realized_pnl = 0.0
    trade_count = 0
    for e in trade_log:
        action = e.get("action")
        ticker = e.get("ticker")
        if _is_buy(action):
            qty = int(num(e.get("shares")))
            price = num(e.get("price"))
            cash -= qty * price
            shares[ticker] = shares.get(ticker, 0) + qty
            trade_count += 1
        elif _is_sell(action):
            qty = int(num(e.get("shares")))
            # 매도대금: net_proceeds 가 없는 라인(2026-07-06 LS ELECTRIC — execution_price 만 기록)은
            # 체결가×주수로 폴백. 폴백까지 없으면 0(기존 동작)이라 cash 불일치로 표면화된다.
            net = num(e.get("net_proceeds"))
            if not net:
                per_share = num(e.get("execution_price")) or num(e.get("net_price_per_share")) or num(e.get("price"))
                net = per_share * qty
            # 왕복 실현손익: realized_delta(신 스키마, 왕복분) 우선 — realized_pnl 은 2026-07-06
            # 라인부터 '누적치'로 의미가 바뀌어 그대로 합산하면 이중계상된다(-77,928 을 왕복분으로
            # 오인 → 계좌 실현손익 65,070원 과대계상, 2026-07-06 감사 발견). rule_attribution 과 동일 규약.
            pnl = num(e.get("realized_delta"))
            if pnl == 0.0 and e.get("realized_delta") is None:
                pnl = num(e.get("realized_pnl"))
            cash += net
            shares[ticker] = shares.get(ticker, 0) - qty
            realized_pnl += pnl
            trade_count += 1
    return {
        "cash": cash,
        "shares": {k: v for k, v in shares.items() if v != 0},
        "realized_pnl": realized_pnl,
        "trade_count": trade_count,
    }


def compare(expected: dict, portfolio: dict) -> list[str]:
    issues: list[str] = []

    actual_cash = num(portfolio.get("cash"))
    if abs(expected["cash"] - actual_cash) > 1:
        issues.append(
            f"cash 불일치: trade_log 기준 {expected['cash']:,.0f} vs portfolio.cash {actual_cash:,.0f}"
        )

    actual_positions = {
        p.get("ticker"): int(num(p.get("shares")))
        for p in portfolio.get("positions", [])
        if isinstance(p, dict) and int(num(p.get("shares"))) > 0
    }
    if expected["shares"] != actual_positions:
        only_expected = {k: v for k, v in expected["shares"].items() if actual_positions.get(k) != v}
        only_actual = {k: v for k, v in actual_positions.items() if expected["shares"].get(k) != v}
        if only_expected or only_actual:
            issues.append(
                f"positions 불일치: trade_log 기준 {only_expected} vs portfolio {only_actual}"
            )

    actual_pnl = num(portfolio.get("realized_pnl"))
    if abs(expected["realized_pnl"] - actual_pnl) > 1:
        issues.append(
            f"realized_pnl 불일치: trade_log 기준 {expected['realized_pnl']:+,.0f} vs portfolio {actual_pnl:+,.0f}"
        )

    return issues


def load_snapshot() -> dict:
    path = ROOT / "state" / "market_snapshot.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def valuation_checks(portfolio: dict, snapshot: dict | None = None) -> tuple[list[str], list[str]]:
    """포트폴리오 평가금액 '산식' 정합성(issues)과 스냅샷 대비 평가가격 괴리(warnings)를 점검한다.

    issues(하드, 자동계산이라 어긋나면 안 됨):
      - market_value ≠ shares × current_price
      - equity ≠ cash + Σ market_value
      - unrealized_pnl ≠ Σ(market_value − cost_basis)
    warnings(권고): current_price 가 최신 스냅샷 last_close 대비 3% 초과 괴리 — 평가가 묵었을 수 있음
      (2026-06-01 삼성전자: portfolio 평가 317,000 vs 스냅샷 344,500 = 8% 괴리를 잡기 위한 신호).
    """
    snapshot = snapshot or {}
    issues: list[str] = []
    warnings: list[str] = []
    cash = num(portfolio.get("cash"))
    ts = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    mv_sum = 0.0
    upnl_sum = 0.0
    for p in portfolio.get("positions", []):
        if not isinstance(p, dict):
            continue
        tk = p.get("ticker")
        shares = num(p.get("shares"))
        # 평가가격·평가금액은 routine 에 따라 current_price/market_value 또는 _approx 접미 필드로 기록된다.
        # compute_allocation.py 와 동일하게 _approx(→entry_price) 폴백을 적용해 필드명 불일치로
        # 평가금액이 0 으로 떨어지며 equity 정합성이 FAIL 하던 문제를 막는다(2026-06-04 삼성전자 매수 사례).
        cur = num(p.get("current_price"))
        if not cur:
            cur = num(p.get("current_price_approx")) or num(p.get("entry_price"))
        mv_field = p.get("market_value")
        if mv_field is None:
            mv_field = p.get("market_value_approx")
        mv = num(mv_field) if mv_field is not None else shares * cur
        mv_sum += mv
        if cur and abs(mv - shares * cur) > 1:
            issues.append(f"{tk} market_value {mv:,.0f} ≠ shares×current_price {shares * cur:,.0f}")
        cost = p.get("cost_basis")
        if cost is None:
            cost = p.get("cost_basis_total")
        if cost is not None:
            upnl_sum += mv - num(cost)
        snap_t = ts.get(tk) if isinstance(ts, dict) else None
        snap_close = snap_t.get("last_close") if isinstance(snap_t, dict) else None
        if cur and snap_close:
            gap = abs(cur - snap_close) / snap_close * 100
            if gap > 3.0:
                warnings.append(
                    f"{tk} 평가가격 {cur:,.0f} 이 최신 스냅샷 {snap_close:,.0f} 대비 {gap:.1f}% 괴리 — 평가 stale 가능(재평가 권고)"
                )
    equity = portfolio.get("equity")
    if equity is not None and abs(num(equity) - (cash + mv_sum)) > 1:
        issues.append(f"equity {num(equity):,.0f} ≠ cash+Σmarket_value {cash + mv_sum:,.0f}")
    upnl = portfolio.get("unrealized_pnl")
    if upnl is not None and abs(num(upnl) - upnl_sum) > 1:
        # 표시용 파생값 — 사이징/heat 안전성과 무관하므로 매매를 막는 hard issue 가 아닌 warning 으로 둔다
        # (equity·market_value 산식은 hard issue 유지: 이 둘은 사이징·heat 계산의 입력이므로).
        warnings.append(
            f"unrealized_pnl {num(upnl):+,.0f} ≠ Σ(market_value−cost_basis) {upnl_sum:+,.0f} (표시값 재계산 권고)"
        )
    return issues, warnings


def main() -> int:
    portfolio = load_json("config/portfolio.json")
    trade_log = load_trade_log()
    initial_capital = num(portfolio.get("initial_capital", 5000000))

    expected = compute_expected(trade_log, initial_capital)
    issues = compare(expected, portfolio)
    val_issues, val_warnings = valuation_checks(portfolio, load_snapshot())
    issues = issues + val_issues

    summary = {
        "trade_log_lines": len(trade_log),
        "expected_cash": round(expected["cash"]),
        "expected_realized_pnl": round(expected["realized_pnl"]),
        "expected_positions": expected["shares"],
        "actual_cash": round(num(portfolio.get("cash"))),
        "actual_realized_pnl": round(num(portfolio.get("realized_pnl"))),
        "issues": issues,
        "warnings": val_warnings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
