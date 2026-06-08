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
- 각 종목에 대해:
  - **종가 vs 목표가 괴리(%)** 계산
  - 정책상 허용 오차 `tolerance_band_pct = 5%` 이내인지 판정
  - 초과 시 사유를 4분류 중 1개로 분류: `매크로` / `섹터` / `개별` / `가정오류`
- 손절가 / 목표가 도달했다면 **종가 기준 가상 청산 체결** 처리
  - 매도가 = 종가 × (1 - slippage 0.002 - tax 0.0018 - commission 0.00015)
  - `portfolio.json`의 cash·positions·realized_pnl·win/loss_count 갱신
  - `state/trade_log.jsonl`에 라인 추가. **(v2.3 장중 시간 규칙)** 18시는 장 마감 후이므로 이 청산은 마감 동시호가(15:30)에 일어난 것으로 본다:
    - `ts` 는 routine 실행 시각(18:00)이 아니라 **정규장 마감 시각 `YYYY-MM-DDT15:30:00+09:00`** 로 기록한다 (반장이면 그 close).
    - `execution_venue":"closing_auction"` 을 **반드시** 포함한다. 이것이 없으면 `scripts/check_trade_log_gate.py` 가 "정규장 밖 체결"로 CI FAIL 시킨다 (`policy.market_hours.trade_timing_gate`).
    - 예: `{"ts":"2026-06-01T15:30:00+09:00","action":"SELL_ORANGE_STOP","ticker":"...","execution_venue":"closing_auction","price_source":"snapshot_fresh|web_verified","close_price":...,"execution_price":...,"reason":"orange 단계 종가 확정 — ..."}`
  - **장중에 손절선을 이미 통과한 종목**은 09/12/15 routine 에서 실시간 체결됐어야 한다 — 18시는 그날 종가로 비로소 손절/목표에 도달한 분만 종가 청산한다.

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
- `capital_plan.cash`, `cash_weight_pct`, `invested_weight_pct`
- 각 `weekly_thesis`의 오늘 판정: 강화 / 유지 / 약화 / 무효화 후보
- `watch_items`: 내일 00시/09시가 이어받아야 할 뉴스·가격·수급 트리거
- `daily_bridge.18:00`에 오늘 요약 1줄 추가 또는 갱신

보유 종목이 기존 목표가에 모두 도달해도 주간 목표에 부족하면, 18시 리포트의 "내일 액션 플랜"에 **현금 활용 후보 / 목표 현실화 / 리스크 축소** 중 하나를 반드시 선택해 적는다.

## 2-2. R/R 1.2 미만 보유 종목 재조정 (의무)
종가 평가 후 보유 종목 각각의 R/R = (target_price - close) / (close - stop_price) 를 계산한다.
- R/R < `policy.reward_risk_management.min_reward_risk_ratio_for_new_entry` (=1.2) 인 종목은 다음 중 하나를 **오늘 18시 안에** 결정해 watchlist 코멘트에 명시한다:
  - (a) 목표가 재조정 — 현재 가격·촉매·저항선 기반 재산정. **재산정 후 컨센 교차검증**(`policy.consensus.target_cross_check`): 새 목표가가 `state/consensus.json` 컨센 목표주가 × 1.15 초과면 정당화 근거를 comments 에 적거나 컨센×1.15 로 상한(컨센 stale/없음/low 면 생략).
  - (b) 손절가 상향 — 트레일링스톱 활성화 또는 가격 진입
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

## 4. 다음 거래일 액션 결정
- 손절·목표 도달로 청산된 종목 자리 → **다음 09시 신규 추천 후보** 선정 메모를 watchlist.json의 `next_day_plan` 필드에 기록
- 청산 없이 유지되는 종목은 그대로 watchlist에 둠
- **📅 임박 촉매 반영** (`config/catalysts.json` 있을 때): `generated_events`+`manual_events` 중 **D-3 이내** 이벤트를 점검. 다음 거래일에 실적발표·매크로 high 촉매가 걸린 **보유 종목은 추가매수 금지·변동성 경고**, **후보는 발표 후로 신규 진입 이연**을 `next_day_plan` 에 1줄로 기록. 추정일(`confirmed=false`)은 웹검색 확정 시도 후 `manual_events` 로 승격.
- lessons.md의 누적 패턴 카운터가 동일 섹터 손실 3회 이상이면 → 해당 섹터 회피 룰을 watchlist.json의 `avoid_sectors`에 추가

## 5. 18시 종합 리포트 작성 (시간대별 분리 — 종합 파일 생성)
**오늘 날짜의 18시 리포트 `reports/YYYY-MM-DD-18.md` 를 새로 생성** 한다 (이미 존재하면 덮어쓰기).
- 00/09/12/15 파일은 **절대 수정하지 않는다** (히스토리·자기보완 학습 재료).
- 18시 파일은 그 4개를 **종합·검증** 하는 별개 파일이다.
- 누락된 시간대가 있으면 본 리포트에서 "(N시 routine 미실행)" 으로 명시.

리포트 파일 양식:
```markdown
# 일일 리포트 — YYYY-MM-DD (요일) · 📊 18:00 종합·확정

> 시리즈 진행: 🌙 00:00 [✓/⚠️] → 🌅 09:00 [✓/⚠️] → 🕛 12:00 [✓/⚠️] → 🔔 15:00 [✓/⚠️] → 📊 18:00 ✓ (확정)
> 오늘의 시간대별 파일:
> - [🌙 자정](./YYYY-MM-DD-00.md)
> - [🌅 09:00](./YYYY-MM-DD-09.md)
> - [🕛 12:00](./YYYY-MM-DD-12.md)
> - [🔔 15:00](./YYYY-MM-DD-15.md)
> 마지막 갱신: YYYY-MM-DD HH:MM KST (18:00 — 일일 확정)
> ※ 모든 시세·지수는 웹검색 근사값. 학습·시뮬레이션 용도.

## 📊 18:00 종합·확정 리포트

### 한눈에 보기 (18:00)
- KOSPI 종가: XXXX.XX (전일 대비 ±X.XX%)
- 내 가상 자산: X,XXX,XXX원 (전일 대비 ±X.XX%, 누적 ±X.XX%)
- 오늘의 한줄평: (1줄, 하루 흐름을 응축)

### 오늘 시장은 어땠을까? (초보자 설명)
- 매크로 이슈 1~2개를 **용어 풀이와 함께** 설명
- 외국인/기관 수급 한 줄
- 우리 보유 종목 섹터와 관련된 산업 이슈

### 종목별 종가 점검
각 종목마다:
#### [종목명]([티커])
- 종가: XX,XXX원 (전일 대비 ±X.XX%)
- 진입가 / 목표가 / 손절가
- 목표가 대비 괴리: ±X.X% — (오차 ±5% 이내인가? 초과면 사유)
- **thesis 상태**: 🟩 intact / 🟧 weakening / 🟥 invalidated — (status 가 intact 가 아니면 충족된 invalidation 조건·type 1줄. `thesis` 필드 있을 때만)
- 오늘의 주요 뉴스 2개 (1줄씩, 검색 출처)
- 18시 의견: 매수 추가 / 홀드 / 비중 축소 / 매도
- **초보자 한줄**: 이 종목을 왜 들고 있는지 / 왜 파는지 / 사업 모델 한 줄

### 가상 포트폴리오 시뮬레이션
| 항목 | 값 |
|---|---|
| 시작 자본 | 5,000,000원 |
| 현재 평가금액 | X,XXX,XXX원 |
| 현금 | X,XXX,XXX원 |
| 누적 수익률 | ±X.XX% |
| 실현 손익 | ±XXX,XXX원 |
| 미실현 손익 | ±XXX,XXX원 |
| 승률 | X/X (XX%) |

### 주간 목표 대시보드
| 항목 | 값 |
|---|---|
| 이번 주 시작 자산 | X,XXX,XXX원 |
| 이번 주 목표 자산 | X,XXX,XXX원 |
| 현재 자산 | X,XXX,XXX원 |
| 목표까지 부족 금액 | X,XXX,XXX원 |
| 현재 현금 비중 | XX.X% |
| 보유 종목 목표가 도달 시 예상 자산 | X,XXX,XXX원 |
| 주간 목표 판정 | 달성 가능 / 공격적 재조정 필요 / 리스크 축소 우선 |

오늘의 가상 체결 내역 (있다면 표로):
| 시각 | 종목 | 매수/매도 | 가격 | 수량 | 사유 |

### 09→12→15→18 의사결정 흐름 검증
하루 동안 한 의사결정을 **시간 순으로 검증** (각 시간대 파일을 직접 참조):
- 09시 결정 → 정당했는가? (3줄)
- 12시 단계 경보 대응 → 적절했는가? (3줄)
- 15시 익일 후보 메모 → 18시 종가로 봤을 때 여전히 유효한가? (3줄)
- 결론: 어디서 좋았고 어디서 실수했는가 (1줄)

### 오늘 배운 것 (자기보완 노트)
- 오차 발생 종목: ... (사유 분류)
- lessons.md 추가 교훈 1~3줄
- 누적 패턴 경고 (있다면)
- weekly_plan에 반영한 watch_items / thesis 변화 1~3줄

### 내일 액션 플랜
- 09시 점검 종목: ...
- 신규 후보 자리: (청산 발생 시) — 어떤 섹터·테마
- 다가오는 매크로 이벤트
- 주간 목표 관점 액션: 현금 활용 / 보유 유지 / 비중 축소 / 목표 재조정 중 1개

---

## ⚠️ 위험·매매 시그널 시각화 (종가 기준)
```
[종목명]([티커]) 진입 XX,XXX원 / 종가 XX,XXX원
손절 -10% ┃━━━━━━━━━●━━━━━━━━━━━━━━━━━━┃ +10% 목표
          (-X.X%)  종가  (+X.X%)
🟢 안전 / 🟡 주의 / 🟠 경보 / 🔴 손절
오늘 단계 이동: 09→18 단계 변화 / 트레일링 스톱 활성 여부
```

---

## 🎓 오늘 배운 학습 포인트 3개 (초보자용)
1. **(주제 한 줄)**: 오늘 하루 흐름에서 가장 인상 깊은 시장 메커니즘 1개
2. **(주제 한 줄)**: 보유 종목 종가가 목표가/손절가와 어떻게 상호작용했는지
3. **(주제 한 줄)**: 자기보완 루프(목표가 오차 분류)가 내일 추천에 어떻게 반영되는지

---

## 📖 오늘 등장한 용어 (사이드박스)
- **목표가 오차 분류**: 실제 종가가 목표가 ±5%를 벗어났을 때 사유를 `매크로/섹터/개별/가정오류` 중 1개로 분류해 lessons.md에 기록 → 내일 추천에 자동 반영.
- **승률·실현/미실현 손익**: 승률=익절 횟수/전체 청산 횟수. 미실현은 아직 안 판 평가차익, 실현은 청산 완료된 차익.
- **트레일링 스톱 활성**: 목표가 70% 도달 후 -3% 동적 손절이 자동 작동. 이익을 일부 지키면서 추가 상승 가능성도 살림.
- (본문에 실제 등장한 것 위주, 5~8개)

---

### 면책
본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
```

## 6. 사용자에게 보내는 요약 (대화창 출력)
리포트 파일 경로 + 5~7줄 요약:
- 오늘 자산 변화
- 종목별 한줄 의견
- 오차가 컸던 종목과 분류
- 내일 액션 한 줄

## 7. 규칙
- **검색 시세는 근사값**임을 모든 수치에 명시
- 종가 데이터가 출처별로 다르면 가장 보수적 값 채택
- lessons.md는 누적될수록 무거워짐 → 6개월 이상 지난 항목은 18시 작업 중 점검만 하고 별도 압축은 향후 사용자 요청 시
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
