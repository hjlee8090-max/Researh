#!/usr/bin/env python3
"""종목 탐색 + 범용 섹터 로테이션 재진입 엔진(v2.7 탐색 → v2.8 섹터 로테이션).

두 가지를 한 번에 산출한다(둘 다 config 로 정의된 모든 섹터/테마에 범용 작동 — 하드코딩 없음):

1) 종목 탐색(universe screening, v2.7): config/universe.json(테마별 대형주 모집단)을
   상대강도+테마로 랭킹해 candidates 에 없는 주도주 '승격 제안'/만성 후행주 '회전아웃 제안'.

2) 섹터 로테이션 재진입(v2.8): 침체·avoid 섹터를 '5일 가격 반등'이 아니라 '호재(촉매)+시장
   몰입(자금이 실제로 도는 발자국)'으로 푼다. 이 스크립트는 '몰입'의 quant 발자국
   (rs_inflection 20일 상대강도 반등·volume_surge 거래량 급증·sector_breadth 동조·theme_heat)을
   섹터/테마 그룹별로 산출한다. **촉매(방아쇠)는 routine 이 출처 URL 로 채우고**, 이 엔진은
   **몰입 증거(안전핀)만** 계산한다(스토리≠자금 — 조선은 LNG 슈퍼사이클 스토리 내내 갖고도 3회 손실).
   출력: state/universe_screen.json.sector_rotation(전 섹터)·avoid_reentry(avoid 항목별).

입력: config/{universe,candidates,themes,policy,watchlist}.json, state/market_snapshot.json
수집: 모집단 중 스냅샷에 없는 종목만 네이버+Yahoo 로 5/20/60일 수익률·거래량 추가 수집(주 1회
전제). 차단 시 graceful degrade(데이터 없음 → 상대강도/몰입 중립).
출력: state/universe_screen.json (제안 + 랭킹 + 섹터 로테이션 + avoid 재진입 + 리포트 MD)
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
    volume_ratio,
)
from score_candidates import relative_strength_score  # noqa: E402

MAX_WORKERS = 8


def load_json(rel: str, default: Any = None) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def _median(xs: list[Any]) -> float | None:
    vals = sorted(x for x in xs if isinstance(x, (int, float)))
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def fetch_returns(ticker: str) -> dict[str, Any]:
    """모집단 종목 1개의 5/20/60일 수익률·거래량비·신뢰도·종가 수집(스냅샷에 없을 때만)."""
    naver_hist = fetch_naver(ticker)
    yahoo_hist = fetch_yahoo(f"{ticker}.KS")
    naver_last = naver_hist[-1]["close"] if naver_hist else None
    yahoo_last = yahoo_hist[-1]["close"] if yahoo_hist else None
    confidence, _gap = compute_confidence(naver_last, yahoo_last)
    primary = naver_hist or yahoo_hist
    return {
        "ret5": five_day_return(primary) if primary else None,
        "ret20": cumulative_return(primary, 20) if primary else None,
        "ret60": cumulative_return(primary, 60) if primary else None,
        "vol_ratio": volume_ratio(primary, 20) if primary else None,
        "last_close": primary[-1]["close"] if primary else None,
        "confidence": confidence,
        "data_ok": bool(primary),
    }


def reuse_from_snapshot(ts: dict[str, Any]) -> dict[str, Any]:
    """스냅샷에 이미 있는 종목은 재수집하지 않고 그 값을 재사용한다."""
    mom = ts.get("momentum", {}) if isinstance(ts, dict) else {}
    liq = ts.get("liquidity", {}) if isinstance(ts, dict) else {}
    return {
        "ret5": ts.get("five_day_cumulative_return_pct"),
        "ret20": mom.get("ret_20d_pct"),
        "ret60": mom.get("ret_60d_pct"),
        "vol_ratio": liq.get("vol_ratio_20d"),
        "last_close": ts.get("last_close"),
        "confidence": ts.get("confidence"),
        "data_ok": ts.get("last_close") is not None,
    }


def compute_immersion(
    members: list[dict[str, Any]],
    theme_strength: float | None,
    icfg: dict[str, Any],
    min_signals: int,
) -> dict[str, Any]:
    """섹터/테마 그룹의 '몰입(자금 유입)' quant 발자국을 계산한다(v2.8).

    섹터 단위 외국인/기관 수급을 직접 못 구하므로 상대강도·거래량·동조로 대체측정한다.
    members: 그룹 구성종목의 per-ticker dict(excess_60d·excess_20d·vol_ratio·ret5·data_ok).
    반환: {signals(bool dict), met(int), immersion_met(bool), members_with_data}.
    """
    valid = [m for m in members if m.get("data_ok")]
    rs_min = float(icfg.get("rs_inflection_min_pct", -10.0))
    vol_x = float(icfg.get("volume_surge_x", 1.5))
    breadth_min = int(icfg.get("breadth_min_members", 2))
    heat_min = float(icfg.get("theme_heat_min", 0.75))

    ex60 = [m.get("excess_60d") for m in valid]
    ex20 = [m.get("excess_20d") for m in valid]
    med20, med60 = _median(ex20), _median(ex60)
    rs_inflection = (
        med20 is not None and med60 is not None and med20 > med60 and med20 >= rs_min
    )
    vs_count = sum(
        1 for m in valid if isinstance(m.get("vol_ratio"), (int, float)) and m["vol_ratio"] >= vol_x
    )
    volume_surge = bool(valid) and vs_count >= max(1, len(valid) // 2)
    br_count = sum(
        1
        for m in valid
        if (isinstance(m.get("excess_20d"), (int, float)) and m["excess_20d"] > 0)
        or (isinstance(m.get("ret5"), (int, float)) and m["ret5"] > 0)
    )
    sector_breadth = br_count >= breadth_min
    theme_heat = isinstance(theme_strength, (int, float)) and theme_strength >= heat_min

    # 집계 대상 = '자금이 실제로 도는' 3개 발자국. theme_heat 는 구조적 강도(context)라 집계 제외.
    signals = {
        "rs_inflection": rs_inflection,
        "volume_surge": volume_surge,
        "sector_breadth": sector_breadth,
    }
    context = {"theme_heat": theme_heat}
    met = sum(1 for v in signals.values() if v)
    return {
        "signals": signals,
        "context": context,
        "met": met,
        "min_signals": min_signals,
        "immersion_met": met >= min_signals,
        "members_with_data": len(valid),
        "median_excess_20d": med20,
        "median_excess_60d": med60,
    }


def main() -> int:
    universe = load_json("config/universe.json", {"pool": []})
    candidates = load_json("config/candidates.json", {"candidates": []})
    themes_cfg = load_json("config/themes.json", {"themes": []})
    policy = load_json("config/policy.json", {})
    snapshot = load_json("state/market_snapshot.json", {"tickers": {}})
    watchlist = load_json("config/watchlist.json", {})

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

    # v2.8 — 섹터 로테이션 재진입 설정(몰입 신호 임계·민감도).
    srr = policy.get("sector_rotation_reentry", {}) if isinstance(policy.get("sector_rotation_reentry"), dict) else {}
    icfg = srr.get("immersion_confirmation", {}) if isinstance(srr.get("immersion_confirmation"), dict) else {}
    sensitivity = srr.get("sensitivity", "medium")
    min_sig_map = icfg.get("min_signals_by_sensitivity", {"aggressive": 1, "medium": 2, "conservative": 3})
    min_signals = int(min_sig_map.get(sensitivity, 2))

    rules = universe.get("screening_rules", {}) if isinstance(universe.get("screening_rules"), dict) else {}
    blend = rules.get("rank_blend", {"relative_strength": 0.6, "thematic": 0.4})
    w_rs = float(blend.get("relative_strength", 0.6))
    w_th = float(blend.get("thematic", 0.4))
    rotate_excess = float(rules.get("rotate_out_excess_pct", -25.0))
    promote_max = int(rules.get("promote_max_per_run", 4))

    regime = snapshot.get("regime", {}) if isinstance(snapshot, dict) else {}
    kospi_ret60 = regime.get("ret_60d_pct") if isinstance(regime, dict) else None
    kospi_ret20 = regime.get("ret_20d_pct") if isinstance(regime, dict) else None
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
    by_ticker: dict[str, dict[str, Any]] = {}
    for p in pool:
        tk = p["ticker"]
        data = reuse_from_snapshot(snap_tickers[tk]) if tk in snap_tickers else fetched.get(tk, {})
        ret60 = data.get("ret60")
        ret20 = data.get("ret20")
        ret5 = data.get("ret5")
        vol_ratio = data.get("vol_ratio")
        rs_score, excess60 = relative_strength_score(ret60, kospi_ret60)
        excess20 = round(ret20 - kospi_ret20, 2) if isinstance(ret20, (int, float)) and isinstance(kospi_ret20, (int, float)) else None
        theme = p.get("theme")
        exposure = float(p.get("exposure", 0.0) or 0.0)
        strength = theme_strength.get(theme, 0.0) if theme else 0.0
        thematic = round(min(1.0, strength * exposure), 3)
        screen_score = round(w_rs * rs_score + w_th * thematic, 3)
        entry = {
            "ticker": tk,
            "name": p.get("name", ""),
            "sector": p.get("sector"),
            "theme": theme,
            "ret5": ret5,
            "ret20": ret20,
            "ret60": ret60,
            "excess_60d": excess60,
            "excess_20d": excess20,
            "excess_vs_kospi_pct": excess60,
            "vol_ratio": vol_ratio,
            "rs_score": rs_score,
            "thematic": thematic,
            "screen_score": screen_score,
            "confidence": data.get("confidence"),
            "data_ok": bool(data.get("data_ok")),
            "in_candidates": tk in cand_tickers,
        }
        ranked.append(entry)
        by_ticker[tk] = entry

    ranked.sort(key=lambda r: r["screen_score"], reverse=True)

    # --- v2.7 종목 탐색: 승격/회전아웃 제안 ---
    promote: list[dict[str, Any]] = []
    for r in ranked:
        if r["in_candidates"] or not r["data_ok"]:
            continue
        if r["excess_60d"] is None or r["excess_60d"] < excess_min:
            continue
        if r["ret5"] is not None and r["ret5"] < hard_floor:
            continue
        promote.append(r)
        if len(promote) >= promote_max:
            break
    rotate_out = [
        r for r in ranked
        if r["in_candidates"] and r["excess_60d"] is not None and r["excess_60d"] <= rotate_excess
    ]

    # --- v2.8 섹터 로테이션: theme(없으면 sector)로 그룹핑해 '몰입' 신호 산출(전 섹터 범용) ---
    groups: dict[str, dict[str, Any]] = {}
    for r in ranked:
        key = r["theme"] or f"sector:{r['sector']}"
        g = groups.setdefault(key, {"key": key, "theme": r["theme"], "members": [], "sectors": set()})
        g["members"].append(r)
        if r.get("sector"):
            g["sectors"].add(r["sector"])
    sector_rotation: list[dict[str, Any]] = []
    for key, g in groups.items():
        strength = theme_strength.get(g["theme"]) if g["theme"] else None
        imm = compute_immersion(g["members"], strength, icfg, min_signals)
        sector_rotation.append({
            "group": key,
            "theme": g["theme"],
            "theme_strength": strength,
            "sectors": sorted(g["sectors"]),
            "tickers": [m["ticker"] for m in g["members"]],
            **imm,
        })
    sector_rotation.sort(key=lambda s: (s["immersion_met"], s["met"], s.get("median_excess_20d") or -999), reverse=True)

    # --- v2.8 avoid 재진입: watchlist.avoid_sectors 의 모든 항목에 동일 적용(범용) ---
    avoid_reentry: list[dict[str, Any]] = []
    for av in watchlist.get("avoid_sectors", []) if isinstance(watchlist.get("avoid_sectors"), list) else []:
        if not isinstance(av, dict):
            continue
        av_tickers = av.get("tickers", []) or []
        members = [by_ticker[t] for t in av_tickers if t in by_ticker]
        # 그룹의 테마 강도(첫 구성종목 기준)
        strength = None
        for m in members:
            if m.get("theme"):
                strength = theme_strength.get(m["theme"])
                break
        imm = compute_immersion(members, strength, icfg, min_signals)
        avoid_reentry.append({
            "sector": av.get("sector"),
            "tickers": av_tickers,
            "effective_from": av.get("effective_from"),
            **imm,
            "catalyst": "routine 확인 필요(출처 URL+게재일 — sector_rotation_reentry.catalyst_trigger)",
            "verdict": (
                "몰입 충족 — 촉매 web_verify 후 avoid 해제·probe 진입 검토"
                if imm["immersion_met"]
                else "avoid 유지(몰입 미충족 — 자금 유입 발자국 부족)"
            ),
        })

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "snapshot_as_of": snapshot.get("as_of") if isinstance(snapshot, dict) else None,
        "kospi_ret60_pct": kospi_ret60,
        "kospi_ret20_pct": kospi_ret20,
        "regime_tier": regime.get("tier") if isinstance(regime, dict) else None,
        "pool_size": len(pool),
        "fetched_count": len(to_fetch),
        "sensitivity": sensitivity,
        "immersion_min_signals": min_signals,
        "rank_blend": {"relative_strength": w_rs, "thematic": w_th},
        "ranked": ranked,
        "promote_suggestions": promote,
        "rotate_out_suggestions": rotate_out,
        "sector_rotation": sector_rotation,
        "avoid_reentry": avoid_reentry,
        "report_section_md": _report_md(ranked, promote, rotate_out, sector_rotation, avoid_reentry, kospi_ret60, regime, min_signals),
        "note": "촉매(방아쇠)는 routine 이 출처 URL 로 채우고 이 엔진은 몰입 증거(안전핀)만 산출. candidates/avoid 자동수정 안 함 — 제안만.",
    }
    out_path = ROOT / "state" / "universe_screen.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    n_heating = sum(1 for s in sector_rotation if s["immersion_met"])
    n_avoid_ready = sum(1 for a in avoid_reentry if a["immersion_met"])
    print(
        f"wrote {out_path.relative_to(ROOT)} pool={len(pool)} fetched={len(to_fetch)} "
        f"promote={len(promote)} rotate_out={len(rotate_out)} "
        f"heating_sectors={n_heating} avoid_reentry_ready={n_avoid_ready} "
        f"sensitivity={sensitivity}(min={min_signals})"
    )
    return 0


def _report_md(
    ranked: list[dict],
    promote: list[dict],
    rotate_out: list[dict],
    sector_rotation: list[dict],
    avoid_reentry: list[dict],
    kospi_ret60: float | None,
    regime: dict,
    min_signals: int,
) -> str:
    lines = ["### 종목 탐색 + 섹터 로테이션", ""]
    tier = regime.get("tier") if isinstance(regime, dict) else None
    lines.append(f"- 벤치마크: KOSPI 60일 {kospi_ret60}% / tier {tier} / 몰입 신호 {min_signals}개 요구")
    lines.append("")
    if promote:
        lines.append("**승격 제안 (주도주·상대강도 상위):**")
        for r in promote:
            lines.append(f"- {r['name']}({r['ticker']}) · {r['sector']} — 초과수익 {r['excess_60d']:+.1f}%p, 5일 {r['ret5']}%")
    else:
        lines.append("**승격 제안: 없음** (상대강도 상위 신규 주도주 미발견 — 데이터 차단 시 다음 주 재시도)")
    if rotate_out:
        lines.append("")
        lines.append("**회전아웃 제안 (만성 후행주):**")
        for r in rotate_out:
            lines.append(f"- {r['name']}({r['ticker']}) — 초과수익 {r['excess_60d']:+.1f}%p (KOSPI 대비 후행)")
    lines.append("")
    lines.append("**🔥 섹터 로테이션 — 몰입 신호 (호재는 routine 이 별도 web_verify):**")
    heating = [s for s in sector_rotation if s["immersion_met"]]
    if heating:
        for s in heating:
            on = [k for k, v in s["signals"].items() if v]
            lines.append(f"- 🔥 {s['group']} (테마강도 {s['theme_strength']}) — 몰입 {s['met']}/{min_signals} ✓ [{', '.join(on)}]")
    else:
        lines.append("- 현재 몰입 충족 섹터 없음 (자금 유입 발자국 부족 — 정상)")
    if avoid_reentry:
        lines.append("")
        lines.append("**🚫→ avoid 재진입 점검:**")
        for a in avoid_reentry:
            mark = "✅ 검토" if a["immersion_met"] else "유지"
            lines.append(f"- [{mark}] {a['sector']} — 몰입 {a['met']}/{min_signals} · {a['verdict']}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
