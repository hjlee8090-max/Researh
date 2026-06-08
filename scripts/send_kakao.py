#!/usr/bin/env python3
"""카카오 '나에게 보내기' API로 routine 알림 발송.

GitHub Actions 에서 09/12/15/18 routine 푸시 후 호출.
커밋 메시지 프리픽스에 따라 다른 요약을 보낸다:
  - 일일 routine(chore(09/12/15)·"report:") → 현재 평가금액(config/portfolio.json)
    + 주요 뉴스(리포트 '한눈에 보기'의 매크로/시황·슬롯 한 줄) 간결 요약
  - 주말/감사/전략 등("weekly:"/"audit:"/"sun-strategy:" 등) → 해당 리포트 요약 불릿

필요한 환경변수:
  KAKAO_REST_API_KEY    카카오 REST API 키
  KAKAO_REFRESH_TOKEN   OAuth refresh token (kakao_oauth_helper.py로 1회 발급)
  KAKAO_CLIENT_SECRET   (선택) Client Secret 활성 상태인 경우 필수
  PAGES_URL             GitHub Pages 베이스 URL
  COMMIT_MESSAGE        (선택) 커밋 메시지. 분기에 사용
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REST_KEY = os.environ["KAKAO_REST_API_KEY"]
REFRESH_TOKEN = os.environ["KAKAO_REFRESH_TOKEN"]
CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET")
PAGES_URL = os.environ.get("PAGES_URL", "").rstrip("/")
COMMIT_MESSAGE = os.environ.get("COMMIT_MESSAGE", "")


def http_post(url: str, data, headers=None) -> dict:
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode("utf-8")
    else:
        body = data
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"HTTP {e.code} from {url}: {body}")


def refresh_access_token() -> dict:
    params = {
        "grant_type": "refresh_token",
        "client_id": REST_KEY,
        "refresh_token": REFRESH_TOKEN,
    }
    if CLIENT_SECRET:
        params["client_secret"] = CLIENT_SECRET
    return http_post(
        "https://kauth.kakao.com/oauth/token",
        params,
        {"Content-Type": "application/x-www-form-urlencoded"},
    )


DAILY_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(00|09|12|15|18))?\.md$")


def find_latest_report() -> Path | None:
    """가장 최근 일일 리포트 (시간대별 분리 파일 또는 구버전 단일 파일)."""
    reports_dir = ROOT / "reports"
    if not reports_dir.exists():
        return None
    candidates: list[tuple[str, int, Path]] = []
    for p in reports_dir.glob("*.md"):
        m = DAILY_REPORT_RE.match(p.name)
        if not m:
            continue
        date = m.group(1)
        slot = int(m.group(2)) if m.group(2) else 99  # legacy single-file = end of day
        candidates.append((date, slot, p))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][2]


def find_latest_matching_report(pattern: str) -> Path | None:
    reports_dir = ROOT / "reports"
    if not reports_dir.exists():
        return None
    files = sorted(reports_dir.glob(pattern))
    return files[-1] if files else None


def find_slot_report(slot_hh: str) -> Path | None:
    """오늘 또는 가장 최근 날짜의 특정 슬롯(`00`,`09`,`12`,`15`,`18`) 리포트.

    시간대별 분리 파일을 우선 찾고, 없으면 구버전 단일 파일(`YYYY-MM-DD.md`)로 폴백.
    """
    reports_dir = ROOT / "reports"
    if not reports_dir.exists():
        return None
    slot_files = sorted(reports_dir.glob(f"*-{slot_hh}.md"))
    if slot_files:
        return slot_files[-1]
    return find_latest_report()


SLOT_META = {
    "00:00": ("🌙", "00:00 글로벌 야간 점검", "## 🌙 00:00 글로벌 야간 점검", "00"),
    "09:00": ("🌅", "09:00 개장 점검", "## 🌅 09:00 개장 점검", "09"),
    "12:00": ("🕛", "12:00 장중 점검", "## 🕛 12:00 장중 점검", "12"),
    "15:00": ("🔔", "15:00 마감 임박 점검", "## 🔔 15:00 마감 임박 점검", "15"),
}

REPORT_HEADER_18 = "## 📊 18:00 종합·확정 리포트"
WEEKEND_HEADER = "## 한눈에 보기"


def detect_slot(commit_msg: str) -> tuple[str, str, str, str] | None:
    """커밋 메시지에서 routine 슬롯 식별. (emoji, title, section_header, slot_hh) 반환."""
    for slot, meta in SLOT_META.items():
        if slot in commit_msg:
            return meta
    return None


def extract_section(md_text: str, header: str) -> str:
    """리포트에서 특정 ## 헤더 섹션의 본문만 추출 (다음 ## 또는 EOF까지)."""
    pattern = re.escape(header) + r"\s*\n(.+?)(?=\n##\s|\Z)"
    m = re.search(pattern, md_text, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_one_glance(section_text: str) -> list[str]:
    """섹션 내부의 '한눈에 보기' 서브섹션에서 불릿 라인을 추출."""
    m = re.search(r"###\s*한눈에 보기.*?\n(.+?)(?=\n###|\Z)", section_text, re.DOTALL)
    if not m:
        # fallback: 섹션 첫 불릿 몇 줄
        body = section_text
    else:
        body = m.group(1)
    lines = []
    for raw in body.strip().splitlines():
        s = raw.strip()
        if s.startswith("-"):
            lines.append(s.lstrip("-").strip())
        elif s.startswith("•"):
            lines.append(s.lstrip("•").strip())
    return lines


def portfolio_equity_line() -> str | None:
    """config/portfolio.json 의 현재 평가금액·누적수익률을 카톡 1줄로."""
    path = ROOT / "config" / "portfolio.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    eq = d.get("equity")
    if not isinstance(eq, (int, float)):
        return None
    cum = d.get("cumulative_return_pct")
    cum_txt = f" (누적 {cum:+.2f}%)" if isinstance(cum, (int, float)) else ""
    return f"💰 평가금액 {int(round(eq)):,}원{cum_txt}"


def cap(s: str, n: int = 64) -> str:
    """공백 정리 후 n자 이내로. 넘으면 구분자(·—,.공백) 경계에서 자르고 … 표기."""
    s = " ".join(s.split())
    if len(s) <= n:
        return s
    cut = s[:n]
    for sep in ("·", " — ", "—", ". ", ", ", " "):
        idx = cut.rfind(sep)
        if idx >= int(n * 0.6):
            return cut[:idx].rstrip(" ·—,.") + "…"
    return cut.rstrip() + "…"


TIER_EMOJI = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴"}


def _tier_emoji(tier: str | None, pct: float | None) -> str:
    """단계색 이모지. tier 필드 우선, 없으면 진입가 대비 변동률로 추정."""
    if tier in TIER_EMOJI:
        return TIER_EMOJI[tier]
    if isinstance(pct, (int, float)):
        if pct <= -10:
            return "🔴"
        if pct <= -7:
            return "🟠"
        if pct <= -5:
            return "🟡"
        return "🟢"
    return ""


def portfolio_holdings_line() -> str | None:
    """config/portfolio.json 의 보유 종목을 '종목 N주 ±X%🟢' 형태로 1줄 요약(캡 66자)."""
    path = ROOT / "config" / "portfolio.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    positions = [p for p in d.get("positions", []) if isinstance(p, dict) and p.get("shares")]
    if not positions:
        return "📌 보유 없음 · 현금 100%"
    parts = []
    for p in positions:
        name = p.get("name") or p.get("ticker") or "?"
        shares = p.get("shares")
        pct = p.get("pct_from_entry")
        if not isinstance(pct, (int, float)):
            ep, cp = p.get("entry_price"), p.get("current_price")
            if isinstance(ep, (int, float)) and isinstance(cp, (int, float)) and ep:
                pct = (cp - ep) / ep * 100
        pct_txt = f"{pct:+.1f}%" if isinstance(pct, (int, float)) else ""
        emoji = _tier_emoji(p.get("tier"), pct if isinstance(pct, (int, float)) else None)
        parts.append(f"{name} {shares}주 {pct_txt}{emoji}".strip())
    return cap("📌 보유: " + ", ".join(parts), 66)


def glance_subsection(section_text: str) -> str:
    """슬롯 섹션 안에서 '### 한눈에 보기' 서브섹션 본문만 반환(없으면 섹션 전체)."""
    m = re.search(r"###\s*한눈에 보기.*?\n(.+?)(?=\n###|\Z)", section_text, re.DOTALL)
    return m.group(1) if m else section_text


def extract_glance_fields(section_text: str) -> list[tuple[str, str]]:
    """'한눈에 보기' 의 표(| 라벨 | 값 |) 또는 불릿(- 라벨: 값)에서 (라벨, 값) 목록을 추출."""
    fields: list[tuple[str, str]] = []
    for raw in section_text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.count("|") >= 3:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2:
                label = cells[0].replace("*", "").strip()
                value = cells[1].replace("*", "").strip()
                if label and value and set(label) != {"-"} and label != "항목":
                    fields.append((label, value))
        elif line.startswith(("-", "•")):
            body = line.lstrip("-•").strip()
            if ":" in body:
                label, value = body.split(":", 1)
                fields.append((label.replace("*", "").strip(), value.replace("*", "").strip()))
            elif body:
                fields.append(("", body.replace("*", "").strip()))
    return fields


NEWS_LABELS = ("매크로", "핵심 인사이트", "인사이트", "KOSPI", "시장 환경", "시황", "뉴스", "지수")
HEADLINE_LABELS = ("한 줄", "오늘의 액션", "액션", "핵심", "촉매")


def pick_news_lines(fields: list[tuple[str, str]], max_lines: int = 2) -> list[str]:
    """라벨 우선순위로 '주요 뉴스/시황' 값을 최대 max_lines 개 고른다(매크로/시황 → 슬롯 한 줄)."""
    picked: list[str] = []
    used: set[int] = set()
    for groups in (NEWS_LABELS, HEADLINE_LABELS):
        for i, (label, value) in enumerate(fields):
            if i in used or not value:
                continue
            if any(kw in label for kw in groups):
                picked.append(value)
                used.add(i)
                break
        if len(picked) >= max_lines:
            break
    if not picked:  # 라벨 매칭 실패 — 첫 비어있지 않은 값으로 폴백
        for _, value in fields:
            if value:
                picked.append(value)
            if len(picked) >= max_lines:
                break
    return picked[:max_lines]


def compose_daily_body(news: list[str]) -> str:
    """평가금액 + 보유 포트폴리오 + 주요 뉴스. 평가금액·보유는 항상 포함하고,
    뉴스는 카톡 200자 한도(본문 ≤168자) 안에서 들어가는 만큼만 그리디로 추가한다."""
    head: list[str] = []
    eq = portfolio_equity_line()
    if eq:
        head.append(eq)
    hold = portfolio_holdings_line()
    if hold:
        head.append(hold)
    body_lines = list(head)
    for nv in news:
        candidate = body_lines + [f"📰 {cap(nv)}"]
        if len("\n".join(candidate)) <= 168:
            body_lines = candidate
        else:
            break
    return "\n".join(body_lines)


def build_slot_message(slot_meta: tuple[str, str, str, str]) -> tuple[str, str, Path | None] | None:
    """리포트 시간대 섹션의 '한눈에 보기' 에서 주요 뉴스를 뽑아 '평가금액 + 주요 뉴스' 본문 생성.

    시간대별 분리 파일(`YYYY-MM-DD-{HH}.md`)을 우선 찾고, 없으면 구버전 단일 파일에서 섹션 추출.
    리포트가 없으면 watchlist.json 종목 의견으로 폴백.
    반환: (title, body, source_path) — source_path는 URL 매핑에 사용.
    """
    emoji, slot_title, section_header, slot_hh = slot_meta
    title = f"{emoji} {slot_title}"
    report = find_slot_report(slot_hh)
    news: list[str] = []
    if report is not None:
        section = extract_section(report.read_text(encoding="utf-8"), section_header)
        if section:
            news = pick_news_lines(extract_glance_fields(glance_subsection(section)))
    body = compose_daily_body(news)
    if body:
        return title, body, report

    # 폴백: watchlist.json 종목별 최신 의견(평가금액·뉴스 추출 실패 시)
    wl_path = ROOT / "config" / "watchlist.json"
    if not wl_path.exists():
        return None
    data = json.loads(wl_path.read_text(encoding="utf-8"))
    stocks = data.get("stocks", [])
    if not stocks:
        return None
    lines = []
    for s in stocks:
        name = s.get("name", s.get("ticker", "?"))
        comments = s.get("comments") or []
        verdict = (comments[-1].get("opinion") or comments[-1].get("action") or "") if comments else "코멘트 없음"
        lines.append(f"- {name}: {verdict}")
    return title, "\n".join(lines), report


def build_report_message() -> tuple[str, str, str] | None:
    """18시 종합 섹션 기반 요약. (title, body, page_stem) 반환.

    시간대별 분리 파일이 있으면 `YYYY-MM-DD-18.md` 를 우선 찾는다.
    """
    report = find_slot_report("18")
    if report is None:
        return None
    page_stem = report.stem  # e.g. "2026-05-22-18" or legacy "2026-05-22"
    date = page_stem.split("-18")[0] if page_stem.endswith("-18") else page_stem
    text = report.read_text(encoding="utf-8")
    section = extract_section(text, REPORT_HEADER_18)
    if not section:
        # 18시 섹션이 없는 구버전 호환: 옛 '## 한눈에 보기' 탐색
        m = re.search(r"##\s*한눈에 보기\s*\n(.+?)(?=\n##|\Z)", text, re.DOTALL)
        section = m.group(1) if m else ""
    news = pick_news_lines(extract_glance_fields(glance_subsection(section))) if section else []
    body = compose_daily_body(news) or "오늘 리포트가 갱신되었습니다."
    title = f"📊 {date} KOSPI 일일 종합"
    return title, body, page_stem


def build_weekend_message() -> tuple[str, str, str] | None:
    """주말 전략 리포트의 한눈에 보기 요약. (title, body, date) 반환."""
    reports_dir = ROOT / "reports"
    if not reports_dir.exists():
        return None
    files = sorted(reports_dir.glob("*-weekend.md"))
    report = files[-1] if files else find_latest_report()
    if report is None:
        return None
    date = report.stem
    text = report.read_text(encoding="utf-8")
    section = extract_section(text, WEEKEND_HEADER)
    glance = extract_one_glance(section) if section else []
    if not glance:
        # fallback: 파일 앞부분의 불릿만 추출
        glance = []
        for raw in text.splitlines()[:40]:
            s = raw.strip()
            if s.startswith("-"):
                glance.append(s.lstrip("-").strip())
    summary = "\n".join(f"- {l}" for l in glance[:4]) if glance else "주말 전략 리포트가 갱신되었습니다."
    title = f"🧭 {date} 주말 전략 리포트"
    return title, summary, date


def build_pattern_report_message(pattern: str, title_prefix: str, fallback: str) -> tuple[str, str, str] | None:
    """패턴에 맞는 최신 리포트의 '요약' 섹션을 모바일 알림으로 변환."""
    report = find_latest_matching_report(pattern)
    if report is None:
        return None
    date = report.stem
    text = report.read_text(encoding="utf-8")
    section = extract_section(text, "## 요약")
    glance = extract_one_glance(section) if section else []
    if not glance:
        glance = []
        for raw in text.splitlines()[:50]:
            s = raw.strip()
            if s.startswith("-"):
                glance.append(s.lstrip("-").strip())
    summary = "\n".join(f"- {l}" for l in glance[:4]) if glance else fallback
    title = f"{title_prefix} {date}"
    return title, summary, date


def send_kakao(access_token: str, title: str, body: str, url: str, button_title: str) -> dict:
    text = f"{title}\n\n{body}"
    if len(text) > 200:
        text = text[:197] + "..."
    template_object = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": url,
            "mobile_web_url": url,
        },
        "button_title": button_title,
    }
    return http_post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template_object, ensure_ascii=False)},
        {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )


def main():
    token_res = refresh_access_token()
    access_token = token_res.get("access_token")
    if not access_token:
        sys.exit(f"failed to refresh: {token_res}")

    new_refresh = token_res.get("refresh_token")
    if new_refresh and new_refresh != REFRESH_TOKEN:
        print("=" * 60, flush=True)
        print("⚠️  NEW REFRESH TOKEN ISSUED — UPDATE GITHUB SECRET!", flush=True)
        print(f"   Secret name: KAKAO_REFRESH_TOKEN", flush=True)
        print(f"   New value  : {new_refresh}", flush=True)
        print("=" * 60, flush=True)

    is_report = COMMIT_MESSAGE.startswith("report:")
    is_weekly = COMMIT_MESSAGE.startswith("weekly:")
    is_weekly_archive = COMMIT_MESSAGE.startswith("weekly-archive:")
    is_audit = COMMIT_MESSAGE.startswith("audit:")
    is_sat_review = COMMIT_MESSAGE.startswith("sat-review:")
    is_sun_strategy = COMMIT_MESSAGE.startswith("sun-strategy:")
    is_policy_review = COMMIT_MESSAGE.startswith("policy-review:")
    base_url = PAGES_URL or "https://github.com/hjlee8090-max/Researh"

    if is_weekly_archive:
        msg = build_pattern_report_message("*-archive.md", "🗂️ 주간 archive", "지난주 archive 파일이 갱신되었습니다.")
        if msg is None:
            print("no weekly archive reports found, skip notify", flush=True)
            return
        title, body, date = msg
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "주간 archive 열기"
    elif is_audit:
        msg = build_pattern_report_message("*-audit.md", "🧪 파이프라인 감사", "파이프라인 감사 리포트가 갱신되었습니다.")
        if msg is None:
            print("no audit reports found, skip notify", flush=True)
            return
        title, body, date = msg
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "감사 리포트 열기"
    elif is_sat_review:
        msg = build_pattern_report_message("*-saturday-review.md", "📈 토요일 사후분석", "토요일 사후분석 리포트가 갱신되었습니다.")
        if msg is None:
            print("no saturday review reports found, skip notify", flush=True)
            return
        title, body, date = msg
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "사후분석 열기"
    elif is_sun_strategy:
        msg = build_pattern_report_message("*-sunday-strategy.md", "🧭 일요일 전략", "일요일 다음주 전략 리포트가 갱신되었습니다.")
        if msg is None:
            print("no sunday strategy reports found, skip notify", flush=True)
            return
        title, body, date = msg
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "전략 리포트 열기"
    elif is_policy_review:
        msg = build_pattern_report_message("*-policy-review.md", "⚙️ 정책 패치 리뷰", "lessons 반영 점검·패치 후보 리포트가 갱신되었습니다.")
        if msg is None:
            print("no policy-review reports found, skip notify", flush=True)
            return
        title, body, date = msg
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "패치 리뷰 열기"
    elif is_weekly:
        msg = build_weekend_message()
        if msg is None:
            print("no weekend reports found, skip notify", flush=True)
            return
        title, body, date = msg
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "전략 리포트 열기"
    elif is_report:
        msg = build_report_message()
        if msg is None:
            print("no reports found, skip notify", flush=True)
            return
        title, body, date = msg
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "리포트 열기"
    else:
        slot_meta = detect_slot(COMMIT_MESSAGE)
        if slot_meta is None:
            # 시간대 미식별 시 최신 리포트로 폴백
            msg = build_report_message()
            if msg is None:
                print(f"unrecognized commit, skip notify: {COMMIT_MESSAGE[:80]}", flush=True)
                return
            title, body, page_stem = msg
            url = f"{PAGES_URL}/{page_stem}.html" if PAGES_URL else base_url
            button = "리포트 열기"
        else:
            slot_msg = build_slot_message(slot_meta)
            if slot_msg is None:
                print("no slot data, skip notify", flush=True)
                return
            title, body, source_path = slot_msg
            if source_path is not None and PAGES_URL:
                url = f"{PAGES_URL}/{source_path.stem}.html"
            else:
                url = base_url
            button = "리포트 열기"

    res = send_kakao(access_token, title, body, url, button)
    print(f"sent: {res}", flush=True)


if __name__ == "__main__":
    main()
