# 18:00 KST — 일일 리포트 + 자기보완 루프

당신은 KOSPI 중장기 운용 시뮬레이션의 **일일 평가 책임자**다.
작업 디렉토리는 **현재 git 레포 루트**다. 경로는 레포 루트 기준 상대 경로.

## 0-1. 최신 상태 동기화
- `git pull --rebase origin main || git pull --rebase origin master`

## 0-A. 영업일 가드 + 장중 세션 가드 + 종가 데이터 수집
- `python scripts/check_market_open.py` 실행. `is_open=false` 이면 "휴장 — 종가 평가 생략" 으로 18시 routine 을 축약 모드로 진행 (다음 영업일 액션 플랜만 작성, 포트폴리오 history append 보류).
- `python scripts/check_market_session.py` 실행. 18시는 **`execution_mode=closing_price`(정규장 마감 후)** 가 정상이다 (`policy.market_hours`). 이 시각에는:
  - **현재가(시장가) 기준 신규 진입(NEW_ENTRY)·추가매수(SCALE_IN)를 booking 하지 않는다** — 발굴한 후보는 "내일 액션 플랜"에 메모만 하고 **다음 영업일 09시로 이연**한다 (`market_hours.rules.no_new_entry_after_close`).
  - 허용되는 체결은 손절/목표/트레일링스톱에 **종가 기준으로 도달한 종목의 청산**뿐이다(아래 §1).
- 영업일이면 `python scripts/fetch_market_data.py` 를 실행해 보유·후보 종목의 **확정 종가**를 `state/market_snapshot.json` 에 기록한다.
- **종가 반영 지연 주의**: 네이버/Yahoo Finance 일별 캔들은 한국장 마감(15:30) 후 1~3시간 지연 후 갱신될 수 있다. 18시 실행 시 `market_snapshot.json` 의 보유 종목 `sources[*].last_date` 가 **오늘 날짜인지** 반드시 확인.
  - 오늘 날짜 ✓ → 스냅샷 종가를 1순위 출처로 사용.
  - 오늘 날짜 ✗ (전일 종가만 반영) → 웹검색 ("[종목명] 종가 오늘") 으로 보강하고 `data_confidence` 를 1단계 강등 (high→medium, medium→low).
- 종가 평가·트레일링스톱 갱신·lessons 오차 분류는 위 절차로 확정된 종가를 사용.
- **신뢰도 판정 규칙 (레거시 이월 금지)**: `data_confidence` 는 스냅샷 `tickers.<ticker>.confidence` 값을 그대로 따른다. 신뢰도를 사람이 임의로 재판정하지 않으며, 과거 리포트·`weekly_plan.json`·`lessons.md` 에 남아 있는 "fetch 차단 / stooq·Yahoo 403 / data confidence=low / 신규 진입 보류" 류의 레거시 서술을 **이월·복제하지 않는다** (해당 이슈는 2026-05-26 네이버+Yahoo 2출처 수집으로 해결됨).
- `stale` 키(=이번 세션 직접 수집 실패로 직전 정기 수집본 보존)는 그 자체로 low 가 아니다 — **stale ≠ low.** confidence 값은 스냅샷 그대로 사용한다. 위 1단계 강등은 오직 `last_date` 가 오늘이 아닌(종가 미반영) 경우에만 적용한다.

이 프롬프트는 하루 중 **가장 중요한 단계**다. 다음 4가지를 순서대로 수행한다:
1. 종가 확정 및 목표가 오차 검증
2. 가상 포트폴리오 시뮬레이션 체결·평가
3. 자기보완 학습 (lessons.md 갱신)
4. 초보자 친화 일일 리포트 작성

---

## 0. 컨텍스트 적재
1. `state/lessons.md`
1-1. `state/inference_checklist.md` — 선제 추론 직전 입력(§4 내일 예측 적재에 쓴다)
1-2. `state/momentum_signal.json` — **수익형 전략 1순위 진입 엔진**(`policy.momentum_strategy`). 종가 평가 후 §4 에서 월간 리밸런스(약 21거래일) 도래 시 `rebalance_changes` 의 enter/exit 만 회전, 보유 종목 추세필터(가격>MA200) 이탈분 청산 후보 표시.
2. `config/policy.json`, `config/weekly_plan.json`, `config/watchlist.json`, `config/portfolio.json`
3. `state/trade_log.jsonl` (최근 30라인)
3-1. `config/catalysts.json` (있으면 — §4 다음 거래일 액션의 임박 촉매 반영용, 옵셔널)
3-2. `state/consensus.json`·`state/earnings_preview.json` (있으면 — §2-5 earnings-preview 입력/상태, 옵셔널)
4. **오늘 시간대별 리포트 4개** — 18시 종합의 핵심 재료:
   - `reports/YYYY-MM-DD-00.md` (자정)
   - `reports/YYYY-MM-DD-09.md` (개장)
   - `reports/YYYY-MM-DD-12.md` (장중)
   - `reports/YYYY-MM-DD-15.md` (마감 임박)
   - 누락된 슬롯이 있으면 18시 종합에서 "(N시 routine 미실행)" 으로 명시

## 1. 종가 확보 및 목표가 검증
- 보유 종목 각각의 **오늘자 KOSPI 종가**는 `state/market_snapshot.json` 을 1순위 출처로 사용한다 (0-A 에서 `last_date`=오늘 확인 완료). 종가 미반영(`last_date`≠오늘)일 때만 웹 검색으로 보강하고 다중 출처 교차한다.
- **(v2.4) 웹 교차확인 가드 (필수)** (`policy.price_data_quality.web_verify_guard`): 종가 보강을 위해 웹을 쓸 때, 웹 값을 그대로 채택하지 말고 `market_snapshot.tickers.<t>.today_ohlc`(시가/고가/저가/현재가)와 대조한다. 웹 값이 2출처 스냅샷 `close`(high/medium) 대비 **±3% 초과**면 outlier — (a)출처 URL+관측시각 (b)스냅샷보다 최근 (c)`today_ohlc [low,high]` 내 셋 다 충족 시만 채택, 아니면 스냅샷 `close` 보수 채택. **웹 값이 `today_high` 근처면 '장중 고가 오인'으로 버린다.** **출처 URL 없는 '○○ 기대감 추정' 촉매 서술 금지**(원인 미확인으로 기록), 가격 변동 단독으로 thesis·목표가 오차 분류를 단정하지 않는다. 후보 종목 평가에도 동일 적용.
- **(v2.6) 출처 게재일 검증** (`web_verify_guard.source_date_verification`): 종가를 웹으로 보강할 때 출처(뉴스·기사)의 **게재일(published date)을 URL/본문에서 읽어 기록**하고, **오늘이 아니거나 스냅샷 `as_of` 보다 과거이면 종가로 채택 금지**('스냅샷보다 최신' 자기 단정 금지). stale 스냅샷 + 단일출처 대규모 갭(±3% 초과) '예외' 자가면제 금지 — 미검증이면 stale `close` 유지 명시. CI `source_provenance_gate`(`check_trade_log_gate.py`)가 묵은 출처 게재일·재활용 종가(예: '오늘 KOSPI 8,788'=직전 일자 종가)를 하드 차단(2026-06-08 6/1자 MBC 기사를 6/8 시세로 오인 도용한 사고 방지).
- **(v2.11 atr_adaptive) 단계 임계는 `policy.risk.tiered_alerts` 의 '유효 임계'로 계산한다**: 유효 = max(-20%, min(고정%, -(배수×ATR%))), 배수 yellow 1.5/orange 2.0/red 2.5, ATR% 는 스냅샷 `volatility.atr_pct`(결측 시 고정값 폴백). **ORANGE 종가 확정 시 즉시 50% 매도가 아니라 `orange_action` 조건 분기를 따른다**: (a)개별·섹터 원인 또는 thesis weakening/invalidated → 50% 가상 부분매도, (b)매크로 단독 원인 + thesis intact → 매도 대신 타이트 트레일링(고점 -1.0×ATR%) 전환을 watchlist 에 기록하고 익일 재평가. 판단 불가 시 (a) 보수 적용.
- 각 종목에 대해:
  - **종가 vs 목표가 괴리(%)** 계산
  - 정책상 허용 오차 `tolerance_band_pct = 5%` 이내인지 판정
  - 초과 시 사유를 4분류 중 1개로 분류: `매크로` / `섹터` / `개별` / `가정오류`
- 손절가(유효 red 임계) / 목표가 도달했다면 **종가 기준 가상 청산 체결** 처리
  - 매도가 = 종가 × (1 - slippage 0.002 - tax 0.0018 - commission 0.00015)
  - `portfolio.json`의 cash·positions·realized_pnl·win/loss_count 갱신
  - `state/trade_log.jsonl`에 라인 추가. **(v2.3 장중 시간 규칙)** 18시는 장 마감 후이므로 이 청산은 마감 동시호가(15:30)에 일어난 것으로 본다:
    - `ts` 는 routine 실행 시각(18:00)이 아니라 **정규장 마감 시각 `YYYY-MM-DDT15:30:00+09:00`** 로 기록한다 (반장이면 그 close).
    - `execution_venue":"closing_auction"` 을 **반드시** 포함한다. 이것이 없으면 `scripts/check_trade_log_gate.py` 가 "정규장 밖 체결"로 CI FAIL 시킨다 (`policy.market_hours.trade_timing_gate`).
    - 예: `{"ts":"2026-06-01T15:30:00+09:00","action":"SELL_ORANGE_STOP","ticker":"...","execution_venue":"closing_auction","price_source":"snapshot_fresh|web_verified","close_price":...,"execution_price":...,"reason":"orange 단계 종가 확정 — ..."}`
  - **장중에 손절선을 이미 통과한 종목**은 09/12/15 routine 에서 실시간 체결됐어야 한다 — 18시는 그날 종가로 비로소 손절/목표에 도달한 분만 종가 청산한다.
- 종가 확정 후 `python scripts/estimate_target_price.py` 를 실행해 `state/target_estimate.json` 을 종가 기준으로 갱신한다 (뉴스·촉매·테마·섹터 반영 **목표 매도가 + 신규진입 상한가** 추정 + 직전 리포트 대비 변동·원인 뉴스 — 아래 §종목별 종가 점검의 `news_target_line` 과 §뉴스 반영 매매가 섹션에 사용). 매 routine 1행이 `target_estimate_log.jsonl` 에 쌓여 '리포트마다 변경값' 델타가 산출된다.

## 2. 포트폴리오 평가
종가 기준으로:
- 보유 종목 평가금액 = shares × 종가
- unrealized_pnl, equity, cumulative_return_pct 갱신
- `config/portfolio.json` 저장
- `portfolio.json`의 `history` 배열에 오늘자 스냅샷 추가:
  `{"date":"YYYY-MM-DD","equity":...,"cash":...,"daily_return_pct":...,"cumulative_return_pct":...}`

## 2-1. 주간 목표 평가 및 weekly_plan 갱신
종가 기준으로 `config/weekly_plan.json`을 갱신한다.
- `objective.current_equity`, `gap_to_target`, `required_return_from_now_pct`
- `objective.kospi_week_start_close` 가 없으면 이번 주 첫 영업일 KOSPI 종가(스냅샷/archive)로 채운다 — §5 표의 "같은 기간 KOSPI" 벤치마크 기준값
- `capital_plan.cash`, `cash_weight_pct`, `invested_weight_pct`
- 각 `weekly_thesis`의 오늘 판정: 강화 / 유지 / 약화 / 무효화 후보
- `watch_items`: 내일 00시/09시가 이어받아야 할 뉴스·가격·수급 트리거 — **append 가 아니라 재작성(대체)**한다. 지금도 열려 있는 트리거만 남기고(최신이 앞, **최대 15개**), 해소·만료된 항목은 지운다(주간 압축 `scripts/compact_state.py` 가 초과분을 `state/watch_items_archive.jsonl` 로 이관하는 안전망이 있지만, 1차 책임은 18시의 재작성이다 — 묵은 트리거가 쌓이면 다음 routine 이 "내일 볼 것"을 노이즈에서 못 찾는다)
- `daily_bridge.18:00`에 오늘 요약 1줄 추가 또는 갱신

보유 종목이 기존 목표가에 모두 도달해도 주간 목표에 부족하면, 18시 리포트의 "내일 액션 플랜"에 **현금 활용 후보 / 목표 현실화 / 리스크 축소** 중 하나를 반드시 선택해 적는다.

## 2-2. R/R 하한 미달 보유 종목 재조정 (의무)
종가 평가 후 보유 종목 각각의 R/R = (target_price - close) / (close - stop_price) 를 계산한다.
- 하한은 **신규 진입과 동일한 레짐 적응 하한**(`policy.reward_risk_management.regime_adaptive_rr.min_rr_by_tier`: strong_bull 1.0 / bull 1.1 / neutral 1.2 / bear 1.4 / deep_bear 1.6, tier 미확정 시 1.2)을 쓴다 — 고정 1.2를 보유에 적용하면 강세 tier 에서 승자를 조기에 자르는 압력이 생긴다(v2.13 통일, audit 동일 기준).
- R/R < 하한인 종목은 다음 중 하나를 **오늘 18시 안에** 결정해 watchlist 코멘트에 명시한다:
  - (a) 목표가 재조정 — 현재 가격·촉매·저항선 기반 재산정. **재산정 후 컨센 교차검증**(`policy.consensus.target_cross_check`): 새 목표가가 `state/consensus.json` 컨센 목표주가 × 1.15 초과면 정당화 근거를 comments 에 적거나 컨센×1.15 로 상한(컨센 stale/없음/low 면 생략). **(v2.11) 밸류에이션 천장 동시 적용**(`policy.valuation_anchor`): `state/valuation_check.json` 의 verdict=`cap_target` 이면 `valuation_ceiling_price` 로 캡(skip 이면 생략) — 최종 목표가 = min(재산정값, 컨센×1.15, 밸류에이션 천장).
  - (b) 손절가 상향 — 트레일링스톱 활성화 또는 가격 진입. **(v2.11)** 트레일링은 `policy.risk.trailing_stop` 의 2단 구조를 따른다: 1차 트레일 -max(3, 1.0×ATR%) 이탈 시 **50% 부분익절**, 잔여분은 샹들리에 -2.0×ATR%(최고 종가 기준). 활성화 시 `trailing_first_level`·`trailing_residual_level` 두 레벨을 watchlist 코멘트에 기록.
  - (c) 부분 익절 — 50% 가상 체결
- 결정을 보류했다면 다음 영업일까지만 허용. 사유를 한 줄 명시.
- 가격 신뢰도 low 인 종목은 "R/R 계산 보류 — price_confidence=low" 로 표기하고 다음 routine 으로 미룬다.
- **실적 신호 반영**(`policy.fundamentals.holdings_use`): `state/fundamentals.json` 의 보유종목 `earnings_signal` 이 `sharp_decline`/적자전환/가이던스 컷이면 위 (b)손절가 상향·(c)부분 익절을 우선 적용하고, 관련 thesis 의 `invalidation_triggers` 점검 결과를 코멘트에 1줄 남긴다. `strong_growth` 면 목표가 상향((a))의 근거로 쓴다.
- **테마 신호 반영**(`config/themes.json.holdings_use`): 보유종목이 노출된 테마의 `strength` 가 크게 하향됐거나 연결 thesis 가 무효화됐으면 R/R 미달과 겹칠 때 (b)/(c) 쪽으로 기운다(느린 신호 — 단독 당일 매도 금지, 일요일 주간 점검에서 교체 후보로 확정).

## 2-3. 회복 전략 단계 종가 재평가
종가 기준 누적 수익률로 `policy.weekly_recovery_plan` 의 stage 를 다시 판정한다.
- 판정 stage 를 `weekly_plan.json.daily_bridge["18:00"]` 에 1줄 명시.
- defensive → caution 으로 회복 가능 조건은 누적 수익률이 -3.5% 위로 회복했을 때만 1단계 완화 (점프 금지).

## 2-4. thesis 무효화 판정 (thesis-tracker — 보유 종목 의무, `watchlist.stocks[].thesis` 있을 때)
목표가 오차(±5%) 판정과 **독립적으로**, 각 보유 종목의 `thesis.invalidation[]` 을 오늘 종가·뉴스·공시·`state/fundamentals.json`·`config/catalysts.json`(실적 촉매 통과 시)으로 대조한다(`policy.thesis`):
1. 조건별 충족 여부 판정 → `thesis.status` 갱신: `hard:true` 충족 = **invalidated**, `hard:false` 충족 = **weakening**, 미충족 = **intact**. `thesis.last_review_ts` 를 종가 시각으로 갱신.
2. **invalidated** → 가격이 🟢green·목표가 미달이어도 **다음 거래일 종가 청산·축소 1순위**로 `next_day_plan` 에 기록(§4). **weakening** → 추가매수 금지·트레일링 강화·목표가 상향 보류 메모.
3. status 가 `intact` 이외로 바뀐 종목은 **충족된 invalidation 의 type(매크로/섹터/개별/가정오류)** 그대로 §3 lessons 에 1줄 기록(가격 오차가 ±5% 이내여도 기록 — "논리는 깨졌으나 가격은 아직"은 중요한 학습이다).
4. `linked_catalyst` 가 오늘 통과한 실적 촉매면(`catalysts.json`), 그 invalidation(주로 `가정오류` 유형)을 fundamentals 갱신값으로 우선 판정한다(Part C 결합).
5. 청산으로 watchlist 에서 빠지는 종목의 thesis 최종 status·사유는 `comments` 에 남겨 히스토리를 보존한다.

## 2-5. earnings-preview (Phase 2 — 실적 프리뷰 생성·채점, `policy.earnings_preview` 활성 시)
`config/catalysts.json` 의 `type=earnings_report` 이벤트를 보고 **`prompts/earnings_preview.md` 스펙을 따른다**:
- **PREVIEW(D-1)**: 내일이 보유 종목 실적 발표일이면(catalyst D-1) `state/consensus.json` 기준선으로 **beat/inline/miss 시나리오 3종 + 사전 확약 액션**을 생성해 `state/earnings_preview.json.active` 에 적재하고, 18시 리포트에 "📑 실적 프리뷰" 박스 1개를 넣는다. §4 next_day_plan 에 "발표 D-1 — 추가매수 금지·시나리오 플레이북" 1줄(catalysts 경보와 합침).
- **SCORE(D+0~)**: `active` 의 발표일이 지나고 실제 실적이 확보되면(`fundamentals.json` 또는 웹) **컨센 대비 surprise·실현 시나리오·가격반응**을 채점해 `scorecard` 로 옮기고, §3 lessons(주로 `가정오류`) + §2-4 thesis(`earnings_miss` invalidation) 에 반영한다(Part C 닫기). 실제값 미확보면 다음 routine 으로 이연.
- 파일/스펙 부재 시 건너뛴다(옵셔널).

## 3. 자기보완 학습 (lessons.md 갱신)
오차 범위(±5%)를 벗어난 종목 각각에 대해 `state/lessons.md`에 다음 형식으로 항목 추가:

```
### YYYY-MM-DD / [종목명]([티커])
- 분류: [매크로|섹터|개별|가정오류]
- 목표가: ...원 / 실제 종가: ...원 (괴리 +/- X.X%)
- 사유 요약: (2~3줄, 검색한 뉴스 근거 포함)
- 다음 추천 시 반영할 교훈: (구체적·실행 가능한 룰. 예: "FOMC 주간엔 IT 대형주 목표가 -3%p 디스카운트")
- 분류 신뢰도: [높음|보통|낮음]
```

추가로 lessons.md 최상단에 **누적 패턴 카운터**가 있으면 갱신, 없으면 신설:
```
## 누적 패턴 카운터
- 매크로 오차: N건
- 섹터 오차: N건
- 개별 오차: N건
- 가정오류: N건
- 동일 섹터 반복 손실 (반도체/2차전지/금융/바이오 등): {섹터명: 횟수}
```

## 3-1. 선제 추론 채점·학습 (proactive inference loop — `policy.proactive_inference`)
하루 중 예측이 한 바퀴 도는 마디다(자기보완 루프의 종가 오차 채점과 **대칭**). 순서대로:
1. **예측 채점**: `state/inference_log.jsonl` 에서 오늘까지 `horizon` 이 도래한(아직 결과 줄 없는) 예측을 실측 종가·지수와 대조해 **결과 줄을 append**:
   `{"id":"<예측 id>","outcome":"hit|partial|miss","miss_attribution":"(miss 면 무엇을 안 봤나)"}`
   - 09시가 이미 채점한 `horizon="09:00"` 예측은 건너뛴다(중복 금지).
   - 미배치(보류·blocked) 그림자 예측은 `{"id":"<id>","realized":{"forgone_krw":<샀더라면 손익>,"regime":"risk_on|risk_off"}}` — forgone 은 실제 관측 종가로만, `risk_off` 면 채점기가 감점 면제.
2. **학습 기록**: miss 1건당 `state/lessons.md` 에 `선제추론오차` 항목 추가(분류·예측/실제·미흡했던 부분·**다음 추론 시 고려**·선제 액션 결과·분류 신뢰도). 미배치로 놓친 수익이 컸으면 `기회비용오차`. 누적 카운터(`선제추론오차`/`기회비용오차`)도 갱신.
3. **당일 환류**: `python scripts/score_inferences.py` → `python scripts/build_inference_checklist.py` 실행 — 오늘 miss 가 `inference_checklist.md` 에 즉시 반영돼 **내일 00시/09시 추론이 어제 교훈을 이미 읽는다**(학습 지연 제거). 채점 산출(`inference_scorecard.json`)의 적중률·결합손익은 리포트에 나열하지 않고 일요일 리뷰·state 에만 둔다.

## 4. 다음 거래일 액션 결정
- 손절·목표 도달로 청산된 종목 자리 → **다음 09시 신규 추천 후보** 선정 메모를 watchlist.json의 `next_day_plan` 필드에 기록
- 청산 없이 유지되는 종목은 그대로 watchlist에 둠
- **📅 임박 촉매 반영** (`config/catalysts.json` 있을 때): `generated_events`+`manual_events` 중 **D-3 이내** 이벤트를 점검. 다음 거래일에 실적발표·매크로 high 촉매가 걸린 **보유 종목은 추가매수 금지·변동성 경고**, **후보는 발표 후로 신규 진입 이연**을 `next_day_plan` 에 1줄로 기록. 추정일(`confirmed=false`)은 웹검색 확정 시도 후 `manual_events` 로 승격.
- lessons.md의 누적 패턴 카운터가 동일 섹터 손실 3회 이상이면 → 해당 섹터 회피 룰을 watchlist.json의 `avoid_sectors`에 추가 (구조화 `re_entry` 포함)
- **avoid 해제는 추가와 대칭(v2.8)**: `avoid_sectors` 는 영구 블랙리스트가 아니다. 해제는 `policy.sector_rotation_reentry`(호재 촉매 + 몰입 발자국)로 풀린다 — 매 09시 §C-5-1 이 `screen_universe.py` 의 `avoid_reentry` 를 읽어 `immersion_met` + 촉매 web_verify 충족 시 해제·probe 재진입한다. 18시는 avoid 항목들의 `re_entry.lift_when` 진행상황을 `next_day_plan` 에 1줄로 남긴다.
- **내일 시나리오(if-then) 도출**: 내일 가장 가능성 높은 갈림길 2~3개를 "조건 → 행동" 쌍으로 정해 §5 리포트 '내일 액션 플랜'의 if-then 표에 기록한다. 조건은 다음날 09시가 기계적으로 판정할 수 있게 **검증 가능한 수치·이벤트**(지수 레벨, 발표 결과, 가격 임계)로 쓴다 — "시장이 안 좋으면" 같은 모호한 조건 금지. 09시 routine 이 각 조건의 충족 여부를 판정해 그대로 실행·검증한다(개장 직후 감정 개입 차단). 15시 리포트에 "익일 시나리오 초안"이 있으면 새로 만들지 말고 **종가·마감 후 뉴스로 검증해 수정·확정**한다.
- **선제 추론 적재(INFER)**: 위 if-then 갈림길을 `state/inference_log.jsonl` 에 예측으로 1~3건 append(`state/inference_checklist.md` 먼저 읽고 `checklist_refs` 증빙, 검증 가능 수치+`horizon` 필수). 보통 `"slot":"18:00"`·`"horizon":"09:00"`. 내일 09시 routine 이 채점한다. 선제 액션은 §3-1·action_ladder Tier 0(준비)만(마감 후 신규매매 금지).
- **선제 커밋 적재(pending_orders — `policy.proactive_inference`)**: 내일 if-then 중 **검증 가능한 수치 트리거**(가격 돌파/이탈)로 표현되는 분기를 `state/pending_orders.json` 의 `orders[]` 에 append(파일 상단 `schema` 참조 — `trigger.type` price_above/price_below, `valid_until`, `tier`, `inference_id`). 장중 모니터(`check_intraday_alerts.py`)가 트리거를 평가해 **카톡 신호만** 보내고, **체결은 다음 영업일 routine 이 §2-PRE 게이트 통과 후** 한다(마감 후 신규매매 금지 원칙 불변). Tier 2(공격·신규매수)는 `action_ladder.tier2_probe.enabled=false` 인 동안 **카톡 승인 후 반자동**. 이미 만료·체결된 주문은 status 정리. kill_switch=true 면 적재하지 않는다.

## 5. 18시 종합 리포트 작성 (시간대별 분리 — 종합 파일 생성)
**오늘 날짜의 18시 리포트 `reports/YYYY-MM-DD-18.md` 를 새로 생성** 한다 (이미 존재하면 덮어쓰기).
- 00/09/12/15 파일은 **절대 수정하지 않는다** (히스토리·자기보완 학습 재료).
- 18시 파일은 그 4개를 **종합·검증** 하는 별개 파일이다.
- 누락된 시간대가 있으면 본 리포트에서 "(N시 routine 미실행)" 으로 명시.

### 리포트 가독성 원칙 (작성 전 필독)
18시 리포트는 하루의 **대표 발행물**이다. 독자는 "오늘 처음 들어온 주식 초보 구독자" — 운영 기록이 아니라 **읽히는 블로그 글**을 쓴다.
1. **블로그 인트로가 최상단**: 머리말 바로 아래 `## 📝 오늘의 이야기` 산문 섹션. 다른 섹션을 안 읽어도 이 글만으로 하루가 완결되게 쓴다.
2. **오르내림에는 반드시 이유**: 지수·보유 종목의 등락은 `### 📈📉 오늘의 상승·하락 이유` 에서 "무엇 때문에(원인) → 어떤 경로로(메커니즘) → 그래서(판단)"를 출처와 함께 산문으로 쓴다. 원인을 못 찾으면 "원인 미확인"으로 명시(무출처 '기대감 추정' 금지 규칙 유지).
3. **싣지 않는 것** (state/·trade_log·커밋 로그에만 남긴다): git pull·스크립트 실행 로그, pre_trade_check/reconcile verdict 원문, source_provenance·web_verify 검증 과정 표(검증 **결론**은 머리말 출처 각주 1줄로 끝— "검증 로그" 섹션 금지), 정책 버전 번호(v2.x)·policy 키 이름·규칙 ID, heat·freshness·tier/stage·R/R 재조정 계산 과정 표 등 운영 지표 나열 — 행동을 바꾼 경우에만 해당 의견·액션의 사유 속에 사람 말로 한 줄 녹인다.
4. **파서 고정 문자열 (변형 금지)**: 슬롯 헤더 `## 📊 18:00 종합·확정 리포트` 와 `### 한눈에 보기` 는 카톡 알림(`scripts/send_kakao.py`)이, `- 오늘의 한줄평: ...` 행은 HTML 빌더(`scripts/build_html.py` og:description)가 파싱한다. 한눈에 보기 불릿은 `- 라벨: 값` 평문으로 쓰고 라벨에 굵게(`**`)를 쓰지 않는다 (특히 한줄평 라벨 뒤에는 반드시 콜론).
5. **용어는 처음 1회만 풀이**: 본문 첫 등장 시 괄호로 1줄. 같은 설명을 여러 섹션에서 반복하지 않는다.
6. **미검증 시세 단정·운영 용어 노출 금지**: 당일 미확인(직전 수집본) 지수·시세는 등락률을 사실처럼 단정 표기하지 말고 수치 옆에 "(전일 종가 기준, 당일 미확인)"을 붙인다. '한눈에 보기'에는 영문 운영 용어(stale·live_verify·web_verify·time_stop·mark-to-market·HTTP 403 등)를 쓰지 않는다 — 행동이 바뀐 경우에만 사람 말로 1줄. audit 이 자동 점검한다.

리포트 파일 양식:
```markdown
# 일일 리포트 — YYYY-MM-DD (요일) · 📊 18:00 종합·확정

> 시리즈 진행: 🌙 00:00 [✓/⚠️] → 🌄 06:00 [✓/⚠️] → 🌅 09:00 [✓/⚠️] → 🕛 12:00 [✓/⚠️] → 🔔 15:00 [✓/⚠️] → 📊 18:00 ✓ (확정)
> 오늘의 시간대별 파일: [🌙 자정](./YYYY-MM-DD-00.md) · [🌅 09:00](./YYYY-MM-DD-09.md) · [🕛 12:00](./YYYY-MM-DD-12.md) · [🔔 15:00](./YYYY-MM-DD-15.md)
> 마지막 갱신: YYYY-MM-DD HH:MM KST (18:00 — 일일 확정)
> ※ 종가 출처·신선도·검증 결론은 이 줄 하나로 끝낸다 (예: "종가: 스냅샷 17:55 수집, 2출처 일치 — 당일 확정값"). 학습·시뮬레이션 용도.

## 📝 오늘의 이야기 — 하루 종합

(그날을 정리하는 블로그 글 — 3~5문단 산문, 표·불릿 금지. 다른 섹션을 안 읽어도 이 글만으로 하루가 완결되게.)
- 1문단: 오늘 시장이 어떻게 시작해 어떻게 끝났는지 — 하루의 줄거리
- 2문단: 그 흐름을 만든 원인 — 가장 큰 이슈 1~2개를 "무슨 일 → 왜 → 우리 종목 영향" 순서로
- 3문단: 우리 계좌 이야기 — 오늘 무엇을 샀/팔았고(또는 왜 아무것도 안 했고) 자산이 어떻게 변했는지, 잘한 것과 아쉬운 것 하나씩
- 4문단: 내일의 관전 포인트로 맺는다
- 수치는 문장 안에 자연스럽게, 전문용어는 괄호 1줄 풀이

## 📊 18:00 종합·확정 리포트

### 한눈에 보기 (18:00)
- KOSPI 종가: XXXX.XX (전일 대비 ±X.XX%)
- 내 가상 자산: X,XXX,XXX원 (전일 대비 ±X.XX%, 누적 ±X.XX%)
- 오늘의 한줄평: (1줄, 하루 흐름을 응축)
- 단계 경보 현황: 🟢 N / 🟡 N / 🟠 N / 🔴 N (진입가 대비)
- 내일 액션 한 줄: ...

### 📈📉 오늘의 상승·하락 이유 (종가 확정)
이 리포트의 중심 섹션. 오늘의 등락을 **원인 → 메커니즘 → 판단** 구조의 산문(항목당 2~4문장)으로 설명한다. 근거 출처(언론사·게재일) 필수, 원인이 매크로(시장 전체)/섹터(업종)/개별(그 종목만) 중 어디인지 문장에 밝힌다.
- **KOSPI가 오른/내린 이유**: 외국인·기관 수급, 글로벌 영향까지 포함해 2~4문장
- **[보유 종목]이 오른/내린 이유**: 종목별 1항목씩 — 시장과 같이 움직였는지(동행) 혼자 움직였는지(차별화), 오늘 나온 종목 뉴스·공시가 있으면 여기서 풀이
- **(체결이 있었던 날) 그 매매의 배경**: 왜 그 시점에 사고/팔았는지 1항목

### 종목별 종가 점검
각 종목마다:
#### [종목명]([티커])
- 종가: XX,XXX원 (전일 대비 ±X.XX%) / 진입가 / 목표가 / 손절가
- 📰 뉴스 반영 추정 목표 매도가: 해당 종목 `state/target_estimate.json.estimates[].news_target_line` 한 줄을 그대로 — 직전 리포트 대비 변동(Δ)·원인 뉴스 포함 (참고 추정 — watchlist 목표가를 대체하지 않는다)
- 목표가 대비 괴리: ±X.X% — 오차 ±5% 초과면 사유를 매크로/섹터/개별/가정오류 중 1개로 분류해 1줄
- thesis 상태: 🟩 intact / 🟧 weakening / 🟥 invalidated — (intact 가 아니면 충족된 조건 1줄. `thesis` 필드 있을 때만)
- 18시 의견: 매수 추가 / 홀드 / 비중 축소 / 매도 — 사유 1줄 (목표가·손절가를 바꿨으면 변경 전→후와 이유 포함)
- 판단 뒤집을 신호: watchlist `thesis.invalidation[]` 중 지금 가장 주시할 조건 1개를 사람 말로 — "○○이 확인되면 이 의견을 뒤집는다" (`thesis` 없으면 생략)
- 초보자 한줄: 이 종목을 왜 들고 있는지 / 왜 파는지 / 사업 모델 한 줄

### 📰 뉴스 반영 매매가 (목표 매도가·신규진입 상한가, 참고 추정)
(`state/target_estimate.json.report_section_md` 의 "### 📰 뉴스 반영 매매가" 마크다운을 **그대로 붙여넣는다** — 보유·후보 종목 추정 목표 매도가 + 신규진입 상한가(R/R 진입 상한)·현재가 위치(🟢진입가능/🟡진입주의=falling knife/🔴상회) + 직전 리포트 대비 변동·원인 뉴스. watchlist 실제 매매가를 대체하지 않는 참고 레이어다 — 내일 09시 신규 진입 후보의 진입 타이밍 판단에 쓴다. 신규진입 상한가는 적정가치가 아니라 R/R 진입 상한이며, 현재가보다 낮으면 '신규 진입엔 업사이드가 얇다'는 신호이지 고평가 판정이 아니다. **차단 게이트가 아닌 진입 타이밍 참고**다(실제 신규 진입 차단은 score_candidates estimate_gate=기대수익<0). 보유 종목 옆 🔴는 청산 신호가 아니고, 앵커가 현재가 폴백인 종목은 상한가가 `—`로 보류된다.)

### 가상 포트폴리오·주간 목표
| 항목 | 값 |
|---|---|
| 시작 자본 | 5,000,000원 |
| 현재 평가금액 (이 중 현금 X,XXX,XXX원) | X,XXX,XXX원 |
| 누적 수익률 | ±X.XX% |
| 같은 기간 KOSPI | 오늘 ±X.XX% · 이번 주 ±X.XX% (내 자산 주간 대비 ±X.Xp) |
| 실현 / 미실현 손익 | ±XXX,XXX원 / ±XXX,XXX원 |
| 승률 | X/X (XX%) |
| 이번 주 목표 자산 | X,XXX,XXX원 (부족 X,XXX,XXX원) |
| 주간 목표 판정 | 달성 가능 / 공격적 재조정 필요 / 리스크 축소 우선 |

오늘의 가상 체결 내역 (있다면 표로):
| 시각 | 종목 | 매수/매도 | 가격 | 수량 | 사유 |

### 하루 의사결정 복기 (09→12→15→18)
시간 순으로 오늘 판단을 검증한다 (각 시간대 파일을 직접 참조, 각 1~2줄):
- 09시 결정 → 정당했는가?
- 12시 단계 경보 대응 → 적절했는가?
- 15시 익일 후보 메모 → 종가로 봤을 때 여전히 유효한가?
- 결론: 어디서 좋았고 어디서 실수했는가 (1줄)

### 오늘 배운 것 (자기보완 노트)
- 오늘 적용된 교훈: 기존 lessons.md 항목이 **오늘 판단을 실제로 바꾼** 경우 "어떤 교훈 → 오늘 어떤 판단" 1줄 (예: "갭다운 버퍼 룰(5/22 교훈) → 자정 갭 예측 -2%p 하향 적용"). 없으면 "오늘 판단을 바꾼 기존 교훈 없음" — 자기보완 루프가 작동하는지 매일 확인하는 줄
- 오차 발생 종목: ... (사유 분류)
- lessons.md 추가 교훈 1~3줄
- 누적 패턴 경고 (있다면)
- weekly_plan에 반영한 watch_items / thesis 변화 1~3줄

### 내일 액션 플랜
- 09시 점검 종목: ...
- 신규 후보 자리: (청산 발생 시) — 어떤 섹터·테마
- 다가오는 매크로 이벤트
- 주간 목표 관점 액션: 현금 활용 / 보유 유지 / 비중 축소 / 목표 재조정 중 1개

내일 시나리오 (if-then — 가장 가능성 높은 갈림길 2~3개만. 다음날 09시가 조건 충족 여부를 판정해 그대로 실행·검증한다):
| 조건 (이것이 보이면) | 행동 (이렇게 한다) |
|---|---|
| 예: 미국 CPI가 예상치 상회 | 신규 진입 보류 유지, 보유 종목 손절 이격 재확인 |
| 예: 삼성전자 347,800원(트레일링 임계) 종가 돌파 | 트레일링 스톱 활성화 기록 |

---

## ⚠️ 위험·매매 시그널 시각화 (종가 기준)
```
[종목명]([티커]) 진입 XX,XXX원 / 종가 XX,XXX원
손절 ┃━━━━━━━━━●━━━━━━━━━━━━━━━━━━┃ 목표
     (-X.X%)  종가  (+X.X%)
🟢 안전 / 🟡 주의 / 🟠 경보 / 🔴 손절
오늘 단계 이동: 09→18 단계 변화 / 트레일링 스톱 활성 여부
```

---

## 🎓 오늘의 학습 노트 (초보자용)
- **포인트 1~3개**: 오늘 하루에서 가장 인상 깊은 시장 메커니즘·의사결정 원칙을 각 2~3줄로 (예: 목표가 오차 분류가 내일 추천에 어떻게 반영되는지)
- **새 용어 3~6개**: 본문에 처음 등장한 용어만 1줄씩 (예: **트레일링 스톱** — 가격이 오르면 손절선도 따라 올리는 동적 손절. 번 이익을 지키며 추세를 더 탄다)

---

### 면책
본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
```

**중요**:
- 구버전 양식의 "오늘 시장은 어땠을까?(초보자 설명)" 섹션은 폐지 — "📝 오늘의 이야기"가 그 역할을 한다. "가상 포트폴리오 시뮬레이션"과 "주간 목표 대시보드" 두 표는 "가상 포트폴리오·주간 목표" 한 표로 통합됐다 (현재 자산 등 중복 행 제거).
- "🔍 검증 로그"·"오차 검증 게이트 표"·"자산 변화 비교 표" 류의 운영 섹션을 임의로 추가하지 않는다 — 해당 내용은 산문 1줄 또는 state/ 파일로 충분하다.

## 6. 사용자에게 보내는 요약 (대화창 출력)
리포트 파일 경로 + 5~7줄 요약:
- 오늘 자산 변화
- 종목별 한줄 의견
- 오차가 컸던 종목과 분류
- 내일 액션 한 줄

## 7. 규칙
- **검색 시세는 근사값** — 리포트 머리말 각주 1줄로만 명시하고 본문 수치마다 반복하지 않는다
- 종가 데이터가 출처별로 다르면 가장 보수적 값 채택
- lessons.md 압축 체계(`policy.context_budget`): ✅codify 완료(policy/prompts/CI 반영) 항목의 본문은 `state/lessons_archive.md` 로 이관하고 lessons.md 에는 헤딩·분류·요약·codify 참조만 남긴다 — 미반영·진행 중 교훈과 누적 패턴 카운터는 절대 건드리지 않는다. 18시는 신규 항목 추가만, 이관은 sunday_policy_review 가 codify 확정 시 수행
- 모든 의사결정은 trade_log.jsonl에 라인으로 남기 (감사 추적성)

## 8. 상태 영속화 (git commit & push) — 가장 중요
모든 작업 종료 직전 반드시 수행. 리포트·포트폴리오·learnings 모두 푸시되어야 다음날 09시 routine이 이어받을 수 있다.
```
git add config/ state/ reports/
git -c user.name="kospi-autoflow-bot" -c user.email="hjlee8090@gmail.com" \
    commit -m "report: YYYY-MM-DD 일일 리포트 확정 + lessons 갱신" || true
git push origin HEAD:main || git push origin HEAD:master
```
- 푸시 실패 시 사용자에게 강하게 경고 (자기보완 루프가 끊김)
- **커밋 메시지 프리픽스 `report:` 는 카톡 알림에서 "18시 종합 리포트" 메시지를 트리거한다 (`scripts/send_kakao.py`의 `is_report` 분기).**
