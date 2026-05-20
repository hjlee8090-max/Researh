#!/usr/bin/env python3
"""카카오 '나에게 보내기' API로 routine 알림 발송.

GitHub Actions 에서 09/12/15/18 routine 푸시 후 호출.
커밋 메시지 프리픽스에 따라 다른 요약을 보낸다:
  - "report:"   → reports/ 최신 .md 의 '한눈에 보기' 요약
  - "chore(...)" → config/watchlist.json 의 종목별 최신 코멘트 요약

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


def find_latest_report() -> Path | None:
    reports_dir = ROOT / "reports"
    if not reports_dir.exists():
        return None
    files = sorted(reports_dir.glob("*.md"))
    return files[-1] if files else None


SLOT_META = {
    "00:00": ("🌙", "00:00 글로벌 야간 점검", "## 🌙 00:00 글로벌 야간 점검"),
    "09:00": ("🌅", "09:00 개장 점검", "## 🌅 09:00 개장 점검"),
    "12:00": ("🕛", "12:00 장중 점검", "## 🕛 12:00 장중 점검"),
    "15:00": ("🔔", "15:00 마감 임박 점검", "## 🔔 15:00 마감 임박 점검"),
}

REPORT_HEADER_18 = "## 📊 18:00 종합·확정 리포트"


def detect_slot(commit_msg: str) -> tuple[str, str, str] | None:
    """커밋 메시지에서 routine 슬롯 식별. (emoji, title, section_header) 반환."""
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


def build_slot_message(slot_meta: tuple[str, str, str]) -> tuple[str, str] | None:
    """리포트 파일에서 해당 시간대 섹션의 '한눈에 보기' 를 뽑아 카톡 본문 생성.
    리포트 섹션이 아직 없으면 watchlist.json 폴백."""
    emoji, slot_title, section_header = slot_meta
    report = find_latest_report()
    if report is not None:
        text = report.read_text(encoding="utf-8")
        section = extract_section(text, section_header)
        if section:
            glance = extract_one_glance(section)
            if glance:
                title = f"{emoji} {slot_title}"
                body = "\n".join(f"- {line}" for line in glance[:4])
                return title, body

    # 폴백: watchlist.json 종목별 의견
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
        if not comments:
            lines.append(f"- {name}: 코멘트 없음")
            continue
        last = comments[-1]
        verdict = last.get("opinion") or last.get("action") or ""
        lines.append(f"- {name}: {verdict}")
    title = f"{emoji} {slot_title}"
    return title, "\n".join(lines)


def build_report_message() -> tuple[str, str, str] | None:
    """18시 종합 섹션 기반 요약. (title, body, date) 반환."""
    report = find_latest_report()
    if report is None:
        return None
    date = report.stem
    text = report.read_text(encoding="utf-8")
    section = extract_section(text, REPORT_HEADER_18)
    if section:
        glance = extract_one_glance(section)
    else:
        # 18시 섹션이 없는 구버전 호환: 옛 '## 한눈에 보기' 탐색
        m = re.search(r"##\s*한눈에 보기\s*\n(.+?)(?=\n##|\Z)", text, re.DOTALL)
        glance = []
        if m:
            for raw in m.group(1).strip().splitlines():
                s = raw.strip()
                if s.startswith("-"):
                    glance.append(s.lstrip("-").strip())
    summary = "\n".join(f"- {l}" for l in glance[:4]) if glance else "오늘 리포트가 갱신되었습니다."
    title = f"📊 {date} KOSPI 일일 종합 리포트"
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
    base_url = PAGES_URL or "https://github.com/hjlee8090-max/Researh"

    if is_report:
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
            title, body, date = msg
            url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
            button = "리포트 열기"
        else:
            wl_msg = build_watchlist_message(slot_meta)
            if wl_msg is None:
                print("no watchlist data, skip notify", flush=True)
                return
            title, body = wl_msg
            url = base_url
            button = "현황 보기"

    res = send_kakao(access_token, title, body, url, button)
    print(f"sent: {res}", flush=True)


if __name__ == "__main__":
    main()
