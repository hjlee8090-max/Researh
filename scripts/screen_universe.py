#!/usr/bin/env python3
"""종목 탐색(universe screening) — 후보 풀의 정체(섹터 로테이션 미추종)를 해소한다(v2.7).

config/candidates.json 이 손으로 넣은 소수 종목에 고정돼 있어, 반도체 주도장에서 조선·금융
후행주를 반복 보유하던 알파누수가 있었다. 이 스크립트는 config/universe.json(테마별 대형주
모집단)을 상대강도(KOSPI 대비 60일 초과수익)+테마로 랭킹해:
  - candidates 에 없는 주도주 → '승격 제안'(promote)
  - 현재 candidate 인데 만성 후행주 → '회전아웃 제안'(rotate_out)
을 state/universe_screen.json 에 기록한다. **candidates.json 을 자동 수정하지 않는다** —
제안만 만들고, 최종 반영은 sunday_strategy(주간) 또는 0900 미배치 분기(tradable<2)에서
routine 이 thesis·theme_exposure(근거 URL)와 함께 한다(환각 방지).

입력:
- config/universe.json — 모집단(pool) + screening_rules
- config/candidates.json — 현재 후보(중복 승격 방지)
- config/themes.json — theme.strength
- config/policy.json — entry_filters(상대강도 임계·하드플로어·구조적악재)
- state/market_snapshot.json — KOSPI ret_60d_pct(벤치마크) + 이미 수집된 종목 재사용

수집: 모집단 중 스냅샷에 없는 종목만 네이버+Yahoo 로 5일/60일 수익률을 추가 수집한다(주 1회
실행 전제). 네트워크 차단(HTTP 403) 시 해당 종목은 데이터 없음으로 표기되고 상대강도 중립
폴백 — 크래시하지 않고 graceful degrade.

출력: state/universe_screen.json (제안 + 랭킹 + 리포트 MD 섹션)
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# 같은 scripts/ 디렉터리의 수집·점수 헬퍼 재사용(DRY). 모듈 import 는 main 을 실행하지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_market_data import (  # noqa: E402
    compute_confidence,
    cumulative_return,
    fetch_naver,
    fetch_yahoo,
    five_day_return,
)
from score_candidates import relative_strength_score  # noqa: E402

MAX_WORKERS = 8


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_returns(ticker: str) -> dict[str, Any]:
    """모집단 종목 1개의 5일/60일 누적수익률·신뢰도·종가를 수집한다(스냅샷에 없을 때만 호출)."""
    naver_hist = fetch_naver(ticker)
    yahoo_hist = fetch_yahoo(f"{ticker}.KS")
    naver_last = naver_hist[-1]["close"] if naver_hist else None
    yahoo_last = yahoo_hist[-1]["close"] if yahoo_hist else None
    confidence, _gap = compute_confidence(naver_last, yahoo_last)
    primary = naver_hist or yahoo_hist
    return {
        "ret5": five_day_return(primary) if primary else None,
        "ret60": cumulative_return(primary, 60) if primary else None,
        "last_close": primary[-1]["close"] if primary else None,
        "confidence": confidence,
        "data_ok": bool(primary),
    }


def reuse_from_snapshot(ts: dict[str, Any]) -> dict[str, Any]:
    """스냅샷에 이미 있는 종목은 재수집하지 않고 그 값을 재사용한다."""
    mom = ts.get("momentum", {}) if isinstance(ts, dict) else {}
    return {
        "ret5": ts.get("five_day_cumulative_return_pct"),
        "ret60": mom.get("ret_60d_pct"),
        "last_close": ts.get("last_close"),
        "confidence": ts.get("confidence"),
        "data_ok": ts.get("last_close") is not None,
    }


def main() -> int:
    universe = load_json("config/universe.json", {"pool": []})
    candidates = load_json("config/candidates.json", {"candidates": []})
    themes_cfg = load_json("config/themes.json", {"themes": []})
    policy = load_json("config/policy.json", {})
    snapshot = load_json("state/market_snapshot.json", {"tickers": {}})

    theme_strength: dict[str, float] = {
        t.get("id"): float(t.get("strength", 0.0))
        for t in themes_cfg.get("themes", [])
        if isinstance(t, dict) and t.get("id")
    }
    cand_tickers = {
        c.get("ticker") for c in candidates.get("candidates", []) if isinstance(c, dict)
    }
    ef_cfg = policy.get("entry_filters", {}) if isinstance(policy.get("entry_filters"), dict) else {}
    rsw = ef_cfg.get("relative_strength_leader_widening", {}) if isinstance(ef_cfg.get("relative_strength_leader_widening"), dict) else {}
    excess_min = float(rsw.get("excess_min_pct", 10.0))
    hard_floor = float(ef_cfg.get("entry_filter_hard_floor_pct", -22.0))
    bear_keywords = ef_cfg.get("structural_bear_keywords", []) or []

    rules = universe.get("screening_rules", {}) if isinstance(universe.get("screening_rules"), dict) else {}
    blend = rules.get("rank_blend", {"relative_strength": 0.6, "thematic": 0.4})
    w_rs = float(blend.get("relative_strength", 0.6))
    w_th = float(blend.get("thematic", 0.4))
    rotate_excess = float(rules.get("rotate_out_excess_pct", -25.0))
    promote_max = int(rules.get("promote_max_per_run", 4))
    exclude_bear = bool(rules.get("exclude_structural_bear", True))

    regime = snapshot.get("regime", {}) if isinstance(snapshot, dict) else {}
    kospi_ret60 = regime.get("ret_60d_pct") if isinstance(regime, dict) else None
    snap_tickers = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}

    pool = [p for p in universe.get("pool", []) if isinstance(p, dict) and p.get("ticker")]

    # 스냅샷에 없는 종목만 네트워크 수집(스레드풀). 있는 종목은 스냅샷 값 재사용.
    to_fetch = [p["ticker"] for p in pool if p["ticker"] not in snap_tickers]
    fetched: dict[str, dict[str, Any]] = {}
    if to_fetch:
        workers = min(len(to_fetch), MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool_ex:
            futs = {tk: pool_ex.submit(fetch_returns, tk) for tk in to_fetch}
            fetched = {tk: f.result() for tk, f in futs.items()}

    ranked: list[dict[str, Any]] = []
    for p in pool:
        tk = p["ticker"]
        data = reuse_from_snapshot(snap_tickers[tk]) if tk in snap_tickers else fetched.get(tk, {})
        ret60 = data.get("ret60")
        ret5 = data.get("ret5")
        rs_score, excess = relative_strength_score(ret60, kospi_ret60)
        theme = p.get("theme")
        exposure = float(p.get("exposure", 0.0) or 0.0)
        strength = theme_strength.get(theme, 0.0) if theme else 0.0
        thematic = round(min(1.0, strength * exposure), 3)
        screen_score = round(w_rs * rs_score + w_th * thematic, 3)
        ranked.append({
            "ticker": tk,
            "name": p.get("name", ""),
            "sector": p.get("sector"),
            "theme": theme,
            "ret5": ret5,
            "ret60": ret60,
            "excess_vs_kospi_pct": excess,
            "rs_score": rs_score,
            "thematic": thematic,
            "screen_score": screen_score,
            "confidence": data.get("confidence"),
            "data_ok": bool(data.get("data_ok")),
            "in_candidates": tk in cand_tickers,
        })

    ranked.sort(key=lambda r: r["screen_score"], reverse=True)

    # 승격 제안: candidates 에 없고 + 상대강도 상위(excess ≥ excess_min) + 5일 추세가
    # 하드플로어 위(자유낙하 아님) + 데이터 유효. 구조적악재 키워드는 이름만으로 못 거르므로
    # routine 이 승격 시 web_verify·bear_case 로 최종 판단(여기선 데이터 기반 1차 제안).
    promote: list[dict[str, Any]] = []
    for r in ranked:
        if r["in_candidates"] or not r["data_ok"]:
            continue
        if r["excess_vs_kospi_pct"] is None or r["excess_vs_kospi_pct"] < excess_min:
            continue
        if r["ret5"] is not None and r["ret5"] < hard_floor:
            continue
        promote.append(r)
        if len(promote) >= promote_max:
            break

    # 회전아웃 제안: 현재 candidate 인데 상대강도 최하위 밴드(만성 후행주).
    rotate_out = [
        r for r in ranked
        if r["in_candidates"]
        and r["excess_vs_kospi_pct"] is not None
        and r["excess_vs_kospi_pct"] <= rotate_excess
    ]

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of") if isinstance(snapshot, dict) else None,
        "kospi_ret60_pct": kospi_ret60,
        "regime_tier": regime.get("tier") if isinstance(regime, dict) else None,
        "pool_size": len(pool),
        "fetched_count": len(to_fetch),
        "rank_blend": {"relative_strength": w_rs, "thematic": w_th},
        "ranked": ranked,
        "promote_suggestions": promote,
        "rotate_out_suggestions": rotate_out,
        "report_section_md": _report_md(ranked, promote, rotate_out, kospi_ret60, regime),
        "note": "제안만 — candidates.json 자동수정 안 함. routine 이 thesis·theme_exposure(근거 URL)와 함께 반영.",
    }
    out_path = ROOT / "state" / "universe_screen.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {out_path.relative_to(ROOT)} pool={len(pool)} fetched={len(to_fetch)} "
        f"promote={len(promote)} rotate_out={len(rotate_out)} "
        f"kospi_ret60={kospi_ret60}"
    )
    return 0


def _report_md(
    ranked: list[dict],
    promote: list[dict],
    rotate_out: list[dict],
    kospi_ret60: float | None,
    regime: dict,
) -> str:
    lines = ["### 종목 탐색(universe screening)", ""]
    tier = regime.get("tier") if isinstance(regime, dict) else None
    lines.append(f"- 벤치마크: KOSPI 60일 {kospi_ret60}% / tier {tier}")
    lines.append("")
    if promote:
        lines.append("**승격 제안 (candidates 에 추가 검토 — 주도주·상대강도 상위):**")
        for r in promote:
            ex = r["excess_vs_kospi_pct"]
            lines.append(
                f"- {r['name']}({r['ticker']}) · {r['sector']} — 초과수익 {ex:+.1f}%p, "
                f"5일 {r['ret5']}%, score {r['screen_score']}"
            )
    else:
        lines.append("**승격 제안: 없음** (상대강도 상위 신규 주도주 미발견 — 데이터 차단 시 다음 주 재시도)")
    if rotate_out:
        lines.append("")
        lines.append("**회전아웃 제안 (만성 후행주 — candidates 에서 강등 검토):**")
        for r in rotate_out:
            lines.append(
                f"- {r['name']}({r['ticker']}) — 초과수익 {r['excess_vs_kospi_pct']:+.1f}%p (KOSPI 대비 후행)"
            )
    lines.append("")
    lines.append("> 상위 10 (screen_score):")
    for r in ranked[:10]:
        mark = "✓후보" if r["in_candidates"] else "  "
        ex = r["excess_vs_kospi_pct"]
        ex_s = f"{ex:+.1f}%p" if ex is not None else "n/a"
        lines.append(f"> {mark} {r['name']}({r['ticker']}) score {r['screen_score']} · 초과 {ex_s}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
