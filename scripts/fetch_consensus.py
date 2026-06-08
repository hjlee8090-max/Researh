#!/usr/bin/env python3
"""보유·후보 종목의 증권사 컨센서스(추정치·목표주가·투자의견)를 수집한다.

컨센서스 레이어 — Phase 2(earnings-preview)의 입력. DART 는 '확정 실적'만 주므로
'시장 예상치(컨센)'는 증권사 추정 집계 업체(FnGuide)에서 가져온다.

소스(무료, 우선순위):
- 1차: FnGuide 컴퍼니가이드 Snapshot (comp.fnguide.com) — 목표주가·투자의견·추정기관수 +
       당기/차기 영업이익·EPS 추정(E)을 한 페이지에서 제공. 서버사이드 렌더(HTML 파싱 가능).
       (fetch_market_data 와 동일하게 브라우저 UA+Referer 로 접근. 샌드박스는 403 이나
        GitHub Actions 러너에서는 동작 — siseJson 과 동일 환경.)

설계 원칙(프로젝트 공통):
- 외부 의존성 0(표준 라이브러리만). 키 불필요.
- graceful degrade: 차단·파싱 실패 시 직전 state/consensus.json 을 보존하고 stale 만 표시.
- 주 1회(일요일) 수집. routine 은 산출물을 읽고 D-1 종목에 한해 웹검색으로 보강·검증.
- **프로브 우선**: `--probe` 는 실제 페이지 접근성·구조(라벨 위치)를 진단 출력한다.
  첫 GitHub Actions 실행에서 구조를 확인한 뒤 파서를 확정하기 위함(맹목 파싱 방지).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
HTTP_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# FnGuide Snapshot. gicode = 'A' + 6자리. KOSPI=701 / KOSDAQ=701 동일 파라미터로 동작.
FNGUIDE_SNAPSHOT = (
    "https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp"
    "?pGB=1&gicode=A{ticker}&cID=&MenuYn=Y&ReportGB=&NewMenuID=11&stkGb=701"
)
# 진단 시 페이지에서 존재를 확인할 한국어 앵커(파서가 의존하는 라벨).
PROBE_ANCHORS = ["목표주가", "투자의견", "추정기관", "컨센서스", "EPS", "영업이익", "당기순이익"]

logger = logging.getLogger(__name__)


def http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://comp.fnguide.com/",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
    )
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
    """{ticker: name} — 보유 + 후보 (fetch_fundamentals 와 동일 소스)."""
    out: dict[str, str] = {}
    for pos in load_json("config/portfolio.json").get("positions", []):
        if pos.get("ticker"):
            out[pos["ticker"]] = pos.get("name", "")
    for c in load_json("config/candidates.json").get("candidates", []):
        if c.get("ticker"):
            out.setdefault(c["ticker"], c.get("name", ""))
    return out


# ---------------------------------------------------------------------------
# 파싱 — 실데이터 구조 확정 전이므로 라벨 기반 best-effort. probe 로 검증 후 정밀화.
# ---------------------------------------------------------------------------
_TAG = re.compile(r"<[^>]+>")
_NUM = re.compile(r"-?[\d,]+\.?\d*")


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", html)).strip()


def _num(s: str | None) -> float | None:
    if not s:
        return None
    m = _NUM.search(s.replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_fnguide(html: str) -> dict[str, Any]:
    """FnGuide Snapshot 에서 컨센서스 핵심값을 best-effort 추출.

    실제 DOM 구조 확정 전이므로 라벨 근방 숫자를 회수한다. probe 출력으로
    실패 라벨을 확인해 정밀 파서로 교체한다. 못 찾은 값은 None.
    """
    text = _strip_tags(html)
    out: dict[str, Any] = {}

    def near(label: str, win: int = 60) -> str | None:
        i = text.find(label)
        return text[i + len(label): i + len(label) + win] if i >= 0 else None

    out["target_price"] = _num(near("목표주가"))
    # 투자의견은 보통 '4.00' 같은 점수 또는 '매수' 텍스트
    opin = near("투자의견")
    out["opinion_score"] = _num(opin)
    if opin:
        m = re.search(r"(매수|중립|매도|적극매수|비중확대|보유)", opin)
        out["opinion_text"] = m.group(1) if m else None
    out["n_estimates"] = _num(near("추정기관수") or near("추정기관"))
    out["raw_found"] = {a: (a in text) for a in PROBE_ANCHORS}
    return out


def fetch_one(ticker: str, name: str, now: datetime) -> tuple[dict[str, Any], bool]:
    url = FNGUIDE_SNAPSHOT.format(ticker=ticker)
    try:
        raw = http_get(url)
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("fnguide fetch failed %s: %s", ticker, exc)
        return {"name": name, "error": f"fetch 실패: {type(exc).__name__}"}, False
    html = raw.decode("utf-8", "replace")
    parsed = parse_fnguide(html)
    has_any = any(parsed.get(k) is not None for k in ("target_price", "opinion_score", "n_estimates"))
    entry = {
        "name": name,
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": "FnGuide Snapshot",
        "source_url": url,
        **parsed,
    }
    return entry, has_any


def probe(tickers: dict[str, str]) -> int:
    """실제 접근성·구조 진단 — 첫 GH Actions 실행에서 파서 확정용."""
    tk = next(iter(tickers)) if tickers else "005930"
    url = FNGUIDE_SNAPSHOT.format(ticker=tk)
    print(f"[probe] GET {url}")
    try:
        raw = http_get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] FETCH FAIL: {type(exc).__name__}: {exc}")
        return 1
    html = raw.decode("utf-8", "replace")
    print(f"[probe] OK bytes={len(html)}")
    for a in PROBE_ANCHORS:
        i = html.find(a)
        if i < 0:
            print(f"[probe] anchor {a!r}: NOT FOUND")
        else:
            ctx = _strip_tags(html[max(0, i - 30): i + 90])
            print(f"[probe] anchor {a!r} @ {i}: ...{ctx}...")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="접근성·구조 진단 출력(수집 안 함)")
    args = ap.parse_args(argv)

    now = datetime.now(KST)
    tickers = collect_tickers()
    out_path = ROOT / "state" / "consensus.json"

    if args.probe:
        return probe(tickers)

    prior = load_json("state/consensus.json", {})
    data: dict[str, Any] = {}
    ok = 0
    for ticker, name in tickers.items():
        entry, is_ok = fetch_one(ticker, name, now)
        if is_ok:
            data[ticker] = entry
            ok += 1
        else:
            # 실패 종목은 직전 값 보존(stale)
            if ticker in prior.get("tickers", {}):
                kept = dict(prior["tickers"][ticker])
                kept["stale"] = True
                data[ticker] = kept
            else:
                data[ticker] = entry

    result = {
        "as_of": now.isoformat(timespec="seconds"),
        "source": "FnGuide 컴퍼니가이드 Snapshot (증권사 컨센서스 집계)",
        "note": "컨센서스=증권사 추정 평균. earnings-preview(Phase 2) 입력. 못 받은 종목은 직전값 보존(stale).",
        "ticker_count": len(tickers),
        "fetched_ok": ok,
        "tickers": data,
    }
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"consensus: wrote {out_path.relative_to(ROOT)} tickers={len(tickers)} ok={ok}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
