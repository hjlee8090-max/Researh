#!/usr/bin/env python3
"""fetch_investor_flows — KRX 투자자별 매매동향(외국인/기관/개인 순매수) 일별 수집 (v1.0).

배경 (reports/2026-08-10-lessons-loop-data-gap-review.md P0-3 — 데이터 갭 #1):
- 외국인/기관 수급은 전 실패 사건(7/8 사이드카·7/9 갭업 역방향·7/16 금통위 크래시·
  7/24 유가·7/28 CXMT)의 공통 결정변수인데 lessons 에 47회 등장 전부가 사후 웹검색
  1회성 인용이었다. 특히 7/29 codify 룰("반등 밴드 상향은 **외국인 순매수 전환** 확인이
  전제 — 미확인이면 하단 유지")은 판정할 데이터가 파이프라인에 없어 실행 불가 상태였다.
- 이 스크립트가 시장 전체(KOSPI) + 보유/후보 종목의 투자자별 순매수 대금을 일별로
  구조화해 `state/investor_flows.json` 에 적재한다 — streak(연속 순매수/순매도 일수)과
  transition(부호 전환) 필드가 위 룰의 전제 조건을 기계 판정 가능하게 만든다.

수집: pykrx(KRX 정보데이터시스템) — `get_market_trading_value_by_date` (순매수 대금, 원).
  pykrx 최신판은 KRX 로그인 필요 — `KRX_ID`/`KRX_PW` 환경변수(GitHub Secrets, 기존
  fetch_prices.yml 과 동일 계정·이미 등록됨) 없으면 빈 응답으로 실패한다.
  장중 실시간성 없음(확정치 전용). 당일치는 장 마감 후 확정되므로 16:45 KST 워크플로
  (fetch_flows.yml)가 수집·커밋하고, 18:00 슬롯이 당일치·06:30 슬롯이 전일치를 읽는다.
실패 처리: pykrx 미설치/네트워크 차단(웹 세션 이그레스 403) 시 기존 파일을 덮어쓰지
  않고 종료(마지막 커밋본 보존 — market_snapshot 과 동일한 "Actions 수집, routine 은
  커밋본 읽기" 패턴). 표준 라이브러리 + pykrx(지연 임포트)만 사용.

사용: python scripts/fetch_investor_flows.py [--days 45] [--selftest]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "investor_flows.json"
KEEP_ROWS = 20  # 시리즈당 보존 거래일 수 (20거래일 ≈ 1개월)


def load_json(rel: str, default: Any) -> Any:
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def target_tickers() -> dict[str, str]:
    """보유 종목 + 진입 후보 — {ticker: name}. 수급은 보유 운용·신규 진입 판단에만 쓴다."""
    out: dict[str, str] = {}
    portfolio = load_json("config/portfolio.json", {})
    for pos in portfolio.get("positions") or []:
        t = str(pos.get("ticker") or "").strip()
        if t:
            out[t] = str(pos.get("name") or t)
    candidates = load_json("config/candidates.json", {})
    for c in candidates.get("candidates") or []:
        t = str(c.get("ticker") or "").strip()
        if t and t not in out:
            out[t] = str(c.get("name") or t)
    return out


def summarize(daily: list[dict[str, Any]]) -> dict[str, Any]:
    """일별 [{date, foreign, institution, individual}] → streak/transition/누적 요약.

    - foreign_streak_days: 최신일 기준 부호가 같은 연속 일수. 양수=연속 순매수, 음수=연속 순매도.
      (예: -11 = 11거래일 연속 순매도 — 7/8 사고의 그 지표)
    - foreign_transition: 최신일 부호 ≠ 직전일 부호 (7/29 룰의 '전환' 전제 판정용).
    - 0원(집계 결측)은 부호 없음으로 streak 를 끊는다.
    """
    if not daily:
        return {}

    def sign(v: float) -> int:
        return 1 if v > 0 else (-1 if v < 0 else 0)

    latest = daily[-1]
    out: dict[str, Any] = {
        "last_date": latest["date"],
        "foreign_today_krw": latest["foreign"],
        "institution_today_krw": latest["institution"],
        "individual_today_krw": latest["individual"],
        "foreign_cum_5d_krw": sum(r["foreign"] for r in daily[-5:]),
        "foreign_cum_20d_krw": sum(r["foreign"] for r in daily[-20:]),
        "institution_cum_5d_krw": sum(r["institution"] for r in daily[-5:]),
    }
    for actor in ("foreign", "institution"):
        s = sign(latest[actor])
        streak = 0
        if s != 0:
            for r in reversed(daily):
                if sign(r[actor]) == s:
                    streak += 1
                else:
                    break
        out[f"{actor}_streak_days"] = streak * s
        prev_sign = sign(daily[-2][actor]) if len(daily) >= 2 else 0
        out[f"{actor}_transition"] = bool(s != 0 and prev_sign != 0 and s != prev_sign)
    return out


def _column(df_columns: list[str], *needles: str) -> str | None:
    """pykrx 응답 컬럼명(한글)에서 대상 컬럼 탐색 — '외국인합계' > '외국인' 순."""
    for needle in needles:
        for c in df_columns:
            if needle in str(c):
                return c
    return None


def fetch_series(code: str, start: str, end: str) -> list[dict[str, Any]]:
    """pykrx 투자자별 순매수 대금(원) 일별 시리즈. code 는 'KOSPI' 또는 6자리 종목코드."""
    from pykrx import stock as krx  # 지연 임포트 — 미설치 환경 무해

    df = krx.get_market_trading_value_by_date(start, end, code)
    if df is None or df.empty:
        return []
    cols = list(df.columns)
    col_foreign = _column(cols, "외국인합계", "외국인")
    col_inst = _column(cols, "기관합계", "기관")
    col_indiv = _column(cols, "개인")
    out: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        out.append({
            "date": idx.strftime("%Y-%m-%d"),
            "foreign": int(row[col_foreign]) if col_foreign else 0,
            "institution": int(row[col_inst]) if col_inst else 0,
            "individual": int(row[col_indiv]) if col_indiv else 0,
        })
    return out[-KEEP_ROWS:]


def selftest() -> int:
    """수집 없이 요약 로직 검증 — 7/8 형(연속 순매도)·7/9 형(전환) 시나리오 재현."""
    daily = [
        {"date": f"2026-07-{d:02d}", "foreign": v, "institution": -v // 2, "individual": 100}
        for d, v in [(1, -300), (2, -200), (3, -100), (6, -400), (7, -800), (8, -880)]
    ]
    s = summarize(daily)
    assert s["foreign_streak_days"] == -6, s
    assert s["foreign_transition"] is False, s
    assert s["foreign_cum_5d_krw"] == -2380, s
    daily.append({"date": "2026-07-09", "foreign": 230, "institution": -10, "individual": -50})
    s2 = summarize(daily)
    assert s2["foreign_streak_days"] == 1, s2
    assert s2["foreign_transition"] is True, s2  # 7/9 순매수 전환 — 갭업 +3.35% 의 그 신호
    assert s2["institution_streak_days"] == -1, s2
    zero = summarize([{"date": "2026-07-01", "foreign": 0, "institution": 5, "individual": -5}])
    assert zero["foreign_streak_days"] == 0 and zero["foreign_transition"] is False, zero
    print("selftest OK — streak/transition/누적 요약 로직 검증 완료")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45, help="조회 달력일 수 (거래일 20개 확보용)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    now = datetime.now(KST)
    start = (now.date() - timedelta(days=args.days)).strftime("%Y%m%d")
    end = now.date().strftime("%Y%m%d")

    try:
        market_daily = fetch_series("KOSPI", start, end)
    except Exception as exc:  # noqa: BLE001 — ImportError·네트워크 차단 포함 전부
        print(f"investor_flows: 시장 수급 수집 실패 — 기존 파일 보존, 커밋본을 읽는다: {exc}",
              file=sys.stderr)
        return 1
    if not market_daily:
        print("investor_flows: 시장 수급 응답 비어있음 — 기존 파일 보존", file=sys.stderr)
        return 1

    tickers_out: dict[str, Any] = {}
    errors: list[str] = []
    for ticker, name in target_tickers().items():
        try:
            daily = fetch_series(ticker, start, end)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ticker}: {exc}")
            continue
        if daily:
            tickers_out[ticker] = {"name": name, "daily": daily, **summarize(daily)}

    out = {
        "as_of": now.isoformat(timespec="seconds"),
        "source": "KRX(pykrx) 투자자별 거래대금 순매수 — 단위 원, 확정 EOD 전용(장중 실시간성 없음)",
        "usage": (
            "06:30/18:00 슬롯 입력. 7/29 codify 룰의 전제 판정: 반등·갭업 예측 밴드 상향은 "
            "market.foreign_transition=true(순매수 전환) 확인 시만 — 미확인이면 하단 유지. "
            "foreign_streak_days ≤ -5 (연속 순매도) 는 반등 시나리오의 반대 증거로 취급."
        ),
        "market": {"name": "KOSPI", "daily": market_daily, **summarize(market_daily)},
        "tickers": tickers_out,
        "errors": errors[:10],
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    m = out["market"]
    print(f"wrote {OUT_PATH.relative_to(ROOT)} — market {m['last_date']} "
          f"외국인 {m['foreign_today_krw']:+,}원 streak {m['foreign_streak_days']:+d}일 "
          f"transition={m['foreign_transition']} · 종목 {len(tickers_out)}개"
          + (f" · 실패 {len(errors)}건" if errors else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
