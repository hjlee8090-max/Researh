#!/usr/bin/env python3
"""지금이 KRX 장중(거래 시간) 중 어느 세션인지, 어떤 체결이 허용되는지 판정한다.

check_market_open.py(영업일 여부)의 '시각(time-of-day)' 짝꿍 가드. 각 routine 0-A 단계에서
호출해 18시처럼 장 마감 후 시각에 '현재가 신규/시장가 체결'이 일어나지 않도록 한다.

세션(영업일 기준, config/market_calendar.json.sessions):
- pre_open        : 00:00~08:30 — 거래 불가(execution_mode=none)
- opening_auction : 08:30~09:00 — 장 시작 동시호가(live)
- regular         : 09:00~15:20 — 정규장(live)
- closing_auction : 15:20~15:30 — 장 마감 동시호가(live, 종가 결정)
- post_close      : 15:30~24:00 — 마감 후. 신규/시장가 체결 금지, 종가 도달 손절/목표/트레일링의
                    '종가 기준 청산'만 허용(execution_mode=closing_price). 18시 routine 이 여기에 속한다.
- closed_holiday  : 비영업일(주말/공휴일) — none

반장(half_days)이 있으면 그 날의 close 를 정규장 마감으로 우선 적용한다.

출력(stdout JSON 1줄): date/weekday/now_kst/is_business_day/session/execution_mode/
                       live_trading_allowed/eod_settlement_allowed/reason
종료 코드: 0=live / 20=closing_price / 21=none(영업일·장 시작 전) / 30=closed(비영업일)

옵션: --date YYYY-MM-DD, --at HH:MM, --now ISO8601 (테스트용 임의 시각).
정책: policy.market_hours / config/market_calendar.json.sessions.
표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import check_market_open as cmo  # 같은 scripts/ — 영업일 판정 단일 출처 재사용

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
CALENDAR_PATH = ROOT / "config" / "market_calendar.json"

# config/market_calendar.json.sessions 가 없을 때의 폴백(정규장 09:00~15:30)
_DEFAULT_SESSIONS = {
    "preopen_auction": {"start": "08:30", "end": "09:00"},
    "regular": {"open": "09:00", "close": "15:30"},
    "closing_auction": {"start": "15:20", "end": "15:30"},
}


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return fallback


def load_calendar() -> dict:
    if not CALENDAR_PATH.exists():
        return {}
    try:
        return json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def session_bounds(target: date, calendar: dict) -> dict[str, time]:
    """해당 날짜의 세션 경계 시각을 반환(반장이면 close 를 덮어쓴다)."""
    sessions = calendar.get("sessions") or _DEFAULT_SESSIONS
    preopen = sessions.get("preopen_auction", _DEFAULT_SESSIONS["preopen_auction"])
    regular = sessions.get("regular", _DEFAULT_SESSIONS["regular"])
    closing = sessions.get("closing_auction", _DEFAULT_SESSIONS["closing_auction"])

    open_t = _parse_hhmm(regular.get("open", "09:00"), time(9, 0))
    close_t = _parse_hhmm(regular.get("close", "15:30"), time(15, 30))
    preopen_t = _parse_hhmm(preopen.get("start", "08:30"), time(8, 30))
    closing_t = _parse_hhmm(closing.get("start", "15:20"), time(15, 20))

    # 반장(단축 거래일) — 그 날의 마감을 우선 적용
    key = target.isoformat()
    for hd in calendar.get("half_days", []) or []:
        if isinstance(hd, dict) and hd.get("date") == key:
            close_t = _parse_hhmm(hd.get("close", "12:30"), close_t)
            closing_t = _parse_hhmm(
                hd.get("closing_auction", ""),
                (datetime.combine(target, close_t) - timedelta(minutes=10)).time(),
            )
            break
    return {"preopen": preopen_t, "open": open_t, "closing_auction": closing_t, "close": close_t}


def classify(target: date, now_t: time, calendar: dict) -> tuple[str, str, str, int]:
    """(session, execution_mode, reason, exit_code) 반환."""
    is_open, open_reason, _ = cmo.evaluate(target)
    if not is_open:
        return "closed_holiday", "none", f"비영업일({open_reason}) — 거래 불가", 30

    b = session_bounds(target, calendar)
    if now_t < b["preopen"]:
        return "pre_open", "none", "장 시작 전(동시호가 이전) — 거래 불가", 21
    if now_t < b["open"]:
        return "opening_auction", "live", "장 시작 동시호가 — 시가 결정 구간", 0
    if now_t < b["closing_auction"]:
        return "regular", "live", "정규장 — 실시간 체결 가능", 0
    if now_t < b["close"]:
        return "closing_auction", "live", "장 마감 동시호가 — 종가 결정 구간", 0
    return (
        "post_close",
        "closing_price",
        f"정규장 마감({b['close'].strftime('%H:%M')}) 후 — 신규/시장가 체결 금지, "
        "종가 기준 손절/목표/트레일링 청산만 허용",
        20,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX 장중 세션 판정")
    parser.add_argument("--date", help="YYYY-MM-DD (생략 시 오늘 KST)")
    parser.add_argument("--at", help="HH:MM (생략 시 현재 KST 시각)")
    parser.add_argument("--now", help="ISO8601 (date+time 한 번에; --date/--at 보다 우선)")
    args = parser.parse_args()

    if args.now:
        dt = datetime.fromisoformat(args.now)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        dt = dt.astimezone(KST)
        target, now_t = dt.date(), dt.time()
    else:
        target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(KST).date()
        now_t = _parse_hhmm(args.at, datetime.now(KST).time()) if args.at else datetime.now(KST).time()

    calendar = load_calendar()
    session, mode, reason, exit_code = classify(target, now_t, calendar)
    weekday_kor = ["월", "화", "수", "목", "금", "토", "일"][target.weekday()]

    print(
        json.dumps(
            {
                "date": target.isoformat(),
                "weekday": weekday_kor,
                "now_kst": now_t.strftime("%H:%M"),
                "is_business_day": exit_code != 30,
                "session": session,
                "execution_mode": mode,
                "live_trading_allowed": mode == "live",
                "eod_settlement_allowed": mode in ("live", "closing_price"),
                "reason": reason,
            },
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
