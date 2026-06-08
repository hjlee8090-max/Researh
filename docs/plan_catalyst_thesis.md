# 계획서 — catalyst-calendar + thesis-tracker 채용

> 출처: Claude 공식 `equity-research` 플러그인의 `catalyst-calendar`·`thesis-tracker` 스킬 설계를
> 우리 KOSPI 자기보완형 오토플로우(GitHub + 마크다운 + 카카오)에 맞게 재구성한 채용 계획서.
> **본 문서는 설계안이며, 구현·커밋은 별도 승인 후 진행한다.**

---

## 0. 배경·목표

| 항목 | 현황 | 채용 후 |
|---|---|---|
| 종목별 다가오는 이벤트(실적·배당락·매크로) | **없음** (`market_calendar.json`은 휴장/세션만) | `config/catalysts.json` 로 종목별 촉매 추적, D-day 경보 |
| 매수 논리 + 무효화 조건 | 주간 단위만 (`weekly_plan.invalidation_triggers`) | **종목별** thesis·invalidation 을 `watchlist.json` 에 박고 18시 루프에서 판정 |
| 18시 자기보완 루프 분류 | 가격 오차(매크로/섹터/개별/가정오류) 중심 | "논리 깨짐(invalidation)"을 가격 오차와 **독립적으로** 추가 판정 |

**핵심 원칙(기존 정책 준수)**
- 무료 데이터만 사용 (DART OpenAPI·웹검색). 유료 커넥터(FactSet 등) 도입 안 함.
- 일봉 기반 시뮬레이션, 종가 청산만. 신규 데이터 소스로 인한 체결 모델 변경 없음.
- 이전 시간대 리포트 파일 수정 금지 원칙 유지.
- 펀더멘털·이벤트는 **후행/확신 레이어**. 타이밍은 regime·momentum 이 담당(기존 철학 유지).

---

## 범위 (Scope)

**In**
- Part A: catalyst-calendar (종목별 촉매 캘린더 + D-day 경보)
- Part B: thesis-tracker (종목별 논리·무효화 추적)
- Part C: A↔B 결합 (실적 촉매 → 논리 무효화 자동 연결)
- Part D: 감사/문서 정합성 갱신

**Out (이번 범위 아님)**
- earnings-preview 시나리오 3종 자동 생성 → Part C 의 후속(Phase 2)으로 분리
- 섹터 로테이션(`sector-analyst`), edge-pipeline → 별도 계획서
- 옵션/페어/13F 등 정책 범위 밖 스킬

---

# Part A — catalyst-calendar (촉매 캘린더)

## A-1. 데이터 모델 — `config/catalysts.json` (신규)

```jsonc
{
  "version": "1.0",
  "as_of": "2026-06-07T18:00:00+09:00",
  "timezone": "Asia/Seoul",
  "source": "DART list.json(공시 이력 기반 추정) + 웹검색 확정 + 수동",
  "note": "earnings_date 는 DART 과거 보고서 제출일 패턴 기반 '추정'일 수 있음. confirmed=true 만 확정.",
  "events": [
    {
      "id": "005930-2026Q2-earnings",
      "ticker": "005930",
      "name": "삼성전자",
      "type": "earnings",          // earnings | earnings_guidance | ex_dividend | dividend_pay | agm | buyback | lockup | macro | index_rebalance
      "scope": "stock",            // stock | macro (매크로는 ticker 생략)
      "date": "2026-07-08",
      "window": "2026-07-07~2026-07-09",  // 추정 폭(미확정 시)
      "confirmed": false,           // 웹검색/IR 확정 여부
      "importance": "high",         // high | medium | low
      "expectation": "잠정실적(가이던스) 발표 추정 — 전분기 OP 57.2조 베이스",
      "linked_thesis": ["hbm_supercycle"],  // watchlist thesis.id 와 연결 (Part B)
      "source_url": "https://...",
      "updated_at": "2026-06-07T18:00:00+09:00"
    },
    {
      "id": "macro-2026-06-fomc",
      "type": "macro", "scope": "macro",
      "date": "2026-06-18", "confirmed": true, "importance": "high",
      "expectation": "FOMC 금리결정 — 환율/외국인 수급 영향",
      "affects_sectors": ["IT/반도체", "금융"]
    }
  ]
}
```

**설계 결정**
- `confirmed` 플래그로 추정/확정을 명확히 구분 → LLM 이 경보 강도를 조절.
- `window` 는 미확정 실적일의 불확실성 폭. 확정되면 `date` 로 좁힘.
- `macro` 이벤트는 `affects_sectors` 로 보유 종목 섹터에 자동 매핑.
- `linked_thesis` 로 Part B 와 직결 (촉매 통과 = 논리 검증 트리거).

## A-2. 데이터 소싱 (무료, 우선순위)

1. **DART `list.json`** (이미 `fetch_fundamentals.py` 가 DART 키 사용 중 → 재사용)
   - 과거 분기보고서/잠정실적 **제출일 패턴**으로 다음 분기 발표 시기 추정.
   - 배당 결정·자사주 취득/소각 등 **이미 공시된** 이벤트는 정확히 수집 가능.
   - 한계: DART 에 "미래 실적발표 예정일" 공식 API 없음 → 추정 + confirmed=false.
2. **웹검색 보강** (routine 내 WebSearch): "[종목명] 2분기 실적발표일", "FOMC 일정" 등으로 confirmed 승격.
3. **수동 시드**: 분기 1회 사람이 IR 캘린더 확인해 핵심 이벤트 입력(선택).

## A-3. 신규 스크립트 — `scripts/fetch_catalysts.py`

- **역할**: DART list.json + 과거 보고서 제출일에서 종목별 다음 실적/배당/AGM 이벤트를 추정 생성.
- **입력**: `config/watchlist.json`(보유), `config/candidates.json`(후보), DART_API_KEY.
- **출력**: `config/catalysts.json` (추정 이벤트는 confirmed=false 로). 기존 confirmed=true·수동 이벤트는 **보존**(merge, 덮어쓰기 금지).
- **의존성·폴백**: 키/네트워크 없으면 기존 파일 보존 + stale 표시(=`fetch_fundamentals.py` 패턴 그대로).
- **실행 주기**: 분기성 데이터이므로 **주간(일요일)** + 매크로 이벤트는 routine 내 웹검색 보강.
- **갱신 원칙**: 지난 이벤트(date < today)는 `events_archive` 로 이동 또는 7일 후 정리.

## A-4. 프롬프트 통합

| 프롬프트 | 추가 섹션 | 동작 |
|---|---|---|
| `0000_global.md` | "오늘~D+2 매크로 촉매" | macro 이벤트(FOMC 등) D-day 경보, 보유 섹터 영향 매핑 |
| `0900_pre_market.md` | `0` 컨텍스트 적재에 `config/catalysts.json` 추가 / `1-2` 뒤 "촉매 임박 경보" | 보유·후보의 D-3 이내 high 촉매 → "실적 D-1, 신규 진입 보류/비중 주의" |
| `1500_close.md` | "익일·금주 촉매" | 다음날 실적발표 보유 종목 → 종가 청산/축소 후보 검토 트리거 |
| `1800_report.md` | `4. 다음 거래일 액션`에 "촉매 D-day" 반영 + Part B 연결 | 실적 발표일 통과 시 thesis 검증으로 연결(Part C) |

**경보 규칙(초안)**
- high 촉매 D-1 이내 + 미확정 방향 → **신규 진입 보류**, 보유는 변동성 경고.
- 실적 D-day 가 손절선 근접과 겹치면 → 기존 v2.1 손절 안전망(실시간 교차확인) 우선 발동.

## A-5. 자동화 — `.github/workflows/fetch_catalysts.yml` (신규, 선택)

- `fetch_fundamentals.yml` 복제 → 주 1회(일 23시경) `fetch_catalysts.py` 실행 후 커밋.
- 커밋 프리픽스: `data(catalysts):` → `auto_merge_routines.yml` 의 허용 프리픽스 목록에 **추가 필요**(D-4 참조).

## A-6. 리포트·카카오 표출

- 각 시간대 리포트 "한눈에 보기"에 **📅 임박 촉매** 1줄(예: "삼성전자 실적 D-1 ⚠️").
- 카카오 요약에도 high·D-2 이내 촉매만 노출(과알림 방지).

---

# Part B — thesis-tracker (종목별 논리·무효화 추적)

## B-1. 데이터 모델 — `watchlist.json` 각 종목 확장

기존 `bull_case`/`bear_case`(서술형)는 유지하고, **구조화된 추적 필드**를 추가:

```jsonc
{
  "ticker": "005930",
  // ... 기존 필드 ...
  "thesis": {
    "id": "hbm_supercycle",
    "statement": "HBM4 양산·밸류업 자사주로 저PBR 재평가 → +10% 목표",
    "entry_ts": "2026-06-01T09:00:00+09:00",
    "horizon": "swing_weeks",
    "key_drivers": ["HBM4 양산 출하", "자사주 매입·소각", "DRAM 수요 회복"],
    "invalidation": [
      {"id": "hbm_share_loss", "cond": "HBM4 AMD/엔비디아 공급 지명 실패 공시", "type": "개별", "hard": true},
      {"id": "fx_breakdown",   "cond": "원달러 1,550원 돌파 + 외국인 5일 순매도",  "type": "매크로", "hard": false},
      {"id": "earnings_miss",  "cond": "2Q OP 가이던스 컷(전분기 대비 -15%↓)",     "type": "가정오류", "hard": true, "linked_catalyst": "005930-2026Q2-earnings"}
    ],
    "status": "intact",   // intact | weakening | invalidated
    "last_review_ts": "2026-06-07T18:00:00+09:00"
  }
}
```

**설계 결정**
- `invalidation[].type` 은 **기존 자기보완 루프 4분류(매크로/섹터/개별/가정오류)와 동일 enum** → lessons 분류와 자동 정합.
- `hard:true` = 충족 시 **강제 청산/비중 축소 후보 상향**. `hard:false` = weakening 신호(즉시 매도 금지, 트레일링 강화).
- `linked_catalyst` 로 Part A 이벤트와 연결 → 실적일 통과 시 해당 invalidation 자동 점검.
- `status` 3단계로 thesis 수명주기 관리.

## B-2. 무효화 판정 로직 (프롬프트 내 규칙, 스크립트 불필요)

18시 루프에서 종목별로:
1. 각 `invalidation` 조건을 오늘 뉴스/공시/스냅샷/fundamentals 로 대조.
2. 충족된 조건 분류:
   - `hard` 충족 → `status=invalidated` → **익절/손절과 무관하게 청산·축소 1순위**.
   - `hard:false` 충족 → `status=weakening` → 트레일링 강화·추가매수 금지·목표가 상향 보류.
   - 미충족 → `status=intact` 유지.
3. status 변경 시 `last_review_ts` 갱신 + lessons 기록(B-4).

**기존 로직과의 관계**
- 현행 18시는 "목표가 오차(±5%)"만 판정. 본 로직은 **가격이 🟢green 이어도 논리가 깨지면 매도 후보**로 올린다(현행 `0900 B-2`의 fundamentals 훼손 처리와 동일 철학을 thesis 로 일반화).

## B-3. 프롬프트 통합

| 프롬프트 | 변경 |
|---|---|
| `0900_pre_market.md` `B`(보유 점검) | thesis.invalidation 조건을 밤사이 뉴스로 1차 점검 → weakening 이면 비중 주의 메모 |
| `1800_report.md` `3. 자기보완 학습` 직전 | **신규 `2-4. thesis 무효화 판정`** 단계 추가 → status 갱신 → `4. 다음 거래일 액션`에 반영 |
| `1800_report.md` 리포트 "종목별 종가 점검" | 각 종목에 `thesis.status` 뱃지(🟩 intact / 🟧 weakening / 🟥 invalidated) 표시 |

## B-4. lessons 연결

- `status` 가 `invalidated/weakening` 으로 바뀐 종목은 `state/lessons.md` 에 **사유 type(매크로/섹터/개별/가정오류)** 그대로 1줄 기록 → 기존 `build_lessons_index.py` 분류·룰 인덱싱과 자동 호환.
- 이로써 "어떤 invalidation 유형이 자주 적중하는가"가 누적 → `sunday_policy_review` 에서 thesis 작성 품질 개선 피드백.

---

# Part C — A↔B 결합 (실적 촉매 → 논리 검증)

- 촉매(`catalysts.json`)의 `type=earnings` 이벤트 date 가 지나면(D+1),
  `linked_thesis`/`linked_catalyst` 로 연결된 thesis 의 `earnings_miss` 류 invalidation 을
  **실제 발표값(fundamentals.json 갱신분)으로 자동 판정**.
- 흐름: `fetch_fundamentals.py`(실적 갱신) → 18시 `2-4 thesis 판정` → status 갱신 → lessons.
- **Phase 2 (이번 범위 밖)**: 실적 D-1 에 beat/inline/miss 3 시나리오 예상 주가반응 자동 생성(`earnings-preview`).

---

# Part D — 감사·문서 정합성

1. `docs/file_references.md` — 신규 파일(`catalysts.json`, `fetch_catalysts.py`)과 각 prompt 의 읽기/쓰기 매핑 추가.
2. `scripts/audit_pipeline.py` — `catalysts.json` 스키마 검증 + 과거 이벤트 미정리 경고 룰 추가.
3. `.github/workflows/auto_merge_routines.yml` — 허용 커밋 프리픽스에 `data(catalysts):` 추가.
4. `README.md` — 디렉토리/스케줄 표에 catalysts 라인 추가.
5. `config/policy.json` — `catalysts.holdings_use`, `thesis.hard_invalidation_action` 등 정책 토글 추가(기본 보수값).

---

# Part E — 마일스톤·검증·롤백

## 단계별 마일스톤

| 단계 | 산출물 | 검증 |
|---|---|---|
| **M1** thesis-tracker (Part B) | watchlist 필드 + 1800 프롬프트 `2-4` + 리포트 뱃지 | 보유 종목에 thesis 수동 1개 입력 → 18시 dry-run 으로 status 판정 동작 확인 |
| **M2** catalyst 데이터 (Part A-1~A-3) | `catalysts.json` + `fetch_catalysts.py` | 키 없이 폴백, 키 있을 때 삼성전자 과거 제출일 추정 1건 생성 확인 |
| **M3** catalyst 경보 (Part A-4~A-6) | 프롬프트 경보 섹션 + 카카오 1줄 | 모의 D-1 이벤트로 경보 출력 확인 |
| **M4** 결합·자동화·문서 (Part C·D) | workflow + audit + file_references | `audit_pipeline.py` green |

> 권장 순서: **M1(thesis) 먼저** — 스크립트 의존성이 없어 가장 빠르게 가치 검증 가능. M2~M4 는 후속.

## 검증 방법
- 각 신규 스크립트: 키/네트워크 없는 환경에서 **폴백 무결성** 우선 확인(비치명적 종료).
- 프롬프트 변경: 실제 routine 발화 전 1회 수동 dry-run(주말 `weekend_dryrun_checklist.md` 절차 준용).
- 회귀: 기존 18시 목표가 오차 루프·09시 진입 로직이 **변형 없이 동작**하는지(추가만, 변경 최소).

## 롤백
- 모든 변경은 `claude/wizardly-clarke-LGwuw` 브랜치. 단계별 커밋으로 분리 → 문제 단계만 revert.
- thesis/ catalysts 필드는 **옵셔널** — 누락 시 프롬프트가 "없으면 건너뜀"으로 동작하도록 작성(기존 동작 보존).

---

# 리스크·완화

| 리스크 | 완화 |
|---|---|
| DART 에 미래 실적일 API 없음 → 추정 부정확 | `confirmed=false` 명시 + 웹검색 확정 승격 + 경보는 high 만 |
| 프롬프트 비대화(이미 0900 40KB) | thesis/catalyst 는 **간결 규칙**으로, 서술 최소화 |
| 과알림(카카오) | D-2 이내 high 촉매만 카카오 노출 |
| thesis 수동 작성 부담 | 진입 시 1회만 작성, 18시가 status 자동 갱신 |
| 기존 루프 회귀 | "추가만, 기존 변경 최소" 원칙 + 옵셔널 필드 |

---

# 미결정 사항 (착수 전 확인 필요)

1. **착수 범위**: M1(thesis)만 먼저? 아니면 M1+M2 까지 한 번에?
2. **hard invalidation 동작**: 충족 시 (a) 즉시 청산 후보 1순위 / (b) 비중 축소만 / (c) 경고만. 기본 제안 = (a)지만 종가청산 정책상 "다음 종가 청산 후보".
3. **catalyst 자동화**: 주간 workflow 신설 vs routine 내 웹검색만으로 충분?
4. **카카오 촉매 알림**: 별도 1줄 추가 vs 기존 요약에 흡수?
