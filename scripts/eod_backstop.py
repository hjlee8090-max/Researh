#!/usr/bin/env python3
"""18시 슬롯 결정론 백스톱 — 루틴이 미발화해도 원장의 하루가 닫히게 한다 (Stage 1, docs/plan_stage1.md §2-D).

배경: 18시 슬롯 결측 2회(7/31·8/24)에 EOD 확정·손절 판정이 통째로 비었고 사후 소급 복구가 필요했다.
실계좌였다면 그날 종가 손절이 사라진다. 결정론으로 할 수 있는 부분(EOD_MARK 기록·하드 룰 판정)을 코드가 맡는다.

동작(워크플로 cron 은 19:15 KST 지만 GitHub schedule 지연으로 자정을 넘겨 실행되는 일이 잦다):
  0. 판정 일자는 실행 시각이 18:30 KST(EOD_MARK 기록 시한) 이후면 오늘, 이전이면 직전 일자다.
     실행 시각의 KST 날짜를 그대로 쓰면 자정 이후 실행이 아직 열리지도 않은 다음 날 자 '유령 EOD' 를 남긴다
     (lessons 2026-09-08·09-16·09-18 — recycled_value_gate FAIL 로 auto_merge 가 매 routine 차단됐다).
  1. 판정 일자의 trade_log 라인이 하나도 없으면 EOD_MARK 1줄을 append 한다
     (equity·cash 는 mark_to_market 이 스냅샷으로 갱신한 portfolio.json 값, kospi_close 는 스냅샷 regime 값 —
     단 regime.as_of 가 판정 일자가 아니면 종가를 주장하지 않고 null 로 둔다).
     원장 사실(cash·shares·realized)은 건드리지 않는다. 이미 라인이 있으면 아무것도 하지 않는다(멱등).
  2. build_order_intents.py 를 호출해 내일 세션의 주문 의도를 산출한다(하드 스톱·추세 이탈 판정 포함).
표준 라이브러리만. --dry-run 지원.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
TRADE_LOG = ROOT / "state" / "trade_log.jsonl"
EOD_DEADLINE = dt_time(18, 30)  # audit_pipeline.audit_trade_log_daily_mark 의 당일 검사 시각과 동일


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", help="판정 일자(기본: 18:30 KST 이후면 오늘, 이전이면 직전 일자)")
    args = ap.parse_args()
    now = datetime.now(KST)
    target = args.date or (now.date() if now.time() >= EOD_DEADLINE else now.date() - timedelta(days=1)).isoformat()

    # 영업일 가드
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import check_market_open as cmo
        is_open, why, _code = cmo.evaluate(datetime.strptime(target, "%Y-%m-%d").date())
    except Exception as exc:  # noqa: BLE001
        is_open, why = True, f"영업일 판정 실패({exc}) — 영업일로 간주"
    if not is_open:
        print(f"[SKIP] {target} 휴장({why}) — 백스톱 없음")
        return 0

    have_target = False
    if TRADE_LOG.exists():
        for line in TRADE_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip() and (f'"ts": "{target}' in line or f'"ts":"{target}' in line):
                have_target = True
                break
    if have_target:
        print(f"[OK] {target} trade_log 라인 존재 — EOD 백스톱 불필요")
    else:
        pf = json.load(open(ROOT / "config" / "portfolio.json", encoding="utf-8"))
        snap = {}
        try:
            snap = json.load(open(ROOT / "state" / "market_snapshot.json", encoding="utf-8"))
        except Exception:
            pass
        regime = snap.get("regime") or {}
        kospi = (regime.get("detail") or {}).get("last_close") or regime.get("last_close")
        if str(regime.get("as_of", ""))[:10] != target:
            kospi = None  # 판정 일자 시세가 아니면 종가로 주장하지 않는다(묵은 값 재활용 방지)
        rec = {"ts": f"{target}T15:30:00+09:00", "action": "EOD_MARK", "execution_venue": "closing_auction",
               "price_source": "snapshot_fresh", "date": target, "equity": pf.get("equity"), "cash": pf.get("cash"),
               "kospi_close": kospi, "filled": 0, "backstop": True,
               "reason": f"{target} EOD 백스톱(eod_backstop.py) — 18시 루틴 미발화로 결정론 기록. 체결 0건. "
                         f"equity 는 mark_to_market 스냅샷 값(as_of {pf.get('as_of')}). 하드 룰 판정은 state/order_intents.json 참조."}
        if args.dry_run:
            print("[DRY] append:", json.dumps(rec, ensure_ascii=False))
        else:
            with open(TRADE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[WRITE] {target} EOD_MARK 백스톱 기록")
    cmd = [sys.executable, str(ROOT / "scripts" / "build_order_intents.py")] + (["--dry-run"] if args.dry_run else [])
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
