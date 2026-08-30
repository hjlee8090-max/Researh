# 정책·프롬프트 패치 리뷰 — 2026-08-30 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-08-30 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 233 (신규 추출 룰 최근 7일 유입: 40건 — `lessons_index.throughput`)
- 교훈 반영 자동 대조(`check_lessons_applied.py`): open_items_hard 0 / open_items_soft 0 / likely_applied 4 — **이번 주 미반영 룰 없음**
- 반복 누적 카운트 ≥ 3: 6개 분류(매크로/섹터/개별/가정오류/선제추론오차/루틴 오차〈지정학 속보 당일 역전〉) — 전부 기존 policy v2.5~v2.36 에 이미 codify, 신규 패치 불요
- 자동 적용 권장 패치: 3건(§0-0 whipsaw-high ratchet 완화, 뉴스 키워드 보강, lessons_rule_sunset 만료 마커 2건) / 사용자 승인 필요: 2건(§3 후보 1 lessons codify 마커, 후보 2 목표가 오차 '측정창 미도래' 라벨링)
- policy 버전: v2.35 → **v2.36**

## 0. §0-0 주간 자기감사 findings 처분 (기계 강제)

`reports/2026-08-30-self-audit.md` / `state/self_audit_findings.json` 인용. open finding 3건 전건 처분 완료, `python scripts/self_audit.py --followup-only` 재확인 결과 `open=3 overdue=0`.

| id | 경과 | 이번 리뷰 처분 |
|---|---|---|
| `whipsaw-high` | 8주째 | **patch** — breach 확정 3건째 도달로 §1-8 즉시 심사 실행(아래 §1-8 참조). `steps[0].when_gain_atr` 1.0→1.5 상향(policy v2.36), mode=shadow 불변. |
| `deployment-below-band` | 8주째 | **observe** — 18시 `sunday_strategy`(08-30)의 진단(게이트 3종 정당 작동·실질 후보 1종 1주만 잔존, 국면 의존)을 정책 리뷰 관점에서 확인·승계. policy 배치 목표·게이트 임계 변경 상정 안 함. |
| `lessons-balance` | 4주째(첫 관측 08-14) | **defer** — archive_candidates 이번 주도 0건(구조적: 어떤 평일 routine 도 ✅codify 마커를 남기지 않음). 다음 주는 임시 조치라도 상정 필요(누적 4주 — 아래 §3 후보 1 참조). |

## 1. lessons → policy/prompt 반영 매트릭스

§1-1 은 §0-B `check_lessons_applied.py` 산출물(`state/lessons_applied.json`)을 1차 입력으로 사용(전문 grep 대신 — 233항목 통읽기는 콘텍스트 예산 위반). 결과: `open_items_hard=0`, `open_items_soft=0`, `resolved_items(likely_applied)=4`(선제추론오차 반복 요인·지수 급락 오판 게이트·선제추론 채점 백로그 방지 절차 — 전부 기존 policy/prompts 에 신호 확인됨). **이번 주 "다음 적용 룰" 중 미반영으로 표면화된 항목 없음.**

단, 자동 스캔이 놓친 수동 발견 1건이 있다 — lessons.md 2026-08-21 NAVER 항목이 "다음 추천 시 반영할 교훈"(스캐너가 찾는 "다음 적용 룰"과 다른 헤딩)으로 **7회째 같은 문장 반복** 후 "일요일 policy_review 안건으로 승격"을 명시적으로 요청했다. `config/`·`prompts/`·`docs/` 전체에 "측정창 미도래"·"측정창 불일치" 관련 배선 0건 확인 — **미반영**. §3 후보 2 로 등록(사용자 승인 필요 — 여러 prompt·산출물 스키마에 걸친 변경).

| lessons 항목 | 다음 적용 룰(요지) | 반영 위치 | 상태 |
|---|---|---|---|
| 반복 6분류(매크로/섹터/개별/가정오류/선제추론오차/루틴〈지정학〉) | 각 카테고리 세부 룰 다수 | `policy.json`(v2.5~v2.36 다회) + `docs/policy_rationale.md` | **반영**(기존 codify) |
| 2026-08-22 은행 3종 증액 금지(expiry 2026-08-28) | 섹터 세 번째 종목=증액 판정 | lessons 원문 한정 서술(정식 policy 필드 미승격) | **만료**(n=1, 승격 근거 미달 — 아래 §1-2-b) |
| 2026-08-21 KB금융 0.3%p 마진 재확인(expiry 2026-08-28) | 유효임계 0.3%p 이내 관통 🟠 축소는 익일 재확인 | 동일 | **만료**(n=1, 승격 근거 미달) |
| 2026-08-21 NAVER "측정창 미도래" 라벨링(7회 반복) | 밸류에이션 밴드 목표가는 지평(horizon) 라벨 별도 집계 | 없음 | **미반영** — §3 후보 2 |
| 뉴스 labor_dispute 무음(silent_type) | 파업 관련 키워드 매칭 | `config/news_keywords.json` | **부분반영 → 이번 리뷰에서 보강**(아래 §2-c) |

## 2. 반복 누적 카운트 ≥ 3 항목

### 매크로/섹터/개별/가정오류/선제추론오차/루틴 오차(지정학 속보 당일 역전) — 각 3건 이상
- 누적: 매크로 14 · 섹터 32 · 개별 3 · 가정오류 24 · 선제추론오차 47 · 루틴(지정학) 3
- 권장 패치: 없음 — `check_lessons_applied` 대조 결과 이 6개 분류의 세부 룰은 이미 policy v2.5~v2.36 다회 반영(신뢰도 규칙 §1-4, 섹터 동행 판정, `intraday_shock_rejudgment` 등)에 흡수됨. 카운터 자체는 일별 목표가 오차 기록의 누적 총계이지 미반영 신호가 아니다.
- 적용 방식: 해당 없음(기 반영)
- 근거: `state/lessons_applied.json` summary.likely_applied=4, `state/lessons_index.json` repeat_counter

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)

- 기준: 2026-08-30T20:08:44+09:00 · 추정 로그 60일 / 채점 표본 930건
- 5td: 적중률 50% · 기대 +9.6% vs 실현 -0.6% · 중앙오차 -7.2%p (n=830)
- 20td: 적중률 59% · 기대 +9.4% vs 실현 -2.8% · 중앙오차 -6.5%p (n=503)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 109건 · fwd20 중앙값 -10.8% · 양수율 24% → 게이트 유효 — 차단 종목이 평균적으로 부진(차단 정당)
- 뉴스 피드: 분류 188건 / 미분류 1865건 / 해외 46건
- 무음 유형(미매칭): earnings_miss_or_guidance_cut, labor_dispute, supply_glut_or_price_drop

**키워드 보강/승격 실행 내역**: 1건. `labor_dispute` 무음 유형을 unclassified 표본과 대조한 결과 실질 파업 뉴스 3건(HD한국조선해양·삼성중공업 관련 "HD현대重·삼호 '줄파업'…하투", "HD현대重 순환파업·포스코 부분파업")이 기존 키워드(총파업/파업예고/파업돌입/쟁의행위/협상결렬/노사갈등/파업찬반/조정결렬) 어느 것에도 매칭되지 않아 버려지고 있었다. `config/news_keywords.json`(v1.3→v1.4) `labor_dispute.any` 에 "줄파업·순환파업·부분파업·하투" 4개 추가. `earnings_miss_or_guidance_cut`·`supply_glut_or_price_drop` 은 unclassified 표본 중 대응 뉴스 확인 안 됨(뉴스 부재 — 조치 없음).
- 추정식 패치 후보: 없음 — 20td 적중률 59%(2주 연속 하락 아님, 08-23 대비 유지)·중앙오차 6.5%p(5%p 초과하나 백테스트 재실행 없이는 파라미터 변경 금지 원칙상 관찰만 지속). 랭킹 편입(틸트) 재심사는 표본 ≥45거래일 도달 전이라 계속 보류.

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — lessons.md 응축(codify 이관) 프로세스 설계
- **대상**: 여러 평일 `prompts/*.md`(어느 슬롯이 codify 확정 표시를 남길지) + `scripts/build_lessons_index.py` 판정 조건
- **현재**: 어떤 routine 도 lessons 항목에 "✅codify 반영 위치" 마커를 남기지 않아 `archive_candidates` 가 4주 연속 0건, lessons.md 494KB(예산 60KB 의 8.2배)로 정체
- **변경 후 제안**: (안) sunday_policy_review 자신이 매주 §1-1 매트릭스에서 "반영" 판정한 항목에 한해 lessons.md 원문에 "✅ codify: [반영 위치]" 1줄을 직접 기입하는 것으로 입구를 열되, 다른 routine 배선은 손대지 않는 최소 범위로 시작 — 다음 리뷰(09-06)에 시범 적용
- **근거 lessons 라인**: `state/self_audit_findings.json` lessons-balance disposition 이력(08-14 첫 관측 ~ 08-30)
- **자동 적용 가능 여부**: 사용자 승인 필요 — 여러 routine 의 산출 계약을 건드릴 가능성
- **부작용 점검**: §1-6 불변 보존 규약(`### ` 헤딩·분류 라인·카운터·미반영 항목 원문)과 충돌하지 않도록 마커 삽입 위치를 별도 라인으로 한정해야 함

### 후보 2 — 목표가 오차 "측정창 미도래(measurement window not due)" 라벨 신설
- **대상**: 목표가 오차 산정 로직(섹터/가정오류 분류가 이뤄지는 평일 prompt들의 §목표가 괴리 섹션) + 관련 집계 스크립트
- **현재**: 진입 D+1~D+19 구간의 목표가 괴리(밸류에이션 밴드 상단 등 멀티위크 지평 목표를 단기 종가와 매일 비교)가 "가정오류"로 반복 산입 — 2026-08-13 이후 7회 동일 문장 반복(NAVER·신한지주·삼성물산 등)
- **변경 후 제안**:
```diff
- (목표가 괴리는 분류 없이 매크로/섹터/개별/가정오류 4분류로만 집계)
+ (진입 후 20거래일 미만 & 목표가가 밸류에이션 밴드 상단/추정 앵커인 종목의 괴리는 '측정창 미도래' 라벨로 4분류와 분리 집계 — 오차 카운터 오염 방지)
```
- **근거 lessons 라인**: 2026-08-21 NAVER 항목("일요일 policy_review 에서 집계 방식 자체를 바꾸는 안건으로 승격") 및 8/13 이후 7회 반복 인용
- **자동 적용 가능 여부**: 사용자 승인 필요 — 집계 스키마 변경, 여러 prompt·리포트 형식에 영향
- **부작용 점검**: 기존 "가정오류" 카운터(현재 24건) 중 상당수가 재분류될 수 있어 반복 카운트 ≥3 판정 임계에 영향 — 도입 시 과거 데이터 재계산 여부를 별도로 결정해야 함

## 4. policy.json dead config (참조 없음)
- 없음 — `scripts/check_policy_hygiene.py` 재실행 결과 `dead=[] unregistered_new=0 review_due=0`.

## 5. 다음 주 routine 적용 우선순위
- (즉시 반영 완료) `config/policy.json` v2.36 — `risk.breakeven_ratchet.steps[0].when_gain_atr` 1.0→1.5, mode=shadow 유지
- (즉시 반영 완료) `config/news_keywords.json` v1.4 — labor_dispute 키워드 4종 추가
- (즉시 반영 완료) `state/lessons.md` — rule_sunset 만료 마커 2건 신규 기입(은행 3종 증액금지·KB금융 0.3%p 재확인, 둘 다 expiry 2026-08-28 도래·n=1). 카카오 상대강도 건은 08-23 리뷰에서 이미 만료 처리됨(재확인만, 신규 조치 없음).
- (사용자 승인 후 다음 주 적용) 후보 1(lessons codify 마커 시범), 후보 2(측정창 미도래 라벨)
- (다음 archive 까지 관찰만 할 항목) ratchet shadow 완화 후 breach 재축적(09-13 재확인), estimate 20td 중앙오차 6.5%p 추이, deployment-below-band 국면 해소 여부

## 6. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: 없음(이번 주 자동 적용 범위 내에서 처리 완료)
- 검토만 권장 2건: lessons codify 마커 설계(§3 후보 1) · 목표가 오차 "측정창 미도래" 라벨 신설(§3 후보 2)
- 자동 적용 완료 3건: ratchet 완화(policy v2.36) · 뉴스 키워드 보강(news_keywords v1.4) · rule_sunset 만료 처분 3건
