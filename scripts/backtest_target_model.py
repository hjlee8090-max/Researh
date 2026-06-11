#!/usr/bin/env python3
"""backtest_target_model — 목표주가 추정식(estimate_target_price)의 과거 데이터 검증·보정 (v1.0).

입력: state/price_history.json (fetch_history.py — 삼성전자·현대차·KOSPI ~2.5년 일봉),
      config/news_history.json (레포 운용 기록에서 추출한 라벨드 뉴스 타임라인),
      config/news_impact.json (검증 대상 가산점 테이블)
출력: state/backtest_target_model.json + 콘솔 요약

방법론 (4단계):
  A. 무라벨 충격-감쇠 연구 — 전 구간에서 KOSPI 대비 초과수익이 max(2.5%, 2×σ60)을 넘는
     '충격일'을 찾아, 충격 후 +5/+10/+20/+60일 누적 초과수익(CAR)을 충격 크기로 나눈
     지속비율 ρ(h)을 측정한다. ρ>0 이면 드리프트(뉴스 효과 지속 — 감쇠 느리게),
     ρ<0 이면 평균회귀(점프가 과반영 — 가산점을 다시 더하면 이중계상).
  B. 라벨드 이벤트 스터디 — news_history 의 종목 스코프 이벤트별로 당일 AR·+5d/+10d CAR 을
     측정해 news_impact 테이블의 유형별 impact_pct 와 대조한다(표본 작음 — A와 교차검증).
  C. 워크포워드 검증 — 5거래일 스텝으로 각 시점 t 에서 t 까지의 정보만으로 프리미엄
     (테마+뉴스+섹터proxy+모멘텀틸트)을 계산하고, 이후 20/60일 실현 초과수익과 회귀.
     β(보정계수)·적중률·과열 구간(52주고점 근접×단기급등) 조건부 수익을 진단한다.
     ※ 섹터 활발성은 universe_screen 의 과거 이력이 없어 종목 자신의 60일 초과수익을
     proxy 로 쓴다(삼성=ai_memory_hbm 그룹 지배 구성원 — 한계는 출력에 명시).
  D. 보정 제안 — A~C 결과를 종합해 v1.1 파라미터(감쇠일수·과열 댐퍼·전역 축소계수 λ·
     모멘텀 틸트 테이블)를 산출한다. 적용은 estimate_target_price.py/news_impact.json 쪽.

의존성 0(표준 라이브러리). 학습·시뮬레이션 목적.
"""
from __future__ import annotations

import importlib.util
import json
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# v1.1 모델 함수(trend_gate·momentum_tilt)를 실제 추정 스크립트에서 임포트 — 검증 대상과
# 운영 코드가 어긋나지 않게 한다(v1.0 은 비교 기준으로 아래에 동결 복제).
_spec = importlib.util.spec_from_file_location("etp", Path(__file__).parent / "estimate_target_price.py")
etp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(etp)
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "backtest_target_model.json"

HORIZONS = [1, 5, 10, 20, 60]
STEP = 5          # 워크포워드 평가 간격(거래일)
WARMUP = 130      # 60일 모멘텀·52주 고점 산출에 필요한 최소 이력
SHOCK_MIN_PCT = 2.5
SHOCK_SIGMA_MULT = 2.0
SHOCK_COOLDOWN = 5

# v1.0 estimate_target_price 와 동일한 틸트·섹터 사다리(검증 대상 그대로 복제)
def momentum_tilt_v10(excess60_pct: float) -> float:
    if excess60_pct >= 30.0:
        return 3.0
    if excess60_pct >= 10.0:
        return 2.0
    if excess60_pct >= 0.0:
        return 0.5
    if excess60_pct >= -10.0:
        return -1.0
    return -2.0


def sector_premium_proxy_v10(excess60_pct: float, max_pct: float) -> float:
    """universe_screen 이력 부재 → 종목 자신의 60일 초과수익을 섹터 활발성 proxy 로 사용."""
    if excess60_pct >= 10.0:
        return max_pct
    if excess60_pct >= 0.0:
        return round(max_pct * 0.5, 2)
    return 0.0


def load_json(rel: str, default: Any) -> Any:
    p = ROOT / rel
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def align(history: dict) -> tuple[list[str], dict[str, dict[str, list[float]]]]:
    """티커·지수 일봉을 공통 날짜로 정렬. 반환: (dates, {key: {close, high}})"""
    series: dict[str, dict[str, dict[str, float]]] = {}
    for t, v in history.get("tickers", {}).items():
        series[t] = {b["date"]: b for b in v["bars"]}
    series["INDEX"] = {b["date"]: b for b in history["index"]["bars"]}
    common = sorted(set.intersection(*(set(s.keys()) for s in series.values())))
    out: dict[str, dict[str, list[float]]] = {}
    for k, s in series.items():
        out[k] = {
            "close": [float(s[d]["close"]) for d in common],
            "high": [float(s[d].get("high") or s[d]["close"]) for d in common],
        }
    return common, out


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0


def excess_window(closes: list[float], idx_closes: list[float], i: int, h: int) -> float | None:
    """[i, i+h] 구간 누적 초과수익(%) = 종목 누적 − 지수 누적."""
    if i + h >= len(closes):
        return None
    return round(pct(closes[i + h], closes[i]) - pct(idx_closes[i + h], idx_closes[i]), 3)


def rolling_sigma(excess_daily: list[float], i: int, window: int = 60) -> float | None:
    lo = max(0, i - window)
    seg = excess_daily[lo:i]
    if len(seg) < 30:
        return None
    return statistics.pstdev(seg)


# ── A. 무라벨 충격-감쇠 연구 ────────────────────────────────────────────────
def shock_study(dates: list[str], closes: list[float], idx: list[float]) -> dict:
    n = len(closes)
    excess_daily = [0.0] + [
        round(pct(closes[i], closes[i - 1]) - pct(idx[i], idx[i - 1]), 4) for i in range(1, n)
    ]
    shocks: list[dict] = []
    last_shock = -10**9
    for i in range(60, n - 1):
        sig = rolling_sigma(excess_daily, i)
        if sig is None:
            continue
        thr = max(SHOCK_MIN_PCT, SHOCK_SIGMA_MULT * sig)
        e = excess_daily[i]
        if abs(e) < thr or i - last_shock <= SHOCK_COOLDOWN:
            continue
        last_shock = i
        rec = {"date": dates[i], "shock_pct": e, "threshold": round(thr, 2)}
        for h in HORIZONS:
            car = excess_window(closes, idx, i, h)
            rec[f"car_{h}d"] = car
            rec[f"persist_{h}d"] = round(car / e, 3) if car is not None and abs(e) > 0.1 else None
        shocks.append(rec)

    def agg(sign: int) -> dict:
        grp = [s for s in shocks if (s["shock_pct"] > 0) == (sign > 0)]
        out: dict[str, Any] = {"n": len(grp)}
        for h in HORIZONS:
            vals = [s[f"persist_{h}d"] for s in grp if s[f"persist_{h}d"] is not None]
            out[f"persist_{h}d_median"] = round(statistics.median(vals), 3) if vals else None
            out[f"persist_{h}d_iqr"] = (
                [round(q, 3) for q in statistics.quantiles(vals, n=4)[::2]] if len(vals) >= 4 else None
            )
        return out

    return {"shocks": shocks, "positive": agg(+1), "negative": agg(-1)}


# ── B. 라벨드 이벤트 스터디 ────────────────────────────────────────────────
def event_study(
    ticker: str, dates: list[str], closes: list[float], idx: list[float],
    events: list[dict], impact_table: dict,
) -> list[dict]:
    date_idx = {d: i for i, d in enumerate(dates)}
    out: list[dict] = []
    for ev in events:
        if ev.get("ticker") != ticker:
            continue
        d = ev.get("date")
        i = date_idx.get(d)
        if i is None:  # 휴장일 라벨이면 다음 거래일
            later = [x for x in dates if x > d]
            if not later:
                continue
            i = date_idx[later[0]]
        ar0 = (
            round(pct(closes[i], closes[i - 1]) - pct(idx[i], idx[i - 1]), 2) if i >= 1 else None
        )
        table_pct = (impact_table.get(ev.get("type")) or {}).get("impact_pct")
        rec = {
            "ticker": ticker, "date": d, "type": ev.get("type"), "scope": ev.get("scope"),
            "label": ev.get("label"), "table_impact_pct": table_pct, "ar_day0_pct": ar0,
        }
        for h in (5, 10):
            rec[f"car_{h}d_pct"] = excess_window(closes, idx, i, h)
        out.append(rec)
    return out


# ── C. 워크포워드 검증 ─────────────────────────────────────────────────────
def walk_forward(
    ticker: str, dates: list[str], closes: list[float], highs: list[float], idx: list[float],
    theme_premium_const: float, news_events: list[dict], impact_table: dict, sector_max_pct: float,
) -> dict:
    date_idx = {d: i for i, d in enumerate(dates)}
    rows: list[dict] = []
    n = len(closes)
    for i in range(WARMUP, n - 20, STEP):
        excess60 = pct(closes[i], closes[i - 60]) - pct(idx[i], idx[i - 60])
        ret20 = pct(closes[i], closes[i - 20])
        hi52 = max(highs[max(0, i - 250): i + 1])
        pct52 = closes[i] / hi52 * 100.0

        tilt = momentum_tilt_v10(excess60)
        sector = sector_premium_proxy_v10(excess60, sector_max_pct)
        # 뉴스 프리미엄: t 시점에 알려진(이전 90일 내) 라벨 이벤트.
        # v1.0: 선형 감쇠만 / v1.1: 감쇠 − 기반영분 차감(클램프) + 양뉴스 추세게이트.
        news10 = 0.0
        news11_pos, news11_neg = 0.0, 0.0
        gate = etp.trend_gate(excess60)
        for ev in news_events:
            if ev.get("ticker") != ticker or ev.get("scope") != "stock":
                continue
            j = date_idx.get(ev.get("date"))
            if j is None or j > i:
                continue
            days_since = i - j  # 거래일 근사
            decay = max(0.0, 1.0 - days_since / 63.0)  # 90역일≈63거래일
            base = (impact_table.get(ev.get("type")) or {}).get("impact_pct") or 0.0
            news10 += base * decay
            realized = excess_window(closes, idx, j, i - j) if i > j else 0.0
            c = base * decay - (realized or 0.0)
            c = max(0.0, min(base, c)) if base >= 0 else min(0.0, max(base, c))
            if c > 0:
                news11_pos += c
            else:
                news11_neg += c
        news10 = max(-12.0, min(12.0, news10))
        news11 = max(-12.0, min(12.0, news11_pos * gate + news11_neg))
        premium = theme_premium_const + news10 + sector + tilt
        tilt11 = etp.momentum_tilt(excess60, pct52)
        premium11 = theme_premium_const * gate + news11 + sector + tilt11

        row = {
            "date": dates[i], "premium_pct": round(premium, 2),
            "premium_v11_pct": round(premium11, 2),
            "components": {"theme": theme_premium_const, "news": round(news10, 2),
                           "sector": sector, "tilt": tilt},
            "components_v11": {"theme": round(theme_premium_const * gate, 2),
                               "news": round(news11, 2), "sector": sector,
                               "tilt": tilt11, "gate": gate},
            "excess60_pct": round(excess60, 2), "ret20_pct": round(ret20, 2),
            "pct_of_52w_high": round(pct52, 1),
        }
        for h in (20, 60):
            row[f"fwd_{h}d_excess_pct"] = excess_window(closes, idx, i, h)
        # 목표가 터치 검증: 프리미엄으로 만든 목표가에 60일 내 고가가 닿았는가
        if i + 60 < n and premium > 0:
            tgt = closes[i] * (1 + premium / 100.0)
            row["target_touched_60d"] = max(highs[i + 1: i + 61]) >= tgt
        if i + 60 < n and premium11 > 0:
            tgt11 = closes[i] * (1 + premium11 / 100.0)
            row["target_v11_touched_60d"] = max(highs[i + 1: i + 61]) >= tgt11
        rows.append(row)

    def regress(h: int, key: str = "premium_pct") -> dict:
        pairs = [(r[key], r[f"fwd_{h}d_excess_pct"]) for r in rows
                 if r.get(f"fwd_{h}d_excess_pct") is not None]
        if len(pairs) < 10:
            return {"n": len(pairs)}
        xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        cov = sum((x - mx) * (y - my) for x, y in pairs)
        varx = sum((x - mx) ** 2 for x in xs)
        beta = cov / varx if varx else None
        sdx, sdy = statistics.pstdev(xs), statistics.pstdev(ys)
        corr = (cov / len(pairs)) / (sdx * sdy) if sdx and sdy else None
        hit = sum(1 for x, y in pairs if x * y > 0) / len(pairs)
        # 이론 기대 β: 프리미엄은 12개월(≈250거래일) 전망 → h일 기대 실현분 = h/250
        return {
            "n": len(pairs), "beta": round(beta, 3) if beta is not None else None,
            "beta_expected_if_linear": round(h / 250, 3),
            "corr": round(corr, 3) if corr is not None else None,
            "hit_rate": round(hit, 3), "mean_premium": round(mx, 2), "mean_fwd": round(my, 2),
        }

    def bucket_fwd(key: str, edges: list[float], h: int = 20) -> list[dict]:
        out = []
        for k in range(len(edges) + 1):
            lo = edges[k - 1] if k > 0 else -10**9
            hi = edges[k] if k < len(edges) else 10**9
            vals = [r[f"fwd_{h}d_excess_pct"] for r in rows
                    if r.get(f"fwd_{h}d_excess_pct") is not None and lo <= r[key] < hi]
            out.append({
                "bucket": f"[{lo if lo > -10**8 else '-inf'}, {hi if hi < 10**8 else 'inf'})",
                "n": len(vals),
                "median_fwd": round(statistics.median(vals), 2) if vals else None,
                "mean_fwd": round(statistics.mean(vals), 2) if vals else None,
            })
        return out

    touched11 = [r for r in rows if "target_v11_touched_60d" in r]
    touched = [r for r in rows if "target_touched_60d" in r]
    overheat = [r["fwd_20d_excess_pct"] for r in rows
                if r.get("fwd_20d_excess_pct") is not None
                and r["pct_of_52w_high"] >= 97 and r["ret20_pct"] >= 15]
    normal_pos = [r["fwd_20d_excess_pct"] for r in rows
                  if r.get("fwd_20d_excess_pct") is not None
                  and r["excess60_pct"] >= 10 and not (r["pct_of_52w_high"] >= 97 and r["ret20_pct"] >= 15)]
    return {
        "n_obs": len(rows),
        "regression": {f"{h}d": regress(h) for h in (20, 60)},
        "regression_v11": {f"{h}d": regress(h, "premium_v11_pct") for h in (20, 60)},
        "momentum_buckets_fwd20": bucket_fwd("excess60_pct", [-10, 0, 10, 30]),
        "pct52_buckets_fwd20": bucket_fwd("pct_of_52w_high", [70, 85, 97]),
        "overheat_diagnostic": {
            "rule": "pct_of_52w_high>=97 AND ret20>=15%",
            "n": len(overheat),
            "median_fwd20": round(statistics.median(overheat), 2) if overheat else None,
            "vs_leader_normal": {
                "n": len(normal_pos),
                "median_fwd20": round(statistics.median(normal_pos), 2) if normal_pos else None,
            },
        },
        "target_touch_60d": {
            "n": len(touched),
            "touch_rate": round(sum(1 for r in touched if r["target_touched_60d"]) / len(touched), 3)
            if touched else None,
            "n_v11": len(touched11),
            "touch_rate_v11": round(
                sum(1 for r in touched11 if r["target_v11_touched_60d"]) / len(touched11), 3
            ) if touched11 else None,
        },
        "rows": rows,
    }


def main() -> int:
    history = load_json("state/price_history.json", None)
    if not history:
        print("state/price_history.json 없음 — fetch_history.yml 먼저 실행")
        return 1
    news_history = load_json("config/news_history.json", {}).get("events", [])
    impact_cfg = load_json("config/news_impact.json", {})
    impact_table = impact_cfg.get("news_type_impact_pct", {})
    sector_max = float(impact_cfg.get("params", {}).get("max_sector_activity_premium_pct", 8.0))

    dates, series = align(history)
    idx = series["INDEX"]["close"]
    print(f"aligned {len(dates)} trading days: {dates[0]} ~ {dates[-1]}")

    # 테마 프리미엄 상수: 현행 v1.0 산출값(estimate 결과와 일치하도록 고정)
    theme_const = {"005930": 5.69, "005380": 4.7}

    out: dict[str, Any] = {
        "as_of": datetime.now(KST).isoformat(timespec="seconds"),
        "window": {"start": dates[0], "end": dates[-1], "trading_days": len(dates)},
        "method_note": __doc__.split("방법론", 1)[1][:600],
        "tickers": {},
    }
    for t in ("005930", "005380"):
        closes, highs = series[t]["close"], series[t]["high"]
        name = history["tickers"][t]["name"]
        print(f"\n── {name}({t}) ──")
        shock = shock_study(dates, closes, idx)
        print(f"  A. 충격 {len(shock['shocks'])}건 | +충격 지속비율(중앙값) 5d/20d/60d:",
              shock["positive"].get("persist_5d_median"), shock["positive"].get("persist_20d_median"),
              shock["positive"].get("persist_60d_median"),
              "| -충격:", shock["negative"].get("persist_5d_median"),
              shock["negative"].get("persist_20d_median"), shock["negative"].get("persist_60d_median"))
        ev = event_study(t, dates, closes, idx, news_history, impact_table)
        for e in ev:
            print(f"  B. {e['date']} {e['type']}({e['scope']}): AR0 {e['ar_day0_pct']}% "
                  f"CAR5 {e['car_5d_pct']}% CAR10 {e['car_10d_pct']}% (테이블 {e['table_impact_pct']}%)")
        wf = walk_forward(t, dates, closes, highs, idx, theme_const[t], news_history, impact_table, sector_max)
        for h in ("20d", "60d"):
            r10, r11 = wf["regression"][h], wf["regression_v11"][h]
            print(f"  C. fwd{h} v1.0: β={r10.get('beta')} corr={r10.get('corr')} hit={r10.get('hit_rate')} "
                  f"평균예측 {r10.get('mean_premium')} vs 실현 {r10.get('mean_fwd')}")
            print(f"     fwd{h} v1.1: β={r11.get('beta')} corr={r11.get('corr')} hit={r11.get('hit_rate')} "
                  f"평균예측 {r11.get('mean_premium')} vs 실현 {r11.get('mean_fwd')}")
        print(f"  C. 과열진단: {wf['overheat_diagnostic']}")
        print(f"  C. 목표가 60d 터치율: {wf['target_touch_60d']}")
        out["tickers"][t] = {"name": name, "shock_study": shock, "event_study": ev, "walk_forward": wf}

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
