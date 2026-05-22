#!/usr/bin/env python3
"""오늘이 KRX 정규 영업일인지 판정한다.

routine prompt 시작 시 호출하여 휴장일이면 자동으로 '휴장 모드' 분기로 진입한다.
- 출력 (stdout JSON 1줄): {"date": "...", "weekday": "...", "is_open": bool, "reason": "..."}
- 종료 코드: 0 = 영업일 / 10 = 휴장(주말) / 11 = 휴장(공휴일)

옵션: --date YYYY-MM-DD 로 임의 날짜 검사 가능.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
CALENDAR_PATH = ROOT / "config" / "market_calendar.json"


def load_holidays() -> dict[str, str]:
    if not CALENDAR_PATH.exists():
        return {}
    data = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    return {h["date"]: h.get("name", "공휴일") for h in data.get("holidays_2026", [])}


def evaluate(target: date) -> tuple[bool, str, int]:
    weekday = target.weekday()  # 0=Mon..6=Sun
    if weekday >= 5:
        return False, f"주말({'토' if weekday == 5 else '일'}요일)", 10
    holidays = load_holidays()
    key = target.isoformat()
    if key in holidays:
        return False, f"공휴일({holidays[key]})", 11
    return True, "정규 영업일", 0


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX 영업일 판정")
    parser.add_argument("--date", help="YYYY-MM-DD (생략 시 오늘 KST)")
    args = parser.parse_args()

    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target = datetime.now(KST).date()

    is_open, reason, exit_code = evaluate(target)
    weekday_kor = ["월", "화", "수", "목", "금", "토", "일"][target.weekday()]
    print(
        json.dumps(
            {
                "date": target.isoformat(),
                "weekday": weekday_kor,
                "is_open": is_open,
                "reason": reason,
            },
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
