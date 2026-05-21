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
    """'오늘의 한줄평' 라인을 og:description으로."""
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


def build_positions_html(portfolio: dict) -> str:
    positions = portfolio.get("positions", [])
    if not positions:
        return "<p><em>보유 종목 없음</em></p>"
    items = ['<ul class="positions">']
    for p in positions:
        pnl = p.get("unrealized_pnl_approx", 0)
        pnl_cls = "pos" if pnl >= 0 else "neg"
        pnl_str = f"{pnl:+,}".replace("+-", "-")
        mv = p.get("market_value_approx", 0)
        items.append(
            f'<li>'
            f'<span><span class="name">{p.get("name", "")}</span>'
            f'<span class="ticker">{p.get("ticker", "")} · {p.get("shares", 0)}주</span></span>'
            f'<span><span>{format_num(mv)}원</span> '
            f'<span class="pnl {pnl_cls}">({pnl_str})</span></span>'
            f'</li>'
        )
    items.append("</ul>")
    return "\n".join(items)


def build_report_list(reports: list[Path]) -> str:
    if not reports:
        return "<p><em>아직 작성된 리포트가 없습니다. 18:00 routine 후 생성됩니다.</em></p>"
    items = ['<ul class="report-list">']
    for r in sorted(reports, reverse=True):
        date = r.stem
        oneline = extract_oneline(r.read_text(encoding="utf-8"))
        items.append(
            f'<li><a href="./{date}.html">'
            f'{date} 리포트'
            f'<span class="preview">{oneline}</span>'
            f'</a></li>'
        )
    items.append("</ul>")
    return "\n".join(items)


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

    index_html = render(
        index_tpl,
        equity=format_num(equity),
        cash=format_num(cash),
        cumulative_return=f"{ret:+.2f}",
        return_class=return_class,
        positions_html=build_positions_html(portfolio),
        report_list=build_report_list(reports),
        updated_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
    )
    (SITE / "index.html").write_text(index_html, encoding="utf-8")
    print(f"built index.html ({len(reports)} reports)")


if __name__ == "__main__":
    main()
