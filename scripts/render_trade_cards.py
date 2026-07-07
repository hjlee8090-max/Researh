#!/usr/bin/env python3
"""매매 판단 카드 렌더러 — 모든 매수·매도를 '사람이 읽고 공감/반박할 수 있는' 카드로 렌더링한다.

배경 (2026-07-06 감사): trade_log 의 reason 한 줄은 서사·수치가 섞여 사람이 "이 매매가
논리적이었나"를 검증하기 어려웠다. policy.price_data_quality.decision_card_gate(v2.22)가
2026-07-07 이후 체결에 구조화된 decision_card(thesis/근거/무효화 조건/트리거)를 의무화하고,
이 스크립트가 카드 + 결과(실현손익·사후 일실)를 한 파일로 묶어 사람이 매 거래를 사후
검토할 수 있게 한다 — "논리가 맞았는데 운이 나빴는지, 논리 자체가 없었는지"를 구분하는 것이 목적.

입력: state/trade_log.jsonl(체결·판단 카드), state/rule_attribution.json(왕복 손익·사후 일실)
출력: state/trade_cards.md (생성 파일 — 수동 편집 금지)
표준 라이브러리만 사용. pipeline_audit(일일)·weekly_self_audit(주간)이 실행한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "trade_cards.md"
CARD_SINCE = "2026-07-07"  # decision_card_gate enforced_since — 이전 체결은 reason 폴백

BUY_ACTIONS = {"BUY"}
SELL_PREFIXES = ("SELL", "TRAILING_STOP")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_trade_log() -> list[dict]:
    path = ROOT / "state" / "trade_log.jsonl"
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def krw(v) -> str:
    return f"{v:+,.0f}원" if isinstance(v, (int, float)) else "?"


def fmt_price(v) -> str:
    return f"{v:,.0f}원" if isinstance(v, (int, float)) else "?"


def match_trip(trips: list[dict], ticker: str, exit_date: str) -> dict | None:
    for tr in trips:
        if tr.get("ticker") == ticker and tr.get("exit_date") == exit_date:
            return tr
    return None


def render_buy(e: dict, open_tickers: set[str]) -> list[str]:
    d = str(e.get("ts", ""))[:10]
    lines = [f"### 🟢 매수 — {e.get('name') or e.get('ticker')} ({e.get('ticker')}) · {d}"]
    px, sh = e.get("price"), e.get("shares")
    total = px * sh if isinstance(px, (int, float)) and isinstance(sh, (int, float)) else None
    lines.append(f"- **체결**: {sh}주 × {fmt_price(px)}" + (f" = {fmt_price(total)}" if total else ""))
    card = e.get("decision_card")
    if isinstance(card, dict):
        lines.append(f"- **왜 지금 (thesis)**: {card.get('thesis', '—')}")
        ev = card.get("evidence")
        if isinstance(ev, list):
            lines.append("- **근거**:")
            lines.extend(f"  - {item}" for item in ev)
        lines.append(f"- **이 판단이 틀렸다고 인정할 조건 (무효화)**: {card.get('invalidation', '—')}")
        if card.get("horizon_days") is not None:
            lines.append(f"- **예상 보유**: {card['horizon_days']}거래일")
        if card.get("alternatives_considered"):
            lines.append(f"- **검토한 대안**: {card['alternatives_considered']}")
    else:
        lines.append(f"- **판단 (reason 폴백 — {CARD_SINCE} 판단카드 도입 전 기록)**: {e.get('reason', '—')}")
    stop = e.get("stop_price")
    if stop and isinstance(px, (int, float)) and px > 0:
        loss = (px - stop) * (sh or 0)
        lines.append(
            f"- **리스크**: 손절 {fmt_price(stop)} ({(stop / px - 1) * 100:+.1f}%)"
            + (f" · 최대손실 약 {loss:,.0f}원" if loss else "")
        )
    if e.get("chase_exception"):
        lines.append(f"- ⚠️ **추격 예외 진입**: {e['chase_exception']}")
    if e.get("ticker") in open_tickers:
        lines.append("- **상태**: 보유 중")
    return lines


def render_sell(e: dict, trips: list[dict]) -> list[str]:
    d = str(e.get("ts", ""))[:10]
    action = e.get("action")
    lines = [f"### 🔴 매도 — {e.get('name') or e.get('ticker')} ({e.get('ticker')}) · {d} · `{action}`"]
    tr = match_trip(trips, e.get("ticker"), d)
    px = e.get("execution_price") or e.get("net_price_per_share") or e.get("price")
    sh = e.get("shares") or e.get("shares_sold")
    venue = e.get("execution_venue")
    lines.append(f"- **체결**: {sh}주 × {fmt_price(px)}" + (f" ({venue})" if venue else ""))
    card = e.get("decision_card")
    if isinstance(card, dict):
        lines.append(f"- **트리거**: {card.get('trigger', '—')}")
        lines.append(f"- **사람의 말로**: {card.get('human_summary', '—')}")
    else:
        lines.append(f"- **트리거 (reason 폴백 — {CARD_SINCE} 판단카드 도입 전 기록)**: {e.get('reason', '—')}")
    if e.get("shock_deferral_ack"):
        lines.append(f"- ⚠️ **지수 쇼크일 즉시체결 예외**: {e['shock_deferral_ack']}")
    if tr:
        pnl = tr.get("realized_pnl")
        entry = tr.get("entry_cost")
        shares = tr.get("shares") or 1
        entry_px = entry / shares if entry and shares else None
        result = f"- **결과**: 실현 {krw(pnl)}"
        if tr.get("hold_days") is not None:
            result += f" · 보유 {tr['hold_days']}일"
        if entry_px:
            result += f" (진입 {tr.get('entry_date')} {fmt_price(entry_px)})"
        lines.append(result)
        post = tr.get("post_exit") or {}
        t5 = post.get("t5")
        if isinstance(t5, dict):
            fg = t5.get("forgone_krw")
            if isinstance(fg, (int, float)):
                judge = "조기청산 비용 — 팔고 나서 올랐다" if fg > 0 else "청산이 손실을 방어했다"
                lines.append(
                    f"- **사후 검증 (t+5)**: {t5.get('date')} 관측가 {fmt_price(t5.get('close'))} → "
                    f"일실 {krw(fg)} ({judge})"
                )
        else:
            lines.append("- **사후 검증 (t+5)**: 관측 대기 중")
        if tr.get("pnl_mismatch"):
            lines.append(
                f"- ⚠️ **원장 불일치**: 로그 {krw(tr.get('logged_realized_pnl'))} vs 재계산 {krw(pnl)} — 라인 점검 필요"
            )
    return lines


def main() -> int:
    entries = load_trade_log()
    attr = load_json(ROOT / "state" / "rule_attribution.json", {})
    trips = attr.get("round_trips") or []
    account = attr.get("account") or {}
    open_tickers = {lot.get("ticker") for lot in attr.get("open_lots") or []}

    cards: list[tuple[str, list[str]]] = []  # (ts, lines)
    for e in entries:
        action = str(e.get("action") or "")
        ts = str(e.get("ts", ""))
        if action in BUY_ACTIONS:
            cards.append((ts, render_buy(e, open_tickers)))
        elif action.startswith(SELL_PREFIXES):
            cards.append((ts, render_sell(e, trips)))
    cards.sort(key=lambda c: c[0], reverse=True)  # 최신이 위

    header = [
        "# 매매 판단 카드 (trade_cards)",
        "",
        "> 생성 파일 — `scripts/render_trade_cards.py` 가 trade_log + rule_attribution 에서 렌더링. 수동 편집 금지.",
        f"> {CARD_SINCE} 이후 체결은 구조화된 decision_card 가 의무(CI: check_trade_log_gate)이며,",
        "> 이전 체결은 reason 한 줄 폴백으로 표시된다. 각 카드의 목적: **이 매매가 논리적이었는지**",
        "> (thesis·근거·무효화 조건) 와 **결과적으로 옳았는지** (실현손익·t+5 일실) 를 분리해서 검증한다.",
        "",
        f"_최종 갱신: {datetime.now(KST).isoformat(timespec='seconds')}_",
        "",
        "## 계좌 요약",
    ]
    if account:
        header.append(
            f"- 왕복 {account.get('closed_exits')}건 · {account.get('wins')}승 {account.get('losses')}패"
            f" (승률 {account.get('win_rate_pct')}%) · 순실현 {krw(account.get('net_realized'))}"
            f" · PF {account.get('profit_factor')} · 기대값 {krw(account.get('expectancy_per_exit'))}/건"
        )
    header += ["", "## 카드 (최신순)", ""]

    body: list[str] = []
    for _, lines in cards:
        body.extend(lines)
        body.append("")

    OUT_PATH.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    print(f"trade_cards: {len(cards)}건 렌더링 → {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
