# 파일 참조 구조 점검 (2026-05-22 갱신)

이 문서는 각 prompt / script 가 **어떤 파일을 읽고 / 어떤 파일을 쓰는지** 한눈에 보여준다.
시간대별 리포트 분리 + 시장 데이터 자동 수집 + 휴장일 가드 작업 이후 갱신.

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

### 🌅 09:00 개장 (`prompts/0900_pre_market.md`)
**읽기**:
- `state/lessons.md` (먼저)
- `config/policy.json`, `config/weekly_plan.json`, `config/watchlist.json`, `config/portfolio.json`
- 오늘 자정 파일: `reports/YYYY-MM-DD-00.md`
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
- 오늘 시간대별 리포트 4개: `reports/YYYY-MM-DD-{00,09,12,15}.md`

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
- 지난주 평일 5일 × 5슬롯 = 최대 25개 시간대별 리포트
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
- 읽기: `config/*` 6개(policy/weekly_plan/watchlist/portfolio/candidates/market_calendar), `state/trade_log.jsonl`, `prompts/*.md` (존재 확인), `reports/*.md` (정규식 `YYYY-MM-DD(-(00|09|12|15|18))?.md`), `scripts/fetch_market_data.py`·`scripts/check_market_open.py` 존재 확인
- 쓰기: 없음 (stdout만)

### `scripts/fetch_market_data.py` (신규)
- 읽기: `config/portfolio.json` (보유), `config/candidates.json` (후보), `config/policy.json` (`entry_filters.block_if_cumulative_return_below_pct`)
- 네트워크: 네이버 siseJson 일별 + Yahoo Finance v8 chart JSON (양쪽 시도, 둘 다 실패 시 직전 스냅샷 보존+stale)
- 쓰기: `state/market_snapshot.json` (GitHub Actions `fetch_prices.yml` 가 수집·커밋, 추적됨)

### `scripts/check_market_open.py` (신규)
- 읽기: `config/market_calendar.json`
- 인자: `--date YYYY-MM-DD` (옵션, 생략 시 오늘 KST)
- 출력: stdout JSON 1줄 + exit code (0=영업일, 10=주말, 11=공휴일)
- 모든 평일 routine 의 0-A 단계 가드. 휴장 시 routine 은 축약 모드 진행 또는 종료.

### `scripts/score_candidates.py` (신규)
- 읽기: `config/candidates.json`, `config/weekly_plan.json`, `state/market_snapshot.json`, `config/policy.json`
- 쓰기: `state/candidate_scores.json` (gitignored)
- 09시 routine 0-B 단계에서 `fetch_market_data.py` 직후 호출. 후보 점수·진입 가능 여부 랭킹.

### `scripts/reconcile_portfolio.py` (신규)
- 읽기: `config/portfolio.json`, `state/trade_log.jsonl`, `state/market_snapshot.json`
- 출력: stdout JSON(`issues`+`warnings`) + exit code (0=일치, 1=불일치)
- trade_log↔portfolio 정합성 + (v2.2) 평가금액 산식 정합성(`valuation_checks`: market_value=shares×current_price, equity=cash+Σmv, unrealized_pnl)과 스냅샷 대비 평가가격 3% 초과 괴리 경고.
- 09시 routine 0-B 단계의 사전 점검. `audit_pipeline.py` 가 subprocess 로 호출해 audit 결과에 흡수.

### `scripts/pre_trade_check.py` (신규 v2.2)
- 읽기: `state/market_snapshot.json`, `state/candidate_scores.json`, `state/allocation.json`, `config/portfolio.json`, `config/policy.json` (+ `reconcile_portfolio` 함수 재사용)
- 출력: stdout JSON(`verdict`) + exit code (0=ok/live_verify, 1=block/resync)
- **매매(booking) 직전 게이트**(`policy.price_data_quality.pre_trade_gate`). freshness·점수/비중 스냅샷 동기화·장부/평가 정합성을 점검해 `ok`/`live_verify_required`/`resync_required`/`block` 판정. 09/12/15 routine 의 §2-PRE(1-PRE/0-C) 에서 모든 BUY/SELL 직전 호출. 2026-06-01 묵은 스냅샷 신규매수 레이스 재발 방지.

### `scripts/build_lessons_index.py` (신규)
- 읽기: `state/lessons.md`
- 쓰기: `state/lessons_index.json` (gitignored)
- 일요일 20시 `sunday_policy_review` routine 의 0-A 단계에서 호출. 분류별 항목·룰·반복 카운트 추출.

### `scripts/write_audit_report.py`
- 읽기: `config/policy.json`, `config/portfolio.json`, `config/weekly_plan.json`, `audit_pipeline.py` stdout
- 쓰기: `reports/YYYY-MM-DD-audit.md`, `state/audit_log.jsonl`, `config/weekly_plan.json` (자동 수정 항목)

### `scripts/build_html.py`
- 읽기: `reports/*.md` (모두), `config/portfolio.json`, `templates/*`
- 쓰기: `_site/*.html`, `_site/style.css`
- 인덱스 페이지는 일일 리포트를 **날짜별로 그룹핑** 해서 5칸 슬롯 카드로 표시 (시간대별 분리 인지)

### `scripts/send_kakao.py`
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

## 7. 점검 체크리스트 (수동 점검 시)

- [ ] 오늘 날짜로 `reports/YYYY-MM-DD-{00,09,12,15,18}.md` 5개 파일이 모두 있는가?
- [ ] 각 파일의 첫 줄(`# 일일 리포트 — ... · 슬롯명`) 이 자기 슬롯과 일치하는가?
- [ ] "시리즈 진행" 줄의 ✓ 표시가 자기 시간대만 ✓ / 나머지는 "대기" 또는 "✓"(이전 시간대) 인가?
- [ ] 이전 시간대 파일 링크가 깨지지 않았는가?
- [ ] `## ⚠️ 위험·매매 시그널 시각화` / `## 🎓 학습 포인트 3개` / `## 📖 오늘 등장한 용어` 세 섹션이 들어 있는가?
- [ ] 일요일 21:00 archive 가 매주 생성되어 평일 routine 콘텍스트가 한 주치 응축으로 유지되는가?
- [ ] (신규) `state/market_snapshot.json` 의 `as_of` 가 최신 routine 시각과 일치하는가? 보유종목 `confidence` 가 모두 `low` 면 출처 차단 신호.
- [ ] (신규) 오늘이 휴장일이면 `check_market_open.py` 결과대로 routine 이 축약 모드로 진행됐는가?
