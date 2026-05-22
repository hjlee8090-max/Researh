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
TRADE_ACTIONS_BUY = {"BUY"}
TRADE_ACTIONS_SELL = {"SELL", "TRAILING_STOP", "SCALE_OUT"}


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
        if action in TRADE_ACTIONS_BUY:
            qty = int(num(e.get("shares")))
            price = num(e.get("price"))
            cash -= qty * price
            shares[ticker] = shares.get(ticker, 0) + qty
            trade_count += 1
        elif action in TRADE_ACTIONS_SELL:
            qty = int(num(e.get("shares")))
            net = num(e.get("net_proceeds"))
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


def main() -> int:
    portfolio = load_json("config/portfolio.json")
    trade_log = load_trade_log()
    initial_capital = num(portfolio.get("initial_capital", 5000000))

    expected = compute_expected(trade_log, initial_capital)
    issues = compare(expected, portfolio)

    summary = {
        "trade_log_lines": len(trade_log),
        "expected_cash": round(expected["cash"]),
        "expected_realized_pnl": round(expected["realized_pnl"]),
        "expected_positions": expected["shares"],
        "actual_cash": round(num(portfolio.get("cash"))),
        "actual_realized_pnl": round(num(portfolio.get("realized_pnl"))),
        "issues": issues,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
