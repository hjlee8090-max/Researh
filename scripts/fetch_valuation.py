#!/usr/bin/env python3
"""fetch_valuation — config/valuation.json 시드 (BPS·선행EPS·PER/PBR 밴드) v1.0.

목표주가 추정식의 '기준가'(멀티플 기반 적정가)와 check_valuation_guard 의 천장 계산에
필요한 밸류에이션 데이터를 시드한다. 네트워크 차단된 웹 세션 대신 Actions 러너에서 실행.

방법(출처·근사 명시 — web_verify_guard.source_date_verification 정합):
  1. 네이버 금융 종목 메인에서 현재가·PER·PBR·추정PER 파싱(span id 기반).
     BPS = 현재가 ÷ PBR, EPS(후행) = 현재가 ÷ PER, 선행EPS = 현재가 ÷ 추정PER(있으면).
     역산이라 파싱 취약점이 최소화되고 산술적으로 자기일관적이다.
  2. 5년 밴드 근사: BPS/EPS 히스토리가 없어 '현재 BPS/EPS 고정' 가정 하에
     state/price_history.json 의 ~2.5년 종가 분포 5/95퍼센타일 ÷ BPS(또는 EPS)로
     [하단, 상단] 밴드를 만든다. 사이클 저점/고점 멀티플의 보수적 근사 — method 필드에 명시.
  3. 기존 값이 있고 source_date 가 더 최신이면 보존(사람/일요일 루틴 시드 우선).
sunday_strategy 주간 갱신이 1차 책임 — 이 스크립트는 시드/백스톱. 의존성 0(표준 라이브러리).
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
CFG_PATH = ROOT / "config" / "valuation.json"
HTTP_TIMEOUT = 20


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; research-pipeline/1.0)",
        "Referer": "https://finance.naver.com/",
    })
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read()
    for enc in ("euc-kr", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _num(text: str | None) -> float | None:
    if not text:
        return None
    t = text.replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def parse_naver_main(ticker: str) -> dict[str, float | None]:
    """네이버 종목 메인에서 현재가(_nowVal)·PER(_per)·PBR(_pbr)·추정PER(_cns_per) 파싱."""
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    try:
        html = http_get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  naver main {ticker} 실패: {exc}")
        return {}
    out: dict[str, float | None] = {"source_url": url}  # type: ignore[dict-item]

    def span(sid: str) -> float | None:
        m = re.search(rf'id="{sid}"[^>]*>([\d,.]+)<', html)
        return _num(m.group(1)) if m else None

    out["per"] = span("_per")
    out["pbr"] = span("_pbr")
    out["cns_per"] = span("_cns_per")
    # 현재가: dl.blind 의 '현재가 NNN,NNN' 또는 _nowVal
    m = re.search(r"현재가\s*([\d,]+)", html)
    out["price"] = _num(m.group(1)) if m else span("_nowVal")
    return out


def band_from_history(ticker: str, denom: float) -> list[float] | None:
    """가격분포 5/95퍼센타일 ÷ denom → 멀티플 밴드 근사 (BPS/EPS 고정 가정)."""
    hist = json.loads((ROOT / "state" / "price_history.json").read_text(encoding="utf-8"))
    bars = ((hist.get("tickers") or {}).get(ticker) or {}).get("bars") or []
    closes = sorted(float(b["close"]) for b in bars if b.get("close"))
    if len(closes) < 200 or not denom:
        return None
    lo = closes[int(len(closes) * 0.05)] / denom
    hi = closes[int(len(closes) * 0.95)] / denom
    return [round(lo, 2), round(hi, 2)]


def main() -> int:
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    updated = 0
    for ticker, v in (cfg.get("tickers") or {}).items():
        if not isinstance(v, dict):
            continue
        # 기존 시드가 오늘보다 최신/동일이고 값이 차 있으면 보존(사람·일요일 루틴 우선)
        if v.get("bps") and v.get("source_date") and v["source_date"] >= today:
            print(f"  {v.get('name', ticker)}: 기존 시드 보존({v['source_date']})")
            continue
        p = parse_naver_main(ticker)
        price, per, pbr, cns_per = p.get("price"), p.get("per"), p.get("pbr"), p.get("cns_per")
        if not price or not pbr:
            print(f"  {v.get('name', ticker)}: 파싱 실패(price={price}, pbr={pbr}) — skip(아무것도 막지 않음)")
            continue
        bps = round(price / pbr, 0)
        eps = round(price / per, 0) if per else None
        eps_fwd = round(price / cns_per, 0) if cns_per else eps
        v["bps"] = bps
        v["eps_fwd"] = eps_fwd
        v["pbr_band_5y"] = band_from_history(ticker, bps)
        v["per_band_5y"] = band_from_history(ticker, eps_fwd) if eps_fwd else None
        v["source_url"] = p["source_url"]
        v["source_date"] = today
        v["method"] = (
            "BPS=현재가÷PBR·EPS=현재가÷PER(네이버 종목메인 역산, 관측일=source_date). "
            "밴드=직전 ~2.5년 종가분포 5/95퍼센타일÷현재 BPS(EPS) 근사 — BPS/EPS 히스토리 부재로 "
            "현재값 고정 가정. sunday_strategy 가 실제 5년 밴드 출처 확보 시 교체."
        )
        updated += 1
        print(f"  {v.get('name', ticker)}: BPS {bps:,.0f} / eps_fwd {eps_fwd} / "
              f"PBR밴드 {v['pbr_band_5y']} / PER밴드 {v['per_band_5y']}")
    cfg["as_of"] = now.isoformat(timespec="seconds")
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated {updated} tickers → config/valuation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
