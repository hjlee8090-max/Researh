# 파일 참조 구조 점검 (2026-07-08 갱신)

이 문서는 각 prompt / script 가 **어떤 파일을 읽고 / 어떤 파일을 쓰는지** 한눈에 보여준다.
시간대별 리포트 분리 + 시장 데이터 자동 수집 + 휴장일 가드 작업 이후 갱신.

> **신규 추가 (2026-07-21, v2.24 추정 기준선 ↔ 매수/매도 정렬 1차)**
> - `policy.reward_risk_management.holding_estimate_review` — 매수측 estimate_gate(v2.12)의 보유측 대응물: A/B 추정 기대수익 <0% 가 2회 연속이면 18시 §2-2 재조정 의무 발동(자동 청산·목표가 자동 변경 없음. 수치 이식 금지 — estimate_scorecard 낙관 편향 −10~−19%p 실측, 부호 유효성은 gate_cost 차단표본 fwd20 중앙 −21.9% 실증)
> - `scripts/compute_exit_levels.py` 확장 — 읽기 추가: `state/target_estimate.json`·`state/target_estimate_log.jsonl`(연속 음수 streak)·policy / 쓰기: `state/exit_levels.json` 의 `tickers.<t>.estimate`(추정가·기대수익·운용 목표 대비 괴리%·streak·review_required·review_reason). `--selftest` 에 streak 판정 3케이스 추가
> - `audit_pipeline.audit_estimate_alignment` — ①보유 운용 목표가가 추정 대비 `target_gap_warn_pct`(20%) 초과 괴리 WARN ②active SELL `price_above` 트리거가 추정 기준선 위(모델상 미도달 구간)면 WARN ③review_required 미처분 표면화(매일 반복 경보)
> - `prompts/1800_report.md` §2-2 — `exit_levels.estimate.review_required` 소비(의무). `prompts/0900_pre_market.md`·1800 §뉴스 반영 매매가 각주에 보유측 게이트 존재 명시
> - `scripts/backtest_estimate_tilt.py` — 추정 기대수익의 랭킹 편입(가산 틸트/타이브레이크) 백테스트. 읽기: `state/target_estimate_log.jsonl`·`state/price_history.json`(+`scripts/score_candidates.py` 밴드 함수 import) / 쓰기: `state/backtest_estimate_tilt.json`. **1차 판정 hold(배선 없음)** — 재심사 트리거는 `prompts/sunday_policy_review.md` §1-5(표본 ≥45거래일), 근거 `reports/2026-07-21-estimate-tilt-research.md`
> - 진단 실측(2026-07-20): 한미반도체 운용 목표 332,696 vs 추정 210,300(−5.3%, +58% 괴리)·LIG넥스원 +28% 괴리·신한지주 익절 트리거 110,829 > 추정 106,900
>
> **신규 추가 (2026-07-02, v2.20 포지션 유동 운영 — 본전 래칫 그림자)**
> - `policy.risk.breakeven_ratchet` — 본전 래칫 스톱(mode=shadow, 관측 전용·체결 변화 0). 함께: `position_sizing.max_positions` 5→6(momentum top_n 동기 — vacant_slots 영구 0 해소), `risk.time_stop.precedence_over_min_hold`·`horizon.min_hold_precedence`(시간손절 vs 최소보유 우선순위 명문화)
> - `scripts/track_ratchet_shadow.py` — 읽기: `config/policy.json`·`config/portfolio.json`·`state/market_snapshot.json` / 쓰기: `state/ratchet_shadow.json` (1800 §1 종가 확정 후 실행 — 멱등 upsert·커밋 대상)
> - `scripts/score_ratchet_shadow.py` — 읽기: `state/ratchet_shadow.json`·`state/price_history.json`·`state/trade_log.jsonl`·policy / 쓰기: `state/ratchet_shadow_scorecard.json` (sunday_policy_review 0-E 실행 → §1-8 승격 심사 입력)
> - 진단·설계 전문: `reports/2026-07-02-position-management-research.md`
>
> **신규 추가 (2026-06-12, v2.13 콘텍스트 예산)**
> - `scripts/compact_state.py` — 핫패스 누적 필드 압축: watchlist 청산 종목·오래된 코멘트 → `state/watchlist_archive.json`,
>   watch_items 초과분 → `state/watch_items_archive.jsonl`, portfolio.history → `state/portfolio_history.jsonl`(config 최근 10개),
>   policy.changelog → `docs/policy_changelog.md`(policy 최근 5건). 일요일 21시 sunday_archive §0-2 + 수동. 멱등·`--dry-run`.
> - `state/lessons_archive.md` — codify 확정 lessons 항목 전문 보존 (sunday_policy_review §1-6 이 이관, routine 은 읽지 않음)
> - `audit_pipeline.audit_context_budget` — 핫패스 크기 임계(`policy.context_budget.audit_thresholds`) 초과 WARN
> - `audit_pipeline.audit_reports` 확장 — 당일 00시 슬롯 누락 WARN(월요일 미발화 표면화) + '한눈에 보기' 운영 용어 노출 WARN
> - `check_lessons_applied.py` haystack 에 `docs/policy_changelog.md` 포함 (changelog 분리에 따른 오탐 방지)
- (v2.33 D) haystack 에 `docs/policy_rationale.md` 추가 — policy 본문 산문 이관분(유래·사례 전문)의 오탐 방지. 신규 policy 룰의 유래 서술은 처음부터 rationale 에 적는다(본문엔 룰·파라미터·ref 만)
> - 보유 R/R 검토 하한 = 진입과 동일 `regime_adaptive_rr.min_rr_by_tier` (1800 §2-2·audit 통일, tier 미확정 1.2 폴백)

> **신규 추가 (2026-06-02, v2.3 장중 시간 정책)**
> - `config/market_calendar.json.sessions` — KRX 장중 세션(정규장 09:00~15:30·동시호가·시간외·반장)
> - `scripts/check_market_session.py` — 장중 세션·execution_mode 판정 (모든 평일 routine 0-A 에서 호출)
> - `policy.market_hours` + `trade_timing_gate` — 마감 후 신규진입 금지·종가 청산은 ts=15:30+execution_venue=closing_auction, CI 하드 강제
>
> **신규 추가 (2026-06-08, v2.7 강세장 배치·종목 탐색)**
> - `config/universe.json` — 신규 진입 후보의 '모집단'(테마별 대형주 ~30종목)
> - `scripts/screen_universe.py` — 모집단을 상대강도+테마로 랭킹 → 승격/회전아웃 제안 → `state/universe_screen.json`
> - `policy.entry_filters.block_if_cumulative_return_below_pct_by_tier` + `relative_strength_leader_widening` + `entry_filter_hard_floor_pct` — 진입필터 레짐 적응형(평면 -7% 제거, `fetch_market_data.apply_entry_filter`)
> - `policy.risk.max_single_trade_risk_pct_of_equity_by_tier` — 단일거래 리스크캡 레짐 적응형(strong_bull 3.5%, `compute_allocation.per_trade_risk_pct`)
>
> **신규 추가 (2026-06-08, v2.8 범용 섹터 로테이션 재진입)**
> - `policy.sector_rotation_reentry` — 호재(촉매)+몰입(자금 발자국)으로 침체·avoid 섹터 재진입(모든 섹터 범용, 조선 하드코딩 없음). v2.9 `price_reversal`(5일선+higher-low) 신호 · v2.10 `sensitivity_mode=auto`+`sensitivity_by_tier`(레짐 tier 로 민감도 자동조정)
> - `fetch_market_data` 추가 필드: 종목별 `momentum.ret_20d_pct`, `liquidity.{volume,vol_ratio_20d}`, (v2.9) `structure.{ma5,above_ma5,higher_low,price_reversal}`(5일선 회복+higher-low '공격' 모드 신호)
> - `scripts/screen_universe.py` 확장: 섹터/테마별 몰입 신호 → `state/universe_screen.json.{sector_rotation,avoid_reentry}`
> - `config/watchlist.json.avoid_sectors[].re_entry` — 구조화(해제 규칙). 추가(1800)와 해제(09시 §C-5-1)가 대칭
>
> **신규 추가 (2026-05-22)**
> - `config/candidates.json` — 신규 진입 후보 종목 목록
> - `config/market_calendar.json` — KRX 휴장일 캘린더
> - `scripts/fetch_market_data.py` — 다중 출처 가격·5거래일 추세 자동 수집 → `state/market_snapshot.json`
> - `scripts/fetch_investor_flows.py` — (2026-08-11 P0-3) KRX 투자자별 순매수(시장 KOSPI + 보유·후보 종목, 원) 일별 수집 → `state/investor_flows.json` (`fetch_flows.yml` 평일 16:45 KST 수집·커밋 — 18:00 당일치·06:30 전일치 소비. 웹 세션은 커밋본만 읽음. streak/transition 필드가 7/29 "반등 밴드 상향은 외국인 순매수 전환 전제" 룰의 판정 입력)
> - `scripts/check_market_open.py` — 영업일/휴장일 판정 (모든 평일 routine 의 0-A 단계에서 호출)
> - `scripts/score_candidates.py` — 후보 자동 점수화 → `state/candidate_scores.json`
> - `scripts/reconcile_portfolio.py` — trade_log ↔ portfolio 정합성 검증 (audit + 09시 사전 점검)
> - `scripts/build_lessons_index.py` — lessons.md 분류·룰 인덱스 → `state/lessons_index.json`
> - `prompts/sunday_policy_review.md` — 일요일 20시 정책 패치 리뷰
> - `state/lessons_index.json` — 매 실행 재생성 (gitignored). `state/market_snapshot.json`·`state/candidate_scores.json` 은 GitHub Actions(`fetch_prices.yml`)가 수집·커밋해 **추적됨**(웹 세션 routine 의 1순위 출처 — §4 fetch_market_data 참조)

## 1. 리포트 파일 명명 규칙

| 형식 | 작성 시간대 | 작성 주체 |
|---|---|---|
| `reports/YYYY-MM-DD-00.md` | 자정 00:00 KST | `prompts/0000_global.md` |
| `reports/YYYY-MM-DD-06.md` | 미국장 마감 06:00 KST (발화 06:30) | `prompts/0630_us_close.md` |
| `reports/YYYY-MM-DD-09.md` | 개장 09:00 KST | `prompts/0900_pre_market.md` |
| `reports/YYYY-MM-DD-12.md` | 장중 12:00 KST | `prompts/1200_midday.md` |
| `reports/YYYY-MM-DD-15.md` | 마감 임박 15:00 KST | `prompts/1500_close.md` |
| `reports/YYYY-MM-DD-18.md` | 종합·확정 18:00 KST | `prompts/1800_report.md` |
| `reports/YYYY-MM-DD-audit.md` | 19:30 KST | `scripts/write_audit_report.py` |
| `reports/YYYY-MM-DD-saturday-review.md` | 토요일 18:00 KST | `prompts/saturday_review.md` |
| `reports/YYYY-MM-DD-sunday-strategy.md` | 일요일 18:00 KST | `prompts/sunday_strategy.md` |
| `reports/YYYY-MM-DD-weekend.md` | 주말 | `prompts/weekend_report.md` |
| `reports/YYYY-Www-archive.md` | 일요일 21:00 KST | `prompts/sunday_archive.md` |
| `reports/YYYY-MM-DD.md` (구버전) | 단일 누적 파일 | 폐기 — 새 파일은 시간대별로 분리 |

## 2. 평일 시간대별 routine 의 입력·출력

각 시간대 routine 은 **이전 시간대 파일을 읽고, 새 파일을 생성** 한다.
"수정"이 아니라 "신규 생성"이라는 점이 중요 — 이전 슬롯 파일은 절대 변경하지 않는다.

### 🌙 00:00 글로벌 야간 (`prompts/0000_global.md`)
**읽기**:
- `state/lessons.md`
- `config/policy.json`, `config/weekly_plan.json`, `config/watchlist.json`, `config/portfolio.json`
- `config/candidates.json` (0-A 스냅샷 수집 대상)
- `state/market_snapshot.json` (0-A 단계에서 `fetch_market_data.py` 로 생성)
- `state/inference_checklist.md` (§2-4 갭 예측 기록 전 필독)
- 직전 영업일 18시 리포트: `reports/YYYY-MM-DD-18.md` (없으면 구버전 `reports/YYYY-MM-DD.md`)
- 직전 주말 archive: `reports/YYYY-Www-archive.md`

**쓰기**:
- `reports/YYYY-MM-DD-00.md` (신규 생성)
- `state/inference_log.jsonl` (개장 갭 예측 append, `horizon=09:00` — 채점은 09시)
- `config/catalysts.json` (`manual_events` — 야간 속보로 촉매 확정 시)
- `config/watchlist.json` (야간 경보 코멘트 추가만)
- `state/lessons.md` (orange/red 사전 경보 시)

### 🌄 06:00 미국장 마감 확정 (`prompts/0630_us_close.md`, 발화 06:30)
**읽기**:
- `state/lessons.md`, `config/policy.json`, `config/weekly_plan.json`, `config/watchlist.json`, `config/portfolio.json`, `config/candidates.json`
- 오늘 자정 파일: `reports/YYYY-MM-DD-00.md` (진행형 태그·개장 갭 예측·if-then 표)
- `state/pending_orders.json`, `state/inference_checklist.md`, `state/market_snapshot.json`

**쓰기**:
- `reports/YYYY-MM-DD-06.md` (신규 생성)
- `state/pending_orders.json` (트리거 값·메모 갱신만 — 체결/status 변경 없음)
- `state/inference_log.jsonl` (개장 갭 갱신 예측 append, `slot":"06:00"`·`horizon="09:00"` — 채점은 09시)
- `config/watchlist.json` (마감 경보 코멘트 추가 시)
- **매매 없음** (한국 폐장 — `execution_mode=none`)

### 🌅 09:00 개장 (`prompts/0900_pre_market.md`)
**읽기**:
- `state/lessons.md` (먼저)
- `config/policy.json`, `config/weekly_plan.json`, `config/watchlist.json`, `config/portfolio.json`
- `config/candidates.json` (자동 추적 후보), `config/catalysts.json` (D-day 경보, 있으면)
- 오늘 자정 파일: `reports/YYYY-MM-DD-00.md`
- 오늘 06시 파일: `reports/YYYY-MM-DD-06.md` (있으면 마감 확정·갱신 갭 예측을 1순위 흡수)
- 직전 영업일 18시: `reports/YYYY-MM-DD-18.md`
- 직전 주말 archive: `reports/YYYY-Www-archive.md`
- 0-B 산출물: `state/market_snapshot.json`, `state/candidate_scores.json`, `state/allocation.json`, `state/exit_levels.json` (compute_exit_levels — 트레일링·손절·목표 단일 소스, 손계산 금지)
- `state/momentum_signal.json` (§0-M 바스켓), `state/pending_orders.json` (§1-PO 집행 판정), `state/intraday_alert.json` (§1-PO — gitignored·원격 fresh clone 에선 부재 가능)
- `state/inference_checklist.md` (§1-0 채점·예측 전 필독), `state/target_estimate.json` (§3-1 뉴스 반영 매매가 표)
- 참고: `state/fundamentals.json`·`state/valuation_check.json`·`state/consensus.json` (§2 사이징·천장 검증)

**쓰기**:
- `reports/YYYY-MM-DD-09.md` (신규 생성)
- `config/watchlist.json`, `config/portfolio.json`
- `config/candidates.json` (신규 후보 등록·갱신 시)
- `state/trade_log.jsonl` (체결 시 1라인 append)
- `state/inference_log.jsonl` (00·06 예측 채점 + 당일 예측 append)
- `state/pending_orders.json` (집행/만료 status 갱신)
- `state/lessons.md` (필요 시)

### 🕛 12:00 장중 (`prompts/1200_midday.md`)
**실행 (0-B)**: `fetch_market_data.py` → `state/market_snapshot.json`, `estimate_target_price.py` → `state/target_estimate.json`, `compute_allocation.py` → `state/allocation.json`, `check_intraday_alerts.py` 직접 실행(pending_orders 트리거·장중 터치 재산출 — gitignored 파일 읽기 의존 금지) → `state/intraday_alert.json`. 매매 booking 직전 §1-PRE: `pre_trade_check.py` (+ fetch/score_candidates/compute_allocation 재실행).

**읽기**:
- `state/lessons.md`
- `config/*` 4개
- `state/market_snapshot.json` (0-B 갱신 — 가격·신뢰도 1순위), `state/allocation.json`(신선도·deploy 판단), `state/target_estimate.json` (§6 뉴스 반영 매매가 표)
- `state/exit_levels.json` — **09시 산출본 인용만**(12시는 compute_exit_levels 재실행·손계산 금지, 안건⑦)
- `state/pending_orders.json` (check_intraday_alerts 입력), `state/inference_checklist.md` (§2-2 예측 전 필독)
- 오늘 09시 파일: `reports/YYYY-MM-DD-09.md` (없으면 `-06.md` → `-00.md` 순 대체)
- 오늘 자정 파일: `reports/YYYY-MM-DD-00.md` (참고)

**쓰기**:
- `reports/YYYY-MM-DD-12.md` (신규 생성)
- `config/watchlist.json`, `config/portfolio.json`
- `state/inference_log.jsonl` (오후장 예측 1건+ append — `slot:"12:00"`·`horizon:"15:00"`)
- `state/trade_log.jsonl`, `state/lessons.md` (orange/red 발생 시)

### 🔔 15:00 마감 임박 (`prompts/1500_close.md`)
**실행 (0-B)**: `fetch_market_data.py` → `state/market_snapshot.json`, `estimate_target_price.py` → `state/target_estimate.json`, `compute_allocation.py` → `state/allocation.json`, `compute_exit_levels.py` → `state/exit_levels.json`(트레일/손절/목표 단일 소스 — 손계산·직전 리포트 이월 금지), 직후 `sync_pending_orders.py`(트레일링 SELL 트리거값 동기화 — 안건②) + `check_intraday_alerts.py` 직접 실행(장중 터치 → "종가 확인 대기" 명기). booking 시 §0-C: `pre_trade_check.py` (+ 재동기화 재실행).

**읽기**:
- `state/lessons.md`
- `config/*` 4개 + `config/catalysts.json` (옵셔널 — 익일 임박 촉매 D-3)
- `state/market_snapshot.json`, `state/allocation.json`, `state/exit_levels.json`, `state/target_estimate.json`(§3 델타 행만), `state/fundamentals.json`(earnings_signal), `state/inference_checklist.md` (§2-1 필독)
- 오늘 12시 파일: `reports/YYYY-MM-DD-12.md`
- 오늘 09시 파일: `reports/YYYY-MM-DD-09.md` (참고, 09/12 둘 다 없으면 `-06.md` → `-00.md` 순 대체)

**쓰기**:
- `reports/YYYY-MM-DD-15.md` (신규 생성)
- `config/watchlist.json`, `config/weekly_plan.json` (watch_items 갱신 — 최대 15개)
- `state/exit_levels.json`·`state/pending_orders.json` (0-B 스크립트 산출·동기화)
- `state/inference_log.jsonl` (12시 예측 채점 append + 종가·익일 예측 1건+ append — `slot:"15:00"`·`horizon:"18:00"`)
- ※ 매매 체결은 원칙적으로 익일 09시 이연·후보 표시만. 예외(§0-B v2.2 deploy 신규 진입·손절 청산)는 §0-C 게이트 통과 후 `state/trade_log.jsonl` append.

### 📊 18:00 종합·확정 (`prompts/1800_report.md`)
**읽기**:
- `state/lessons.md`
- `config/*` 4개
- `state/trade_log.jsonl` (최근 30라인)
- 오늘 시간대별 리포트 5개: `reports/YYYY-MM-DD-{00,06,09,12,15}.md`

**쓰기**:
- `reports/YYYY-MM-DD-18.md` (신규 생성)
- `config/portfolio.json` (종가 평가·history append)
- `config/watchlist.json` (next_day_plan)
- `config/weekly_plan.json` (objective·capital_plan·daily_bridge 갱신)
- `state/lessons.md` (오차 종목 항목 추가)
- `state/trade_log.jsonl` (체결 시)

## 3. 주말 routine 의 입력·출력

### 토요일 18:00 사후분석 (`prompts/saturday_review.md`)
**읽기**: 지난주 평일 리포트 5일 + lessons.md + config/* + state/*
**쓰기**: `reports/YYYY-MM-DD-saturday-review.md`

### 일요일 18:00 전략 (`prompts/sunday_strategy.md`)
**읽기**: 토요일 사후분석 + 매크로 캘린더 검색 + config/* + state/*
**쓰기**: `reports/YYYY-MM-DD-sunday-strategy.md`, `config/weekly_plan.json`

### 일요일 20:00 정책 패치 리뷰 (`prompts/sunday_policy_review.md`) — 신규 (2026-05-22)
**읽기**:
- `state/lessons.md` (1차 입력)
- `config/policy.json`, `prompts/*.md`, 직전 `reports/YYYY-Www-archive.md`
- 이번 주말 saturday_review·sunday_strategy 산출물

**쓰기**:
- `reports/YYYY-MM-DD-policy-review.md` (신규 생성)
- (자동 적용 가능 항목 한정) `config/policy.json` 또는 `prompts/*.md` 패치
- 커밋 prefix `policy-review:` → 카톡 알림 트리거

### 일요일 21:00 archive (`prompts/sunday_archive.md`) — 새로 추가
**읽기**:
- 지난주 평일 5일 × 6슬롯 = 최대 30개 시간대별 리포트
- 토요일 사후분석 + 일요일 전략 (선택)
- config/* 4개, state/lessons.md

**쓰기**:
- `reports/YYYY-Www-archive.md` (주차별 응축 1개 파일)
- 원본 30개 파일은 그대로 둔다 (감사 추적성)
- 다음주 평일 routine 은 이 archive 1개만 읽으면 됨 → 콘텍스트 절약

### 주말 노트 (`prompts/weekend_report.md`)
**읽기·쓰기**: `reports/YYYY-MM-DD-weekend.md` 기반의 자유 노트.

## 4. 보조 스크립트의 참조 구조

### `scripts/audit_pipeline.py`
- 읽기: `config/*` 6개(policy/weekly_plan/watchlist/portfolio/candidates/market_calendar), `state/trade_log.jsonl`, `prompts/*.md` (존재 확인), `reports/*.md` (정규식 `YYYY-MM-DD(-(00|06|09|12|15|18))?.md`), `scripts/fetch_market_data.py`·`scripts/check_market_open.py`·`scripts/check_market_session.py`·`scripts/check_trade_log_gate.py` 존재 확인
- `audit_trade_provenance` 가 `check_trade_log_gate.py` 를 subprocess 로 실행해 price_source 누락 + 장중 시간 밖 booking 을 FAIL 로 흡수
- 쓰기: 없음 (stdout만)

### `scripts/fetch_market_data.py` (신규, v2.4 today_ohlc 추가)
- 읽기: `config/portfolio.json` (보유), `config/candidates.json` (후보), `config/policy.json` (`entry_filters` — v2.7 레짐 적응형 임계 `block_if_cumulative_return_below_pct_by_tier`·`relative_strength_leader_widening`·`entry_filter_hard_floor_pct`. 레짐 tier 확정 후 `apply_entry_filter` 로 종목별 임계 산출)
- 네트워크: 네이버 siseJson 일별 + Yahoo Finance v8 chart JSON (양쪽 시도, 둘 다 실패 시 직전 스냅샷 보존+stale)
- 쓰기: `state/market_snapshot.json` (GitHub Actions `fetch_prices.yml` 가 수집·커밋, 추적됨)
- (v2.4) 종목별 `today_ohlc`(시가/고가/저가/현재가, last_date=오늘일 때만) 노출 — 웹 교차확인이 개장/장중 고가를 '현재가'로 오인하는 것을 막는 범위 맥락(`policy.price_data_quality.web_verify_guard`). 이미 수집한 일봉에서 파생, 네트워크 무관.

### `scripts/fetch_catalysts.py` (신규 — catalyst-calendar Part A)
- 읽기: `config/portfolio.json`(보유), `config/candidates.json`(후보), `config/catalysts.json`(직전 manual_events 보존), 환경변수 `DART_API_KEY`(옵션)
- 네트워크: DART list.json(정기공시) — 있으면 최근 제출분으로 다음 회차 보정. 없어도 한국 정기보고서 법정기한(달력)으로 generated_events 생성(graceful degrade)
- 쓰기: `config/catalysts.json` — `generated_events`(스크립트 소유, 매 실행 재생성) / `manual_events`(사람·routine 소유, 보존) / `events_archive`(경과분 14일 보관)
- 실행: `.github/workflows/fetch_catalysts.yml` 주 1회(일 06:30 KST). 데일리 routine 은 읽기 + manual_events 갱신만.
- 소비처: `prompts/0000_global.md`(매크로 촉매 기록·D-day), `0900_pre_market.md`(1-4 촉매 임박 경보), `1500_close.md`(익일 사전 알림), `1800_report.md`(§4 다음 거래일 액션). 정책: `policy.catalysts`.

### `scripts/fetch_consensus.py` (신규 — 컨센서스 레이어, Phase 2 입력)
- 읽기: `config/portfolio.json`(보유), `config/candidates.json`(후보), `state/consensus.json`(직전값 보존)
- 네트워크: FnGuide 컴퍼니가이드 Snapshot(comp.fnguide.com) — 브라우저 UA+Referer. 차단 시 graceful degrade(직전값+stale)
- 쓰기: `state/consensus.json` — 종목별 target_price·opinion_score/text·eps_consensus·per_consensus·n_estimates·consensus_date
- 실행: `.github/workflows/fetch_consensus.yml` 주 1회(일 06:45 KST). `--probe` 로 접근성·구조 진단.
- 소비처: Phase 2 earnings-preview(`prompts/earnings_preview.md`) baseline + **목표가 컨센 교차검증**(`policy.consensus.target_cross_check` — 0900 §2 진입 목표가·1800 §2-2 재조정 시 우리 목표가가 컨센×1.15 초과면 경고/상한, audit `audit_target_consensus`). 정책: `policy.consensus`.
- **검증 완료**(2026-06-08): FnGuide 러너 접근 정상, 파서가 컨센 요약 박스(투자의견 4.0/목표주가 415,200/EPS 42,998/PER 7.7/추정기관수 25)를 정확 추출. 영업이익 추정치는 후속 확장.

### `scripts/check_market_open.py` (신규)
- 읽기: `config/market_calendar.json`
- 인자: `--date YYYY-MM-DD` (옵션, 생략 시 오늘 KST)
- 출력: stdout JSON 1줄 + exit code (0=영업일, 10=주말, 11=공휴일)
- 모든 평일 routine 의 0-A 단계 가드. 휴장 시 routine 은 축약 모드 진행 또는 종료.

### `scripts/check_market_session.py` (신규 v2.3)
- 읽기: `config/market_calendar.json.sessions`(+ `check_market_open` 영업일 판정 재사용), `policy.market_hours`
- 인자: `--date YYYY-MM-DD`, `--at HH:MM`, `--now ISO8601` (테스트용 임의 시각)
- 출력: stdout JSON 1줄(session·execution_mode·live_trading_allowed·eod_settlement_allowed) + exit code (0=live, 20=closing_price, 21=none(장 시작 전), 30=closed(비영업일))
- `check_market_open`(영업일)의 '시각' 짝꿍 가드. 모든 평일 routine 0-A 에서 호출해 현재 세션(pre_open/opening_auction/regular/closing_auction/post_close)과 허용 체결 모드를 판정. 18시(post_close)는 `closing_price` — 신규진입 금지·종가 청산만(`policy.market_hours`).

### `scripts/score_candidates.py` (신규)
- 읽기: `config/candidates.json`, `config/weekly_plan.json`, `state/market_snapshot.json`, `config/policy.json`
- 쓰기: `state/candidate_scores.json` (GitHub Actions `fetch_prices.yml` 가 수집·커밋 — **추적됨**, gitignore 대상 아님)
- 09시 routine 0-B 단계에서 `fetch_market_data.py` 직후 호출. 후보 점수·진입 가능 여부 랭킹.

### `scripts/screen_universe.py` (신규 v2.7 — 종목 탐색)
- 읽기: `config/universe.json`(모집단), `config/candidates.json`(중복 방지), `config/themes.json`(strength), `config/policy.json`(entry_filters 상대강도 임계·하드플로어), `state/market_snapshot.json`(KOSPI ret60 벤치마크 + 기수집 종목 재사용)
- 네트워크: 모집단 중 스냅샷에 없는 종목만 네이버+Yahoo 수집(주 1회 전제). 차단 시 graceful degrade(데이터 없음·상대강도 중립 폴백).
- 쓰기: `state/universe_screen.json` — `promote_suggestions`·`rotate_out_suggestions` + (v2.8) `sector_rotation`(전 섹터 몰입 신호)·`avoid_reentry`(avoid 섹터별 해제 점검)·랭킹·리포트 MD
- 소비처: `sunday_strategy`(주간 발굴) + `0900_pre_market.md` §C(tradable<2 미배치 분기). **candidates.json 자동수정 안 함(제안만)** — routine 이 thesis·theme_exposure(근거 URL)와 함께 승격.

### `scripts/reconcile_portfolio.py` (신규)
- 읽기: `config/portfolio.json`, `state/trade_log.jsonl`, `state/market_snapshot.json`
- 출력: stdout JSON(`issues`+`warnings`) + exit code (0=일치, 1=불일치)
- trade_log↔portfolio 정합성 + (v2.2) 평가금액 산식 정합성(`valuation_checks`: market_value=shares×current_price, equity=cash+Σmv, unrealized_pnl)과 스냅샷 대비 평가가격 3% 초과 괴리 경고.
- 09시 routine 0-B 단계의 사전 점검. `audit_pipeline.py` 가 subprocess 로 호출해 audit 결과에 흡수.

### `scripts/pre_trade_check.py` (신규 v2.2)
- 읽기: `state/market_snapshot.json`, `state/candidate_scores.json`, `state/allocation.json`, `config/portfolio.json`, `config/policy.json` (+ `reconcile_portfolio` 함수 재사용)
- 출력: stdout JSON(`verdict`) + exit code (0=ok/live_verify, 1=block/resync)
- **매매(booking) 직전 게이트**(`policy.price_data_quality.pre_trade_gate`). freshness·점수/비중 스냅샷 동기화·장부/평가 정합성을 점검해 `ok`/`live_verify_required`/`resync_required`/`block` 판정. 09/12/15 routine 의 §2-PRE(1-PRE/0-C) 에서 모든 BUY/SELL 직전 호출. 2026-06-01 묵은 스냅샷 신규매수 레이스 재발 방지.

### `scripts/check_trade_log_gate.py` (신규 v2.2, 확장 v2.3)
- 읽기: `state/trade_log.jsonl`, `config/policy.json` (+ `reconcile_portfolio` BUY/SELL 분류 재사용)
- 출력: stdout JSON(`provenance_violations`+`timing_violations`+통합 `violations`+`ok`) + exit code (0=통과, 1=위반)
- **trade log 하드 게이트 — 두 검사를 한 번에**:
  - (1) **provenance**(`policy.price_data_quality.trade_provenance_gate`): `price_source_required_since`(2026-06-02) 이후 booking 에 `price_source`(snapshot_fresh|web_verified) 누락 시 위반.
  - (2) **timing**(`policy.market_hours.trade_timing_gate`, v2.3): `enforced_since`(2026-06-02) 이후 체결 ts 시각이 정규장(09:00~15:30) 밖이면 위반. 단 `execution_venue=closing_auction` 인 SELL(EOD 종가 청산)은 예외, BUY(마감 후 신규진입)는 예외 없음.
- `auto_merge_routines.yml` 가 병합 전 실행해 위반 커밋의 main 병합을 차단하고, `audit_pipeline.py(audit_trade_provenance)` 가 build_and_notify 빌드를 FAIL 시킨다. 프롬프트(pre_trade_gate·market_hours)를 우회한 묵은/미검증·장외 체결의 마지막 방어선.

### `scripts/build_lessons_index.py` (신규)
- 읽기: `state/lessons.md`
- 쓰기: `state/lessons_index.json` (gitignored)
- 일요일 20시 `sunday_policy_review` routine 의 0-A 단계에서 호출. 분류별 항목·룰·반복 카운트 추출.

### `scripts/score_inferences.py` (신규 — 선제적 추론 루프 Phase 1)
- 읽기: `state/inference_log.jsonl`(예측 원장), `state/rule_attribution.json`(inference_id 결합 손익), `config/policy.json`(min_samples)
- 쓰기: `state/inference_scorecard.json` (슬롯·subject 종류·confidence 구간별 적중률 + 결합 실현손익/PF + 미배치 forgone)
- 실행: 18시 routine 당일 즉시 채점 + 일 20시 `sunday_policy_review` §0-D. 표본<min_samples(5) 채점 보류. 의존성 0.

### `scripts/build_inference_checklist.py` (신규 — 선제적 추론 루프 Phase 1)
- 읽기: `state/lessons.md`(선제추론오차/기회비용오차 항목의 `다음 추론 시 고려`), `state/inference_scorecard.json`(반복 miss 요인), `config/policy.json`(체크리스트 줄 상한)
- 쓰기: `state/inference_checklist.md` (**핫패스** — 추론 직전 먼저 읽음, 상한 40줄·`context_budget.audit_thresholds.inference_checklist_max_lines`)
- 실행: 18시 routine 직후(당일 환류) + 일 20시. `build_lessons_index.NEXT_RULE_RE` 의 `다음 추론 시 고려` 캡처 계약에 의존.
- 근거: `docs/plan_proactive_inference.md` (선제 추론 루프 ①INFER→②ACT→③SCORE→④LEARN→체크리스트 환류).

### `scripts/check_intraday_alerts.py` (확장 — 선제 커밋 Phase 3)
- 읽기: `state/market_snapshot.json`·`config/portfolio.json`·`config/policy.json`·`state/pending_orders.json`
- 쓰기: `state/intraday_alert.json`(escalations + **pending_signals**)·`state/intraday_alert_state.json`(캐시 dedup — 단계 + `__pending_fired__`)
- 기존 보유 종목 단계 경보에 더해 **조건부 사전주문 트리거 평가**(수치 price_above/below) → **카톡 신호만, 체결 안 함**(워크플로 contents:read). 체결은 09시 routine 이 게이트 통과 후. `proactive_inference.kill_switch`/`enabled=false` 면 pending 평가 끔.
- `intraday_monitor.yml`(평일 09:03~15:33 30분 간격)이 실행. yml 변경 없음(스크립트 확장만).

### `state/pending_orders.json` (신규 — 선제 커밋 Phase 3)
- 작성: 18시 routine §4(내일 if-then 의 수치 트리거 분기). 소비: 09시 routine §1-PO(게이트 통과 후 집행·status 갱신) + `check_intraday_alerts.py`(장중 트리거 신호).
- 스키마: 파일 상단 `schema` 키. status active→triggered/expired/cancelled. Tier 2 는 카톡 승인 후 반자동.

### `scripts/compact_state.py` (신규 v2.13 — 콘텍스트 예산 · v2.32 P0 커버리지 확장)
- 읽기: `config/watchlist.json`·`config/portfolio.json`·`config/weekly_plan.json`·`config/policy.json`·`config/catalysts.json`·`state/pending_orders.json`·`state/inference_log.jsonl`·`state/target_estimate_log.jsonl`·`state/lessons.md` + 기존 archive 파일들
- 쓰기: 위 config/state(압축) + `state/watchlist_archive.json`(청산 종목·코멘트·상위 comments/cross_check_notes)·`state/watch_items_archive.jsonl`·`state/portfolio_history.jsonl`·`docs/policy_changelog.md`·`state/pending_orders_archive.jsonl`(종결 7일+ 주문·날짜형 _meta 키)·`state/catalysts_archive.jsonl`(manual 과거 7일+)·`state/weekly_plan_archive.jsonl`(weekend_review 날짜키 14일+)·`state/inference_log_archive.jsonl`(채점완료 90일+)·`state/target_estimate_log_archive.jsonl`·`state/lessons_archive.md`(갱신 체인)
- 실행: **매일 19:00 KST `weekly_compact.yml`(v2.32 일간 승격 — 19:30 감사 직전이라 당일 감사가 압축 후 상태 측정)** + 일요일 21시 `sunday_archive` §0-2 + 수동. 멱등, `--dry-run` 지원.
- 원칙: 학습 재료 삭제 없음(이관만) · 청산 종목 candidates 자동 재등록 금지(재발굴은 universe→screen_universe) · 보존 개수는 `policy.context_budget.retention`.
- P0 소비자 계약(2026-08-13 검증): `check_intraday_alerts`(status active 만 평가)·`sync_pending_orders`(active SELL 만)·`estimate_target_price`(과거 촉매 days_until<-7 스킵 — `catalysts_manual_past_keep_days` 7 미만 금지)·`score_inferences`(스코어카드 = 90일 롤링창, target_estimate 선례와 동일)·`check_state_schema`(미채점·위반 라인 보존으로 보정 표면 유지). 설계 전문: `docs/plan_removal_exclusion.md` §5-A.

### `scripts/estimate_target_price.py` (목표주가 추정 레이어 v1.x)
- 읽기: `config/valuation.json`·`state/consensus.json`(기준가), `config/themes.json`·`config/news_impact.json`·`config/news_keywords.json`·`config/catalysts.json`·`state/news_feed.json`(테마·뉴스/촉매 프리미엄), `state/universe_screen.json`(섹터), `state/market_snapshot.json`·`state/price_history.json`(추세 게이트·기반영 차감), `config/watchlist.json`·`config/candidates.json`·`config/portfolio.json`·`config/policy.json`, 참고 `state/fundamentals.json`·`state/valuation_check.json`
- 쓰기: `state/target_estimate.json`(목표 매도가+신규진입 상한가·report_section_md) + `state/target_estimate_log.jsonl`(매 실행 스냅샷 append — score_target_estimates 채점 입력)
- 실행: `fetch_prices.yml` 매 수집 + 12/15시 routine 0-B. watchlist target_price 를 덮어쓰지 않는 참고 레이어.

### `scripts/fetch_valuation.py` (v1.1 — 밸류에이션 시드)
- 읽기: DART OpenAPI(fnlttSinglAcnt, 환경변수 `DART_API_KEY`)·`state/price_history.json`·네이버 PBR — 분기 BPS·TTM EPS 시계열로 진짜 PER/PBR 5년 밴드 산출(키·이력 부족 시 가격분포 근사 폴백, band_quality 구분)
- 쓰기: `config/valuation.json` (기존 값의 source_date 가 더 최신이면 보존 — sunday_strategy 주간 시드가 1차 책임, 이 스크립트는 백스톱)
- 실행: `fetch_valuation.yml` 주 1회(일 07:00 KST) + 수동.

### `scripts/check_valuation_guard.py` (v2.11 — 목표가 천장·과열 가드)
- 읽기: `config/valuation.json`, `config/watchlist.json`(보유 target_price), `state/market_snapshot.json`(현재가)
- 쓰기: `state/valuation_check.json` — 종목별 verdict(ok/cap_target/overheat_entry/deep_value/skip). 소비처: 0900 §2·1800 §2-2 목표가 캡, `score_candidates` valuation_tilt(±0.03), `estimate_target_price` 천장 캡.

### `scripts/fetch_fundamentals.py` (IR/펀더멘털 레이어)
- 읽기: DART OpenAPI(환경변수 `DART_API_KEY`), `config/portfolio.json`·`config/candidates.json`·`config/universe.json` 종목 풀 — 최신 분기 주요계정(매출·영업이익·순이익·earnings_signal). 키·네트워크 없으면 직전본 보존+stale(비치명적)
- 쓰기: `state/fundamentals.json` (+ gitignored 캐시 `state/dart_corpcodes.json`)
- 실행: `fetch_fundamentals.yml` 주 1회(일 07:00 KST). 데일리 routine 은 산출물을 확신·검증 레이어로 소비(타이밍 신호 아님).

### `scripts/sync_pending_orders.py` (신규 v2.21 안건② — 트리거값 동기화)
- 읽기: `state/exit_levels.json`, `state/pending_orders.json`
- 쓰기: `state/pending_orders.json` in-place — active·SELL·트레일링 계열(trailing_first/trailing_residual/chandelier) 사전주문의 trigger.value 를 exit_levels 산출값으로 갱신(고정값 표류 제거, 목표가·BUY 는 대상 아님)
- 실행 슬롯: 09시(compute_exit_levels 직후)·15시(v2.22 ⑥)·18시(EOD 갱신 직후).

### `scripts/update_exit_tracking.py` (신규 v2.22 ⑩ — 보유 종가 영속 적재)
- 읽기: `config/portfolio.json`, `state/market_snapshot.json`(five_day_history 일자별 bar)
- 쓰기: `state/exit_tracking.json` — 보유 종목 일별 확정 종가 append(기존 (ticker,date) 불변·confidence=low 는 당일 보류). compute_exit_levels 의 '진입 이후 최고 종가'가 6일 창 폴백에 갇히던 제약 해소
- 실행: 18시 EOD — `fetch_market_data` 직후·`compute_exit_levels` 직전.

### `scripts/self_audit.py` (신규 v2.22 ⑥ — 주간 자기감사)
- 읽기: `state/trade_log.jsonl`·`config/portfolio.json`·`state/rule_attribution.json`·`state/price_history.json` 등 (+ `reconcile_portfolio`·`check_trade_log_gate` 재사용) — 원장 정합·PF·vs KOSPI 격차·스톱 휩쏘율·게이트 위반·패치 vs 검증 속도·배치·청산 오버레이 A~H 재측정
- 쓰기: `state/self_audit.json`(히스토리), `state/self_audit_findings.json`(finding 수명·처분), `reports/YYYY-MM-DD-self-audit.md`
- 실행: `weekly_self_audit.yml` 일 17:00 KST. `sunday_policy_review` §0-0 이 의무 인용·disposition 기입, `--followup-only`+`AUDIT_ENFORCE=1` 에서 무처분 2주+ overdue 존재 시 exit 1(워크플로 FAIL).

### `scripts/sync_watchlist.py` (신규 2026-07-08 — watchlist 정본 동기화)
- 읽기: `config/portfolio.json`(보유 정본), `state/exit_levels.json`(청산선 정본)
- 쓰기: `config/watchlist.json` — 보유 종목의 shares_held·stop_price·target_price 를 정본 값으로 덮어쓰고 status="held" 보장(watchlist 가 폐기된 '제3값'을 들고 있던 B-1/B-2 드리프트 해소). portfolio 에 없는 held 종목은 shares_held=0+경고만(이관은 compact_state 소관)
- 실행: 18시 EOD(확정 후) + 정합성 이슈 발견 시 수동. 멱등·`--dry-run`.

### `scripts/write_audit_report.py`
- 읽기: `config/policy.json`, `config/portfolio.json`, `config/weekly_plan.json`, `audit_pipeline.py` stdout
- 쓰기: `reports/YYYY-MM-DD-audit.md`, `state/audit_log.jsonl`, `config/weekly_plan.json` (자동 수정 항목)

### `scripts/build_html.py`
- 읽기: `reports/*.md` (모두), `config/portfolio.json`, `templates/*`
- 쓰기: `_site/*.html`, `_site/style.css`
- 인덱스 페이지는 일일 리포트를 **날짜별로 그룹핑** 해서 6칸 슬롯 카드(`STD_SLOTS` = 00/06/09/12/15/18)로 표시 (시간대별 분리 인지)

### `scripts/send_kakao.py`
- **발송 가드 3종 (2026-06-12 — 오발송 사고 재발 방지)**:
  - `detect_slot` 은 커밋 **제목 줄만** 보고 `chore(HH:00` 프리픽스를 1순위 매칭 (본문 ISO 타임스탬프의 "00:00" 오인 차단)
  - 슬롯 미식별 커밋(`chore(context)` 등)은 **발송 스킵** — '최신 리포트' 폴백 제거 (전일 리포트 오발송 차단)
  - `is_dated_today`(리포트 파일 날짜=오늘) + `push_modified`(이번 push 가 해당 리포트 파일을 실제 변경 — `CHANGED_FILES_FILE`, build_and_notify notify 잡이 before..after diff 로 생성) 둘 다 통과해야 발송 (중복·묵은 리포트 차단). `KAKAO_DRY_RUN=1` 로 발송 없이 판정 테스트 가능.
- 읽기: `reports/` 안에서 커밋 메시지 기반 슬롯 매핑
  - `chore(00:00 ...)` → `reports/*-00.md` 우선
  - `chore(09:00 ...)` → `reports/*-09.md` 우선
  - `chore(12:00 ...)` → `reports/*-12.md` 우선
  - `chore(15:00 ...)` → `reports/*-15.md` 우선
  - `report:` (18시) → `reports/*-18.md` 우선
  - `weekly-archive:` → `reports/*-archive.md`
  - `audit:` → `reports/*-audit.md`
  - `sat-review:` → `reports/*-saturday-review.md`
  - `sun-strategy:` → `reports/*-sunday-strategy.md`
  - `policy-review:` → `reports/*-policy-review.md` (신규)
- 시간대별 분리 파일이 없으면 구버전 `reports/YYYY-MM-DD.md` 로 폴백
- 쓰기: 카카오 API 호출만 (디스크 쓰기 없음)

## 5. GitHub Actions 워크플로우

### `.github/workflows/fetch_prices.yml`
- 트리거: **`workflow_dispatch`(1순위 — 외부 스케줄러 cron-job.org 가 routine 5분 전 정시 호출)** + `schedule` 백업 1겹(routine 약 1시간 전 :05). 설정: `docs/price_fetch_trigger.md`
- 단계: `fetch_market_data.py`(시세 병렬 수집) → `score_candidates.py` → 변경 시 `state/market_snapshot.json`·`candidate_scores.json` 커밋·푸시
- 효과: dispatch 는 큐 지연 0초 → 스냅샷 age ~5분(fresh) → routine 웹 교차확인 부담 해소

### `.github/workflows/build_and_notify.yml`
- 트리거: `reports/`·`config/`·`scripts/`·`templates/`·`docs/` 변경, `workflow_dispatch`
- 단계: audit → build_html → upload pages → deploy → notify (Kakao)
- notify if-clause 허용 커밋 prefix: `report:`, `weekly:`, `weekly-archive:`, `audit:`, `sat-review:`, `sun-strategy:`, `policy-review:`, `chore(`

### `.github/workflows/pipeline_audit.yml`
- 트리거: 평일 19:30 KST cron, `workflow_dispatch`
- write_audit_report.py 실행 → audit 리포트 생성·커밋·푸시 → 카톡 알림

## 6. config 파일 간 일관성 규칙

- `config/portfolio.json.equity` ↔ `config/weekly_plan.json.objective.current_equity`
  - 18시 routine 과 audit script 가 이 값을 동기화한다
- `config/policy.json.risk.weekly_account_target_return_pct` → `config/weekly_plan.json.objective.target_return_pct`
- `config/watchlist.json` 의 `weekly_thesis_id` → `config/weekly_plan.json.weekly_thesis[].id`
- (thesis-tracker, Part B) `config/watchlist.json.stocks[].thesis` = `{id, statement, key_drivers[], invalidation[], status, entry_ts, last_review_ts}`. `invalidation[].type` 은 18시 자기보완 4분류(매크로/섹터/개별/가정오류)와 **동일 enum** (`policy.thesis.invalidation_type_enum`). `invalidation[].linked_catalyst` → `config/catalysts.json` 의 earnings 촉매 id (Part C 결합).
  - 소비처: `0900_pre_market.md`(B 2-1 무효화 1차 점검), `1800_report.md`(2-4 무효화 판정 + 종목별 종가 점검 status 뱃지 + §3 lessons type 기록). audit: `audit_pipeline.audit_thesis`.
- (earnings-preview, Phase 2) `prompts/earnings_preview.md` (이벤트 기반 스펙) + `state/earnings_preview.json`(active 프리뷰 + scorecard). 입력: `catalysts.json`(언제)·`consensus.json`(예상치)·`watchlist.thesis`(논리)·`fundamentals.json`(실제값). 호출: `1800_report.md` §2-5(PREVIEW/SCORE 주), `0900_pre_market.md` 1-4(발표일 재확인/보강). 메타: `sunday_policy_review` 가 scorecard hit-rate 점검. 정책: `policy.earnings_preview`. audit: consensus/earnings_preview 블록.

## 7. 점검 체크리스트 (수동 점검 시)

- [ ] 오늘 날짜로 `reports/YYYY-MM-DD-{00,06,09,12,15,18}.md` 6개 파일이 모두 있는가?
- [ ] 각 파일의 첫 줄(`# 일일 리포트 — ... · 슬롯명`) 이 자기 슬롯과 일치하는가?
- [ ] "시리즈 진행" 줄의 ✓ 표시가 자기 시간대만 ✓ / 나머지는 "대기" 또는 "✓"(이전 시간대) 인가?
- [ ] 이전 시간대 파일 링크가 깨지지 않았는가?
- [ ] `## ⚠️ 위험·매매 시그널 시각화` / `## 🎓 오늘의 학습 노트` 두 섹션이 들어 있는가? (구버전 "🎓 학습 포인트 3개"·"📖 오늘 등장한 용어"는 "🎓 오늘의 학습 노트"로 통합)
- [ ] 일요일 21:00 archive 가 매주 생성되어 평일 routine 콘텍스트가 한 주치 응축으로 유지되는가?
- [ ] (신규) `state/market_snapshot.json` 의 `as_of` 가 최신 routine 시각과 일치하는가? 보유종목 `confidence` 가 모두 `low` 면 출처 차단 신호.
- [ ] (신규) 오늘이 휴장일이면 `check_market_open.py` 결과대로 routine 이 축약 모드로 진행됐는가?
- [ ] (v2.3) 모든 BUY/SELL 체결의 `ts` 시각이 정규장(09:00~15:30) 안인가? 18시 종가 청산은 `ts=15:30`+`execution_venue=closing_auction` 로 기록됐는가? (`check_trade_log_gate.py` 가 자동 검증 — 위반 시 CI FAIL)
- [ ] (v2.3) 18시 routine 이 신규 진입(BUY)을 booking 하지 않고 다음 영업일 09시로 이연했는가?
- [ ] (v2.4) 종목별 '현재가'가 `today_ohlc`(시가/고가/저가)와 함께 제시됐는가? 웹 보강값이 스냅샷 close 대비 ±3% 초과 outlier인데 `today_high` 근처면 버리고 스냅샷을 썼는가? 출처 URL 없는 '○○ 기대감 추정' 촉매 서술이 없는가? (`policy.price_data_quality.web_verify_guard`)
