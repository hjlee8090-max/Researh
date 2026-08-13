# KOSPI 자기보완형 주식 오토플로우

500만원 가상 포트폴리오로 KOSPI 대형주 최대 6종목(`policy.position_sizing.max_positions`)을 중장기 운용하는 시뮬레이션 파이프라인.
매일 여러 번(00/06/09/12/15/18시) 자동으로 뉴스를 조사하고 의사결정을 갱신하며,
18시에 목표가 오차를 분석해 다음날 추천에 반영하는 **자기보완 루프**를 갖는다.

> 본 산출물은 학습·시뮬레이션 용도이며 실제 투자 권유가 아니다.

## 정책
- **종목군**: KOSPI 대형주(시총 상위) 중심
- **운용 기간**: 중장기 (스윙 ~ 수 주)
- **목표 수익**: 종목당 +10%
- **손절선**: 종목당 -10%
- **섹터**: 제한 없음
- **포트폴리오**: 500만원, 최대 6종목(`policy.position_sizing.max_positions`), 종목당 최대 35%(`max_position_weight_pct`), 현금 최소 5%(`min_cash_weight_pct`)
- **거래비용**: 슬리피지 0.2% + 거래세 0.18%(매도) + 수수료 0.015% (`policy.trading_cost`, 시뮬레이션)

## 디렉토리
```
config/
  policy.json              정책 파라미터 (목표/손절/비중)
  portfolio.json           현금·보유종목·평가금액
  watchlist.json           현재 추천 종목(최대 6종목 — policy.position_sizing.max_positions) + 진입가·목표가·손절가·코멘트
  weekly_plan.json         이번 주 thesis·watch_items·invalidation_triggers
  candidates.json          신규 진입 후보 목록 (fetch_market_data가 5거래일 추세 자동 수집 대상)
  universe.json            (v2.7) 신규 진입 후보의 모집단 — screen_universe.py가 상대강도+테마로 랭킹·승격/회전아웃 제안
  market_calendar.json     KRX 휴장일 + 장중 세션(정규장 09:00~15:30·동시호가) — 0-A 영업일·세션 가드
  catalysts.json           종목별 다가오는 촉매(실적발표·배당·매크로) 캘린더 — generated_events(법정기한 추정)+manual_events(웹검색 확정). D-day 경보·신규 진입 보류 (catalyst-calendar)
  news_impact.json         뉴스 유형별 주가 가산점 테이블(+manual_news 기록) — estimate_target_price.py 의 뉴스/촉매 프리미엄 입력
  news_keywords.json       뉴스 자동 분류 키워드 레지스트리(12개 유형과 1:1, 종목 별칭 포함) — fetch_news.py 입력. 키워드 보강=분류 보강
  news_history.json        백테스트용 라벨드 뉴스 타임라인(레포 운용 기록 추출) — backtest_target_model.py 입력
state/
  lessons.md               자기보완 학습 노트 (오차 사유 누적 — ✅codify 완료 항목 본문은 lessons_archive.md 로 이관)
  lessons_archive.md       응축된 lessons 항목의 전문 보존 (routine 은 읽지 않음 — 복기용)
  inference_log.jsonl      (선제적 추론 루프 Phase 1) 예측 원장 — 라인당 1예측(상황추론·예측·확신·선제액션·사후 채점결과). 핫패스 아님
  inference_scorecard.json score_inferences.py 채점 산출 — 슬롯·subject·확신구간별 적중률 + 결합 실현손익/PF + 미배치 forgone
  inference_checklist.md   추론 직전 먼저 읽는 응축 체크리스트(핫패스, 상한 40줄) — build_inference_checklist.py 가 lessons+scorecard 에서 파생
  pending_orders.json      (Phase 3) 조건부 사전주문(선제 커밋) — 18시가 작성, 06시가 미국장 마감 확정으로 트리거 값만 갱신(체결·status 변경 없음), check_intraday_alerts 가 장중 트리거 평가·카톡 신호만, 체결은 09시 routine 이 게이트 통과 후·Tier2 승인
  trade_log.jsonl          모든 의사결정 이력 (라인당 1 JSON)
  audit_log.jsonl          파이프라인 자동 점검 이력
  watchlist_archive.json   watchlist 에서 이관된 청산 종목 전체 기록 + 오래된 코멘트·상위 노트 (compact_state.py)
  watch_items_archive.jsonl weekly_plan.watch_items 만료분 보존 (compact_state.py)
  pending_orders_archive.jsonl (v2.32 P0) 종결 상태(expired/filled/cancelled/resolved_*) 7일+ 주문 보존 — routine 은 읽지 않음
  catalysts_archive.jsonl  (v2.32 P0) manual_events 과거 7일+ 이벤트 보존 (estimate 의 과거촉매 사용창 D-7 과 정렬)
  weekly_plan_archive.jsonl (v2.32 P0) weekend_review 날짜 키 14일+ 보존
  inference_log_archive.jsonl (v2.32 P0) 채점 완료 + 90일 경과 예측·결과 라인 보존 (스코어카드는 90일 롤링창)
  portfolio_history.jsonl  일일 equity 스냅샷 전체 이력 (config/portfolio.json 엔 최근 10개만)
  ratchet_shadow.json      (v2.20) 본전 래칫 스톱 그림자 관측 — track_ratchet_shadow.py 가 18시 종가 기준 stage·가상 breach·해방가능 heat 기록 (관측 전용, 체결 없음)
  ratchet_shadow_scorecard.json score_ratchet_shadow.py 채점 — 가상 breach 의 t+1/t+5 반사실 손익·noise율·실제 청산 대비 보호액 (일 20시 policy_review §1-8 승격 심사 입력)
  market_snapshot.json     fetch_market_data.py가 생성하는 다중출처 가격·5일추세 스냅샷 — GitHub Actions(fetch_prices.yml)가 수집·커밋해 추적됨(웹 세션 routine 의 1순위 출처)
  investor_flows.json      (2026-08-11 P0-3) KRX 투자자별 순매수 일별 — 시장(KOSPI)+보유·후보 종목, 외국인 streak(연속 순매수/순매도 일수)·transition(전환) 포함. fetch_flows.yml(평일 16:45 KST)이 수집·커밋, 06:30/18:00 슬롯이 읽음 — "반등 밴드 상향은 외국인 순매수 전환 확인 전제"(7/29 룰)의 판정 데이터
reports/
  YYYY-MM-DD-00.md         🌙 자정 글로벌 야간 리포트
  YYYY-MM-DD-06.md         🌄 미국장 마감 확정 리포트 (발화 06:30)
  YYYY-MM-DD-09.md         🌅 개장 점검 리포트
  YYYY-MM-DD-12.md         🕛 장중 점검 리포트
  YYYY-MM-DD-15.md         🔔 마감 임박 점검 리포트
  YYYY-MM-DD-18.md         📊 18시 종합·확정 리포트
  YYYY-MM-DD-audit.md      파이프라인 자동 감사 리포트 (평일 19:30)
  YYYY-MM-DD-saturday-review.md  토요일 사후분석
  YYYY-MM-DD-sunday-strategy.md  일요일 전략
  YYYY-Www-archive.md      일요일 21시 — 지난주 평일 30개 파일을 1개로 응축
prompts/
  0000_global.md           자정 글로벌 야간 점검
  0630_us_close.md         06시 미국장 마감 확정 (발화 06:30)
  0900_pre_market.md       09시 개장 점검
  1200_midday.md           12시 장중 점검
  1500_close.md            15시 마감 임박
  1800_report.md           18시 종합·확정 + 자기보완 루프
  saturday_review.md       토요일 사후분석
  sunday_strategy.md       일요일 다음주 전략
  sunday_policy_review.md  일요일 20시 정책·프롬프트 패치 리뷰 (lessons → policy 반영 점검)
  sunday_archive.md        일요일 21시 주간 archive (콘텍스트 정리)
  weekend_report.md        주말 노트
docs/
  file_references.md       파일 참조 구조 점검표 (어느 prompt/script가 어느 파일을 읽는지)
  github_mobile_pipeline.md
  weekend_dryrun_checklist.md  주말 routine 첫 실행 점검표
prompts/ (추가)
  earnings_preview.md      Phase 2 — 실적 발표 전 beat/inline/miss 시나리오 + 발표 후 자기채점 (이벤트 기반, 0900·1800 호출)
docs/ (추가)
  policy_changelog.md      policy.json changelog 전문 (policy 엔 최근 5건만 — compact_state.py 이관)
  plan_context_compaction.md  콘텍스트 압축·연결 보강 계획서 (2026-06-12)
scripts/
  fetch_market_data.py     네이버 + Yahoo Finance 다중출처 가격 수집 + 5거래일 추세 자동 산출
  fetch_catalysts.py       종목별 다가오는 촉매 추정 (정기보고서 법정기한 + DART list.json 보정) → config/catalysts.json
  fetch_consensus.py       증권사 컨센서스 수집 (FnGuide — 목표주가·투자의견·추정치) → state/consensus.json (Phase 2 earnings-preview 입력)
  compact_state.py         핫패스 콘텍스트 압축 — watchlist 청산종목·코멘트·상위노트/watch_items/history/changelog/종결 pending_orders/과거 manual 촉매/weekend_review 날짜키/채점완료 inference_log 를 archive 로 이관 (매일 19:00 KST weekly_compact.yml + 일 21시 archive routine + 수동, 멱등·--dry-run — v2.32 P0 확장)
  check_market_open.py     KRX 영업일/휴장일 판정 (exit 0=영업, 10=주말, 11=공휴일)
  check_market_session.py  KRX 장중 세션·체결모드 판정 (live/closing_price/none) — 18시 종가청산만, 마감후 신규진입 금지
  score_candidates.py      후보 종목 자동 점수화 (추세·신뢰도·thesis·악재) → 09시 routine 진입 후보 랭킹
  estimate_target_price.py 목표주가 추정 v1.1 — 밸류 밴드·컨센·테마(호라이즌할인·추세게이트)·뉴스/촉매(시간감쇠·기반영차감)·섹터 활발성 결합 → state/target_estimate.json
  fetch_news.py            종목 뉴스 자동 수집(Google News RSS 국문·영문+네이버 종목뉴스)·키워드 분류 → state/news_feed.json (fetch_news.yml 평일 07:30/17:40 KST)
  fetch_investor_flows.py  (2026-08-11 P0-3) KRX 투자자별 순매수 일별 수집(pykrx, KRX_ID/PW) → state/investor_flows.json (fetch_flows.yml 평일 16:45 KST)
  score_target_estimates.py 추정 vs 실현 주간 채점 + 뉴스 키워드 보강 점검 → state/estimate_scorecard.json (sunday_policy_review 0-C)
  fetch_history.py         백테스트용 장기 일봉(~2.5년) 수집 → state/price_history.json (fetch_history.yml 수동/push 트리거)
  backtest_target_model.py 목표주가 추정식 백테스트 — 충격-감쇠·이벤트 스터디·워크포워드 검증, v1.0 vs v1.1 비교 → state/backtest_target_model.json
  screen_universe.py       (v2.7/2.8) 모집단(universe.json) 상대강도+테마 랭킹 → 승격/회전아웃 제안 + 섹터별 몰입(sector_rotation·avoid_reentry) → state/universe_screen.json
  reconcile_portfolio.py   trade_log ↔ portfolio.json cash·positions·realized_pnl 정합성 검증
  sync_watchlist.py        (2026-07-08 신설) watchlist 보유 종목 필드(shares_held·stop/target)를 portfolio·exit_levels 정본과 동기화 (18시 EOD·수동, 멱등·--dry-run)
  build_lessons_index.py   lessons.md 분류·룰 자동 인덱싱 → sunday_policy_review 1차 입력 (선제 추론 루프 위해 '다음 추론 시 고려' 라벨도 캡처)
  score_inferences.py      (선제 추론 루프) 예측 vs 실측 채점 — rule_attribution 손익 결합 → state/inference_scorecard.json (18시·일 20시)
  build_inference_checklist.py (선제 추론 루프) lessons+scorecard → state/inference_checklist.md 응축(상한 40줄) — 다음 추론 직전 입력
  track_ratchet_shadow.py  (v2.20) 본전 래칫 스톱 그림자 트래커 — 18시 EOD 실행, 이익 +1×ATR 시 스톱→본전 래칫의 가상 stage·breach·해방 heat 기록 → state/ratchet_shadow.json (관측 전용)
  score_ratchet_shadow.py  래칫 그림자 채점 — 가상 breach t+1/t+5 반사실 손익·noise율·보호액 → state/ratchet_shadow_scorecard.json (일 20시 policy_review 0-E)
  mark_to_market.py        (2026-08-05 신설) portfolio.json 평가 필드를 스냅샷 시세로 갱신 — 카톡·인덱스 평가금액의 정본. fetch_prices 워크플로 + 09/12/15/18시 routine 실행 (원장 사실 불변, --dry-run·--selftest)
  compute_dynamic_bands.py (2026-08-05 신설, policy.dynamic_reprice) ATR×레짐 tier 매수/매도 참조 밴드 + 재산정 신호(목표 소진·참조 괴리·손절폭 과대) → state/dynamic_bands.json — 목표가 경직성 보완, 매 슬롯 재산정·이월 금지
  audit_pipeline.py        파이프라인 무결성 점검 (의존성 0)
  write_audit_report.py    audit 결과 + 자동 수정 → 사람 친화 리포트
  build_html.py            reports/*.md → _site/*.html (GitHub Pages) — 헤드라인 평가금액은 빌드 시점 스냅샷 마크 값
  send_kakao.py            카카오 '나에게 보내기' 알림 — 평가금액·보유 등락률은 발송 시점 스냅샷 마크 값(+시세 기준시각 표기)
  kakao_oauth_helper.py    1회 refresh_token 발급
```

## 스케줄 (Asia/Seoul)
**평일** — 시간대별 분리 파일 6개 생성 (한 파일 = 한 슬롯)

| 시각 | 내용 | 생성 파일 |
|------|------|------------|
| 00:00 | 글로벌 야간 점검 (미국장·유럽장·환율·원자재) → 보유 종목 야간 영향 매핑·한국 개장 갭 예측 | `reports/YYYY-MM-DD-00.md` |
| 06:30 | 미국장 마감 확정 → 자정 예측 확정·정정(진행형 지정학 역전 봉합), 개장 동시호가(08:30) 전 갭 예측·pending_orders 트리거 갱신 (발화 06:30, 슬롯·파일명은 `06` 유지·매매 없음). **발화 요일은 화~토** — 직전 밤 미국 세션이 있는 아침에만 발화(월요일 제외, 토요일은 금요일 마감 정리 축약) | `reports/YYYY-MM-DD-06.md` |
| 09:20 | 자정·06시 예측 검증 + 미국장 마감(05:00)까지 흐름 + 한국 개장 인사이트 (발화 09:20, 슬롯·파일명은 `09` 유지) | `reports/YYYY-MM-DD-09.md` |
| 12:00 | 장중 점검 (단계 경보·함정 패턴 cross-check) | `reports/YYYY-MM-DD-12.md` |
| 15:00 | 마감 임박 점검, 종가 임박치로 1차 검증, 익일 09시 액션 후보 정리 | `reports/YYYY-MM-DD-15.md` |
| 18:00 | (마감 후) 종가 확정 → 목표가 오차 판정 → lessons.md 갱신, 포트폴리오 평가, **종가 청산만**(ts=15:30·closing_auction, 신규진입은 09시 이연), 종합 리포트 | `reports/YYYY-MM-DD-18.md` |

**주말**

| 시각 | 내용 | 생성 파일 |
|------|------|------------|
| 매일 00:00 | 글로벌 야간 점검은 **주말에도 발화** — 단 일·월 자정은 미국 현물장 휴장이라 주말 자정 모드(주말 지정학·보유 종목 뉴스 중심, 미국 지수는 "(금요일 종가)" 표기 강제) | `reports/YYYY-MM-DD-00.md` |
| 토 06:30 | 금요일 미국 세션 마감 확정 (06시 슬롯의 토요일 발화분 — 한국 휴장이라 §0-B 축약 모드: 갭 예측·주문 갱신 없이 마감 정리만) | `reports/YYYY-MM-DD-06.md` |
| 토 18:00 | 지난주 사후분석 | `reports/YYYY-MM-DD-saturday-review.md` |
| 일 18:00 | 다음주 전략·weekly_plan 갱신 | `reports/YYYY-MM-DD-sunday-strategy.md` |
| **일 21:00** | **지난주 평일 30개 시간대별 파일 → 1개 archive 응축** (콘텍스트 절약) | `reports/YYYY-Www-archive.md` |

> 각 시간대 파일은 **자기 슬롯만 담는다**. 이전 시간대 결론은 "📝 오늘의 이야기" 첫 문단에서 산문으로 1~2문장 이어받는다(구버전 "이어받기 박스"는 폐지). **2026-07-04 개편: '한눈에 보기'(오늘의 액션 포함)가 본문 최상단, 이야기는 그 직후** (docs/report_contract.md §8). 이전 파일은 **절대 수정하지 않음** (히스토리·자기보완 학습 재료 보존).

## 수익형 전략 엔진 (듀얼모멘텀 로테이션 — 백테스트 검증)
레포 내 실제 일봉(30종목 × 592거래일)으로 검증한 규칙기반 전략. **현 계좌가 진 단 하나의 이유는
강세장(KOSPI +198%) 내내 현금을 들고 있었던 것** — `web_verify` 차단 시 자동 마비되는 구조 결함.
- `scripts/backtest_strategy.py` — 그리드+walk-forward 백테스트 → `state/backtest_strategy.json`
- `scripts/momentum_signal.py` — 오늘 목표 바스켓(추세 상위 10종목 동일가중) → `state/momentum_signal.json`
- 권장안(Top10·월간리밸·MA200·항시투자): 총수익 **+313%**·Sharpe **2.34** 로 벤치마크(+198%·2.24) 상회, 낙폭 동등.
- 설계·결과·한계 전문: `docs/strategy_momentum.md`. **핵심 교정 = "현금 탈출, 추세에 태우기".**

## 자기보완 루프
1. 18시 프롬프트가 watchlist의 **각 종목 실제 종가 vs 목표가** 비교
2. ±5% 이내면 OK, 초과면 사유 분류
   - `매크로` (환율/금리/지수)
   - `섹터` (업종 이슈)
   - `개별` (실적/공시/뉴스)
   - `가정오류` (애널리스트 가정 자체가 틀림)
3. `state/lessons.md`에 누적
4. **모든 추천·점검 프롬프트는 동작 직전 lessons.md를 먼저 읽고 동일 실수를 피한다**

## 선제적 추론 루프 (Proactive Inference Loop — Phase 1 관측 중)
자기보완 루프(결과→반응)와 **대칭**으로, 종합 상황을 추론해 **결과를 미리 예측하고 (보수적으로) 먼저 액션**하는 루프.
빗나간 예측은 "다음엔 무엇까지 볼지"를 구조화해 다음 추론에 환류한다. 설계 전문: `docs/plan_proactive_inference.md`.
1. **추론(INFER)**: 각 슬롯이 `inference_checklist.md`(과거 빗나간 요인)를 먼저 읽고 검증 가능한 예측을 `inference_log.jsonl`에 적재
2. **선제 액션(ACT)**: 확신·데이터품질에 따라 액션 사다리(`policy.proactive_inference.action_ladder`) Tier 0(준비)~1(리스크감소)~2(probe). **"먼저 액션"은 추측 베팅이 아니라 기존 게이트를 전부 통과하는 probe·리스크감소로 제한**
3. **채점(SCORE)**: `score_inferences.py`가 예측 vs 실측을 채점하되 **적중률이 아닌 실현 손익·기회비용(rule_attribution forgone)** 중심. 보류(미배치)도 그림자 예측으로 채점 — false negative 를 1급 오차로 본다
4. **학습(LEARN)**: miss → lessons `선제추론오차`/`기회비용오차` + `다음 추론 시 고려` → `build_inference_checklist.py`가 응축 → 다음 추론이 읽음
> **Phase 1 은 관측 전용(행동 변화 0)**. 채점 적중률·손익이 입증돼야 Tier 2(공격)를 개방한다(`action_ladder.tier2_probe.open_when`).

**선제 커밋(Phase 3 — 속도 엣지의 본체)**: 18시가 내일 if-then 을 `pending_orders.json` 에 **검증 가능한 수치 트리거**로 적재 → 장중 `check_intraday_alerts.py`(평일 30분 간격)가 트리거를 평가해 **카톡 신호만** 보냄 → **체결은 다음 routine 이 `pre_trade_gate` 통과 후**(묵은 가격 선체결 금지 불변). 결정을 밤에 앞당기되 실행 안전은 그대로 — "18시→09시 이연 구멍"을 닫는다. **안전 못**: 장중은 신호만(체결 X)·Tier 2 신규매수는 카톡 승인 후 반자동·`policy.proactive_inference.kill_switch=true` 로 즉시 전체 정지. **(2026-08-11 P1-c)** 같은 모니터가 **장중 KOSPI 지수 쇼크(|±3%|/|±5%| 사이드카급)도 감지**해 카톡 경보 — 발동일 12/15시 슬롯은 오전 예측 유지 금지·재예측 의무(`policy.proactive_inference.intraday_shock_rejudgment`, "사이드카 후 15시 적중률 급상승" 8회 반복의 룰화).

## 콘텍스트 예산 (v2.13 — `policy.context_budget`)
매 routine 이 의무로 읽는 핫패스 파일(watchlist·policy·weekly_plan·portfolio·lessons)이 무한 누적되면
콘텍스트 오버 → 규칙 누락·판단 열화로 이어진다 (2026-06-12 진단: 의무 적재 ~500KB, watchlist 1,945줄).
- **원칙**: 학습 재료는 삭제하지 않고 **archive 로 이관** — git + archive 파일에 전문 보존, 핫패스에서만 제거
- **압축기**: `scripts/compact_state.py` (매일 19:00 KST `weekly_compact.yml` + 일요일 21시 archive routine, 멱등·`--dry-run`)
  - watchlist: 청산 종목 → `state/watchlist_archive.json` (재발굴은 universe→screen_universe 경로 — candidates 자동 재등록 금지), 보유 코멘트 최근 12개 + 상위 comments·cross_check_notes 최근 12건 유지
  - weekly_plan.watch_items ≤15개 (18시·일요일 전략이 재작성으로 1차 정리 — 초과분 archive) + weekend_review 날짜 키 최근 14일
  - portfolio.history 최근 10개 (전체는 `state/portfolio_history.jsonl`)
  - policy.changelog 최근 5건 (전문은 `docs/policy_changelog.md`)
  - (v2.32 P0 — `docs/plan_removal_exclusion.md`) pending_orders 종결 7일+·catalysts manual 과거 7일+·inference_log 채점완료 90일+ 이관, 체크리스트 바이트 캡 집행. **누적이 자동이면 제거도 자동** — 압축 담체를 주 1회에서 매일로 승격
- **감시**: `audit_pipeline.audit_context_budget` 가 크기 임계 초과를 매일 WARN (매매 룰 래칫 감시와 동형의 크기 래칫 감시)
- lessons.md 는 ✅codify 확정 항목만 본문을 `state/lessons_archive.md` 로 이관 (sunday_policy_review §1-6 — 카운터·미반영 항목 불변)

## 목표주가 추정 레이어 (estimate_target_price.py, v1.1)
파이프라인의 흩어진 신호를 하나의 식으로 결합해 **12개월 내 도달 가능한 대략적 목표가(원)** 를 산출한다:

```
추정목표가 = 기준가 × (1 + 추세게이트×(테마P + 양뉴스P) + 음뉴스P + 섹터P + 모멘텀틸트) → 천장 캡
```

v1.1은 삼성전자·현대차 2.5년(592거래일) 백테스트로 보정됐다
(`reports/2026-06-10-target-model-backtest.md`): ①추세 게이트 — 테마·호재는 자금이 따라오는
주도주(KOSPI 대비 60일 초과수익 ≥+10%p)에서만 전액 반영(후행주 0.3배, 60일 적중률 25.9%→70.4%)
②뉴스 기반영분 차감 — 뉴스가 이미 움직인 초과수익을 가산점에서 빼 이중계상 차단
③모멘텀 틸트 재보정 — 초과수익 [10,30) 구간 최고·극단(≥30) 둔화 + 52주고점 근접 가점.

v1.2는 뉴스 입력을 자동화했다: `fetch_news.py`(평일 07:30/17:40 KST)가 Google News RSS와
네이버 종목뉴스를 수집해 `config/news_keywords.json`의 유형별 키워드로 분류 →
`state/news_feed.json`. 자동 분류 항목은 confidence factor(0.6) 할인으로 가산점에 반영되고,
검증을 거친 manual_news 가 항상 우선한다. **유형 미매칭 기사도 unclassified 로 보존**되므로
라우틴이 검토해 manual_news 로 승격하거나 키워드를 보강한다(재현율 우선 — 놓친 뉴스는
sunday_policy_review 에서 키워드 레지스트리에 반영).

v1.3은 해외뉴스와 연속 섹터값을 더했다(`reports/2026-06-11-sector-global-research.md`):
①해외뉴스 — 영어 쿼리 8종(채널·대상 종목 태깅) 수집·분류 후 **채널 전이계수**(오버나이트 β
실증: 동종 0.45·고객 0.35·매크로 0)로 할인해 가산. 교차섹터 전이 없음(β≈0)이 실증돼 쿼리별
affects_tickers 매핑이 강제된다. ②**섹터값** — 섹터 거래대금 점유율(자금 집중도 0.7) +
상대모멘텀(0.3)의 연속값으로, 섹터 프리미엄 = 최대 8% × (0.5×몰입 사다리 + 0.5×섹터값) 블렌드
(60일 예측력 사다리 단독 대비 +40%, 조선 0.521·AI메모리 0.451).

v1.4는 자기보완 루프에 편입됐다: 추정 스냅샷이 `state/target_estimate_log.jsonl` 에 매 실행
적재되고, `score_target_estimates.py` 가 추정 vs 실현(5/20/60거래일)을 채점해
`state/estimate_scorecard.json` 을 만든다. sunday_policy_review(일 20시)가 0-C 단계에서
실행해 §1-5 로 점검한다 — 적중률 악화 시 추정식 패치 후보 상정(단 파라미터 변경은 백테스트
재실행 근거 필수), unclassified/오분류 검토 → manual_news 승격·키워드 보강 의무.

v1.5에서 매수 프로세스에 연결됐다(policy v2.12 `entry_filters.estimate_gate`):
추정 기대수익이 음(-)인 종목(등급 A/B)은 점수 게이트를 통과해도 **신규 진입 차단** —
score_candidates 가 block_reasons 로 사유를 노출해 리포트에 자동 전파된다. 등급 C·추정
누락·24h stale 은 게이트 미적용(결측 래칫 방지), 공격 트리거(추정 +X% 매수)는 채점 표본
누적 후 재검토.

2026-07-21(policy v2.24)에 **매도(보유) 측에도 연결**됐다(`reward_risk_management.holding_estimate_review`):
매수는 음수 추정을 차단하면서 보유는 음수 전환·지속에 무반응이던 비대칭을 닫는다 —
A/B 등급 추정 기대수익이 0% 미만으로 2회 연속(target_estimate_log 기준)이면
`compute_exit_levels.py` 가 `state/exit_levels.json` 의 `tickers.<t>.estimate.review_required=true`
로 표면화하고, 18시 §2-2 가 목표가 재조정/손절 상향(트레일링 강화)/부분 익절 중 택1 을
**의무 결정**한다(자동 청산·목표가 자동 변경 없음 — 추정 수치는 낙관 편향(estimate_scorecard
5td 중앙오차 −10.4%p)이라 부호·지속성 신호만 연결). `audit_pipeline.audit_estimate_alignment`
가 보유 운용 목표가 ↔ 추정 괴리(+20% 초과)·추정 기준선 위 SELL price_above 트리거(모델상
미도달 구간)·review_required 미처분을 매일 WARN 으로 감시한다. **랭킹 편입(가산 틸트/
타이브레이크)은 1차 백테스트(2026-07-21, `scripts/backtest_estimate_tilt.py` 22거래일)에서
보류(hold)** — 횡단면 순위 정보력은 실재(A/B IC +0.23·양일 77%, 같은 창 모멘텀 프록시 −0.12)하나
소폭 가산은 픽 변경 0일(죽은 파라미터)이고 픽을 바꿀 만큼 키우면 무해성 기준을 미달했다.
표본 ≥45거래일에 sunday_policy_review §1-5 가 사전 등록 기준 그대로 재심사한다
(`reports/2026-07-21-estimate-tilt-research.md`). 수치 캘리브레이션 연결도 동일하게 별도 상정.
- **기준가**: PER/PBR 5년 밴드 중앙값 적정가(valuation.json) + 컨센서스 목표가(consensus.json) 평균. 결측 시 현재가 폴백(등급 하향)
- **테마P** (≤20%): Σ(테마 strength × 종목 노출) × 호라이즌 할인 — "3~5년 메가트렌드"는 12개월 목표가에 1/3만 반영
- **뉴스P** (±12%): `config/news_impact.json` 유형별 가산점 — 과거 뉴스는 90일 시간감쇠, 다가오는 촉매(catalysts.json)는 발생확률×D-day 근접가중×방향(DART earnings_signal)으로 할인
- **섹터P** (≤8%): 섹터 몰입 신호(universe_screen.json)로 "활발성이 언제 올지"를 4단계(현재 활발/1~2개월/2~4개월/촉매 대기)로 추정해 차등 반영
- **천장 캡**: policy.valuation_anchor 동일 — min(추정치, 컨센×1.15, 밸류에이션 천장)

출력 `state/target_estimate.json` 은 fetch_prices 워크플로마다 갱신되며, watchlist 의 target_price 를 자동으로 덮어쓰지 않는다(routine 의 dynamic_exit_model 목표가 산정 참고 레이어). 신뢰등급 A/B/C 는 가용 데이터 레이어 수(밸류 밴드·컨센·시세·테마·섹터·실적신호) 기준 — 밸류 밴드·컨센이 시드되기 전에는 B/C 수준의 거친 추정이다.

## 실행 방법
GitHub 레포 `hjlee8090-max/Researh`에 호스팅됨. 어디서든 동일 상태를 이어받아 동작.

### A. 원격 routine (PC 꺼져있어도 자동 실행) — 기본 모드
- 평일 06:30 / 09:20 / 12:00 / 15:00 / 18:00 KST + 매일 00:00 KST에 Anthropic 클라우드에서 자동 발화
  - 09시 슬롯은 **발화 시각만 09:20**(개장 직후 변동성 진정 + 시세 스냅샷 안착 대기). 슬롯 식별자·파일명(`-09.md`)·파서 고정문자열(`## 🌅 09:00 개장 점검`)은 관례상 `09` 로 유지한다.
  - 06시 슬롯도 같은 관례 — **발화 시각은 06:30**(미국장 마감 EDT 05:00 / EST 06:00 KST 정착 대기)이나 슬롯 식별자·파일명(`-06.md`)·파서 고정문자열(`## 🌄 06:00 미국장 마감 확정`)은 `06` 로 유지한다.
- 각 routine은 이 레포를 git clone → 해당 시각 prompt 파일 읽기 → 실행 → git commit/push
- 등록·관리: https://claude.ai/code/routines

| 시각 | Routine ID |
|---|---|
| 00:00 | 등록됨 — **매일 00:00 KST 발화로 수정 완료(2026-06-12 사용자 등록 변경)**. 이전 등록은 화~토만 발화해 월요일 자정 3주 연속 미실행(5/25·6/1·6/8)이었음. 일·월 자정은 미국 현물장 휴장이라 `prompts/0000_global.md` §0-0 **주말 자정 모드**(금요일 종가 표기 강제·주말 지정학 중심)로 분기. 검증: 다음 일·월 자정 리포트 생성 여부 + 월요일 19:30 audit(00 파일 누락 WARN) |
| 06:30 | 등록됨 (2026-07-02 — `prompts/0630_us_close.md`, **화~토 06:30 KST** — 미국 세션(월~금 ET)이 있는 다음날 아침에만 발화. 월요일은 직전 미국 세션이 없어 발화하지 않고, 주말 경과분은 매일 발화하는 00시 슬롯이 커버, 2026-07-20 운영 확정). 미국장 마감 확정·개장 전 갱신. 토요일은 §0-B 한국 휴장 모드로 금요일 마감 정리 축약 리포트. 미 공휴일 다음날은 프롬프트 §0-0 주말 마감 모드로 자동 분기. 검증: 화~토 06시 리포트(`-06.md`) 생성 여부 + 카톡 `🌄 06:00` 알림 수신 |
| 09:20 | `trig_01SMcVbAS1L2tUrhKAWbHUk7` |
| 12:00 | `trig_01Fx8FfsxXqCsugnW3XjZM6M` |
| 15:00 | `trig_01U8ZvyhgVRkYTDeP9BjttjQ` |
| 18:00 | `trig_01TD41NpsamHcveUeokYcyyM` |
| 토 18:00 | 등록됨 (2026-06-10 — `prompts/saturday_review.md`, rule_attribution 의무 인용) |
| 일 18:00 | 등록됨 (2026-06-10 — `prompts/sunday_strategy.md`, valuation.json 주간 시드 포함) |
| 일 17:00 | **GitHub Actions**(`weekly_self_audit.yml`, 루틴 아님·결정적 스크립트) — 주간 자기감사: 원장 정합성·PF·vs KOSPI 격차·휩쏘율·게이트 위반·패치 vs 검증 속도 재측정 + findings 수명 갱신(`state/self_audit_findings.json`). 무처분 2주 이상 finding 존재 시 follow-up gate FAIL |
| 일 20:00 | 등록됨 (2026-06-10 — `prompts/sunday_policy_review.md`, lessons → policy 패치 리뷰 + 룰 손익 채점·일몰 심사. **v2.22 §0-0: 17시 self-audit findings 의무 인용·처분(disposition) 기입 — 검사(17시, 기계)→보완(20시, LLM)→검증(다음주 17시, 기계) 닫힌 루프의 보완 담당**) |
| 일 21:00 | 등록됨 (매주 일요일 21:00 KST — `prompts/sunday_archive.md`) |

> **routine 산출물의 main 자동 반영**: 원격 routine 이 격리 환경에서 세션 브랜치에만 push 하고 main 에 머지되지 않는 경우를 대비해 `.github/workflows/auto_merge_routines.yml` 가 동작한다. routine 커밋 프리픽스(`chore(` / `report:` / `audit:` / `sat-review:` / `sun-strategy:` / `policy-review:` / `weekly:` / `weekly-archive:`)이고 봇 작성자인 브랜치 push 를, routine 커밋을 `origin/main` 위에 rebase 한 뒤 fast-forward 로 main 에 머지한다(헤드 커밋 메시지 보존 → 카톡 알림 정상 발화). 충돌 시에는 머지하지 않고 브랜치를 남겨 수동 검토를 유도한다. routine 프롬프트 §commit 의 `git push origin HEAD:main` 이 환경 제약으로 세션 브랜치에 떨어져도 이 워크플로가 닫아준다.

### B. 로컬 Claude Code (선택)
PC에서 직접 돌리고 싶을 때:
```
git pull --rebase
prompts/0900_pre_market.md 실행 (또는 1200/1500/1800)
```
프롬프트 내부에 git pull/push 절차가 포함되어 있어 원격과 동일한 상태 일관성을 보장한다.

### C. 로컬 Windows 작업스케줄러 (옵션)
PC가 항상 켜져있고 빠른 응답을 원할 때 추가 등록 가능:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1
```
원격 routine이 이미 PC 오프에도 동작하므로 **필수 아님**. 중복 실행되어도 git rebase로 충돌 없이 흡수된다.

## 첫 가동
- 구조 세팅 + GitHub 푸시 완료. **다음 09:00 KST 원격 routine 발화 시 종목 3개 첫 추천**.
- 추천 직후 가상 매수 체결 기록 → 18시부터 정상 자기보완 루프.

## 모바일 노티 셋업 (HTML 리포트 + 카카오톡)

각 routine 은 **자기 시간대 전용 리포트 파일을 새로 생성** 한다 (이전 파일 수정 금지):
1. 00/06/09/12/15/18 routine → `reports/YYYY-MM-DD-{00,06,09,12,15,18}.md` 각각 1개
2. GitHub Actions가 `reports/*.md` → HTML 변환 → GitHub Pages 배포
3. 카카오 '나에게 보내기' API 로 **해당 시간대 파일의 '한눈에 보기'** 요약 + Pages 링크 전송 (그 슬롯 HTML 페이지로 바로 이동)
4. 인덱스 페이지(`/index.html`)에서 날짜별로 6개 슬롯이 한 카드로 묶여 있어 "왜 이 결정을 했는지" 추적 가능
5. 일요일 21시 archive routine 이 지난주 평일 30개 파일을 1개 `reports/YYYY-Www-archive.md` 로 응축 → 다음주 routine 콘텍스트 절약

### 시간대별 리포트 파이프라인 (분리 파일)
```
🌙 00:00 글로벌 야간 점검    → reports/YYYY-MM-DD-00.md
🌄 06:00 미국장 마감 확정    → reports/YYYY-MM-DD-06.md  (발화 06:30. 자정 예측 확정·개장 전 갱신, 매매 없음)
🌅 09:00 개장 점검          → reports/YYYY-MM-DD-09.md  (이전: -00.md·-06.md를 "이어받기"로 요약)
🕛 12:00 장중 점검          → reports/YYYY-MM-DD-12.md  (이전: -09.md 요약)
🔔 15:00 마감 임박 점검      → reports/YYYY-MM-DD-15.md  (이전: -12.md 요약)
📊 18:00 종합·확정 리포트    → reports/YYYY-MM-DD-18.md  (이전 5개를 모두 종합·검증)
🗂️ 일 21:00 주간 archive    → reports/YYYY-Www-archive.md  (지난주 평일 30개 → 1개로 응축)
```

각 시간대 파일은 다음 공통 섹션을 포함한다 (초보자 친화, 2026-07-04 개편 순서):
- **한눈에 보기**: 본문 최상단 — 오늘의 액션·핵심 수치로 30초 의사결정 지원 (카톡 요약의 원천)
- **📝 오늘의 이야기**: 그 직후 블로그 산문 — 첫 문단에서 이전 슬롯 결론을 이어받아 단일 파일만 봐도 흐름 추적 가능
- **⚠️ 위험·매매 시그널 시각화**: 손절·현재가·목표를 1줄 텍스트 게이지로 (전체는 00·18시, 09/12/15시는 변경 종목만 — 델타 원칙)
- **🎓 오늘의 학습 노트**: 핵심 학습 포인트 + 신규 용어만 풀이 (기등재 용어는 `state/glossary.md` 참조)

이전 시간대 파일은 **절대 수정하지 않는다** (히스토리·자기보완 학습 재료 보존).

### 1회 셋업

**A. GitHub Pages 활성화** (1회)
- Settings → Pages → Source: **GitHub Actions** 선택

**B. Kakao Developers 앱 등록** (1회)
- https://developers.kakao.com 에서 앱 생성
- [앱 설정 > 플랫폼 > Web] 에 `https://example.com` 추가
- [제품 설정 > 카카오 로그인] 활성화, Redirect URI `https://example.com`
- [동의항목] '카카오톡 메시지 전송 (talk_message)' 사용 설정
- REST API 키 복사

**C. Refresh Token 발급** (1회, 로컬에서)
```bash
export KAKAO_REST_API_KEY=발급받은_키
python scripts/kakao_oauth_helper.py
# 출력된 URL 브라우저로 열고 동의 → ?code=XXX 복사 → 입력
# 출력된 refresh_token 복사
```

**D. GitHub Secrets 등록** (1회)
- Settings → Secrets and variables → Actions → New repository secret
- `KAKAO_REST_API_KEY` = REST API 키
- `KAKAO_REFRESH_TOKEN` = 발급받은 refresh_token

### 동작
- 00시 commit (`chore(00:00 ...)`) — 🌙 글로벌 야간 섹션 요약을 카톡 발송 (자정에 자고 있어도 아침에 확인 가능)
- 09/12/15시 commit (`chore(09:00 ...)` / `chore(12:00 ...)` / `chore(15:00 ...)`) — 해당 시간대 섹션 요약을 카톡 발송
- 18시 commit (`report:`) — 📊 18시 종합 섹션의 '한눈에 보기' 요약을 카톡 발송
- **오발송 가드(2026-06-12)**: 슬롯 식별은 커밋 제목 줄의 `chore(HH:00` 프리픽스만 신뢰하고, 슬롯 미식별 커밋은 발송하지 않으며(전일 리포트 폴백 제거), 리포트 파일 날짜=오늘 + 이번 push 가 그 파일을 실제로 변경했을 때만 발송한다(중복·묵은 리포트 차단)
- `refresh_token`은 60일 유효. 만료 임박 시 send_kakao.py 로그에 신규 토큰이 출력됨 → Secret 업데이트
- 60일 지나 완전 만료되면 1회 셋업 C/D 단계 재실행
