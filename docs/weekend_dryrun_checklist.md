# 주말 routine 첫 실행 dry-run 체크리스트

> 작성: 2026-05-22 / 대상: 2026-05-23(토) saturday_review, 2026-05-24(일) sunday_strategy, 2026-05-24(일) 21시 sunday_archive
> 목적: 첫 주말 routine 이 실제로 시작되기 전에 prompt·입력 파일·기대 산출물이 모두 갖춰져 있는지 점검.

## 1. 사전 점검 (토요일 18:00 발화 전)

### 입력 파일 존재
- [ ] `state/lessons.md` (마지막 갱신: 2026-05-22 09시) — 4건 누적
- [ ] `config/policy.json` v1.2
- [ ] `config/weekly_plan.json` week_id `2026-W21`
- [ ] `config/watchlist.json` (5/22 12시 시점 KB금융·삼성전자 코멘트)
- [ ] `config/portfolio.json` (5/22 09:05 트레일링스톱 체결 반영)
- [ ] `config/candidates.json` 3종목 (신규)
- [ ] `config/market_calendar.json` 13건 휴일 (신규)
- [ ] `state/trade_log.jsonl` 10라인 (5/22 09:05 트레일링스톱 포함)
- [ ] 이번 주 리포트 5일치:
  - 2026-05-20.md (구버전 단일)
  - 2026-05-21.md (구버전 단일)
  - 2026-05-22-00.md / -09.md / -12.md / -15.md / -18.md (-15, -18 은 발화 전이라 미존재)

### 스크립트 dry-run 확인
- [ ] `python scripts/check_market_open.py --date 2026-05-23` → `is_open=false`, reason=주말
- [ ] `python scripts/check_market_open.py --date 2026-05-25` → `is_open=false`, reason=부처님오신날 대체휴일
- [ ] `python scripts/fetch_market_data.py` → state/market_snapshot.json 생성 (네트워크 가용 시 high/medium 신뢰도, 차단 시 low)
- [ ] `python scripts/audit_pipeline.py` → 모든 신규 파일/스크립트 OK 표시

## 2. saturday_review.md routine (2026-05-23 18:00)

### 산출물 검증 포인트
- [ ] `reports/2026-05-23-saturday-review.md` 생성
- [ ] 주간 성과 대시보드: 시작 자산 5,000,000 → 현재 (5/22 18시 종가 평가 후 결정)
- [ ] 종목별 사후분석: 기아(손절) / 삼성전자(트레일링스톱) / KB금융(보유) 3건
- [ ] 루틴 연결성 평가: 00→09→12→15→18 단계별 끊긴 지점 식별 (5/20 자정 속보 미포착 등)
- [ ] lessons.md `weekend_review.last_completed = 2026-05-23` 갱신
- [ ] 0-A 단계에서 fetch_market_data.py 실행됐는지 (snapshot ts = 토요일 18시 인접 시각)

### 커밋·알림
- [ ] commit prefix `sat-review:` → 카톡 발송 트리거 동작 확인

## 3. sunday_strategy.md routine (2026-05-24 18:00)

### 산출물 검증 포인트
- [ ] `reports/2026-05-24-sunday-strategy.md` 생성
- [ ] `config/weekly_plan.json` 갱신:
  - `week_id = "2026-W22"`
  - `objective.starting_equity` = 새 주 시작 자산
  - `weekly_thesis` 재설계 (이전 주 결과 반영)
  - `daily_bridge` 갱신
  - `watch_items` 에 **"2026-05-25(월) 부처님오신날 대체휴일 — 휴장 모드"** 명시 (0-B 단계 결과)
  - `weekend_review.last_completed = 2026-05-24`
  - `weekend_review.next_due = 2026-05-30` (또는 다음 주말)
- [ ] 운영 모드 판정 (`growth` / `balanced` / `defensive`) — 누적 수익률 기준
- [ ] 0-B 단계에서 5/25 휴장 확인되어 다음주 routine 일정에 반영됐는가

### 커밋·알림
- [ ] commit prefix `sun-strategy:` → 카톡 발송 트리거 동작 확인

## 4. sunday_archive.md routine (2026-05-24 21:00)

### 산출물 검증 포인트
- [ ] `reports/2026-W21-archive.md` 생성 (첫 archive 파일)
- [ ] 응축 범위: 5/18(월)~5/22(금) 평일 × 슬롯별 = 최대 25개 → 단 5/20·21·22 만 존재 (3일치)
- [ ] 원본 25개 파일은 그대로 유지 (감사 추적성)
- [ ] 다음주 평일 routine 이 이 archive 1개만 읽으면 콘텍스트 절약 가능한 형태인가

## 5. 5/25(월) 첫 휴장일 routine 동작 확인

- [ ] 00:00 routine — 글로벌 야간 점검 정상 진행 (해외장은 정상)
- [ ] 09:00 routine — 0-A 가드에서 `is_open=false` 확인 후 휴장 모드 1줄 리포트만 작성
- [ ] 12:00·15:00 routine — 0-A 가드에서 즉시 종료 (skip)
- [ ] 18:00 routine — 0-A 가드에서 종가 평가 생략, 다음 영업일(5/26 화) 액션 플랜만 작성

## 6. 보강이 필요할 수 있는 항목 (사전 인지)

- **2026-W21 archive 가 평일 3일치(5/20·21·22)뿐** — sunday_archive.md prompt 가 "정상 5일치 가정"으로 작성됐다면 첫 주는 부분 archive 임을 명시할 필요
- **5/22 (금) 18시 routine 미발화 시점에 토요일 routine 진입** → saturday_review 가 5/22 종가 데이터를 어디서 가져올지 prompt 확인 필요 (현재는 `state/market_snapshot.json` + 웹검색 보강)
- **다음주 월요일이 휴장(5/25)** → sunday_strategy 의 "월요일 09시 첫 액션" 섹션이 실제로는 화요일(5/26) 09시 액션이 되어야 함. prompt 가 휴장일을 자동 인식하는지 검증
