#!/usr/bin/env python3
"""fetch_valuation — config/valuation.json 시드 (BPS·선행EPS·PER/PBR 밴드) v1.1.

목표주가 추정식의 '기준가'(멀티플 기반 적정가)와 check_valuation_guard 의 천장 계산에
필요한 밸류에이션 데이터를 시드한다. 네트워크 차단된 웹 세션 대신 Actions 러너에서 실행.

v1.1 — 진짜 멀티플 히스토리(2026-06-11 anchor 왜곡 사후 보완 ①②):
  ① DART 분기 자본총계·당기순이익 히스토리(fnlttSinglAcnt, 2023연간~현재)로
     분기 BPS(t)=자본총계(t)÷주식수, TTM EPS(t) 시계열을 만들고, price_history 종가와 결합해
     **분모가 변하는 진짜 PBR/PER 시계열**의 5/95 퍼센타일 밴드를 산출한다.
     band_quality="dart_quarterly" — estimate 가 기준가(anchor)로 사용 가능.
     주식수는 DART 최신 자본총계 × 네이버 PBR ÷ 현재가로 역산(자기일관·파싱 최소화,
     기간 중 증자·자사주 소각은 미반영 — 한계 명시).
  ② 자기일관성 게이트: 시드 직후 현재 멀티플이 밴드 상단×1.3 초과 또는 하단×0.7 미만이면
     데이터 자기모순(낡은 시드·파싱 오류) 의심 → band_quality="inconsistent" 강등
     (anchor 사용 차단, 천장·가드는 estimate 쪽 'ceiling>현재가' 가드가 방어).
  DART 키/이력 부족 시 v1.0 가격분포 근사로 폴백(band_quality="approx_price_percentile",
  anchor 사용 금지 — estimate_target_price 가 구분).

기존 값이 있고 source_date 가 더 최신이면 보존(사람/일요일 루틴 시드 우선).
sunday_strategy 주간 갱신이 1차 책임 — 이 스크립트는 시드/백스톱. 의존성 0(표준 라이브러리).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
CFG_PATH = ROOT / "config" / "valuation.json"
HTTP_TIMEOUT = 20
DART_BASE = "https://opendart.fss.or.kr/api"
# (reprt_code, 분기말 월일) — 손익 누적치는 q1=c1, q2=반기-c1, q3=3Q-반기, q4=연간-3Q 로 분기화
QUARTER_REPORTS = [("11013", "03-31"), ("11012", "06-30"), ("11014", "09-30"), ("11011", "12-31")]
NI_ALIASES = ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익", "당기순이익(지배)"]

_spec = importlib.util.spec_from_file_location("ff", Path(__file__).parent / "fetch_fundamentals.py")
ff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ff)  # http_get·get_corp_map 재사용


def http_get_html(url: str) -> str:
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
    try:
        return float(text.replace(",", "").strip())
    except ValueError:
        return None


def parse_naver_main(ticker: str) -> dict[str, Any]:
    """네이버 종목 메인에서 현재가·PER(_per)·PBR(_pbr)·추정PER(_cns_per) 파싱."""
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    try:
        html = http_get_html(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  naver main {ticker} 실패: {exc}")
        return {}
    out: dict[str, Any] = {"source_url": url}

    def span(sid: str) -> float | None:
        m = re.search(rf'id="{sid}"[^>]*>([\d,.]+)<', html)
        return _num(m.group(1)) if m else None

    out["per"], out["pbr"], out["cns_per"] = span("_per"), span("_pbr"), span("_cns_per")
    m = re.search(r"현재가\s*([\d,]+)", html)
    out["price"] = _num(m.group(1)) if m else span("_nowVal")
    return out


# ── ① DART 분기 자본총계·순이익 히스토리 ─────────────────────────────────────
def fetch_quarter(api_key: str, corp: str, year: int, reprt: str) -> dict | None:
    url = (f"{DART_BASE}/fnlttSinglAcnt.json?crtfc_key={api_key}"
           f"&corp_code={corp}&bsns_year={year}&reprt_code={reprt}")
    try:
        payload = json.loads(ff.http_get(url))
    except Exception:  # noqa: BLE001
        return None
    if payload.get("status") != "000" or not payload.get("list"):
        return None
    rows = payload["list"]

    def find(names: list[str]) -> int | None:
        for nm in names:
            r = next((x for x in rows if x.get("account_nm") == nm and x.get("fs_div") == "CFS"), None) \
                or next((x for x in rows if x.get("account_nm") == nm), None)
            if r:
                v = (r.get("thstrm_amount") or "").replace(",", "").strip()
                try:
                    return int(v)
                except ValueError:
                    return None
        return None

    return {"equity": find(["자본총계"]), "ni_cum": find(NI_ALIASES)}


def equity_history(api_key: str, corp: str, this_year: int) -> list[dict]:
    """[{period_end, equity, ni_q(분기화 순이익)}] 시계열 (2023연간~현재, 분기말 기준)."""
    jobs: list[tuple[int, str, str]] = [(2023, "11011", "2023-12-31")]
    for y in range(2024, this_year + 1):
        for reprt, md in QUARTER_REPORTS:
            jobs.append((y, reprt, f"{y}-{md}"))
    results: dict[str, dict | None] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pe: pool.submit(fetch_quarter, api_key, corp, y, r) for y, r, pe in jobs}
        for pe, fut in futs.items():
            results[pe] = fut.result()
    hist: list[dict] = []
    cum_by_year: dict[int, dict[str, int]] = {}
    for (y, reprt, pe) in jobs:
        r = results.get(pe)
        if not r or r.get("equity") is None:
            continue
        rec = {"period_end": pe, "equity": r["equity"], "reprt": reprt}
        if r.get("ni_cum") is not None:
            cum_by_year.setdefault(y, {})[reprt] = r["ni_cum"]
        hist.append(rec)
    # 손익 누적치 → 분기화(연간 보고서만 있는 연도는 연간÷4 근사 — 2023)
    order = ["11013", "11012", "11014", "11011"]
    for rec in hist:
        y = int(rec["period_end"][:4])
        cums = cum_by_year.get(y, {})
        reprt = rec["reprt"]
        if reprt not in cums:
            rec["ni_q"] = None
            continue
        idx = order.index(reprt)
        prev = next((cums[order[i]] for i in range(idx - 1, -1, -1) if order[i] in cums), None)
        if idx == 0 or prev is None:
            rec["ni_q"] = cums[reprt] if idx == 0 else (cums[reprt] // (idx + 1))
        else:
            rec["ni_q"] = cums[reprt] - prev
    return sorted(hist, key=lambda x: x["period_end"])


def percentile_band(series: list[float]) -> list[float] | None:
    s = sorted(x for x in series if x and x > 0)
    if len(s) < 100:
        return None
    return [round(s[int(len(s) * 0.05)], 2), round(s[int(len(s) * 0.95)], 2)]


def multiple_bands(ticker: str, hist: list[dict], shares: float) -> tuple[list | None, list | None, int]:
    """price_history × 분기 BPS/TTM EPS → (pbr_band, per_band, 사용 일수)."""
    ph = json.loads((ROOT / "state" / "price_history.json").read_text(encoding="utf-8"))
    bars = ((ph.get("tickers") or {}).get(ticker) or {}).get("bars") or []
    pbr_s: list[float] = []
    per_s: list[float] = []
    n_used = 0
    for b in bars:
        d, c = b.get("date"), b.get("close")
        if not d or not c:
            continue
        past = [h for h in hist if h["period_end"] <= d]
        if not past:
            continue
        n_used += 1
        bps = past[-1]["equity"] / shares
        if bps > 0:
            pbr_s.append(float(c) / bps)
        nis = [h["ni_q"] for h in past if h.get("ni_q") is not None][-4:]
        if len(nis) == 4:
            ttm_eps = sum(nis) / shares
            if ttm_eps > 0:
                per_s.append(float(c) / ttm_eps)
    return percentile_band(pbr_s), percentile_band(per_s), n_used


def main() -> int:
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    api_key = os.environ.get("DART_API_KEY", "").strip()
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    corp_map: dict[str, str] = {}
    if api_key:
        try:
            corp_map = ff.get_corp_map(api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"corp_code 매핑 실패: {exc} — 가격분포 근사로 폴백")

    updated = 0
    for ticker, v in (cfg.get("tickers") or {}).items():
        if not isinstance(v, dict):
            continue
        # 더 신선한 기존 시드(사람·일요일 루틴) 보존 — 단 근사 시드는 DART 로 업그레이드 시도
        if (v.get("bps") and v.get("source_date") and v["source_date"] >= today
                and v.get("band_quality") not in (None, "approx_price_percentile")):
            print(f"  {v.get('name', ticker)}: 기존 시드 보존({v['source_date']}, {v.get('band_quality')})")
            continue
        p = parse_naver_main(ticker)
        price, per, pbr, cns_per = p.get("price"), p.get("per"), p.get("pbr"), p.get("cns_per")
        if not price or not pbr:
            print(f"  {v.get('name', ticker)}: 네이버 파싱 실패 — skip(아무것도 막지 않음)")
            continue
        bps_now = round(price / pbr, 0)
        eps_fwd = round(price / cns_per, 0) if cns_per else (round(price / per, 0) if per else None)

        pbr_band = per_band = None
        quality = "approx_price_percentile"
        method = None
        corp = corp_map.get(ticker)
        if api_key and corp:
            hist = equity_history(api_key, corp, now.year)
            if len(hist) >= 4:
                shares = hist[-1]["equity"] / bps_now  # 주식수 역산(DART 최신 자본총계 ÷ 네이버 BPS)
                pbr_band, per_band, n_used = multiple_bands(ticker, hist, shares)
                if pbr_band:
                    quality = "dart_quarterly"
                    method = (
                        f"DART 분기 자본총계 {len(hist)}개(2023연간~) ÷ 역산주식수 → 분기 BPS(t), "
                        f"TTM 순이익 → EPS(t). price_history {n_used}일 종가와 결합한 실측 멀티플 "
                        "시계열의 5/95퍼센타일 밴드. 한계: 주식수 고정(증자·소각 미반영)·창 ~2.5년."
                    )
        if pbr_band is None:  # DART 실패 폴백 — v1.0 가격분포 근사(천장·가드 전용)
            ph = json.loads((ROOT / "state" / "price_history.json").read_text(encoding="utf-8"))
            closes = sorted(float(b["close"]) for b in ((ph.get("tickers") or {}).get(ticker) or {}).get("bars") or [] if b.get("close"))
            if len(closes) >= 200:
                pbr_band = [round(closes[int(len(closes) * .05)] / bps_now, 2), round(closes[int(len(closes) * .95)] / bps_now, 2)]
                per_band = [round(closes[int(len(closes) * .05)] / eps_fwd, 2), round(closes[int(len(closes) * .95)] / eps_fwd, 2)] if eps_fwd else None
            method = ("밴드=직전 ~2.5년 종가분포 5/95퍼센타일÷현재 BPS(EPS) 근사 — 천장·가드 전용, "
                      "기준가(anchor) 사용 금지. DART 키/이력 확보 시 dart_quarterly 로 자동 승격.")

        # ② 자기일관성 게이트 — 방금 만든 밴드와 현재 멀티플이 크게 모순이면 강등
        if pbr_band:
            cur_mult = price / bps_now
            lo, hi = pbr_band
            if cur_mult > hi * 1.3 or cur_mult < lo * 0.7:
                print(f"  [WARN] {v.get('name', ticker)}: 현재 PBR {cur_mult:.2f} 가 밴드 {pbr_band} 와 모순(×1.3/×0.7 초과) — band_quality=inconsistent 강등")
                quality = "inconsistent"

        v.update({
            "bps": bps_now, "eps_fwd": eps_fwd,
            "pbr_band_5y": pbr_band, "per_band_5y": per_band,
            "source_url": p["source_url"], "source_date": today,
            "band_quality": quality, "method": method,
        })
        updated += 1
        print(f"  {v.get('name', ticker)}: BPS {bps_now:,.0f} | PBR밴드 {pbr_band} | PER밴드 {per_band} | {quality}")

    cfg["as_of"] = now.isoformat(timespec="seconds")
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated {updated} tickers → config/valuation.json (dart_key={'O' if api_key else 'X'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
