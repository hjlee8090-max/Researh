#!/usr/bin/env python3
"""backtest_sector_global — 섹터값(자금 집중도)·해외뉴스 전이계수 검증 (v1.0).

입력: state/price_history.json (fetch_history v1.1 — universe 30종목 + NVDA·SOXX·TSM·S&P500)
출력: state/backtest_sector_global.json + 콘솔 요약

세 가지 연구:
  1. 오버나이트 전이계수 — 미국 심볼의 전일 수익률(미국장 마감 ≈ KST 새벽)이 다음 한국
     거래일의 종목 '초과수익'(KOSPI 대비)에 얼마나 전이되는지 회귀(β). 해외뉴스 가산점의
     channel_transmission(고객 NVDA·동종 SOXX/TSM·매크로 S&P500) 값을 실증한다.
     |미국 변동| ≥2% 의 '큰 뉴스 날'만 따로 측정 — 뉴스 가산은 큰 이벤트에 쓰이므로.
  2. 섹터값(sector_value) — '섹터에 자금이 몰리는 집중도'를 연속값 [0,1] 로 정의:
       heat = 섹터 거래대금 점유율(20d) ÷ 자기 120d 평균 점유율 → clamp((비율-0.8)/0.8)
       rs   = 섹터 중앙값 20d 초과수익 → clamp((ex20+5)/15)
       sector_value = w×heat + (1-w)×rs   (w 는 그리드 탐색)
     검증: sector_value(t) → 멤버 중앙값 forward 20/60d 초과수익 상관. 현행 v1.2 사다리
     (excess60 기반 이산 3단)와 예측력 비교.
  3. 조선 멤버 워크포워드 — 조선 4사(009540·010140·042660·329180)에 추정식 프리미엄
     (테마 2.56%·v1.1 틸트·추세게이트)을 사다리 섹터 vs 연속 섹터값으로 계산해 비교.

의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import importlib.util

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "backtest_sector_global.json"

_spec = importlib.util.spec_from_file_location("etp", Path(__file__).parent / "estimate_target_price.py")
etp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(etp)

GROUP_FALLBACK = {"005930": "ai_memory_hbm", "005380": "humanoid_robotics"}
SHIPBUILDERS = ["009540", "010140", "042660", "329180"]
THEME_CONST_SHIP = 2.56  # strength 0.8 × exposure 0.8 × 호라이즌할인(3-7y→0.2) × 20%


def load_history() -> dict:
    return json.loads((ROOT / "state" / "price_history.json").read_text(encoding="utf-8"))


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0


def corr(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 10:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in pairs) / len(pairs)
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    return round(cov / (sx * sy), 3) if sx and sy else None


def beta(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 10:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    varx = sum((x - mx) ** 2 for x in xs)
    return round(sum((x - mx) * (y - my) for x, y in pairs) / varx, 3) if varx else None


def regress(pairs: list[tuple[float, float]]) -> dict:
    """단순회귀 y = a + b·x. (beta, corr, se, t, n) 반환. 표본 10 미만이면 전부 None.

    t 통계량을 함께 내는 이유: 계수를 '0으로 둘지'를 눈대중이 아니라 유의성으로 정하기
    위해서다. |t| < 2 면 0과 구분되지 않는다고 본다.
    """
    n = len(pairs)
    if n < 10:
        return {"n": n, "beta": None, "corr": None, "se": None, "t": None}
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return {"n": n, "beta": None, "corr": None, "se": None, "t": None}
    b = sum((x - mx) * (y - my) for x, y in pairs) / sxx
    a = my - b * mx
    sse = sum((y - (a + b * x)) ** 2 for x, y in pairs)
    se = (sse / (n - 2) / sxx) ** 0.5 if n > 2 and sse > 0 else None
    return {
        "n": n, "beta": round(b, 3), "corr": corr(pairs),
        "se": round(se, 3) if se else None,
        "t": round(b / se, 2) if se else None,
    }


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ── 데이터 정렬 ───────────────────────────────────────────────────────────────
def align(history: dict):
    idx_bars = {b["date"]: b for b in history["index"]["bars"]}
    dates = sorted(idx_bars)
    tickers: dict[str, dict] = {}
    for t, v in history["tickers"].items():
        bars = {b["date"]: b for b in v["bars"]}
        tickers[t] = {
            "name": v["name"],
            "group": v.get("group") or GROUP_FALLBACK.get(t),
            "close": [float(bars[d]["close"]) if d in bars else None for d in dates],
            "high": [float(bars[d].get("high") or bars[d]["close"]) if d in bars else None for d in dates],
            "tv": [  # 거래대금(원) — close×volume
                (float(bars[d]["close"]) * float(bars[d]["volume"]))
                if d in bars and bars[d].get("volume") else None
                for d in dates
            ],
        }
    idx_close = [float(idx_bars[d]["close"]) for d in dates]
    return dates, tickers, idx_close


def excess_fwd(closes: list, idx: list, i: int, h: int) -> float | None:
    if i + h >= len(closes) or closes[i] is None or closes[i + h] is None:
        return None
    return round(pct(closes[i + h], closes[i]) - pct(idx[i + h], idx[i]), 3)


# ── 1. 오버나이트 전이계수 ────────────────────────────────────────────────────
BETA_TARGETS = ("005930", "000660", "009540", "005380")  # v1.0 대조군(계수 이력 비교용)


def _us_returns(g: dict) -> list[tuple[str, float]]:
    bars = g.get("bars") or []
    out = []
    for i in range(1, len(bars)):
        if bars[i - 1]["close"] and bars[i]["close"]:
            out.append((bars[i]["date"], pct(bars[i]["close"], bars[i - 1]["close"])))
    return out


def _next_kr_day(dates: list[str], us_d: str, cursor: int) -> tuple[int, str | None]:
    """미국 d일 종가(≈KST d+1 새벽) 이후 첫 한국 거래일."""
    while cursor < len(dates) and dates[cursor] <= us_d:
        cursor += 1
    return cursor, (dates[cursor] if cursor < len(dates) else None)


def overnight_transmission(history: dict, dates: list[str], tickers: dict, idx_close: list[float],
                           universe: tuple[str, ...] | None = None) -> dict:
    """미국 오버나이트 수익률 → 다음 한국 거래일 수익률 β.

    v1.1 (2026-08-19) — 두 가지 기준을 함께 낸다:
      beta_*        : 한국 종목의 **초과수익**(KOSPI 대비) 기준. v1.0 과 동일 정의.
      beta_total_*  : 한국 종목의 **절대수익** 기준.
    목표주가는 절대 가격(원)이라 프리미엄이 곱해지는 대상도 절대값이다. 초과수익 기준
    β 는 시장 전체 충격을 KOSPI 가 흡수하므로 정의상 0 에 가까워지는데, 그걸 근거로
    매크로 채널 전이를 0 으로 둔 것이 2026-08-19 사고의 원인이다 — 어젯밤 반도체
    급락(할인율 충격)이 목표가에 한 푼도 반영되지 않았다.
    """
    out: dict[str, Any] = {}
    targets = tuple(universe) if universe else BETA_TARGETS
    kr_ex: dict[str, dict[str, float]] = {}
    kr_tot: dict[str, dict[str, float]] = {}
    for t, v in tickers.items():
        me, mt = {}, {}
        for i in range(1, len(dates)):
            c0, c1 = v["close"][i - 1], v["close"][i]
            if c0 and c1:
                r = pct(c1, c0)
                mt[dates[i]] = r
                me[dates[i]] = r - pct(idx_close[i], idx_close[i - 1])
        kr_ex[t], kr_tot[t] = me, mt

    for sym, g in (history.get("global") or {}).items():
        us_ret = _us_returns(g)
        sym_out = {}
        for t in targets:
            if t not in kr_ex:
                continue
            ex, ex_big, tot, tot_big = [], [], [], []
            di = 0
            for us_d, r in us_ret:
                di, kr_d = _next_kr_day(dates, us_d, di)
                if kr_d is None:
                    break
                ye, yt = kr_ex[t].get(kr_d), kr_tot[t].get(kr_d)
                if ye is None or yt is None:
                    continue
                ex.append((r, ye)); tot.append((r, yt))
                if abs(r) >= 2.0:
                    ex_big.append((r, ye)); tot_big.append((r, yt))
            re_, rb = regress(ex), regress(ex_big)
            rt, rtb = regress(tot), regress(tot_big)
            sym_out[t] = {
                # v1.0 호환 필드(초과수익 기준)
                "n": re_["n"], "beta_all": re_["beta"], "corr_all": re_["corr"],
                "n_big": rb["n"], "beta_big_moves": rb["beta"], "corr_big_moves": rb["corr"],
                # v1.1 추가 — 절대수익 기준 + 유의성
                "beta_excess_big_t": rb["t"],
                "beta_total_all": rt["beta"], "corr_total_all": rt["corr"],
                "beta_total_big": rtb["beta"], "corr_total_big": rtb["corr"],
                "beta_total_big_t": rtb["t"], "beta_total_big_se": rtb["se"],
            }
        out[sym] = {"name": g.get("name"), "targets": sym_out}
    return out


def index_transmission(history: dict, dates: list[str], idx_close: list[float]) -> dict:
    """미국 오버나이트 → 다음 한국 거래일 **KOSPI 지수 자체**의 β.

    종목 절대수익 β 는 대략 '지수 β + 초과수익 β' 로 분해된다. 초과수익 기준만 보던
    기존 방식이 통째로 버린 것이 바로 이 지수 β 다 — 매크로 채널의 실체가 여기 있다.
    """
    kr_idx: dict[str, float] = {}
    for i in range(1, len(dates)):
        kr_idx[dates[i]] = pct(idx_close[i], idx_close[i - 1])
    out = {}
    for sym, g in (history.get("global") or {}).items():
        pairs, big = [], []
        di = 0
        for us_d, r in _us_returns(g):
            di, kr_d = _next_kr_day(dates, us_d, di)
            if kr_d is None:
                break
            y = kr_idx.get(kr_d)
            if y is None:
                continue
            pairs.append((r, y))
            if abs(r) >= 2.0:
                big.append((r, y))
        out[sym] = {"name": g.get("name"), "all": regress(pairs), "big_moves": regress(big)}
    return out


# ── 2. 섹터값 ────────────────────────────────────────────────────────────────
def rolling_mean(vals: list, i: int, w: int) -> float | None:
    seg = [v for v in vals[max(0, i - w + 1): i + 1] if v is not None]
    return sum(seg) / len(seg) if len(seg) >= max(3, w // 3) else None


def sector_value_series(dates, tickers, idx_close, w_heat: float):
    """그룹별 sector_value(t) 시계열 + 멤버 중앙값 forward 수익. 반환: {group: rows}"""
    groups: dict[str, list[str]] = {}
    for t, v in tickers.items():
        if v["group"]:
            groups.setdefault(v["group"], []).append(t)
    groups = {g: ms for g, ms in groups.items() if len(ms) >= 2}

    # 전 추적 종목 거래대금 20d 평균(분모)
    n = len(dates)
    tv20: dict[str, list[float | None]] = {
        t: [rolling_mean(v["tv"], i, 20) for i in range(n)] for t, v in tickers.items()
    }
    total20 = [sum(tv20[t][i] or 0.0 for t in tickers) or None for i in range(n)]

    out: dict[str, list[dict]] = {}
    for g, members in groups.items():
        share: list[float | None] = []
        for i in range(n):
            tot = total20[i]
            s = sum(tv20[t][i] or 0.0 for t in members)
            share.append(s / tot if tot else None)
        rows = []
        for i in range(150, n, 5):
            if share[i] is None:
                continue
            base = rolling_mean(share, i - 1, 120)
            if not base:
                continue
            conc_ratio = share[i] / base
            heat = clamp01((conc_ratio - 0.8) / 0.8)
            ex20 = [
                pct(tickers[t]["close"][i], tickers[t]["close"][i - 20]) - pct(idx_close[i], idx_close[i - 20])
                for t in members
                if tickers[t]["close"][i] and tickers[t]["close"][i - 20]
            ]
            if not ex20:
                continue
            rs = clamp01((statistics.median(ex20) + 5.0) / 15.0)
            sv = w_heat * heat + (1 - w_heat) * rs
            # 비교용: 현행 v1.2 사다리(멤버 중앙값 excess60 기반 8/4/0)
            ex60 = [
                pct(tickers[t]["close"][i], tickers[t]["close"][i - 60]) - pct(idx_close[i], idx_close[i - 60])
                for t in members
                if tickers[t]["close"][i] and tickers[t]["close"][i - 60]
            ]
            med60 = statistics.median(ex60) if ex60 else None
            ladder = 1.0 if (med60 or -99) >= 10 else (0.5 if (med60 or -99) >= 0 else 0.0)
            fwd = {}
            for h in (20, 60):
                f = [excess_fwd(tickers[t]["close"], idx_close, i, h) for t in members]
                f = [x for x in f if x is not None]
                fwd[h] = statistics.median(f) if f else None
            rows.append({
                "date": dates[i], "heat": round(heat, 3), "rs": round(rs, 3),
                "conc_ratio": round(conc_ratio, 3), "sector_value": round(sv, 3),
                "ladder": ladder, "fwd20": fwd[20], "fwd60": fwd[60],
            })
        out[g] = rows
    return out


# ── 3. 조선 워크포워드 (사다리 vs 연속 섹터값) ───────────────────────────────
def ship_walk_forward(dates, tickers, idx_close, sv_rows_by_group: dict) -> dict:
    sv_by_date = {r["date"]: r for r in sv_rows_by_group.get("shipbuilding_supercycle", [])}
    results = {}
    for t in SHIPBUILDERS:
        v = tickers.get(t)
        if not v:
            continue
        rows = []
        for i in range(150, len(dates) - 20, 5):
            d = dates[i]
            if d not in sv_by_date or not v["close"][i] or not v["close"][i - 60]:
                continue
            ex60 = pct(v["close"][i], v["close"][i - 60]) - pct(idx_close[i], idx_close[i - 60])
            hi52 = max(x for x in v["high"][max(0, i - 250): i + 1] if x) if any(v["high"][max(0, i - 250): i + 1]) else None
            pct52 = v["close"][i] / hi52 * 100 if hi52 else None
            gate = etp.trend_gate(ex60)
            tilt = etp.momentum_tilt(ex60, pct52)
            svr = sv_by_date[d]
            prem_ladder = THEME_CONST_SHIP * gate + 8.0 * svr["ladder"] + tilt
            prem_cont = THEME_CONST_SHIP * gate + 8.0 * svr["sector_value"] + tilt
            row = {"date": d, "prem_ladder": round(prem_ladder, 2), "prem_cont": round(prem_cont, 2)}
            for h in (20, 60):
                row[f"fwd{h}"] = excess_fwd(v["close"], idx_close, i, h)
            rows.append(row)

        def stats(key: str, h: int) -> dict:
            pairs = [(r[key], r[f"fwd{h}"]) for r in rows if r.get(f"fwd{h}") is not None]
            hit = sum(1 for x, y in pairs if x * y > 0) / len(pairs) if pairs else None
            return {"n": len(pairs), "corr": corr(pairs),
                    "hit": round(hit, 3) if hit is not None else None,
                    "mean_pred": round(statistics.mean([p[0] for p in pairs]), 2) if pairs else None,
                    "mean_fwd": round(statistics.mean([p[1] for p in pairs]), 2) if pairs else None}

        results[t] = {
            "name": v["name"],
            "ladder": {f"{h}d": stats("prem_ladder", h) for h in (20, 60)},
            "continuous": {f"{h}d": stats("prem_cont", h) for h in (20, 60)},
        }
    return results


def estimate_universe(tickers: dict) -> tuple[str, ...]:
    """estimate_target_price 와 같은 모집단(후보 ∪ 보유) 중 가격이력이 있는 종목."""
    want: list[str] = []
    for c in etp.load_json("config/candidates.json", {}).get("candidates", []):
        if isinstance(c, dict) and c.get("ticker"):
            want.append(c["ticker"])
    for pos in etp.load_json("config/portfolio.json", {}).get("positions", []):
        if isinstance(pos, dict) and pos.get("ticker") and (pos.get("shares") or 0) > 0:
            want.append(pos["ticker"])
    seen, out = set(), []
    for t in want:
        if t in tickers and t not in seen:
            seen.add(t); out.append(t)
    return tuple(out)


def main() -> int:
    history = load_history()
    dates, tickers, idx_close = align(history)
    print(f"aligned {len(dates)} KR days, {len(tickers)} tickers, global={list((history.get('global') or {}).keys())}")

    print("\n── 1-0. 지수 전이 (미국 전일 → 다음 한국 거래일 KOSPI β) ──")
    idx_trans = index_transmission(history, dates, idx_close)
    for sym, v in idx_trans.items():
        b = v["big_moves"]
        print(f"  {sym}→KOSPI: β큰뉴스(|2%|+) {b['beta']} (corr {b['corr']}, t={b['t']}, n={b['n']}) | "
              f"β전체 {v['all']['beta']} (corr {v['all']['corr']}, n={v['all']['n']})")

    print("\n── 1. 오버나이트 전이계수 (미국 전일 → 한국 당일 β) ──")
    est_universe = estimate_universe(tickers)
    trans = overnight_transmission(history, dates, tickers, idx_close, est_universe)
    for sym, v in trans.items():
        for t, st in v["targets"].items():
            nm = tickers[t]["name"]
            print(f"  {sym}→{nm}: 초과 β {st['beta_big_moves']} (t={st['beta_excess_big_t']}) | "
                  f"절대 β {st['beta_total_big']} (corr {st['corr_total_big']}, t={st['beta_total_big_t']}, n={st['n_big']})")

    print("\n── 2. 섹터값 vs 사다리 예측력 (그룹별 corr) ──")
    grid = {}
    for w in (0.3, 0.5, 0.7):
        sv = sector_value_series(dates, tickers, idx_close, w)
        per_group = {}
        for g, rows in sv.items():
            p20 = [(r["sector_value"], r["fwd20"]) for r in rows if r["fwd20"] is not None]
            p60 = [(r["sector_value"], r["fwd60"]) for r in rows if r["fwd60"] is not None]
            l20 = [(r["ladder"], r["fwd20"]) for r in rows if r["fwd20"] is not None]
            l60 = [(r["ladder"], r["fwd60"]) for r in rows if r["fwd60"] is not None]
            b20 = [((r["ladder"] + r["sector_value"]) / 2, r["fwd20"]) for r in rows if r["fwd20"] is not None]
            b60 = [((r["ladder"] + r["sector_value"]) / 2, r["fwd60"]) for r in rows if r["fwd60"] is not None]
            per_group[g] = {"n": len(rows), "sv_corr20": corr(p20), "sv_corr60": corr(p60),
                            "ladder_corr20": corr(l20), "ladder_corr60": corr(l60),
                            "blend_corr20": corr(b20), "blend_corr60": corr(b60)}
        valid = [v["sv_corr20"] for v in per_group.values() if v["sv_corr20"] is not None]
        grid[w] = {"per_group": per_group,
                   "avg_sv_corr20": round(statistics.mean(valid), 3) if valid else None}
        print(f"  w_heat={w}: 평균 sv_corr20 = {grid[w]['avg_sv_corr20']}")
    best_w = max(grid, key=lambda w: grid[w]["avg_sv_corr20"] or -9)
    print(f"  → 최적 w_heat = {best_w}")
    for g, v in grid[best_w]["per_group"].items():
        print(f"    {g}: sv {v['sv_corr20']}/{v['sv_corr60']} | 사다리 {v['ladder_corr20']}/{v['ladder_corr60']} | 블렌드 {v['blend_corr20']}/{v['blend_corr60']} (20d/60d)")
    for variant in ("sv_corr60", "ladder_corr60", "blend_corr60", "sv_corr20", "ladder_corr20", "blend_corr20"):
        vals = [v[variant] for v in grid[best_w]["per_group"].values() if v[variant] is not None]
        print(f"  전 그룹 평균 {variant}: {round(statistics.mean(vals), 3)}")

    print("\n── 3. 조선 4사 워크포워드 (사다리 vs 연속 섹터값) ──")
    sv_best = sector_value_series(dates, tickers, idx_close, best_w)
    ship = ship_walk_forward(dates, tickers, idx_close, sv_best)
    for t, v in ship.items():
        l, c = v["ladder"]["20d"], v["continuous"]["20d"]
        l6, c6 = v["ladder"]["60d"], v["continuous"]["60d"]
        print(f"  {v['name']}: 20d 사다리 corr {l['corr']}/hit {l['hit']} → 연속 {c['corr']}/{c['hit']} | "
              f"60d 사다리 {l6['corr']}/{l6['hit']} → 연속 {c6['corr']}/{c6['hit']}")

    out = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "window": {"start": dates[0], "end": dates[-1], "days": len(dates)},
        "index_transmission": idx_trans,
        "overnight_transmission": trans,
        "sector_value_grid": {str(w): {"avg_sv_corr20": grid[w]["avg_sv_corr20"],
                                       "per_group": grid[w]["per_group"]} for w in grid},
        "best_w_heat": best_w,
        "shipbuilding_walk_forward": ship,
        "sector_value_series_best": {g: rows[-12:] for g, rows in sv_best.items()},
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
