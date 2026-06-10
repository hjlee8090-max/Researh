#!/usr/bin/env python3
"""fetch_news — 종목 뉴스 자동 수집·키워드 분류 → state/news_feed.json (v1.0).

목표주가 추정식(estimate_target_price v1.2)의 뉴스 가산점 입력을 자동화한다.
config/news_keywords.json 의 유형별 키워드(news_impact.json 의 가산점 테이블과 1:1)로
헤드라인을 분류하고, 유형 미매칭이어도 종목 기사면 unclassified 로 보존한다(재현율 우선 —
'키워드와 관련된 부분은 꼭 캐치' — 놓친 기사는 라우틴 검토→manual_news 승격 또는 키워드 보강).

소스(네트워크 되는 Actions 러너에서 실행 — fetch_news.yml):
  1. Google News RSS: news.google.com/rss/search?q=<종목명>+when:14d (키 불필요)
  2. 네이버 종목뉴스 HTML: finance.naver.com/item/news_news.naver?code=<ticker> (폴백·보강)
둘 다 실패한 종목은 직전 news_feed 항목을 보존한다(graceful degrade — consensus 패턴 동일).

자동 분류 항목은 추정식에서 auto_news_confidence_factor(0.6) 할인으로 반영되고, 같은 유형의
manual_news(사람/라우틴이 출처 확인 후 기록)가 ±5일 내 있으면 manual 이 우선한다 —
web_verify_guard 철학 유지: 자동은 후보, 확정은 검증을 거친 기록.
의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "news_feed.json"
HTTP_TIMEOUT = 20


def load_json(rel: str, default: Any) -> Any:
    p = ROOT / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def http_get(url: str, extra_headers: dict[str, str] | None = None) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; research-pipeline/1.0)"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def norm(text: str) -> str:
    """매칭용 정규화 — 공백·태그 제거('공급 계약'='공급계약')."""
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html.unescape(text or "")))


# ── 수집 ─────────────────────────────────────────────────────────────────────
def fetch_google_rss(query: str, max_age_days: int, lang: str = "ko") -> list[dict]:
    locale = "&hl=ko&gl=KR&ceid=KR:ko" if lang == "ko" else "&hl=en-US&gl=US&ceid=US:en"
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(f"{query} when:{max_age_days}d")
        + locale
    )
    try:
        raw = http_get(url)
        root = ET.fromstring(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"  google rss '{query}' 실패: {exc}")
        return []
    items: list[dict] = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        src = it.find("{*}source")
        try:
            published = parsedate_to_datetime(pub).astimezone(KST).strftime("%Y-%m-%d") if pub else None
        except (TypeError, ValueError):
            published = None
        if title:
            items.append({
                "title": html.unescape(title), "url": link, "published": published,
                "source": (src.text or "").strip() if src is not None else "google_news",
                "feed": "google_rss",
            })
    return items


NAVER_ROW_RE = re.compile(
    r'<a[^>]*news_read[^>]*>(?P<title>.*?)</a>.*?'
    r'<td class="info">(?P<info>[^<]*)</td>\s*'
    r'<td class="date">\s*(?P<date>[\d.]+)',
    re.S,
)


def fetch_naver_item_news(ticker: str) -> list[dict]:
    url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page=1"
    try:
        raw = http_get(url, {"Referer": "https://finance.naver.com/"})
    except Exception as exc:  # noqa: BLE001
        print(f"  naver news {ticker} 실패: {exc}")
        return []
    text = None
    for enc in ("euc-kr", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    items: list[dict] = []
    for m in NAVER_ROW_RE.finditer(text):
        d = m.group("date").strip().rstrip(".")
        published = d.replace(".", "-") if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", d) else None
        title = re.sub(r"<[^>]+>", "", m.group("title")).strip()
        if title:
            items.append({
                "title": html.unescape(title),
                "url": f"https://finance.naver.com/item/news_news.naver?code={ticker}",
                "published": published, "source": m.group("info").strip() or "naver_finance",
                "feed": "naver_item_news",
            })
    return items


# ── 분류 ─────────────────────────────────────────────────────────────────────
def classify(title: str, type_keywords: dict, impact_table: dict) -> dict | None:
    """헤드라인 1건을 뉴스 유형으로 분류. 매칭 없으면 None(→ unclassified 보존)."""
    t = norm(title)
    matched: list[dict] = []
    for ntype, kw in type_keywords.items():
        if any(norm(x) in t for x in kw.get("exclude", [])):
            continue
        hits = [x for x in kw.get("any", []) if norm(x) in t]
        if not hits:
            continue
        boosted = [x for x in kw.get("boost", []) if norm(x) in t]
        matched.append({
            "type": ntype,
            "matched_keywords": hits + boosted,
            "confidence": "keyword_boosted" if boosted else "keyword",
            "impact_pct": (impact_table.get(ntype) or {}).get("impact_pct"),
        })
    if not matched:
        return None
    # 복수 유형 → |impact| 최대를 primary 로(이중계상 방지, news_keywords.match_rules 동일)
    matched.sort(key=lambda m: abs(m.get("impact_pct") or 0), reverse=True)
    return {"primary": matched[0], "all": matched}


def norm_en(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).lower()


def classify_en(title: str, type_keywords_en: dict) -> dict | None:
    """영어 헤드라인 분류 — 소문자·공백정규화 후 구문 부분일치."""
    t = norm_en(title)
    matched = []
    for ntype, kw in type_keywords_en.items():
        if any(x.lower() in t for x in kw.get("exclude", [])):
            continue
        hits = [x for x in kw.get("any", []) if x.lower() in t]
        if hits:
            matched.append({"type": ntype, "matched_keywords": hits,
                            "impact_pct": kw.get("impact_pct")})
    if not matched:
        return None
    matched.sort(key=lambda m: abs(m.get("impact_pct") or 0), reverse=True)
    return matched[0]


def collect_global(kw_cfg: dict, max_age: int, prev_global: list) -> list[dict]:
    """해외뉴스 수집·분류 (v1.1). 쿼리별 영어 RSS → type_keywords_en 분류 → 채널·대상 태깅.

    전이계수(channel_transmission)는 여기서 곱하지 않는다 — estimate_target_price 가
    config 값을 읽어 적용(계수 보정 시 재수집 불필요).
    """
    gcfg = kw_cfg.get("global_news", {})
    type_kw = gcfg.get("type_keywords_en", {})
    out: list[dict] = []
    fetched_any = False
    for q in gcfg.get("queries", []):
        items = fetch_google_rss(q.get("query", ""), max_age, lang="en")
        if items:
            fetched_any = True
        seen: set[str] = set()
        kept = 0
        for it in items:
            key = norm_en(it["title"])[:60]
            if not key or key in seen:
                continue
            seen.add(key)
            c = classify_en(it["title"], type_kw)
            if not c:
                continue
            out.append({
                **it, "query_id": q.get("id"), "channel": q.get("channel"),
                "affects_tickers": q.get("affects_tickers", []),
                "affects_group": q.get("affects_group"),
                "type": c["type"], "impact_pct": c["impact_pct"],
                "matched_keywords": c["matched_keywords"],
            })
            kept += 1
        print(f"  [해외] {q.get('id')}: raw {len(items)} → 분류 {kept}건")
    if not fetched_any and prev_global:
        print("  [해외] 전 쿼리 수집 실패 — 직전값 보존(stale)")
        return prev_global
    return out


def main() -> int:
    now = datetime.now(KST)
    kw_cfg = load_json("config/news_keywords.json", {})
    type_keywords = kw_cfg.get("type_keywords", {})
    aliases = kw_cfg.get("ticker_aliases", {})
    rules = kw_cfg.get("match_rules", {})
    max_age = int(rules.get("max_age_days", 14))
    keep_uncls = int(rules.get("unclassified_keep", 10))
    impact_table = load_json("config/news_impact.json", {}).get("news_type_impact_pct", {})
    prev_feed = load_json("state/news_feed.json", {})
    prev = prev_feed.get("tickers", {})

    # 키워드 커버리지 가드 — 가산점 테이블의 유형에 키워드가 없으면 분류가 구멍난다.
    missing = [k for k in impact_table if k not in type_keywords]
    if missing:
        print(f"[WARN] news_keywords 에 키워드 없는 유형: {missing} — 해당 유형은 자동 캐치 불가")

    # 대상: 후보 ∪ 보유 (estimate_target_price 와 동일 모집단)
    tickers: dict[str, str] = {}
    for c in load_json("config/candidates.json", {}).get("candidates", []):
        if isinstance(c, dict) and c.get("ticker"):
            tickers[c["ticker"]] = c.get("name", c["ticker"])
    for s in load_json("config/watchlist.json", {}).get("stocks", []):
        if isinstance(s, dict) and s.get("ticker") and (s.get("shares_held") or 0) > 0:
            tickers.setdefault(s["ticker"], s.get("name", s["ticker"]))

    cutoff = (now - timedelta(days=max_age)).strftime("%Y-%m-%d")
    out_tickers: dict[str, Any] = {}
    total_classified = total_uncls = fetched_ok = 0
    for ticker, name in tickers.items():
        names = aliases.get(ticker, [name])
        raw_items = fetch_google_rss(names[0], max_age) + fetch_naver_item_news(ticker)
        if not raw_items:
            kept = prev.get(ticker)
            if kept:
                kept["stale"] = True
                out_tickers[ticker] = kept
            print(f"  {name}({ticker}): 수집 0건 — 직전값 {'보존(stale)' if kept else '없음'}")
            continue
        fetched_ok += 1
        seen: set[str] = set()
        classified: list[dict] = []
        unclassified: list[dict] = []
        for it in raw_items:
            key = norm(it["title"])[:60]
            if not key or key in seen:
                continue
            seen.add(key)
            if it.get("published") and it["published"] < cutoff:
                continue
            # 종목 관련성: 별칭 포함 또는 종목 전용 피드(naver_item_news)
            relevant = it["feed"] == "naver_item_news" or any(norm(a) in norm(it["title"]) for a in names)
            if not relevant:
                continue
            c = classify(it["title"], type_keywords, impact_table)
            if c:
                classified.append({
                    **it, "type": c["primary"]["type"],
                    "impact_pct": c["primary"]["impact_pct"],
                    "matched_keywords": c["primary"]["matched_keywords"],
                    "confidence": c["primary"]["confidence"],
                    "all_types": [m["type"] for m in c["all"]],
                })
            else:
                unclassified.append(it)
        classified.sort(key=lambda x: x.get("published") or "", reverse=True)
        unclassified.sort(key=lambda x: x.get("published") or "", reverse=True)
        total_classified += len(classified)
        total_uncls += len(unclassified)
        out_tickers[ticker] = {
            "name": name,
            "fetched_at": now.isoformat(timespec="seconds"),
            "raw_count": len(raw_items),
            "classified": classified,
            "unclassified": unclassified[:keep_uncls],
        }
        types = {}
        for x in classified:
            types[x["type"]] = types.get(x["type"], 0) + 1
        print(f"  {name}({ticker}): raw {len(raw_items)} → 분류 {len(classified)}건 {types or ''} / 미분류 보존 {min(len(unclassified), keep_uncls)}건")

    print("해외뉴스 수집:")
    global_items = collect_global(kw_cfg, max_age, prev_feed.get("global", []))

    out = {
        "as_of": now.isoformat(timespec="seconds"),
        "source": "Google News RSS(국문+영문) + 네이버 종목뉴스 (fetch_news.yml — Actions 러너)",
        "keyword_registry": "config/news_keywords.json (news_impact.news_type_impact_pct 와 1:1)",
        "usage_note": "estimate_target_price v1.2 가 classified 를 auto_news_confidence_factor 할인으로 반영. unclassified 는 라우틴 검토용(manual_news 승격 또는 키워드 보강 → sunday_policy_review).",
        "ticker_count": len(tickers),
        "fetched_ok": fetched_ok,
        "classified_total": total_classified,
        "unclassified_total": total_uncls,
        "global_total": len(global_items),
        "tickers": out_tickers,
        "global": global_items,
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} fetched_ok={fetched_ok}/{len(tickers)} classified={total_classified} unclassified={total_uncls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
