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
ARROW_RE = re.compile(r"[\u2192\u27a1]|->")
_QUOTES = "'\"\u2018\u2019\u201c\u201d\u300c\u300d"


def alias_spec(raw: Any, name: str) -> dict:
    """ticker_aliases 항목을 {any, exclude} 로 정규화. 구 포맷(list)도 그대로 받는다."""
    if isinstance(raw, dict):
        return {"any": raw.get("any") or [name], "exclude": raw.get("exclude") or []}
    if isinstance(raw, list) and raw:
        return {"any": raw, "exclude": []}
    return {"any": [name], "exclude": []}


def alias_hit(title: str, spec: dict) -> bool:
    """제목이 이 종목을 가리키는가. 계열사명을 먼저 지우고 남은 자리에서 별칭을 찾는다.

    '카카오뱅크 노사…'는 카카오(035720)가 아니라 카카오뱅크(323410) 기사인데, 단순
    부분일치는 '카카오'가 걸려 통과시킨다(2026-08-19: 카카오 분류뉴스 1건 전부 오귀속).
    계열사명을 지운 뒤 검사하므로 '카카오, 카카오뱅크 지분 매각'처럼 본체가 함께
    언급된 기사는 그대로 남는다.
    """
    t = norm(title)
    for x in spec.get("exclude", []):
        t = t.replace(norm(x), " ")
    return any(norm(a) in t for a in spec.get("any", []) if a)


def is_demotion_swap(t: str, alias_any: list[str]) -> bool:
    """'최선호주 A\u2192B' 처럼 우리 종목이 화살표 앞에 있으면 강등 기사다.

    '최선호주'\u00b7'톱픽'은 종목이 목록에서 빠질 때도 제목에 그대로 남아 호재로 뒤집힌다
    (2026-08-19: 모건스탠리 최선호주 교체 기사 2건이 +3.0% 로 분류). 숫자 교체
    ('목표가 10만원\u219212만원')와 구분하려고 두 조건을 함께 본다 — 화살표 직전이
    우리 종목명으로 끝나고, 화살표 직후가 숫자가 아니어야 한다.
    """
    names = [norm(a) for a in alias_any if a]
    for m in ARROW_RE.finditer(t):
        head = t[: m.start()].rstrip(_QUOTES)
        tail = t[m.end() :].lstrip(_QUOTES)
        if not tail or tail[0].isdigit():
            continue
        if any(head.endswith(a) for a in names) and not any(a in tail for a in names):
            return True
    return False


def classify(title: str, type_keywords: dict, impact_table: dict,
             alias_any: list[str] | None = None) -> dict | None:
    """헤드라인 1건을 뉴스 유형으로 분류. 매칭 없으면 None(→ unclassified 보존)."""
    t = norm(title)
    matched: list[dict] = []
    for ntype, kw in type_keywords.items():
        if any(norm(x) in t for x in kw.get("exclude", [])):
            continue
        hits = [x for x in kw.get("any", []) if norm(x) in t]
        if not hits:
            continue
        if kw.get("swap_guard") and is_demotion_swap(t, alias_any or []):
            continue  # 'A→B' 교체 기사 — 우리 종목은 빠지는 쪽이다
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
    # 보유 정본은 portfolio.positions — watchlist.shares_held 는 결측(null) 이력이 있어
    # 이 필드에만 의존하면 보유 종목이 수집 대상에서 통째로 빠진다 (2026-07-08 보강)
    for p in load_json("config/portfolio.json", {}).get("positions", []):
        if isinstance(p, dict) and p.get("ticker") and (p.get("shares") or 0) > 0:
            tickers.setdefault(p["ticker"], p.get("name", p["ticker"]))
    for s in load_json("config/watchlist.json", {}).get("stocks", []):
        if isinstance(s, dict) and s.get("ticker") and (s.get("shares_held") or 0) > 0:
            tickers.setdefault(s["ticker"], s.get("name", s["ticker"]))

    cutoff = (now - timedelta(days=max_age)).strftime("%Y-%m-%d")
    out_tickers: dict[str, Any] = {}
    total_classified = total_uncls = fetched_ok = 0
    for ticker, name in tickers.items():
        spec = alias_spec(aliases.get(ticker), name)
        names = spec["any"]
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
            named = alias_hit(it["title"], spec)
            relevant = it["feed"] == "naver_item_news" or named
            if not relevant:
                continue
            # 종목페이지 피드라도 제목이 이 종목을 가리키지 않으면 분류하지 않는다.
            # 네이버 종목뉴스에는 시황·칼럼·타사 기사가 섞여 들어와, 관련성 무검사로
            # 통과시키면 남의 회사 재료가 가산점이 된다(2026-08-19: 신한지주 페이지의
            # '농심 목표가 상향' 기사가 +3.0% 로 분류). 재현율은 unclassified 로 지킨다.
            c = classify(it["title"], type_keywords, impact_table, names) if named else None
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

    # 하이브리드 분류 2단계: 키워드(1차) 미매칭 잔여를 routine LLM(2차)이 분류·승격하도록 큐 제공.
    # 키워드는 재현율이 한정적(신조어·문장형 헤드라인). LLM 이 큐를 읽어 news_type 으로 분류하면
    # manual_news 승격(즉시 반영) 또는 news_keywords 보강(sunday_policy_review) 으로 환류한다.
    llm_queue = []
    for tk, tv in out_tickers.items():
        for u in (tv.get("unclassified") or []):
            if u.get("title"):
                llm_queue.append({"ticker": tk, "name": tv.get("name"), "title": u.get("title"),
                                  "url": u.get("url"), "published": u.get("published")})
    llm_queue = llm_queue[:80]  # 컨텍스트 보호 상한(초과분은 다음 회차)
    denom = total_classified + total_uncls

    out = {
        "as_of": now.isoformat(timespec="seconds"),
        "source": "Google News RSS(국문+영문) + 네이버 종목뉴스 (fetch_news.yml — Actions 러너)",
        "keyword_registry": "config/news_keywords.json (news_impact.news_type_impact_pct 와 1:1)",
        "usage_note": "하이브리드 분류: ①키워드(fetch_news) 1차 → ②LLM 2차(routine 이 llm_review_queue 를 news_type 으로 분류해 manual_news 승격=즉시반영 또는 키워드 보강=sunday_policy_review). estimate_target_price 가 classified 를 가산점으로 반영.",
        "classification_summary": {
            "classified": total_classified,
            "unclassified": total_uncls,
            "classified_rate_pct": round(total_classified / denom * 100, 1) if denom else None,
            "llm_review_pending": len(llm_queue),
            "note": "classified_rate 가 낮으면 llm_review_queue 를 routine 이 처리해야 함. 키워드 보강분은 차주 재현율로 회수.",
        },
        "ticker_count": len(tickers),
        "fetched_ok": fetched_ok,
        "classified_total": total_classified,
        "unclassified_total": total_uncls,
        "global_total": len(global_items),
        "llm_review_queue": llm_queue,
        "tickers": out_tickers,
        "global": global_items,
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} fetched_ok={fetched_ok}/{len(tickers)} classified={total_classified} unclassified={total_uncls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
