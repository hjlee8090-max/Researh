#!/usr/bin/env python3
"""카카오 '나에게 보내기' API로 routine 알림 발송.

GitHub Actions 에서 00/06/09/12/15/18 routine 푸시 후 호출.
커밋 메시지 프리픽스에 따라 다른 요약을 보낸다:
  - 일일 routine(chore(06/09/12/15)·"report:") → 현재 평가금액(config/portfolio.json)
    + 주요 뉴스(리포트 '한눈에 보기'의 매크로/시황·슬롯 한 줄) 간결 요약
  - 주말/감사/전략 등("weekly:"/"audit:"/"sun-strategy:" 등) → 해당 리포트 요약 불릿

필요한 환경변수:
  KAKAO_REST_API_KEY    카카오 REST API 키
  KAKAO_REFRESH_TOKEN   OAuth refresh token (kakao_oauth_helper.py로 1회 발급)
  KAKAO_CLIENT_SECRET   (선택) Client Secret 활성 상태인 경우 필수
  PAGES_URL             GitHub Pages 베이스 URL
  COMMIT_MESSAGE        (선택) 커밋 메시지. 분기에 사용
  CHANGED_FILES_FILE    (선택) 이번 push 가 변경한 파일 목록(줄당 1개) 파일 경로.
                        주어지면 "리포트 파일을 실제로 변경한 push"만 알림 발송
                        (동일 routine 의 후속 잡무 커밋이 같은 슬롯 알림을 중복 발송하는 것 방지)
  KAKAO_DRY_RUN         (선택) truthy 면 발송하지 않고 판정·본문만 출력 (로컬 테스트)
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

REST_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
REFRESH_TOKEN = os.environ.get("KAKAO_REFRESH_TOKEN", "")
CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET")
PAGES_URL = os.environ.get("PAGES_URL", "").rstrip("/")
COMMIT_MESSAGE = os.environ.get("COMMIT_MESSAGE", "")
CHANGED_FILES_FILE = os.environ.get("CHANGED_FILES_FILE", "")
DRY_RUN = os.environ.get("KAKAO_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")

# 발송 이력 원장 (docs/plan_hourly_report_gap_fix.md Phase 1-3) — 시도·성공·실패·스킵을 전부 남겨
# audit_github_notify 가 "어제 리포트의 발송이 실제로 나갔는지"를 대사한다. 워크플로가 커밋한다.
NOTIFY_LOG = ROOT / "state" / "notify_log.jsonl"


def log_notify(event: str, **fields) -> None:
    """원장 append — 어떤 실패도 발송 흐름을 깨지 않는다(로깅은 부수 기능)."""
    if DRY_RUN:
        return
    try:
        entry = {"ts": datetime.now(KST).isoformat(timespec="seconds"), "event": event}
        entry.update({k: v for k, v in fields.items() if v is not None})
        with NOTIFY_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:  # noqa: BLE001
        print(f"notify_log append failed (ignored): {exc}", flush=True)


def ledger_slot_label() -> str:
    """원장용 슬롯 라벨 — 커밋 프리픽스에서 도출 (00/06/09/12/15/18/audit/…)."""
    for prefix, label in (
        ("report:", "18"), ("audit:", "audit"), ("weekly-archive:", "archive"),
        ("weekly:", "weekend"), ("sat-review:", "sat"), ("sun-strategy:", "sun"),
        ("policy-review:", "policy"),
    ):
        if COMMIT_MESSAGE.startswith(prefix):
            return label
    meta = detect_slot(COMMIT_MESSAGE)
    return meta[3] if meta else "?"


def http_post(url: str, data, headers=None, retries: int = 3) -> dict:
    """POST + 재시도 — 네트워크 오류·5xx 만 지수 백오프(2/4/8s), 4xx 는 즉시 실패.

    (Phase 2-2, 진단 P5) 이전엔 시도 1회 + 즉시 sys.exit 라 일시 장애 1번에
    슬롯 알림이 통째로 유실됐다. 실패는 최종적으로 sys.exit → main 의 원장 기록 경로.
    """
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode("utf-8")
    else:
        body = data
    last_err = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code < 500:
                sys.exit(f"HTTP {e.code} from {url}: {err_body}")
            last_err = f"HTTP {e.code} from {url}: {err_body[:120]}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = f"network error to {url}: {e}"
        if attempt < retries:
            wait = 2 ** attempt
            print(f"http_post retry {attempt}/{retries - 1} in {wait}s — {last_err}", flush=True)
            time.sleep(wait)
    sys.exit(f"failed after {retries} attempts: {last_err}")


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


DAILY_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(00|06|09|12|15|18))?\.md$")


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


# 슬롯 헤더 고정 문자열 계약 — 단일 스펙은 docs/report_contract.md.
# 변경 시 반드시 함께 갱신: check_report_contract.py(검사)·build_html.py·prompts/*.md 파서 고정 문자열 절.
SLOT_META = {
    "00:00": ("🌙", "00:00 글로벌 야간 점검", "## 🌙 00:00 글로벌 야간 점검", "00"),
    "06:00": ("🌄", "06:00 미국장 마감 확정", "## 🌄 06:00 미국장 마감 확정", "06"),
    "09:00": ("🌅", "09:00 개장 점검", "## 🌅 09:00 개장 점검", "09"),
    "12:00": ("🕛", "12:00 장중 점검", "## 🕛 12:00 장중 점검", "12"),
    "15:00": ("🔔", "15:00 마감 임박 점검", "## 🔔 15:00 마감 임박 점검", "15"),
}

REPORT_HEADER_18 = "## 📊 18:00 종합·확정 리포트"
WEEKEND_HEADER = "## 한눈에 보기"


def detect_slot(commit_msg: str) -> tuple[str, str, str, str] | None:
    """커밋 메시지 **제목 줄**에서 routine 슬롯 식별. (emoji, title, section_header, slot_hh) 반환.

    본문(멀티라인)은 보지 않는다 — 본문의 ISO 타임스탬프(`...T15:00:00+09:00`)에
    "00:00" 이 부분 문자열로 들어 있어 15:00 커밋이 자정 슬롯으로 오인된 사고 방지
    (2026-06-12 15:23 오발송). `chore(HH:00` 프리픽스를 1순위로 매칭하고,
    chore( 인데 슬롯 프리픽스가 아니면(예: chore(context)) routine 커밋이 아니므로 None.
    """
    subject = commit_msg.splitlines()[0] if commit_msg else ""
    m = re.match(r"^chore\((00|06|09|12|15):00", subject)
    if m:
        return SLOT_META[f"{m.group(1)}:00"]
    if subject.startswith("chore("):
        return None
    for slot, meta in SLOT_META.items():
        if slot in subject:
            return meta
    return None


def changed_files() -> set[str] | None:
    """이번 push 가 변경한 파일 목록. None = 정보 없음(가드 비활성 — dispatch 경유 등)."""
    if not CHANGED_FILES_FILE:
        return None
    path = Path(CHANGED_FILES_FILE)
    if not path.exists():
        return None
    files = {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    return files or None


def detect_slot_from_files() -> tuple[str, str, str, str] | None:
    """이번 push 가 변경한 '오늘자' 슬롯 리포트 파일명에서 슬롯 도출 (프리픽스 보완 신호, Phase 2-4).

    커밋 제목 문자열 규약에만 결합된 슬롯 식별(진단 P6: 오타 1글자 = 조용한 미발송)을 완화한다.
    오늘 날짜의 슬롯 리포트가 정확히 1개 변경됐을 때만 신호로 인정 — 0개(리포트 외 push)나
    복수(백필 일괄 push)는 None 을 반환해 제목 프리픽스에 위임한다. 18시는 build_report_message
    경로가 별도라 대상에서 제외(00/06/09/12/15만).
    """
    files = changed_files()
    if not files:
        return None
    today = datetime.now(KST).date().isoformat()
    pattern = re.compile(rf"^reports/{today}-(00|06|09|12|15)\.md$")
    slots = sorted({m.group(1) for f in files if (m := pattern.match(f))})
    if len(slots) != 1:
        return None
    return SLOT_META.get(f"{slots[0]}:00")


def push_modified(report: Path | None) -> bool:
    """알림 대상 리포트 파일이 이번 push 에서 실제로 변경됐는가.

    같은 routine 이 후속 잡무 커밋(스냅샷 stale 마커 등)을 별도 push 하면 슬롯 프리픽스가
    같아 동일 알림이 중복 발송되던 문제(2026-06-12 00:18/00:24 중복)의 방지 가드.
    변경 목록 정보가 없으면(workflow_dispatch 등) 통과.
    """
    if report is None:
        return True
    files = changed_files()
    if files is None:
        return True
    rel = report.relative_to(ROOT).as_posix()
    return rel in files


def is_dated_today(report: Path | None) -> bool:
    """리포트 파일명 날짜가 오늘(KST)인가. 날짜 없는 파일(주간 archive 등)은 면제.

    슬롯 미식별 폴백이 '가장 최근' 파일(=전일 리포트)을 집어 어제 일일 종합이
    오늘 오후에 발송되던 문제(2026-06-12 17:21 — 6/11 일일 종합)의 방지 가드.
    """
    if report is None:
        return True
    m = re.match(r"(\d{4}-\d{2}-\d{2})", report.name)
    if not m:
        return True
    return m.group(1) == datetime.now(KST).date().isoformat()


def guard_or_skip(report: Path | None, what: str) -> bool:
    """공통 발송 가드 — 통과 못 하면 사유를 남기고 False."""
    if not is_dated_today(report):
        print(f"skip notify: {what} 리포트({report.name if report else '?'})가 오늘 날짜가 아님 — 묵은 리포트 재발송 방지", flush=True)
        log_notify("skip", slot=ledger_slot_label(), what=what, reason="stale_report",
                   report=report.name if report else None)
        return False
    if not push_modified(report):
        print(f"skip notify: 이번 push 가 {what} 리포트를 변경하지 않음 — 후속 잡무 커밋 중복 알림 방지", flush=True)
        log_notify("skip", slot=ledger_slot_label(), what=what, reason="push_not_modified",
                   report=report.name if report else None)
        return False
    return True


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
    """보유 요약 1줄 — 압축형 '보유 N종목 · 특이만' (Phase 2-1, 진단 I1·I17).

    이전 형태(전 종목 나열)는 66자 캡에 6종목 중 4종목만 실리고, current_price 키
    오참조(portfolio 실제 키: current_price_approx)로 등락률이 항상 공란이라 정보량
    없이 예산 1/3을 소비했다. 이제 진입가 대비 ±3% 밖이거나 단계색이 green 이 아닌
    종목만 명기하고, 나머지는 개수로 요약한다.
    """
    path = ROOT / "config" / "portfolio.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    positions = [p for p in d.get("positions", []) if isinstance(p, dict) and p.get("shares")]
    if not positions:
        return "📌 보유 없음 · 현금 100%"
    notables: list[tuple[float, str]] = []
    all_green = True
    for p in positions:
        pct = p.get("pct_from_entry")
        if not isinstance(pct, (int, float)):
            ep = p.get("entry_price")
            cp = p.get("current_price_approx") or p.get("current_price")
            pct = (cp - ep) / ep * 100 if (
                isinstance(ep, (int, float)) and isinstance(cp, (int, float)) and ep
            ) else None
        tier = p.get("tier")
        if tier and tier != "green":
            all_green = False
        if (isinstance(pct, (int, float)) and abs(pct) >= 3.0) or (tier and tier != "green"):
            name = p.get("name") or p.get("ticker") or "?"
            pct_txt = f" {pct:+.1f}%" if isinstance(pct, (int, float)) else ""
            emoji = _tier_emoji(tier, pct if isinstance(pct, (int, float)) else None)
            notables.append((abs(pct) if isinstance(pct, (int, float)) else 99.0, f"{name}{pct_txt}{emoji}"))
    base = f"📌 보유 {len(positions)}종목"
    if not notables:
        return base + (" · 전종목 진입가 ±3% 이내 🟢" if all_green else " · 특이 없음")
    notables.sort(key=lambda x: -x[0])
    return cap(base + " · 특이: " + ", ".join(t for _, t in notables), 64)


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
HEADLINE_LABELS = ("한줄평", "한 줄", "오늘의 액션", "액션", "핵심", "촉매")


def pick_news_lines(fields: list[tuple[str, str]], max_lines: int = 2) -> list[tuple[str, str]]:
    """(라벨, 값) 목록에서 카톡 본문 후보를 고른다 — ⚡액션/한줄평(HEADLINE) 1순위, 시황(NEWS) 2순위.

    (Phase 2-1, 진단 I1) 이전엔 시황 라벨(NEWS)을 먼저 스캔해 KOSPI 시세가 항상 첫 슬롯을
    차지하고 액션 라인은 2순위+예산 부족으로 구조적으로 탈락했다(−7.89% 폭락일 행동 지시 0건).
    순서를 뒤집어 "내가 뭘 해야 하나"가 먼저 실린다. 라벨을 함께 반환해 compose 가 ⚡/📰 를 구분한다.
    """
    picked: list[tuple[str, str]] = []
    used: set[int] = set()
    for groups in (HEADLINE_LABELS, NEWS_LABELS):
        for i, (label, value) in enumerate(fields):
            if i in used or not value:
                continue
            if any(kw in label for kw in groups):
                picked.append((label, value))
                used.add(i)
                break
        if len(picked) >= max_lines:
            break
    if not picked:  # 라벨 매칭 실패 — 첫 비어있지 않은 값으로 폴백
        for label, value in fields:
            if value:
                picked.append((label, value))
            if len(picked) >= max_lines:
                break
    return picked[:max_lines]


def compose_daily_body(news: list[tuple[str, str]]) -> str:
    """카톡 본문 조립 — ⚡액션 → 💰평가금액 → 📌보유(압축) → 📰시황 순 그리디(≤168자).

    (Phase 2-1, 진단 I1) 이전 조립은 평가금액+보유 전 종목 나열이 168자 예산을 선점해
    액션 라인이 항상 잘렸다. 이제 1순위 픽(액션/한줄평)이 예산 최우선으로 항상 실리고,
    평가·보유·시황은 남는 예산에서만 그리디로 붙는다.
    """
    def line_emoji(label: str) -> str:
        return "⚡" if any(kw in label for kw in HEADLINE_LABELS) else "📰"

    body_lines: list[str] = []
    if news:
        label, value = news[0]
        body_lines.append(f"{line_emoji(label)} {cap(value, 72)}")
    for extra in (portfolio_equity_line(), portfolio_holdings_line()):
        if not extra:
            continue
        candidate = body_lines + [extra]
        if len("\n".join(candidate)) <= 168:
            body_lines = candidate
    for label, value in news[1:]:
        candidate = body_lines + [f"{line_emoji(label)} {cap(value)}"]
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
    news: list[tuple[str, str]] = []
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
    is_report = COMMIT_MESSAGE.startswith("report:")
    is_weekly = COMMIT_MESSAGE.startswith("weekly:")
    is_weekly_archive = COMMIT_MESSAGE.startswith("weekly-archive:")
    is_audit = COMMIT_MESSAGE.startswith("audit:")
    is_sat_review = COMMIT_MESSAGE.startswith("sat-review:")
    is_sun_strategy = COMMIT_MESSAGE.startswith("sun-strategy:")
    is_policy_review = COMMIT_MESSAGE.startswith("policy-review:")
    base_url = PAGES_URL or "https://github.com/hjlee8090-max/Researh"

    def report_path(stem: str) -> Path:
        return ROOT / "reports" / f"{stem}.md"

    if is_weekly_archive:
        msg = build_pattern_report_message("*-archive.md", "🗂️ 주간 archive", "지난주 archive 파일이 갱신되었습니다.")
        if msg is None:
            print("no weekly archive reports found, skip notify", flush=True)
            return
        title, body, date = msg
        if not guard_or_skip(report_path(date), "주간 archive"):
            return
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "주간 archive 열기"
    elif is_audit:
        msg = build_pattern_report_message("*-audit.md", "🧪 파이프라인 감사", "파이프라인 감사 리포트가 갱신되었습니다.")
        if msg is None:
            print("no audit reports found, skip notify", flush=True)
            return
        title, body, date = msg
        if not guard_or_skip(report_path(date), "감사"):
            return
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "감사 리포트 열기"
    elif is_sat_review:
        msg = build_pattern_report_message("*-saturday-review.md", "📈 토요일 사후분석", "토요일 사후분석 리포트가 갱신되었습니다.")
        if msg is None:
            print("no saturday review reports found, skip notify", flush=True)
            return
        title, body, date = msg
        if not guard_or_skip(report_path(date), "토요일 사후분석"):
            return
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "사후분석 열기"
    elif is_sun_strategy:
        msg = build_pattern_report_message("*-sunday-strategy.md", "🧭 일요일 전략", "일요일 다음주 전략 리포트가 갱신되었습니다.")
        if msg is None:
            print("no sunday strategy reports found, skip notify", flush=True)
            return
        title, body, date = msg
        if not guard_or_skip(report_path(date), "일요일 전략"):
            return
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "전략 리포트 열기"
    elif is_policy_review:
        msg = build_pattern_report_message("*-policy-review.md", "⚙️ 정책 패치 리뷰", "lessons 반영 점검·패치 후보 리포트가 갱신되었습니다.")
        if msg is None:
            print("no policy-review reports found, skip notify", flush=True)
            return
        title, body, date = msg
        if not guard_or_skip(report_path(date), "정책 패치 리뷰"):
            return
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "패치 리뷰 열기"
    elif is_weekly:
        msg = build_weekend_message()
        if msg is None:
            print("no weekend reports found, skip notify", flush=True)
            return
        title, body, date = msg
        if not guard_or_skip(report_path(date), "주말"):
            return
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "전략 리포트 열기"
    elif is_report:
        msg = build_report_message()
        if msg is None:
            print("no reports found, skip notify", flush=True)
            return
        title, body, date = msg
        if not guard_or_skip(report_path(date), "18시 종합"):
            return
        url = f"{PAGES_URL}/{date}.html" if PAGES_URL else base_url
        button = "리포트 열기"
    else:
        slot_meta = detect_slot(COMMIT_MESSAGE)
        file_meta = detect_slot_from_files()
        if slot_meta is not None and file_meta is not None and slot_meta[3] != file_meta[3]:
            # 두 신호(제목 프리픽스 vs 변경 파일) 불일치 — 오발송 방지가 우선이므로
            # 발송하지 않고 원장에 남긴다 (Phase 2-4, 미식별=미발송 원칙 유지).
            print(f"slot signal mismatch: prefix={slot_meta[3]} vs files={file_meta[3]} — skip notify", flush=True)
            log_notify("skip", reason="slot_signal_mismatch",
                       prefix_slot=slot_meta[3], file_slot=file_meta[3])
            return
        if slot_meta is None and file_meta is not None:
            # 제목이 슬롯을 말하지 않아도(오타 등) push 가 오늘자 슬롯 리포트를 정확히 1개
            # 변경했다면 그 파일 신호로 발송한다 — "제목 오타 1글자 = 조용한 미발송" 완화 (P6).
            print(f"slot from changed files: {file_meta[3]} (제목 프리픽스 미식별 보완)", flush=True)
            log_notify("slot_from_files", slot=file_meta[3])
            slot_meta = file_meta
        if slot_meta is None:
            # 폴백 발송 금지 — 슬롯 미식별 커밋(chore(context) 등 비-routine)이
            # '가장 최근'(=전일) 리포트를 발송하던 사고 방지 (2026-06-12 17:21 6/11 일일 종합).
            print(f"unrecognized commit, skip notify: {COMMIT_MESSAGE.splitlines()[0][:80] if COMMIT_MESSAGE else '(empty)'}", flush=True)
            log_notify("skip", reason="unrecognized_commit",
                       commit=(COMMIT_MESSAGE.splitlines()[0][:80] if COMMIT_MESSAGE else ""))
            return
        slot_msg = build_slot_message(slot_meta)
        if slot_msg is None:
            print("no slot data, skip notify", flush=True)
            return
        title, body, source_path = slot_msg
        if not guard_or_skip(source_path, f"{slot_meta[3]}시 슬롯"):
            return
        if source_path is not None and PAGES_URL:
            url = f"{PAGES_URL}/{source_path.stem}.html"
        else:
            url = base_url
        button = "리포트 열기"

    if DRY_RUN:
        print(f"[DRY_RUN] would send — title: {title}", flush=True)
        print(f"[DRY_RUN] url: {url} / button: {button}", flush=True)
        print(f"[DRY_RUN] body:\n{body}", flush=True)
        return

    slot_label = ledger_slot_label()
    try:
        if not REST_KEY or not REFRESH_TOKEN:
            sys.exit("KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 환경변수 필요")
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
            # 토큰 값은 원장에 기록하지 않는다 — 만료 D-7 경보(audit)의 기준 시각만 남긴다.
            log_notify("token_refresh")

        res = send_kakao(access_token, title, body, url, button)
    except SystemExit as exc:
        # sys.exit 경로(토큰 실패·HTTP 오류)도 원장에 남긴다 — 무음 실패 방지 (P5).
        log_notify("send", slot=slot_label, ok=False, reason=str(exc)[:160])
        raise
    print(f"sent: {res}", flush=True)
    log_notify("send", slot=slot_label, ok=True, title=title[:60])


if __name__ == "__main__":
    main()
