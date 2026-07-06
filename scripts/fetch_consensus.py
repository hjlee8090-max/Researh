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
import ssl
import sys
import time
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


def _opinion_text(score: float | None) -> str | None:
    """FnGuide 투자의견 점수(1~5) → 한글 등급. 강력매도1·매도2·중립3·매수4·강력매수5."""
    if score is None:
        return None
    if score >= 4.5:
        return "강력매수"
    if score >= 3.5:
        return "매수"
    if score >= 2.5:
        return "중립"
    if score >= 1.5:
        return "매도"
    return "강력매도"


# 컨센 요약 박스의 고정 라벨 시퀀스 뒤에 값 5개가 순서대로 온다(FnGuide 템플릿, probe 확인):
#   "... 투자의견 목표주가 EPS PER 추정기관수  4.0 415,200 42,998 7.7 25"
_CONSENSUS_ROW = re.compile(
    r"투자의견\s+목표주가\s+EPS\s+PER\s+추정기관수[\s:]*"
    r"([-\d.,]+)\s+([-\d.,]+)\s+([-\d.,]+)\s+([-\d.,]+)\s+([-\d.,]+)"
)
_CONSENSUS_DATE = re.compile(r"투자의견\s*컨센서스\s*\[(\d{4}/\d{2}/\d{2})\]")


def parse_fnguide(html: str) -> dict[str, Any]:
    """FnGuide Snapshot 컨센 요약 박스에서 투자의견·목표주가·EPS·PER·추정기관수 추출.

    라벨 시퀀스 '투자의견 목표주가 EPS PER 추정기관수' 직후 5개 값을 회수한다
    (probe 로 확인한 고정 템플릿). 박스를 못 찾으면 빈 dict.
    """
    text = _strip_tags(html)
    out: dict[str, Any] = {}
    m = _CONSENSUS_ROW.search(text)
    if m:
        out["opinion_score"] = _num(m.group(1))
        out["target_price"] = _num(m.group(2))
        out["eps_consensus"] = _num(m.group(3))
        out["per_consensus"] = _num(m.group(4))
        out["n_estimates"] = _num(m.group(5))
        out["opinion_text"] = _opinion_text(out["opinion_score"])
    d = _CONSENSUS_DATE.search(text)
    if d:
        out["consensus_date"] = d.group(1)
    return out


def fetch_one(ticker: str, name: str, now: datetime) -> tuple[dict[str, Any], bool]:
    url = FNGUIDE_SNAPSHOT.format(ticker=ticker)
    # FnGuide 는 순차 요청이 몰리면 간헐적으로 SSL EOF 로 끊는다. 짧은 backoff 로 재시도.
    raw = None
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            raw = http_get(url)
            break
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError) as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    if raw is None:
        logger.warning("fnguide fetch failed %s: %s", ticker, last_exc)
        return {"name": name, "error": f"fetch 실패: {type(last_exc).__name__}"}, False
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


def detect_duplicated_consensus(fresh: dict[str, dict[str, Any]], min_group: int = 3) -> set[str]:
    """서로 다른 종목이 '동일 target_price' 를 공유하면, 파서가 종목별 실데이터가 아니라
    고정 템플릿/오류 페이지를 긁은 것이다 (2026-07-06 사고: 17종목 전부 target 505,625 →
    카카오 목표가 +684% 폭발). 다수(과반 또는 min_group 이상)가 공유하는 target 값의
    종목군을 '오염'으로 반환한다. 정상 수집이면 종목마다 target 이 달라 빈 집합.
    """
    from collections import Counter

    counts = Counter(
        e.get("target_price") for e in fresh.values() if e.get("target_price") is not None
    )
    if not counts:
        return set()
    n_valued = sum(counts.values())
    threshold = max(min_group, n_valued // 2 + 1)
    bad_values = {tp for tp, c in counts.items() if c >= threshold}
    return {t for t, e in fresh.items() if e.get("target_price") in bad_values}


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

    # 1) 각 앵커의 '모든' 출현 위치 (어느 게 메뉴/JS 이고 어느 게 데이터인지 구분용)
    for a in PROBE_ANCHORS + ["추정기관수", "12(E)", "12(P)", "예상실적", "확정실적"]:
        idxs = [m.start() for m in re.finditer(re.escape(a), html)]
        print(f"[probe] anchor {a!r}: {len(idxs)} hits @ {idxs[:12]}")

    # 2) 컨센 요약 박스 덤프 — '추정기관수' 주변(투자의견/목표주가/EPS/추정기관수 값이 모여 있음)
    i = html.find("추정기관수")
    if i >= 0:
        print("[probe] ===== CONSENSUS SUMMARY BOX (around 추정기관수) =====")
        print(_strip_tags(html[max(0, i - 1800): i + 300]))
        print("[probe] ===== END SUMMARY BOX =====")

    # 3) 컨센 실적 표 덤프 — '예상실적' 또는 '영업이익, 억원' 주변
    for key in ("예상실적", "영업이익"):
        j = html.find(key)
        if j >= 0:
            print(f"[probe] ===== EARNINGS TABLE (around {key!r}) =====")
            print(_strip_tags(html[max(0, j - 200): j + 1400]))
            print("[probe] ===== END EARNINGS TABLE =====")
            break
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
    _CONSENSUS_FIELDS = ("target_price", "eps_consensus", "per_consensus",
                         "opinion_score", "n_estimates", "opinion_text", "consensus_date")

    def keep_prior_or_strip(ticker: str, entry: dict[str, Any], reason: str) -> dict[str, Any]:
        """오염·실패 종목 — 직전 정상값이 있으면 stale 로 보존, 없으면 컨센 값만 제거(결측 처리)."""
        if ticker in prior.get("tickers", {}):
            kept = dict(prior["tickers"][ticker])
            kept["stale"] = True
            kept["parse_warning"] = reason
            return kept
        stripped = {k: v for k, v in entry.items() if k not in _CONSENSUS_FIELDS}
        stripped["parse_warning"] = reason
        return stripped

    fresh: dict[str, Any] = {}  # 이번에 실제로 파싱 성공한 항목(오염 감지 후 확정)
    data: dict[str, Any] = {}
    for idx, (ticker, name) in enumerate(tickers.items()):
        if idx:
            time.sleep(0.8)  # FnGuide 순차요청 SSL EOF 완화
        entry, is_ok = fetch_one(ticker, name, now)
        if is_ok:
            fresh[ticker] = entry
        else:
            data[ticker] = keep_prior_or_strip(ticker, entry, "fetch 실패 — 직전값 보존")

    # 오염 감지 — 동일 target 이 다수 종목에 복제됐으면 파싱 실패로 간주해 이번 fetch 를 폐기한다
    # (fetched_ok 오집계 → estimate_target_price 앵커 폭발을 원천 차단, 2026-07-06 사고).
    dup = detect_duplicated_consensus(fresh)
    for ticker, entry in fresh.items():
        if ticker in dup:
            data[ticker] = keep_prior_or_strip(
                ticker, entry, "동일 target 다수 복제 — 파싱 오류로 이번 fetch 폐기")
        else:
            data[ticker] = entry
    ok = len(fresh) - len(dup)

    result = {
        "as_of": now.isoformat(timespec="seconds"),
        "source": "FnGuide 컴퍼니가이드 Snapshot (증권사 컨센서스 집계)",
        "note": "컨센서스=증권사 추정 평균. earnings-preview(Phase 2) 입력. 못 받은 종목은 직전값 보존(stale).",
        "ticker_count": len(tickers),
        "fetched_ok": ok,
        "tickers": data,
    }
    if dup:
        result["corruption_detected"] = {
            "kind": "duplicated_target_price",
            "n_tickers": len(dup),
            "note": "동일 target 이 다수 종목에 복제됨 — FnGuide 파싱 실패. 해당 종목은 직전값 보존/결측 처리.",
        }
        print(f"::warning::consensus corruption detected — {len(dup)} tickers shared identical target, discarded")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"consensus: wrote {out_path.relative_to(ROOT)} tickers={len(tickers)} ok={ok}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
