#!/usr/bin/env python3
"""check_valuation_guard — PER/PBR 밴드 기반 '냉정한 목표가 상한'과 진입 과열 가드 (v2.11).

배경: 2026-05-20~06-09 운용에서 목표가 도달 0/6 — 모멘텀·ATR 만으로 부풀린 목표가가 원인 중
하나. 기업가치 밴드로 목표가의 천장(ceiling)과 진입 과열 경고를 만든다. 밸류에이션은
후행·저속 신호이므로 **타이밍 신호가 아니라 가드(상한·경고·확신 틸트)로만** 쓴다
(policy.valuation_anchor — 기존 '타이밍은 regime·momentum, 펀더멘털은 확신 레이어' 위계 동일).
사이클 업종은 PER 함정(피크 실적=최저 PER) 때문에 preferred_metric=PBR.

입력: config/valuation.json(sunday_strategy 가 출처 검증 후 시드/갱신),
      config/watchlist.json(보유 target_price), state/market_snapshot.json(현재가)
출력: state/valuation_check.json — 종목별 verdict:
      ok            목표가가 밸류에이션 천장 이내
      cap_target    목표가 > ceiling → 상한 적용 권고(0900 §2·1800 §2-2 가 캡)
      overheat_entry 현재가 멀티플 > 밴드 상단 → 신규/재진입 probe 사이즈
      deep_value    현재가 멀티플 < 밴드 하단 — 단독 매수신호 아님(밸류트랩),
                    sector_rotation_reentry 촉매+몰입 통과 시 probe 근거로만
      skip          데이터 결측/stale(90일 초과) — 아무것도 막지 않는다
의존성 0(표준 라이브러리). score_candidates 가 verdict 를 valuation_tilt(±0.03)로 반영.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_PATH = ROOT / "state" / "valuation_check.json"
STALE_DAYS = 90


def load_json(rel: str, default: Any) -> Any:
    path = ROOT / rel
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _band(v: Any) -> tuple[float | None, float | None]:
    if isinstance(v, list) and len(v) == 2:
        return _num(v[0]), _num(v[1])
    return None, None


def evaluate(ticker: str, cfg: dict, current: float | None, target: float | None, today: datetime) -> dict:
    out: dict[str, Any] = {
        "ticker": ticker,
        "name": cfg.get("name", ticker),
        "preferred_metric": cfg.get("preferred_metric", "PBR"),
        "current_price": current,
        "target_price": target,
        "verdict": "skip",
        "note": None,
    }
    src_date = cfg.get("source_date")
    if src_date:
        try:
            age = (today.date() - datetime.fromisoformat(src_date).date()).days
            if age > STALE_DAYS:
                out["note"] = f"source_date {src_date} 가 {age}일 경과(>{STALE_DAYS}) — stale, skip"
                return out
        except ValueError:
            out["note"] = "source_date 형식 오류 — skip"
            return out

    metric = (cfg.get("preferred_metric") or "PBR").upper()
    if metric == "PBR":
        base, band = _num(cfg.get("bps")), _band(cfg.get("pbr_band_5y"))
        metric_key = "pbr"
    else:
        base, band = _num(cfg.get("eps_fwd")), _band(cfg.get("per_band_5y"))
        metric_key = "per"
    lo, hi = band
    if not base or hi is None:
        out["note"] = f"{metric} 산정 데이터 결측(base/밴드 미시드) — skip"
        return out

    ceiling = round(hi * base, 0)
    out["valuation_ceiling_price"] = ceiling
    if current:
        out["current_multiple"] = {metric_key: round(current / base, 2)}
    if target:
        out["target_implied_multiple"] = {f"{metric_key}_at_target": round(target / base, 2)}

    if current and lo is not None and current / base < lo:
        out["verdict"] = "deep_value"
        out["note"] = f"현재 {metric} {round(current/base,2)} < 밴드 하단 {lo} — 밸류트랩 주의, 단독 매수신호 아님"
    elif current and current / base > hi:
        out["verdict"] = "overheat_entry"
        out["note"] = f"현재 {metric} {round(current/base,2)} > 밴드 상단 {hi} — 신규/재진입 probe 사이즈"
    elif target and target > ceiling:
        out["verdict"] = "cap_target"
        out["note"] = f"목표가 {target:,.0f} > 밸류에이션 천장 {ceiling:,.0f}({metric} {hi}×{base:,.0f}) — 상한 적용 권고"
    else:
        out["verdict"] = "ok"
    return out


def main() -> int:
    valuation = load_json("config/valuation.json", {})
    watchlist = load_json("config/watchlist.json", {})
    snapshot = load_json("state/market_snapshot.json", {})
    today = datetime.now(KST)

    targets: dict[str, float] = {}
    for s in watchlist.get("stocks", []) or []:
        if isinstance(s, dict) and s.get("ticker") and _num(s.get("target_price")):
            targets[s["ticker"]] = float(s["target_price"])

    snap_tickers = snapshot.get("tickers", {}) if isinstance(snapshot, dict) else {}
    results = []
    counts: dict[str, int] = {}
    for ticker, cfg in (valuation.get("tickers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        ts = snap_tickers.get(ticker, {}) if isinstance(snap_tickers, dict) else {}
        current = _num(ts.get("last_close")) if isinstance(ts, dict) else None
        r = evaluate(ticker, cfg, current, targets.get(ticker), today)
        results.append(r)
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    out = {
        "as_of": today.isoformat(timespec="seconds"),
        "verdict_counts": counts,
        "tickers": {r["ticker"]: r for r in results},
        "policy_ref": "policy.valuation_anchor — 최종 목표가 = min(동적목표가, 컨센×1.15, valuation_ceiling_price). skip 은 아무것도 막지 않음.",
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"valuation_guard: {counts or '대상 없음'} → state/valuation_check.json")
    for r in results:
        if r["verdict"] != "skip":
            print(f"  [{r['verdict']}] {r['name']}: {r.get('note') or 'ok'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
