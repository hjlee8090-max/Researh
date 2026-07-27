#!/usr/bin/env python3
"""보유·후보 종목의 다가오는 '촉매(catalyst)' 이벤트를 추정·수집한다.

촉매 캘린더 레이어 — equity-research 플러그인의 catalyst-calendar 채용(Part A).
종목별 실적발표(정기보고서)·다가오는 이벤트를 미리 알아 D-day 경보·신규 진입 보류 판단에 쓴다.

설계:
- **백본은 한국 정기보고서 법정 제출기한(달력 계산)** — DART 키·네트워크가 없어도 항상 동작한다.
  · 1분기보고서: 분기말(3/31) + 45일 → 5/15
  · 반기보고서:   반기말(6/30) + 45일 → 8/14
  · 3분기보고서:  분기말(9/30) + 45일 → 11/14
  · 사업보고서:   결산(12/31) + 90일 → 3/31
  (대형주는 '잠정실적'이 보고서보다 1주가량 먼저 나오므로 window 로 앞쪽 폭을 둔다.)
- **DART list.json(정기공시) 보정(있을 때만)** — 가장 최근 제출된 정기보고서 접수일을 읽어,
  '다음 회차'를 그 이후 첫 법정기한으로 정확히 잡는다. 키 없으면 today 이후 첫 기한으로 폴백.
- 모든 추정 이벤트는 confirmed=false. 매크로(FOMC·금통위)·배당기준일·자사주 등 확정 이벤트는
  routine 이 웹검색으로 manual_events 에 추가/승격하며, 본 스크립트는 manual_events 를 보존한다.

출력: config/catalysts.json
  · generated_events : 본 스크립트가 매 실행마다 재생성(소유)
  · manual_events    : 사람/routine 이 관리(보존)
  · events_archive   : 지난(날짜 경과) generated 이벤트를 일정 기간 보관

키·네트워크가 없으면 직전 generated_events 를 보존하고 stale 표시만 남긴다(비치명적).
"""
from __future__ import annotations

import io
import json
import logging
import os
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DART_BASE = "https://opendart.fss.or.kr/api"
HTTP_TIMEOUT = 15
ARCHIVE_KEEP_DAYS = 14  # 경과한 generated 이벤트를 events_archive 에 보관하는 기간
# (콘텍스트 압축 v2 Phase 1) 핫패스 지평 — 이 날짜를 넘는 generated 이벤트는 events_future 로
# 분리한다. 09시 routine 이 11월 실적 법정기한까지 매일 읽을 이유가 없다(2026-07-27 실측:
# 54건 44.1KB 중 절반이 D+45 밖). manual_events 는 routine 소유라 손대지 않는다.
HOTPATH_HORIZON_DAYS = 45

# 분기말(월,일) → (법정기한 월,일, 보고서명, 잠정실적 선행 추정일수)
# 잠정실적 선행 일수: 대형주가 보고서 법정기한보다 대략 며칠 먼저 잠정실적을 내는 폭(window 시작).
STATUTORY = [
    {"q": "1Q",   "end": (3, 31),  "due": (5, 15),  "report": "분기보고서(1Q)",  "lead": 38, "importance": "high"},
    {"q": "Half", "end": (6, 30),  "due": (8, 14),  "report": "반기보고서",       "lead": 38, "importance": "high"},
    {"q": "3Q",   "end": (9, 30),  "due": (11, 14), "report": "분기보고서(3Q)",  "lead": 38, "importance": "high"},
    {"q": "FY",   "end": (12, 31), "due": (3, 31),  "report": "사업보고서(연간)", "lead": 60, "importance": "high"},
]

logger = logging.getLogger(__name__)


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kospi-autoflow/1.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return default if default is not None else {}


def collect_tickers() -> dict[str, str]:
    """{ticker: name} — 보유 + 후보 (fetch_fundamentals.collect_tickers 와 동일 소스)."""
    out: dict[str, str] = {}
    for pos in load_json("config/portfolio.json").get("positions", []):
        if pos.get("ticker"):
            out[pos["ticker"]] = pos.get("name", "")
    for c in load_json("config/candidates.json").get("candidates", []):
        if c.get("ticker"):
            out.setdefault(c["ticker"], c.get("name", ""))
    return out


def get_corp_map(api_key: str) -> dict[str, str]:
    """stock_code(6) → corp_code(8). fetch_fundamentals 와 같은 캐시(state/dart_corpcodes.json)를 공유."""
    cache_path = ROOT / "state" / "dart_corpcodes.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("map"):
                return cached["map"]
        except (json.JSONDecodeError, ValueError):
            pass
    raw = http_get(f"{DART_BASE}/corpCode.xml?crtfc_key={api_key}")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        corp = (item.findtext("corp_code") or "").strip()
        if stock and corp:
            mapping[stock] = corp
    if mapping:
        cache_path.parent.mkdir(exist_ok=True)
        cache_path.write_text(
            json.dumps({"as_of": datetime.now(KST).isoformat(timespec="seconds"), "map": mapping},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    return mapping


def latest_periodic_filing(api_key: str, corp_code: str, today: date) -> date | None:
    """DART 정기공시(pblntf_ty=A) 중 가장 최근 접수일을 반환. 실패 시 None(=폴백)."""
    bgn = (today - timedelta(days=200)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    url = (
        f"{DART_BASE}/list.json?crtfc_key={api_key}&corp_code={corp_code}"
        f"&bgn_de={bgn}&end_de={end}&pblntf_ty=A&page_count=100"
    )
    try:
        payload = json.loads(http_get(url))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("dart list failed corp=%s: %s", corp_code, exc)
        return None
    if payload.get("status") != "000" or not payload.get("list"):
        return None
    dates: list[date] = []
    for row in payload["list"]:
        nm = row.get("report_nm") or ""
        if not any(k in nm for k in ("분기보고서", "반기보고서", "사업보고서")):
            continue
        raw = (row.get("rcept_dt") or "").strip()
        if len(raw) == 8 and raw.isdigit():
            dates.append(date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])))
    return max(dates) if dates else None


def upcoming_deadlines(after: date, count: int = 2) -> list[dict[str, Any]]:
    """`after` 이후의 법정 제출기한을 가까운 순서로 count 개 만든다."""
    out: list[dict[str, Any]] = []
    year = after.year
    for y in (year, year + 1, year + 2):
        for s in STATUTORY:
            # 사업보고서(FY)는 결산연도(12/31) 다음해 3/31 이 기한이다.
            due_year = y + 1 if s["q"] == "FY" else y
            due = date(due_year, *s["due"])
            if due > after:
                out.append({**s, "due": due})
    out.sort(key=lambda e: e["due"])
    return out[:count]


def build_generated(tickers: dict[str, str], corp_map: dict[str, str],
                    api_key: str, today: date, now: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for ticker, name in tickers.items():
        anchor = today
        if api_key and corp_map.get(ticker):
            last = latest_periodic_filing(api_key, corp_map[ticker], today)
            if last and last > anchor:
                anchor = last  # 가장 최근 제출분 이후로 다음 회차를 정확히 잡는다
        for idx, dl in enumerate(upcoming_deadlines(anchor, count=2)):
            due: date = dl["due"]
            win_start = due - timedelta(days=dl["lead"])
            period_year = due.year - 1 if dl["q"] == "FY" else due.year
            events.append({
                "id": f"{ticker}-{period_year}{dl['q']}-earnings",
                "ticker": ticker,
                "name": name,
                "type": "earnings_report",
                "scope": "stock",
                "date": due.isoformat(),
                "window": f"{win_start.isoformat()}~{due.isoformat()}",
                "confirmed": False,
                "importance": dl["importance"] if idx == 0 else "medium",
                "expectation": (
                    f"{dl['report']} 법정 제출기한(추정). 대형주는 잠정실적이 "
                    f"{win_start.isoformat()} 전후로 먼저 나올 수 있음 → 웹검색으로 확정일 보정."
                ),
                "linked_thesis": [],
                "source_url": "https://dart.fss.or.kr (정기공시 법정기한 추정)",
                "managed_by": "script",
                "updated_at": now.isoformat(timespec="seconds"),
            })
    events.sort(key=lambda e: (e["date"], e["ticker"]))
    return events


def main() -> int:
    api_key = os.environ.get("DART_API_KEY", "").strip()
    out_path = ROOT / "config" / "catalysts.json"
    now = datetime.now(KST)
    today = now.date()
    tickers = collect_tickers()
    prior = load_json("config/catalysts.json", {})
    manual_events = prior.get("manual_events", [])

    if not api_key:
        # 키 없어도 법정기한 백본은 생성 가능 — 단 list.json 보정은 생략(폴백).
        generated = build_generated(tickers, {}, "", today, now)
        note = "DART_API_KEY 미설정 — 법정기한 추정만(최근 제출분 보정 생략). 키: https://opendart.fss.or.kr"
        key_present = False
    else:
        try:
            corp_map = get_corp_map(api_key)
        except (urllib.error.URLError, zipfile.BadZipFile, ET.ParseError, TimeoutError) as exc:
            logger.warning("corp_code map fetch failed: %s", exc)
            corp_map = {}
        generated = build_generated(tickers, corp_map, api_key, today, now)
        note = "법정기한 추정 + DART 최근 정기보고서 접수일로 다음 회차 보정. confirmed=false 는 웹검색으로 승격."
        key_present = True

    # 경과한 generated 이벤트는 archive 로 (manual 은 routine 이 직접 관리하므로 손대지 않는다).
    archive = [e for e in prior.get("events_archive", [])
               if e.get("date", "") >= (today - timedelta(days=ARCHIVE_KEEP_DAYS)).isoformat()]
    horizon = (today + timedelta(days=HOTPATH_HORIZON_DAYS)).isoformat()
    fresh, expired, future = [], [], []
    for e in generated:
        if e["date"] < today.isoformat():
            expired.append(e)
        elif e["date"] > horizon:
            future.append(e)      # 지평 밖 — 보존하되 핫패스에서 뺀다
        else:
            fresh.append(e)
    archive.extend(expired)

    result = {
        "version": "1.0",
        "as_of": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "source": "DART OpenAPI(정기공시) + 한국 정기보고서 법정기한",
        "note": note,
        "key_present": key_present,
        "ticker_count": len(tickers),
        "generated_count": len(fresh),
        "manual_count": len(manual_events),
        "generated_events": fresh,
        "manual_events": manual_events,
        "events_future_ref": (
            f"state/catalysts_future.json (D+{HOTPATH_HORIZON_DAYS} 밖 예정 이벤트 — "
            "지평 진입 시 다음 실행이 generated_events 로 승격)"
        ),
        "events_archive": archive[-100:],
    }
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 지평 밖 이벤트는 핫패스 밖(state/)에 따로 보관한다 — routine 은 읽지 않고
    # check_thesis_cards 가 checkpoint 날짜 조회용으로만 참조한다(v2.26).
    future_path = ROOT / "state" / "catalysts_future.json"
    future_path.parent.mkdir(exist_ok=True)
    future_path.write_text(json.dumps({
        "version": "1.0",
        "purpose": f"D+{HOTPATH_HORIZON_DAYS} 지평 밖 예정 촉매 — 핫패스 분리 보관(v2.26).",
        "count": len(future),
        "events": future,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"catalysts: wrote {out_path.relative_to(ROOT)} "
          f"generated={len(fresh)} manual={len(manual_events)} key={key_present}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
