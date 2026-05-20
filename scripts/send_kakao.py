#!/usr/bin/env python3
"""카카오 '나에게 보내기' API로 일일 리포트 알림 발송.

GitHub Actions에서 18:00 리포트 푸시 후 호출.
필요한 환경변수:
  KAKAO_REST_API_KEY   카카오 REST API 키
  KAKAO_REFRESH_TOKEN  OAuth refresh token (kakao_oauth_helper.py로 1회 발급)
  PAGES_URL            GitHub Pages 베이스 URL (예: https://hjlee8090-max.github.io/Researh)
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


def extract_summary(md_text: str) -> str:
    """리포트 본문에서 카톡용 짧은 요약 추출 (180자 이내)."""
    m = re.search(r"##\s*한눈에 보기\s*\n(.+?)(?=\n##|\Z)", md_text, re.DOTALL)
    if not m:
        return ""
    lines = []
    for raw in m.group(1).strip().splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        line = line.lstrip("-").strip()
        lines.append(line)
    summary = " · ".join(lines[:3])
    return summary[:180]


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

    report = find_latest_report()
    if report is None:
        print("no reports found, skip notify", flush=True)
        return
    date = report.stem
    text = report.read_text(encoding="utf-8")
    summary = extract_summary(text) or "오늘 리포트가 갱신되었습니다."

    url = f"{PAGES_URL}/{date}.html" if PAGES_URL else "https://github.com/hjlee8090-max/Researh"

    title = f"📊 {date} KOSPI 일일 리포트"
    body_text = f"{title}\n\n{summary}"
    if len(body_text) > 200:
        body_text = body_text[:197] + "..."

    template_object = {
        "object_type": "text",
        "text": body_text,
        "link": {
            "web_url": url,
            "mobile_web_url": url,
        },
        "button_title": "리포트 열기",
    }

    res = http_post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template_object, ensure_ascii=False)},
        {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    print(f"sent: {res}", flush=True)


if __name__ == "__main__":
    main()
