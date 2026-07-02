# 파일 참조 구조 점검 (2026-06-12 갱신)

이 문서는 각 prompt / script 가 **어떤 파일을 읽고 / 어떤 파일을 쓰는지** 한눈에 보여준다.
시간대별 리포트 분리 + 시장 데이터 자동 수집 + 휴장일 가드 작업 이후 갱신.

> **신규 추가 (2026-06-12, v2.13 콘텍스트 예산)**
> - `scripts/compact_state.py` — 핫패스 누적 필드 압축: watchlist 청산 종목·오래된 코멘트 → `state/watchlist_archive.json`,
>   watch_items 초과분 → `state/watch_items_archive.jsonl`, portfolio.history → `state/portfolio_history.jsonl`(config 최근 10개),
>   policy.changelog → `docs/policy_changelog.md`(policy 최근 5건). 일요일 21시 sunday_archive §0-2 + 수동. 멱등·`--dry-run`.
> - `state/lessons_archive.md` — codify 확정 lessons 항목 전문 보존 (sunday_policy_review §1-6 이 이관, routine 은 읽지 않음)
> - `audit_pipeline.audit_context_budget` — 핫패스 크기 임계(`policy.context_budget.audit_thresholds`) 초과 WARN
> - `audit_pipeline.audit_reports` 확장 — 당일 00시 슬롯 누락 WARN(월요일 미발화 표면화) + '한눈에 보기' 운영 용어 노출 WARN
> - `check_lessons_applied.py` haystack 에 `docs/policy_changelog.md` 포함 (changelog 분리에 따른 오탐 방지)
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
> - `scripts/check_market_open.py` — 영업일/휴장일 판정 (모든 평일 routine 의 0-A 단계에서 호출)
> - `scripts/score_candidates.py` — 후보 자동 점수화 → `state/candidate_scores.json`
> - `scripts/reconcile_portfolio.py` — trade_log ↔ portfolio 정합성 검증 (audit + 09시 사전 점검)
> - `scripts/build_lessons_index.py` — lessons.md 분류·룰 인덱스 → `state/lessons_index.json`
> - `prompts/sunday_policy_review.md` — 일요일 20시 정책 패치 리뷰
> - `state/{market_snapshot,candidate_scores,lessons_index}.json` — 모두 매 routine 마다 신규 생성 (gitignored)

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
- 직전 영업일 18시 리포트: `reports/YYYY-MM-DD-18.md` (없으면 구버전 `reports/YYYY-MM-DD.md`)
- 직전 주말 archive: `reports/YYYY-Www-archive.md`

**쓰기**:
- `reports/YYYY-MM-DD-00.md` (신규 생성)
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
- 오늘 자정 파일: `reports/YYYY-MM-DD-00.md`
- 오늘 06시 파일: `reports/YYYY-MM-DD-06.md` (있으면 마감 확정·갱신 갭 예측을 1순위 흡수)
- 직전 영업일 18시: `reports/YYYY-MM-DD-18.md`
- 직전 주말 archive: `reports/YYYY-Www-archive.md`

**쓰기**:
- `reports/YYYY-MM-DD-09.md` (신규 생성)
- `config/watchlist.json`, `config/portfolio.json`
- `state/trade_log.jsonl` (체결 시 1라인 append)
- `state/lessons.md` (필요 시)

### 🕛 12:00 장중 (`prompts/1200_midday.md`)
**읽기**:
- `state/lessons.md`
- `config/*` 4개
- 오늘 09시 파일: `reports/YYYY-MM-DD-09.md`
- 오늘 자정 파일: `reports/YYYY-MM-DD-00.md` (참고)

**쓰기**:
- `reports/YYYY-MM-DD-12.md` (신규 생성)
- `config/watchlist.json`, `config/portfolio.json`
- `state/trade_log.jsonl`, `state/lessons.md` (orange/red 발생 시)

### 🔔 15:00 마감 임박 (`prompts/1500_close.md`)
**읽기**:
- `state/lessons.md`
- `config/*` 4개
- 오늘 12시 파일: `reports/YYYY-MM-DD-12.md`
- 오늘 09시 파일: `reports/YYYY-MM-DD-09.md` (참고)

**쓰기**:
- `reports/YYYY-MM-DD-15.md` (신규 생성)
- `config/watchlist.json`, `config/weekly_plan.json` (watch_items 갱신)
- ※ 매매 체결은 권유하지 않음. 익일 09시 후보만 표시.

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
- 원본 25개 파일은 그대로 둔다 (감사 추적성)
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
- 쓰기: `state/candidate_scores.json` (gitignored)
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

### `scripts/compact_state.py` (신규 v2.13 — 콘텍스트 예산)
- 읽기: `config/watchlist.json`·`config/portfolio.json`·`config/weekly_plan.json`·`config/policy.json` + 기존 archive 파일들
- 쓰기: 위 4개 config(압축) + `state/watchlist_archive.json`·`state/watch_items_archive.jsonl`·`state/portfolio_history.jsonl`·`docs/policy_changelog.md`(전문 보존)
- 실행: 일요일 21시 `sunday_archive` §0-2 (commit 범위에 config/state/docs 포함) + 수동. 멱등, `--dry-run` 지원.
- 원칙: 학습 재료 삭제 없음(이관만) · 청산 종목 candidates 자동 재등록 금지(재발굴은 universe→screen_universe) · 보존 개수는 `policy.context_budget.retention`.

### `scripts/write_audit_report.py`
- 읽기: `config/policy.json`, `config/portfolio.json`, `config/weekly_plan.json`, `audit_pipeline.py` stdout
- 쓰기: `reports/YYYY-MM-DD-audit.md`, `state/audit_log.jsonl`, `config/weekly_plan.json` (자동 수정 항목)

### `scripts/build_html.py`
- 읽기: `reports/*.md` (모두), `config/portfolio.json`, `templates/*`
- 쓰기: `_site/*.html`, `_site/style.css`
- 인덱스 페이지는 일일 리포트를 **날짜별로 그룹핑** 해서 5칸 슬롯 카드로 표시 (시간대별 분리 인지)

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
- [ ] `## ⚠️ 위험·매매 시그널 시각화` / `## 🎓 학습 포인트 3개` / `## 📖 오늘 등장한 용어` 세 섹션이 들어 있는가?
- [ ] 일요일 21:00 archive 가 매주 생성되어 평일 routine 콘텍스트가 한 주치 응축으로 유지되는가?
- [ ] (신규) `state/market_snapshot.json` 의 `as_of` 가 최신 routine 시각과 일치하는가? 보유종목 `confidence` 가 모두 `low` 면 출처 차단 신호.
- [ ] (신규) 오늘이 휴장일이면 `check_market_open.py` 결과대로 routine 이 축약 모드로 진행됐는가?
- [ ] (v2.3) 모든 BUY/SELL 체결의 `ts` 시각이 정규장(09:00~15:30) 안인가? 18시 종가 청산은 `ts=15:30`+`execution_venue=closing_auction` 로 기록됐는가? (`check_trade_log_gate.py` 가 자동 검증 — 위반 시 CI FAIL)
- [ ] (v2.3) 18시 routine 이 신규 진입(BUY)을 booking 하지 않고 다음 영업일 09시로 이연했는가?
- [ ] (v2.4) 종목별 '현재가'가 `today_ohlc`(시가/고가/저가)와 함께 제시됐는가? 웹 보강값이 스냅샷 close 대비 ±3% 초과 outlier인데 `today_high` 근처면 버리고 스냅샷을 썼는가? 출처 URL 없는 '○○ 기대감 추정' 촉매 서술이 없는가? (`policy.price_data_quality.web_verify_guard`)
