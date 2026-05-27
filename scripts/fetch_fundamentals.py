#!/usr/bin/env python3
"""DART 전자공시 OpenAPI 로 보유·후보 종목의 최신 분기 실적(주요계정)을 수집한다.

IR/펀더멘털 레이어 — 분기 단위로만 갱신되므로 주간(sunday_strategy)에 실행하고,
데일리 routine 은 산출물 state/fundamentals.json 을 '확신·검증 레이어'로 소비한다.
(타이밍은 regime·momentum 이 담당. 펀더멘털은 후행 지표.)

전제:
- 환경변수 DART_API_KEY (https://opendart.fss.or.kr 무료 발급) 필요.
- 네트워크 정책에 opendart.fss.or.kr 허용 필요.
- 키·네트워크가 없으면 직전 state/fundamentals.json 을 보존하고 stale 표시만 남긴다(비치명적).

수집 항목(연결 우선): 매출액·영업이익·당기순이익·영업이익률·전기대비 영업이익 증감.
주요계정 API 의 frmtrm 은 분기에서 '전기'(직전기간)일 수 있어 엄밀한 YoY 가 아니다 —
period 라벨을 함께 저장해 해석은 thesis·LLM 에 맡긴다.
"""
from __future__ import annotations

import io
import json
import logging
import os
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DART_BASE = "https://opendart.fss.or.kr/api"
HTTP_TIMEOUT = 15
# 계정명은 업종마다 다르다(특히 금융지주·은행·증권·보험은 매출액/영업이익 대신 영업수익 등을 쓴다).
# 지표별로 우선순위 별칭을 순서대로 시도해 매칭률을 높인다(연결 CFS 우선).
ACCOUNT_ALIASES = {
    "revenue": ["매출액", "영업수익", "수익(매출액)", "이자수익", "보험손익"],
    "operating_profit": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익", "당기순이익(지배)"],
}
# 최신 → 과거 순으로 시도할 (연도오프셋, reprt_code, 라벨). 1Q=11013 반기=11012 3Q=11014 사업=11011.
REPORT_ORDER = [
    (0, "11013", "1분기"), (0, "11012", "반기"), (0, "11014", "3분기"), (0, "11011", "사업(연간)"),
    (-1, "11011", "전년 사업(연간)"), (-1, "11014", "전년 3분기"), (-1, "11012", "전년 반기"),
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
    return json.loads(path.read_text(encoding="utf-8"))


def collect_tickers() -> dict[str, str]:
    """{ticker: name} — 보유 + 후보."""
    out: dict[str, str] = {}
    for pos in load_json("config/portfolio.json").get("positions", []):
        if pos.get("ticker"):
            out[pos["ticker"]] = pos.get("name", "")
    for c in load_json("config/candidates.json").get("candidates", []):
        if c.get("ticker"):
            out.setdefault(c["ticker"], c.get("name", ""))
    return out


def get_corp_map(api_key: str) -> dict[str, str]:
    """stock_code(6자리) → corp_code(8자리) 매핑. state/dart_corpcodes.json 에 캐시(코드 변경 드묾)."""
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


def _to_int(s: str | None) -> int | None:
    if not s or s.strip() in ("-", ""):
        return None
    try:
        return int(s.replace(",", "").strip())
    except ValueError:
        return None


def fetch_financials(api_key: str, corp_code: str, year: int) -> dict[str, Any] | None:
    """가장 최신의 사용 가능한 보고서를 찾아 주요계정(연결 우선)을 추출한다."""
    for off, reprt, label in REPORT_ORDER:
        url = (
            f"{DART_BASE}/fnlttSinglAcnt.json?crtfc_key={api_key}"
            f"&corp_code={corp_code}&bsns_year={year + off}&reprt_code={reprt}"
        )
        try:
            payload = json.loads(http_get(url))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            logger.warning("dart fetch failed corp=%s %s: %s", corp_code, reprt, exc)
            continue
        if payload.get("status") != "000" or not payload.get("list"):
            continue
        rows = payload["list"]
        vals: dict[str, Any] = {}
        frmtrm_label = None
        for key, aliases in ACCOUNT_ALIASES.items():
            # 지표별 별칭을 우선순위대로, 각 별칭은 연결(CFS) 우선·없으면 별도(OFS) 로 찾는다.
            match = None
            for nm in aliases:
                match = next(
                    (r for r in rows if r.get("account_nm") == nm and r.get("fs_div") == "CFS"), None
                ) or next((r for r in rows if r.get("account_nm") == nm), None)
                if match:
                    break
            if match:
                vals[key] = _to_int(match.get("thstrm_amount"))
                vals[f"{key}_frmtrm"] = _to_int(match.get("frmtrm_amount"))
                vals[f"{key}_account_nm"] = match.get("account_nm")
                frmtrm_label = match.get("frmtrm_nm") or frmtrm_label
        if not any(vals.get(k) for k in ACCOUNT_ALIASES):
            continue
        return {
            "bsns_year": year + off,
            "reprt_code": reprt,
            "period_label": label,
            "thstrm_label": rows[0].get("thstrm_nm"),
            "frmtrm_label": frmtrm_label,
            **vals,
            "source_url": f"https://dart.fss.or.kr (corp_code={corp_code}, {year + off} {label})",
        }
    return None


def derive(fin: dict[str, Any]) -> dict[str, Any]:
    """영업이익률·전기대비 영업이익 증감·earnings_signal 파생."""
    rev, op = fin.get("revenue"), fin.get("operating_profit")
    op_prev = fin.get("operating_profit_frmtrm")
    fin["op_margin_pct"] = round(op / rev * 100, 2) if rev and op is not None and rev != 0 else None
    growth = None
    if op is not None and op_prev not in (None, 0):
        growth = round((op - op_prev) / abs(op_prev) * 100, 1)
    fin["op_growth_pop_pct"] = growth  # period-over-period (전기 대비), 엄밀 YoY 아님
    if growth is None:
        signal = "unknown"
    elif growth >= 20:
        signal = "strong_growth"
    elif growth >= 0:
        signal = "growth"
    elif growth >= -20:
        signal = "decline"
    else:
        signal = "sharp_decline"
    fin["earnings_signal"] = signal
    return fin


def main() -> int:
    api_key = os.environ.get("DART_API_KEY", "").strip()
    out_path = ROOT / "state" / "fundamentals.json"
    now = datetime.now(KST)
    tickers = collect_tickers()

    if not api_key:
        prior = load_json("state/fundamentals.json", {})
        result = {
            "as_of": now.isoformat(timespec="seconds"),
            "source": "DART OpenAPI",
            "key_present": False,
            "note": "DART_API_KEY 미설정 — 펀더멘털 수집 보류. 직전 데이터가 있으면 보존(stale). 키 발급: https://opendart.fss.or.kr",
            "stale": bool(prior.get("tickers")),
            "tickers": prior.get("tickers", {}),
        }
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"fundamentals: DART_API_KEY 미설정 — 보류(prior tickers={len(result['tickers'])})")
        return 0

    try:
        corp_map = get_corp_map(api_key)
    except (urllib.error.URLError, zipfile.BadZipFile, ET.ParseError, TimeoutError) as exc:
        logger.warning("corp_code map fetch failed: %s", exc)
        corp_map = {}

    data: dict[str, Any] = {}
    ok = 0
    for ticker, name in tickers.items():
        corp = corp_map.get(ticker)
        if not corp:
            data[ticker] = {"name": name, "error": "corp_code 매핑 실패"}
            continue
        fin = fetch_financials(api_key, corp, now.year)
        if not fin:
            data[ticker] = {"name": name, "corp_code": corp, "error": "재무 데이터 없음"}
            continue
        data[ticker] = {"name": name, "corp_code": corp, "fetched_at": now.isoformat(timespec="seconds"), **derive(fin)}
        ok += 1

    result = {
        "as_of": now.isoformat(timespec="seconds"),
        "source": "DART OpenAPI (fnlttSinglAcnt 주요계정, 연결 우선)",
        "key_present": True,
        "note": "op_growth_pop_pct 는 전기대비(분기는 직전기간)이며 엄밀 YoY 가 아니다. period_label 로 해석할 것.",
        "ticker_count": len(tickers),
        "fetched_ok": ok,
        "tickers": data,
    }
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"fundamentals: wrote {out_path.relative_to(ROOT)} tickers={len(tickers)} ok={ok}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
