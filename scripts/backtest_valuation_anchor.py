#!/usr/bin/env python3
"""backtest_valuation_anchor — 기준가(anchor)의 밸류밴드 성분 검증 (v1.0).

estimate_target_price 의 기준가는 5년 멀티플 밴드 **중앙값**으로 적정가를 잡는다:
    적정가 = base(BPS 또는 선행EPS) × (밴드하단 + 밴드상단) / 2
    기준가 = mean(적정가, 컨센서스, 현재가)   ← 컨센 결측 시 (적정가 + 현재가)/2
그래서 밴드가 넓을수록 '중앙값으로 회귀한다'는 주장이 커지고, 상승여력이 커진다.
2026-08-19 진단: 카카오 +52% 중 49%p, HD현대일렉 +51% 중 45%p 가 이 성분이었다.
LS ELECTRIC 의 PER 밴드는 24.2~72.2(3.0배 폭)로 중앙값이 사실상 임의값이다.

이 스크립트가 답하는 것 — **밴드가 주장하는 상승여력이 실제로 실현되는가.**
  1. 패널 회귀(종목 고정효과) — 종목 내에서 demean 한 '밴드 상승여력'으로 forward
     초과수익을 회귀한다. β 가 1 이면 주장한 만큼 실현, 0.1 이면 10배 과대주장.
     종목 내 demean 이라 base 스냅샷 오차(과거 시점의 BPS/EPS 는 지금과 다르다)가
     상수항으로 빠져 기울기에 거의 영향을 주지 않는다.
  2. 밴드 폭(상단/하단 비율)별 층화 — 넓은 밴드에서 예측력이 더 나쁜지.
  3. 앵커 후보 비교 — 중앙값 / 하단 / (하단+중앙)/2 / 폭 캡 적용.

한계: 밴드·base 는 현재 스냅샷 1개뿐이라 과거 시점의 실제 밴드를 복원할 수 없다.
종목 내 시간변동(=가격 변동)에 대한 검정이며, 종목 간 수준 비교는 하지 않는다.

의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import importlib.util
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "backtest_valuation_anchor.json"

_spec = importlib.util.spec_from_file_location("bt", Path(__file__).parent / "backtest_sector_global.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)

HORIZONS = (60, 120, 250)


def band_of(cfg: dict) -> tuple[float, float, float] | None:
    """(base, 밴드하단, 밴드상단). anchor_price 와 같은 품질 화이트리스트를 적용한다."""
    q = cfg.get("band_quality")
    if q not in (None, "verified", "dart_quarterly") or "근사" in (cfg.get("method") or ""):
        return None
    metric = (cfg.get("preferred_metric") or "PBR").upper()
    base = cfg.get("eps_fwd") if metric == "PER" else cfg.get("bps")
    band = cfg.get("per_band_5y") if metric == "PER" else cfg.get("pbr_band_5y")
    if not base or not isinstance(band, list) or len(band) != 2 or not all(band):
        return None
    return float(base), float(band[0]), float(band[1])


def panel(rows: list[tuple[str, float, float]]) -> dict:
    """종목 고정효과 패널 회귀 — 종목 내 demean 후 단순회귀."""
    by_t: dict[str, list[tuple[float, float]]] = {}
    for t, x, y in rows:
        by_t.setdefault(t, []).append((x, y))
    pairs = []
    for t, ps in by_t.items():
        if len(ps) < 20:
            continue
        mx = statistics.mean(p[0] for p in ps)
        my = statistics.mean(p[1] for p in ps)
        pairs += [(p[0] - mx, p[1] - my) for p in ps]
    r = bt.regress(pairs)
    r["tickers"] = len(by_t)
    return r


def main() -> int:
    hist = bt.load_history()
    dates, tickers, idx = bt.align(hist)
    val = json.loads((ROOT / "config" / "valuation.json").read_text(encoding="utf-8"))["tickers"]

    specs = {}
    for t, cfg in val.items():
        b = band_of(cfg)
        if b and t in tickers:
            specs[t] = {"name": cfg.get("name") or tickers[t]["name"], "base": b[0], "lo": b[1], "hi": b[2],
                        "width": round(b[2] / b[1], 2), "metric": (cfg.get("preferred_metric") or "PBR").upper()}
    print(f"밴드 사용 가능 종목 {len(specs)} / valuation 등록 {len(val)}")

    # 앵커 후보별 적정가 배수
    VARIANTS = {
        "mid": lambda lo, hi: (lo + hi) / 2,
        "low": lambda lo, hi: lo,
        "low_mid": lambda lo, hi: (lo + (lo + hi) / 2) / 2,
        "q25": lambda lo, hi: lo + 0.25 * (hi - lo),
        "width_cap_2.5": lambda lo, hi: (lo + min(hi, lo * 2.5)) / 2,
        "width_cap_2.0": lambda lo, hi: (lo + min(hi, lo * 2.0)) / 2,
        "width_cap_1.5": lambda lo, hi: (lo + min(hi, lo * 1.5)) / 2,
        # 폭 적응형 — 좁은 밴드는 중앙값이 실증적으로 버티고(D+250 β 0.87),
        # 넓은 밴드에서만 하단으로 당긴다.
        "adaptive_2.5": lambda lo, hi: (lo + hi) / 2 if hi / lo <= 2.5 else lo,
        "adaptive_3.0": lambda lo, hi: (lo + hi) / 2 if hi / lo <= 3.0 else lo,
        "adaptive_cap2.5": lambda lo, hi: (lo + hi) / 2 if hi / lo <= 2.5 else (lo + lo * 2.5) / 2,
    }

    out = {"as_of": datetime.now(KST).isoformat(timespec="seconds"),
           "window": {"start": dates[0], "end": dates[-1], "days": len(dates)},
           "tickers": specs, "panel": {}, "by_width": {}, "variants": {}}

    def evaluate_beta(fn, h: int) -> float | None:
        rows = []
        for t, sp in specs.items():
            fair = sp["base"] * fn(sp["lo"], sp["hi"])
            cl = tickers[t]["close"]
            for i in range(len(dates)):
                if cl[i] is None:
                    continue
                fx = bt.excess_fwd(cl, idx, i, h)
                if fx is not None:
                    rows.append((t, (fair / cl[i] - 1.0) * 100.0, fx))
        return panel(rows)["beta"]

    # ── 1. 밴드 상승여력 → forward 초과수익 (중앙값 앵커) ──────────────────────
    print("\n── 1. 밴드 상승여력이 실현되는가 (중앙값 앵커, 종목 고정효과 패널) ──")
    print(f"{'호라이즌':<10}{'β':>8}{'corr':>8}{'t':>8}{'n':>8}{'종목':>6}   해석")
    for h in HORIZONS:
        rows = []
        for t, sp in specs.items():
            fair = sp["base"] * VARIANTS["mid"](sp["lo"], sp["hi"])
            cl = tickers[t]["close"]
            for i in range(len(dates)):
                if cl[i] is None:
                    continue
                fx = bt.excess_fwd(cl, idx, i, h)
                if fx is None:
                    continue
                rows.append((t, (fair / cl[i] - 1.0) * 100.0, fx))
        r = panel(rows)
        out["panel"][str(h)] = r
        b = r["beta"]
        tag = "—" if b is None else ("주장만큼 실현" if b >= 0.8 else
              f"{1/b:.0f}배 과대주장" if b >= 0.05 else "예측력 없음" if b > -0.05 else "역방향")
        print(f"D+{h:<8}{(b if b is not None else float('nan')):>8.3f}{(r['corr'] or float('nan')):>8.3f}"
              f"{(r['t'] or float('nan')):>8.2f}{r['n']:>8}{r['tickers']:>6}   {tag}")

    # ── 2. 밴드 폭 층화 ────────────────────────────────────────────────────────
    widths = sorted(sp["width"] for sp in specs.values())
    cut = widths[len(widths) // 2]
    print(f"\n── 2. 밴드 폭 층화 (중위 {cut}배 기준) ──")
    print(f"{'구간':<16}{'종목':>5}{'D+60 β':>10}{'D+120 β':>10}{'D+250 β':>10}{'평균폭':>8}")
    for label, pick in (("좁은 밴드", lambda w: w <= cut), ("넓은 밴드", lambda w: w > cut)):
        sel = {t: sp for t, sp in specs.items() if pick(sp["width"])}
        row = {}
        for h in HORIZONS:
            rows = []
            for t, sp in sel.items():
                fair = sp["base"] * VARIANTS["mid"](sp["lo"], sp["hi"])
                cl = tickers[t]["close"]
                for i in range(len(dates)):
                    if cl[i] is None:
                        continue
                    fx = bt.excess_fwd(cl, idx, i, h)
                    if fx is not None:
                        rows.append((t, (fair / cl[i] - 1.0) * 100.0, fx))
            row[str(h)] = panel(rows)
        out["by_width"][label] = row
        aw = round(statistics.mean(sp["width"] for sp in sel.values()), 2)
        vals = [row[str(h)]["beta"] for h in HORIZONS]
        print(f"{label:<15}{len(sel):>5}" + "".join(f"{(v if v is not None else float('nan')):>10.3f}" for v in vals) + f"{aw:>8.2f}")

    # ── 3. 앵커 후보 비교 ──────────────────────────────────────────────────────
    print("\n── 3. 앵커 후보별 예측력·주장 크기 ──")
    print(f"{'후보':<16}{'D+120 β':>10}{'corr':>8}{'평균 주장 상승여력':>18}")
    for name, fn in VARIANTS.items():
        rows, claims = [], []
        for t, sp in specs.items():
            fair = sp["base"] * fn(sp["lo"], sp["hi"])
            cl = tickers[t]["close"]
            for i in range(len(dates)):
                if cl[i] is None:
                    continue
                up = (fair / cl[i] - 1.0) * 100.0
                fx = bt.excess_fwd(cl, idx, i, 120)
                if fx is not None:
                    rows.append((t, up, fx)); claims.append(up)
        r = panel(rows)
        out["variants"][name] = {**r, "mean_claim_pct": round(statistics.mean(claims), 1) if claims else None}
        print(f"{name:<16}{(r['beta'] if r['beta'] is not None else float('nan')):>10.3f}"
              f"{(r['corr'] or float('nan')):>8.3f}{statistics.mean(claims):>18.1f}%")

    # ── 4. 수준(level) 검증 + 캡 민감도 ───────────────────────────────────────
    # 패널 회귀는 종목 내 demean 이라 수준 오차를 통째로 지운다 — 기울기만 보면
    # '밴드 하단' 처럼 수준이 크게 어긋난 후보를 최적으로 고르게 된다. 별도로 잰다.
    # 과거 구간은 현재 BPS/EPS 스냅샷을 과거 가격에 대는 편향으로 비율이 체계적으로
    # 낮게 나오므로(2년 < 250일 < 오늘) '오늘' 기준을 1순위로 본다.
    def level(fn, look: int) -> float | None:
        rs = []
        for t, sp in specs.items():
            fair = sp["base"] * fn(sp["lo"], sp["hi"])
            cl = tickers[t]["close"]
            rng = range(len(dates) - 1, len(dates)) if look == 1 else range(max(0, len(dates) - look), len(dates))
            for i in rng:
                if cl[i]:
                    rs.append(cl[i] / fair)
        return round(statistics.median(rs), 3) if rs else None

    print("\n── 4. 캡 민감도 — 기울기 vs 수준 (목표 수준비율 ≈ 0.90~0.95) ──")
    print(f"{'캡':<10}{'적용종목':>8}{'β D+120':>10}{'β D+250':>10}{'수준 오늘':>10}{'수준 250일':>11}{'수준 2년':>10}")
    sens = {}
    for cap in (None, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5):
        fn = (lambda lo, hi: (lo + hi) / 2) if cap is None else (lambda lo, hi, c=cap: (lo + min(hi, lo * c)) / 2)
        n_cap = 0 if cap is None else sum(1 for sp in specs.values() if sp["width"] > cap)
        row = {"n_capped": n_cap,
               "beta_120": evaluate_beta(fn, 120), "beta_250": evaluate_beta(fn, 250),
               "level_today": level(fn, 1), "level_250d": level(fn, 250), "level_all": level(fn, 10 ** 9)}
        sens["none" if cap is None else str(cap)] = row
        lbl = "없음(현행)" if cap is None else str(cap)
        print(f"{lbl:<10}{n_cap:>8}{row['beta_120']:>10.3f}{row['beta_250']:>10.3f}"
              f"{row['level_today']:>10.2f}{row['level_250d']:>11.2f}{row['level_all']:>10.2f}")
    out["cap_sensitivity"] = sens

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
