#!/usr/bin/env python3
"""Markdown 리포트를 HTML로 변환해서 _site/ 디렉토리에 출력.

GitHub Actions에서 호출되며, GitHub Pages 배포 artifact로 업로드된다.
"""
import json
import re
import shutil
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import markdown
except ModuleNotFoundError:
    markdown = None

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
SITE = ROOT / "_site"
TEMPLATES = ROOT / "templates"
CONFIG = ROOT / "config"

KST = timezone(timedelta(hours=9))


def render(template: str, **vars) -> str:
    """간단한 {{ var }} 치환 (Jinja2 의존 회피)."""
    out = template
    for k, v in vars.items():
        out = out.replace("{{ " + k + " }}", str(v))
    return out


def extract_oneline(md_text: str) -> str:
    """'오늘의 한줄평' 라인을 og:description으로. (고정 문자열 계약: docs/report_contract.md §2)"""
    m = re.search(r"오늘의 한줄평\s*[:：]\s*(.+)", md_text)
    if m:
        return m.group(1).strip().lstrip("- ").strip()
    # fallback: 한눈에 보기 섹션 첫 줄
    m = re.search(r"## 한눈에 보기\s*\n+\s*-\s*(.+)", md_text)
    if m:
        return m.group(1).strip()
    return "KOSPI 자기보완형 시뮬레이션 일일 리포트"


def md_to_html(md_text: str) -> str:
    if markdown is None:
        blocks = []
        in_list = False
        for raw in md_text.splitlines():
            line = raw.rstrip()
            if not line:
                if in_list:
                    blocks.append("</ul>")
                    in_list = False
                continue
            if line.startswith("# "):
                if in_list:
                    blocks.append("</ul>")
                    in_list = False
                blocks.append(f"<h1>{html.escape(line[2:].strip())}</h1>")
            elif line.startswith("## "):
                if in_list:
                    blocks.append("</ul>")
                    in_list = False
                blocks.append(f"<h2>{html.escape(line[3:].strip())}</h2>")
            elif line.startswith("### "):
                if in_list:
                    blocks.append("</ul>")
                    in_list = False
                blocks.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
            elif line.startswith("- "):
                if not in_list:
                    blocks.append("<ul>")
                    in_list = True
                blocks.append(f"<li>{html.escape(line[2:].strip())}</li>")
            elif line.startswith("> "):
                if in_list:
                    blocks.append("</ul>")
                    in_list = False
                blocks.append(f"<blockquote>{html.escape(line[2:].strip())}</blockquote>")
            else:
                if in_list:
                    blocks.append("</ul>")
                    in_list = False
                blocks.append(f"<p>{html.escape(line)}</p>")
        if in_list:
            blocks.append("</ul>")
        return "\n".join(blocks)

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )
    return md.convert(md_text)


def format_num(n) -> str:
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def num(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _position_eval(p: dict) -> dict:
    """portfolio.json 의 포지션을 평가현황으로 환산.

    평가가격·평가금액·평가손익은 routine 에 따라 current_price/market_value/
    unrealized_pnl 또는 *_approx 접미 필드로 기록된다. reconcile_portfolio.py 와
    동일한 폴백을 적용해 필드명 불일치로 평가금액이 0 으로 떨어지던 인덱스 표시
    버그를 막는다.
    """
    shares = num(p.get("shares"))
    cur = num(p.get("current_price")) or num(p.get("current_price_approx")) or num(p.get("entry_price"))
    mv_field = p.get("market_value")
    if mv_field is None:
        mv_field = p.get("market_value_approx")
    mv = num(mv_field) if mv_field is not None else shares * cur
    cost = p.get("cost_basis")
    if cost is None:
        cost = p.get("cost_basis_total")
    cost = num(cost)
    pnl_field = p.get("unrealized_pnl")
    if pnl_field is None:
        pnl_field = p.get("unrealized_pnl_approx")
    pnl = num(pnl_field) if pnl_field is not None else (mv - cost if cost else 0.0)
    avg = num(p.get("avg_cost")) or (cost / shares if shares else 0.0)
    pnl_pct = (pnl / cost * 100) if cost else 0.0
    return {"shares": shares, "cur": cur, "mv": mv, "cost": cost, "pnl": pnl, "avg": avg, "pnl_pct": pnl_pct}


def build_positions_html(portfolio: dict, snapshot: dict | None = None, exit_levels: dict | None = None) -> str:
    """보유 현황 패널 — 시세는 market_snapshot(09/12/15/18시 리포트 발행 시 커밋) 오버레이.

    portfolio.json 의 current_price_approx 는 매매·EOD 때만 갱신돼 장중에 낡는다 —
    스냅샷 당일가를 우선 사용해 09/12/15시 리포트가 나올 때마다 인덱스 보유 현황이
    최신 시세·손절/목표/트레일선(exit_levels)으로 갱신되게 한다 (2026-07-04 사용자 요청).
    """
    snap_tickers = (snapshot or {}).get("tickers", {}) if isinstance(snapshot, dict) else {}
    exit_tickers = (exit_levels or {}).get("tickers", {}) if isinstance(exit_levels, dict) else {}
    positions = [
        p for p in portfolio.get("positions", [])
        if isinstance(p, dict) and num(p.get("shares")) > 0
    ]
    if not positions:
        return '<p class="no-pos"><em>보유 종목 없음 — 전량 현금</em></p>'
    items = ['<ul class="positions">']
    for p in positions:
        snap = snap_tickers.get(str(p.get("ticker")), {}) if isinstance(snap_tickers, dict) else {}
        snap_cur = 0.0
        if isinstance(snap, dict):
            ohlc = snap.get("today_ohlc")
            if isinstance(ohlc, dict):
                snap_cur = num(ohlc.get("close"))
            if not snap_cur:
                snap_cur = num(snap.get("last_close"))
        if snap_cur:
            p = dict(p)
            p["current_price"] = snap_cur  # 스냅샷 시세 오버레이 — _position_eval 이 최우선 사용
        e = _position_eval(p)
        pnl_cls = "pos" if e["pnl"] >= 0 else "neg"
        pnl_str = f'{e["pnl"]:+,.0f}원'.replace("+-", "-")
        pct_str = f'{e["pnl_pct"]:+.1f}%'
        lv = exit_tickers.get(str(p.get("ticker")), {}) if isinstance(exit_tickers, dict) else {}
        target = (lv.get("target_price") if isinstance(lv, dict) else None) or p.get("target_price")
        stop = (lv.get("stop_price") if isinstance(lv, dict) else None) or p.get("stop_price")
        sub_bits = [f'평단 {format_num(e["avg"])} → 현재 {format_num(e["cur"])}']
        if target:
            sub_bits.append(f'목표 {format_num(target)}')
        if stop:
            sub_bits.append(f'손절 {format_num(stop)}')
        if isinstance(lv, dict) and lv.get("trailing_activated") and lv.get("trailing_first_level"):
            sub_bits.append(f'트레일1차 {format_num(lv["trailing_first_level"])}')
        items.append(
            f'<li>'
            f'<div class="pos-row">'
            f'<span class="pos-id"><span class="name">{html.escape(str(p.get("name", "")))}</span>'
            f'<span class="ticker">{html.escape(str(p.get("ticker", "")))} · {int(e["shares"])}주</span></span>'
            f'<span class="pos-num"><span class="mv">{format_num(e["mv"])}원</span>'
            f'<span class="pnl {pnl_cls}">{pnl_str} ({pct_str})</span></span>'
            f'</div>'
            f'<div class="pos-sub">{" · ".join(sub_bits)}</div>'
            f'</li>'
        )
    items.append("</ul>")
    return "\n".join(items)


SLOT_LABEL = {
    "00": ("🌙", "자정"),
    "06": ("🌄", "06시"),
    "09": ("🌅", "09시"),
    "12": ("🕛", "12시"),
    "15": ("🔔", "15시"),
    "18": ("📊", "18시"),
}

DAILY_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d{2}))?$")
STD_SLOTS = ("00", "06", "09", "12", "15", "18")
AUDIT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-audit$")
WEEKEND_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(saturday-review|sunday-strategy|policy-review)$")
ARCHIVE_RE = re.compile(r"^(\d{4})-W(\d{2})-archive$")

# 주말 카드 슬롯 — 표시 순서대로 (키, 이모지, 라벨)
WEEKEND_SLOTS = [
    ("sat00", "🌙", "토 자정"),
    ("sat_review", "🔎", "토 사후분석"),
    ("sun00", "🌙", "일 자정"),
    ("sun_strategy", "🧭", "일 전략"),
    ("policy", "📐", "정책 리뷰"),
    ("archive", "🗂️", "주간 아카이브"),
    ("audit", "🔍", "감사"),
]
WEEKEND_SUFFIX_SLOT = {
    "saturday-review": "sat_review",
    "sunday-strategy": "sun_strategy",
    "policy-review": "policy",
}


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _iso_key(d) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def _preview_of(path: Path) -> str:
    try:
        return extract_oneline(path.read_text(encoding="utf-8"))
    except OSError:
        return ""


def _chip(path: Path, emoji: str, label: str, cls: str = "present") -> str:
    return f'<a class="slot {cls}" href="./{path.stem}.html">{emoji} {label}</a>'


def _weekday_card(date: str, slots: dict) -> str:
    """평일 카드 — 00·09·12·15·18 시간대 슬롯(미생성분은 점선) + 비표준 시간대 + 감사 + 구버전 단일 파일."""
    extras = sorted(k for k in slots if k.isdigit() and k not in STD_SLOTS)
    preview_path = next(
        (slots[k] for k in ("18", "15", "12", "09", "06", "00", *extras, "legacy", "audit") if k in slots),
        None,
    )
    preview = _preview_of(preview_path) if preview_path else ""
    chips = []
    for hh in STD_SLOTS:
        emoji, _ = SLOT_LABEL[hh]
        if hh in slots:
            chips.append(_chip(slots[hh], emoji, hh))
        else:
            chips.append(f'<span class="slot missing">{emoji} {hh}</span>')
    for hh in extras:
        chips.append(_chip(slots[hh], "🕐", hh))
    if "audit" in slots:
        chips.append(_chip(slots["audit"], "🔍", "감사", cls="present audit"))
    if "legacy" in slots:
        chips.append(_chip(slots["legacy"], "📄", "단일 파일 (구버전)", cls="legacy"))
    return (
        f'<li class="daily-card">'
        f'<div class="daily-head"><strong>{date}</strong>'
        f'<span class="preview">{preview}</span></div>'
        f'<div class="slots">{"".join(chips)}</div>'
        f'</li>'
    )


def _weekend_card(key: tuple[int, int], slots: dict, dates: set | None) -> str:
    """주말 카드 — ISO 주 단위로 토·일 점검/사후분석/전략/정책 + 주간 아카이브를 한 칸에."""
    preview_path = next(
        (slots[k] for k in ("sun_strategy", "sat_review", "policy", "sun00", "sat00", "archive")
         if k in slots),
        None,
    )
    preview = _preview_of(preview_path) if preview_path else ""
    ds = sorted(dates) if dates else []
    if len(ds) >= 2:
        label = f"{ds[0]} ~ {ds[-1][8:]}"
    elif len(ds) == 1:
        label = ds[0]
    else:
        label = f"{key[0]}-W{key[1]:02d}"
    known = {k for k, _, _ in WEEKEND_SLOTS}
    chips = []
    for k, emoji, lbl in WEEKEND_SLOTS:
        if k in slots:
            cls = "present archive" if k == "archive" else "present audit" if k == "audit" else "present"
            chips.append(_chip(slots[k], emoji, lbl, cls=cls))
    # 예외적으로 분류 못한 주말 슬롯(예상 밖 시간대)도 링크는 잃지 않도록 노출
    for k, path in slots.items():
        if k not in known:
            chips.append(_chip(path, "📄", k))
    return (
        f'<li class="daily-card weekend">'
        f'<div class="daily-head"><strong>{label}</strong>'
        f'<span class="badge">주말 · {key[0]}-W{key[1]:02d}</span>'
        f'<span class="preview">{preview}</span></div>'
        f'<div class="slots">{"".join(chips)}</div>'
        f'</li>'
    )


def build_report_list(reports: list[Path]) -> str:
    """리포트 목록 — 평일 / 주말·주간 / 리서치·기타 3개 섹션으로 구분.

    평일: 날짜별 카드(00·09·12·15·18 슬롯 + 감사 + 구버전 단일 파일).
    주말: ISO 주별 카드(토·일 자정 점검·사후분석·전략·정책 + 주간 아카이브).
    리서치·기타: 백테스트·리서치 등 비정기 리포트.
    토요일 -00(주말 자정 점검) 파일이 평일 카드로 섞여 깨진 평일처럼 보이던 문제도
    실제 요일(weekday) 기준 분류로 해소한다.
    """
    if not reports:
        return "<p><em>아직 작성된 리포트가 없습니다. routine 실행 후 생성됩니다.</em></p>"

    weekday_cards: dict[str, dict] = {}
    weekend_cards: dict[tuple, dict] = {}
    weekend_dates: dict[tuple, set] = {}
    research: list[Path] = []

    for r in reports:
        stem = r.stem
        m = DAILY_REPORT_RE.match(stem)
        if m:
            date, slot = m.group(1), m.group(2) or "legacy"
            d = _parse_date(date)
            if d and d.weekday() >= 5:  # 토(5)·일(6)
                key = _iso_key(d)
                if slot in ("00", "legacy"):
                    sub = "sun00" if d.weekday() == 6 else "sat00"
                else:
                    sub = slot
                weekend_cards.setdefault(key, {})[sub] = r
                weekend_dates.setdefault(key, set()).add(date)
            else:
                weekday_cards.setdefault(date, {})[slot] = r
            continue
        m = AUDIT_RE.match(stem)
        if m:
            date = m.group(1)
            d = _parse_date(date)
            if d and d.weekday() >= 5:
                key = _iso_key(d)
                weekend_cards.setdefault(key, {})["audit"] = r
                weekend_dates.setdefault(key, set()).add(date)
            else:
                weekday_cards.setdefault(date, {})["audit"] = r
            continue
        m = WEEKEND_RE.match(stem)
        if m:
            date, suffix = m.group(1), m.group(2)
            d = _parse_date(date)
            if d:
                key = _iso_key(d)
                weekend_cards.setdefault(key, {})[WEEKEND_SUFFIX_SLOT[suffix]] = r
                weekend_dates.setdefault(key, set()).add(date)
                continue
        m = ARCHIVE_RE.match(stem)
        if m:
            key = (int(m.group(1)), int(m.group(2)))
            weekend_cards.setdefault(key, {})["archive"] = r
            continue
        research.append(r)

    # 2026-07-04 목록 구성 개편: 최근분만 펼치고 과거는 <details> 로 접는다 —
    # 리포트 200+개가 한 페이지에 전부 펼쳐져 최신 확인에 스크롤이 길어지던 문제 해소.
    def _folded(cards_html: list[str], recent_n: int, label: str) -> list[str]:
        out = ['<ul class="report-list">'] + cards_html[:recent_n] + ["</ul>"]
        older = cards_html[recent_n:]
        if older:
            out.append(f'<details class="rl-older"><summary>이전 {label} {len(older)}건 펼치기</summary>')
            out.append('<ul class="report-list">')
            out.extend(older)
            out.append("</ul></details>")
        return out

    blocks: list[str] = []
    if weekday_cards:
        blocks.append('<h3 class="rl-section">📅 평일 리포트 <span class="rl-hint">최근 7일 — 과거는 아래 접힘</span></h3>')
        cards = [_weekday_card(d, weekday_cards[d]) for d in sorted(weekday_cards, reverse=True)]
        blocks.extend(_folded(cards, 7, "평일"))
    if weekend_cards:
        blocks.append('<h3 class="rl-section">🗓️ 주말 · 주간 리포트</h3>')
        cards = [
            _weekend_card(k, weekend_cards[k], weekend_dates.get(k))
            for k in sorted(weekend_cards, reverse=True)
        ]
        blocks.extend(_folded(cards, 2, "주말·주간"))
    if research:
        blocks.append('<h3 class="rl-section">🔬 리서치 · 기타</h3>')
        cards = [
            f'<li><a href="./{r.stem}.html">{r.stem}'
            f'<span class="preview">{_preview_of(r)}</span></a></li>'
            for r in sorted(research, key=lambda p: p.stem, reverse=True)
        ]
        blocks.extend(_folded(cards, 5, "리서치"))
    return "\n".join(blocks)


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)

    report_tpl = (TEMPLATES / "report.html").read_text(encoding="utf-8")
    index_tpl = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    css = (TEMPLATES / "style.css").read_text(encoding="utf-8")
    (SITE / "style.css").write_text(css, encoding="utf-8")

    reports = sorted(REPORTS.glob("*.md")) if REPORTS.exists() else []
    for md_path in reports:
        text = md_path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", text, re.M)
        title = title_match.group(1).strip() if title_match else md_path.stem
        og_desc = extract_oneline(text)
        body = md_to_html(text)
        html = render(
            report_tpl,
            title=title,
            og_description=og_desc,
            date=md_path.stem,
            body=body,
        )
        out = SITE / (md_path.stem + ".html")
        out.write_text(html, encoding="utf-8")
        print(f"built {out.name}")

    # 인덱스
    portfolio_path = CONFIG / "portfolio.json"
    if portfolio_path.exists():
        portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    else:
        portfolio = {}
    equity = portfolio.get("equity", 0)
    cash = portfolio.get("cash", 0)
    ret = portfolio.get("cumulative_return_pct", 0)
    return_class = "pos" if ret >= 0 else "neg"
    as_of_raw = portfolio.get("as_of", "")
    try:
        portfolio_as_of = datetime.fromisoformat(as_of_raw).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        portfolio_as_of = str(as_of_raw).replace("T", " ")[:16] or "—"

    # 시세 기준시각 — market_snapshot 은 09/12/15/18시 리포트 발행(+장중 fetch_prices)마다 커밋된다.
    def _load_state(name: str) -> dict:
        path = ROOT / "state" / name
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    snapshot = _load_state("market_snapshot.json")
    exit_levels = _load_state("exit_levels.json")
    snap_as_of_raw = str(snapshot.get("as_of", ""))
    price_as_of = snap_as_of_raw.replace("T", " ")[:16] or portfolio_as_of

    index_html = render(
        index_tpl,
        price_as_of=price_as_of,
        equity=format_num(equity),
        cash=format_num(cash),
        cumulative_return=f"{ret:+.2f}",
        return_class=return_class,
        portfolio_as_of=portfolio_as_of,
        positions_html=build_positions_html(portfolio, snapshot, exit_levels),
        report_list=build_report_list(reports),
        updated_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
    )
    (SITE / "index.html").write_text(index_html, encoding="utf-8")
    print(f"built index.html ({len(reports)} reports)")


if __name__ == "__main__":
    main()
