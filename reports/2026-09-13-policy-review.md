# 정책·프롬프트 패치 리뷰 — 2026-09-13 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-09-13 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 294 (신규 추출 룰 최근 7일 유입: 28건)
- 교훈 반영 자동 대조(`check_lessons_applied.py`): open_items_hard **2**(동일 항목 2줄) / open_items_soft **1** / resolved(이미 반영) **3**
- 반복 누적 카운트 ≥ 3: 6개 분류(매크로22·섹터41·개별5·가정오류31·선제추론오차57·루틴〈지정학〉3) — 전부 기존 policy v2.5~v2.36 에 흡수, 신규 패치 불요
- **정책 동결(Stage 0) 유지 중** — `config/policy.json` 무편집. 동결 backlog **4건**(이번 리뷰 신규 1건)
- 자동 적용 완료: **3건**(①lessons-balance 구조적 해법 — `build_lessons_index.py` codify_candidates 탐지기 신설 ②lessons 응축 2건 전문 이관 ③rule_sunset 만료 5건 판정 기입) / 동결 backlog 등록: **1건**(신규) / 사용자 승인 대기(이월): **2건**

## 0. §0-0 주간 자기감사 findings 처분 (기계 강제)

`reports/2026-09-13-self-audit.md`(오늘 `scripts/self_audit.py` 직접 실행 생성 — 17시 `weekly_self_audit.yml` 산출물 부재) / `state/self_audit_findings.json` 인용. open finding 3건 전건 처분 완료, `python scripts/self_audit.py --followup-only` 재확인 결과 `open=3 overdue=0`.

| id | 경과 | 이번 리뷰 처분 |
|---|---|---|
| `whipsaw-high` | 10주째 🔴(재발 이력) | **defer**(동결 backlog #2 유지, 내용 불변) — score_ratchet_shadow 재실행 결과 09-06 대비 수치 불변(breach 5건·noise율 100%·net 보호 -161,800원, 신규 breach 0건). 추가 완화는 policy.json 수정이 필요해 동결 게이트에 걸린다. mode=shadow 불변(실제 체결 무변화). |
| `deployment-below-band` | 10주째 | **observe** — 주식비중 37.3%(09-06과 동일), heat 잔여 238,717원/예산 347,341원(68.7% 여유 — 09-06 대비 회복). 게이트 통과 신규 후보가 구조적으로 희소한 국면 지속. 동결 중이라 목표·임계 변경 상정 범위 밖. |
| `lessons-balance` | 5주째 🔴(이번 회차 진입 전 overdue) | **patch**(구조적 착수) — 아래 §5 참조. archive_candidates 가 늘 0건이던 진짜 원인(✅codify 마커를 붙이는 상류 단계 부재)을 스크립트에 탐지기로 신설, 직접 대조 검증한 2건을 확정 이관. 이전 2회(08-30·09-06)의 "재발·효과 없음" 무효화와 달리 재사용 가능한 파이프라인을 남겼다. |

## 1. lessons → policy/prompt 반영 매트릭스

§1-1 은 `check_lessons_applied.py` 산출물(`state/lessons_applied.json`)을 1차 입력으로 사용(294항목 통읽기는 콘텍스트 예산 위반).

| lessons 항목 | 다음 적용 룰(요지) | 반영 위치 | 상태 |
|---|---|---|---|
| 반복 6분류(매크로/섹터/개별/가정오류/선제추론오차/루틴〈지정학〉) | 각 카테고리 세부 룰 다수 | `policy.json`(v2.5~v2.36 다회) + `docs/policy_rationale.md` | **반영**(기존 codify) |
| 2026-08-03 루틴 오차 — 09시 지연 지수값 앵커 | 09시에도 `index_snapshot_confirmation` 역검증 의무화 | `prompts/0900_pre_market.md` §price_data_quality | **반영(신규 확인·이번 리뷰 codify 마킹)** |
| 2026-08-11 하나금융지주 target_gap 영구 신호 | 동적참조 밸류에이션 캡이 verdict 무관 적용되던 결함 | `scripts/compute_dynamic_bands.py`(09-06 수정, 08-13 종결 기록과 동일 결함) | **반영(신규 확인·이번 리뷰 codify 마킹)** |
| **2026-09-11 사전 경보 — 밴드 폭 캘리브레이션(재료 인용 세션 수 카운팅의 역설)** | 어제 처방(전폭 대신 잔여분만)을 정확히 이행했는데 오늘은 그것이 오차 원인이 됨 — 단일 숫자 규칙으로 환원 안 되는 판단 난제 | 없음 | **미반영(hard, 2일 전 — 관찰 지속, 성급한 규칙화 보류)** |
| 2026-08-31 선제추론오차 — 잭슨홀 "확정 재료" 오독(1건, soft) | 확정 재료라도 개장 갭에 값이 이미 지불됐는지 먼저 확인 | 없음 | **미반영**(단발 — 검토 후보, 반복 마커 없음) |
| 08-23 estimate tilt score_candidates 배선 (verdict=wire) | tilt_bands × w=0.03~0.08 가중 배선 | 미배선 | **미반영 — 사용자 승인 필요, 동결 backlog #3 이월** |
| 08-30 "측정창 미도래" 라벨링 (사용자 승인 대기) | 목표가 오차 판정에 지평(horizon) 라벨 별도 집계 | 미반영 | **이월**(승인 대기 — 변화 없음) |

## 2. 반복 누적 카운트 ≥ 3 항목

### 매크로22 · 섹터41 · 개별5 · 가정오류31 · 선제추론오차57 · 루틴오차(지정학)3
- 권장 패치: 없음 — 6개 분류 세부 룰은 이미 policy v2.5~v2.36 다회 반영에 흡수됨(09-06과 동일 결론).
- 적용 방식: 해당 없음(기 반영)
- 근거: `state/lessons_index.json` repeat_counter, `state/lessons_applied.json` summary

### 1-2-b 룰 손익 채점 (rule_attribution)
- 청산 24건(승9/패15, 승률 37.5%) · PF 0.48 · 순실현 -349,040원. 개별 청산 룰별 n 이 1~5건으로 적어 "2주 연속 음(-)" 판정에 필요한 시계열 비교가 불가(state/rule_attribution.json 은 스냅샷만 보존, 주간 이력 없음) — 신규 패치 후보 상정 안 함. `blocked_day_rate_pct` 는 이번 표본 2/2일(100%)이나 표본 자체가 작아(관측일 2일) 래칫 과잉 신호로 보기엔 이르다.
- rule_sunset 만료 5건 §1-2-b 판정: 아래 §5 참조.

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)
- 기준: 2026-09-13T20:07:02+09:00 · 추정 로그 69일 / 채점 표본 1133건
- 5td: 적중률 48% · 기대 +10.1% vs 실현 -0.7% · 중앙오차 -7.8%p (n=1053)
- 20td: 적중률 57%(08-23 55%→08-30 59%→09-06 58%→09-13 57%, 2주 연속 하락 아님) · 기대 +8.7% vs 실현 -1.3% · 중앙오차 -6.4%p (n=683)
- 60td: 적중률 47% · 기대 +5.7% vs 실현 -22.7% · 중앙오차 -23.8%p (n=32, 09-06 n=9 대비 표본 확대)
- estimate_gate 손익: 차단표본 134건 · fwd20 중앙값 -5.0% · 양수율 33% → `alpha_block_alert=false`, 게이트 유효(차단 정당)
- **추정식 패치 후보: 없음** — 20td 2주 연속 하락 아님. 중앙오차가 5%p 임계를 계속 초과하나(6.4%p·23.8%p) 백테스트 재실행 없이는 파라미터 변경 금지 원칙 유지(09-06과 동일 결론). 60td n=32 로 표본이 커졌고 실현 오차가 더 벌어진 점(60td 오차 확대 추세)은 다음 주 재확인 대상으로 관찰만 지속.
- **뉴스 키워드 보강**: `news_loop.unclassified_samples`(분류 101건/미분류 1906건) 훑어봄 — 방향 반전을 만들 실질 촉매(관세환급류 오분류 패턴 포함)는 발견되지 않음. `silent_types`(무음 유형: `earnings_miss_or_guidance_cut`·`labor_dispute`)도 이번 주 대응 뉴스 없음 → **보강/승격 실행 내역: 없음**.
- **랭킹 편입(estimate tilt) 재심사**: §1 매트릭스 참조 — verdict=wire(08-23) 확정 상태 불변, 동결 backlog #3 이월(변화 없음).

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — reward_risk_management (b)손절 상향 처방 순서 명문화 (동결 backlog 신규 등록)
- **대상**: `config/policy.json` §risk.reward_risk_management
- **현재**: R/R 하한(bull 1.1) 미달 시 (b)손절 상향을 우선 처방 — 정본에 처방 순서 명문화 없음
- **변경 후 제안**: `(목표−종가) < 2.0×ATR×종가` 이면 (b) 처방 전에 "이 종목은 (b)로 하한을 살 수 없다"를 먼저 판정하고, 해소 수단을 ①목표 도달 종가 익절 ②트레일 1차선 이탈 시 부분익절 두 조건으로 명문화(2026-09-01 lessons, expiry 2026-09-08 도래·§1-2-b 승격 판정)
- **근거 lessons 라인**: 2026-09-01(하나금융지주 조건부 종결 계약 사례, expiry 도래)
- **자동 적용 가능 여부**: **불가 — 정책 동결(Stage 0) 대상.** `state/policy_freeze.json.backlog` #4 로 등록 완료(이번 리뷰).
- **부작용 점검**: 단일 사례(하나금융지주) 기반이라 동결 해제 후에도 재현 1~2건 추가 관측 후 승격 권장(required_samples 에 명시)

### 후보 2 (이월, 09-06 그대로) — estimate tilt score_candidates 배선 (동결 backlog 등록)
- **대상**: `scripts/score_candidates.py` + `config/policy.json` §momentum_strategy/score_blend_weights
- **현재**: 미배선(fundamental_tilt·valuation_tilt 만 존재)
- **변경 후 제안**: `state/backtest_estimate_tilt.json`(2026-08-23, verdict=wire) 근거로 tilt_bands × w=0.03~0.08 배선
- **자동 적용 가능 여부**: 사용자 승인 필요 + 정책 동결 대상 — 변화 없음(이월)
- **부작용 점검**: 동결 해제 시점까지는 어차피 실행 불가

### 후보 3 (이월, 08-30 그대로) — 목표가 오차 "측정창 미도래" 라벨 신설
- **대상**: `prompts/*.md`(목표가 오차 판정 섹션)
- **변경 후 제안**: 08-30 제안 그대로 이월 — 사용자 승인 대기
- **자동 적용 가능 여부**: 사용자 승인 필요

### 후보 4 — build_lessons_index.py codify_candidates 탐지기 신설 (자동 적용 완료)
- **대상**: `scripts/build_lessons_index.py`
- **현재(수정 전)**: `archive_candidates` 는 이미 ✅codify 마커가 붙은 섹션만 스캔 — 마커를 붙이는 상류 단계가 없어 5주 연속 0건이었다(lessons-balance finding 구조적 원인, 08-23 리뷰가 이미 진단했으나 미해결).
- **변경 후**: ✅codify 마커가 없는 30일+ 경과 섹션 전체를 대상으로 '다음 적용 룰'의 강신호(따옴표·백틱)가 policy.json/docs/prompts haystack 에 이미 등장하는지 대조해 "반영됐는데 마커만 없는" 항목을 `codify_candidates` 로 표면화(자동 마킹은 안 함 — 오탐 방지, 사람 확인 후 마킹).
- **근거**: `state/self_audit_findings.json` lessons-balance 08-23/08-30/09-06 disposition_history(구조적 해법 필요성 반복 지적)
- **자동 적용 가능 여부**: 가능 — **scripts/*.py 버그/기능 보강은 정책 동결 예외 허용 항목**(policy.json 수치 불변, lessons 북키핑 자동화일 뿐 전략 로직 무관)
- **검증**: 실행 결과 `codify_candidates=35`. 이 중 4건을 직접 grep+코드 대조로 검증 — 2건 확정(§5), 2건 오탐 판명(sync_pending_orders 트레일 SELL 매칭 개선·portfolio EOD 연속성 체크는 grep 신호는 있었으나 실제 코드에는 해당 로직 없음 — 오탐 방지 설계 의도대로 작동, 자동 마킹하지 않아 오류가 lessons.md 에 유입되지 않음).
- **부작용 점검**: 출력 스키마에 필드 추가만(`codify_candidates`·`codify_candidates_total`) — 기존 필드·소비자(0-A 문서, 1-6 절차) 영향 없음.

## 4. policy.json dead config (참조 없음)
- 없음 — `scripts/check_policy_hygiene.py` 결과 `dead=[] unregistered_new=0 review_due=0`.

## 5. lessons.md 응축 (§1-6, 수지 균형 의무) + rule_sunset 만료 판정 (§1-2-b)

**응축(이관)**: 이번 리뷰 이관 **2건** — ①2026-08-03(루틴 오차 — 09시 지연 지수값 앵커, `index_snapshot_confirmation` 09시 명문화로 반영 확인) ②2026-08-11(섹터 — 하나금융지주 target_gap, `compute_dynamic_bands` verdict 게이팅 수정으로 반영 확인). 둘 다 `codify_candidates`(§3 후보4) 검증을 거쳐 §1-6 절차대로 전문을 `state/lessons_archive.md`(§이관 2026-09-13)로 이관하고 lessons.md 본문을 4줄(분류·요약·✅codify 반영 위치·전문 이관 표기)로 교체했다.
- 결과: lessons.md 619,749B → **617,599B**(-2,150B). `build_lessons_index.py` 재실행으로 entries=294 불변(카운터·미반영 항목 원문 불변 보존) 확인.
- **수지 균형 판정: 미충족** — 이관 2건 ≪ 신규 유입 28건, 잔여 617,599B ≫ 예산 60,000B. 다만 09-06까지의 "1건 시범 후 재발" 패턴과 다르게, 이번엔 근본 병목(마커 부착 상류 단계 부재)을 스크립트로 해소했다 — `codify_candidates` 잔여 33건이 다음 리뷰들의 우선순위 목록으로 남아 있어, 매주 수 건씩이라도 검증·이관을 지속하면 처음으로 유입을 따라잡을 여지가 생긴다. 이번 처분이 다시 무효화되는지는 다음 주 재발 여부로 검증된다(§0-0 처분 규약).

**rule_sunset 만료 판정(§1-2-b)**: `lessons_index.rule_sunset.expired` 5건 전건 처분 완료(lessons.md 해당 항목에 인라인 마커 추가):
| 항목 | expiry | 판정 |
|---|---|---|
| 2026-09-04 수급 전환 1일 판정 유보 | 09-11 | 만료(실효 확정) — 재발 없음 |
| 2026-09-01 (b)손절 상향 R/R 구조 | 09-08 | **승격 후보** — 동결 backlog #4 등록(§3 후보1) |
| 2026-08-22 섹터 3번째 종목 증액 판정 | 08-28 | 만료(실효 확정) — 이벤트 구간 한정 룰, 구간 종료로 자연 실효 |
| 2026-08-21 KB금융 🟠 축소 재확인 | 08-28 | 만료(실효 확정) — 재발 없음 |
| 2026-08-14 카카오 상대강도 방아쇠 | 08-21 | 만료(실효 확정) — 단일 종목 사례, 재발 없음 |

`rule_sunset.unregistered`(차단·상한 류인데 expiry 미표기) **22건**은 이번 리뷰에서 개별 태깅을 완료하지 못했다(범위상 우선순위 조정 — lessons-balance 구조적 해법에 시간 배분) — 다음 리뷰 이월 대상으로 명시. `policy_hygiene.review_due`는 0건(해당 없음).

## 6. 다음 주 routine 적용 우선순위
- (즉시 반영 완료) `scripts/build_lessons_index.py` — codify_candidates 탐지기 신설(lessons-balance 구조적 해법)
- (즉시 반영 완료) `state/lessons.md`/`state/lessons_archive.md` — codify 이관 2건 + rule_sunset 만료 판정 5건
- (동결 backlog 등록, 해제 후 최우선) breakeven_ratchet 추가 완화/기각(#2) · estimate tilt 배선(#3) · reward_risk_management (b)처방 순서 명문화(#4, 신규)
- (사용자 승인 대기, 이월) 측정창 미도래 라벨링(§3 후보3)
- (다음 리뷰 최우선 이월) `codify_candidates` 잔여 33건 검증·이관 · rule_sunset.unregistered 22건 태깅
- (다음 archive 까지 관찰만) whipsaw-high 09-20 재확인 · deployment-below-band 국면 해소 여부 · 09-11 사전 경보 밴드 캘리브레이션 난제(hard 미반영) 재발 여부

## 7. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: 없음(자동 적용 범위 내 처리 완료, 나머지는 정책 동결로 등록만)
- 검토만 권장 2건: estimate tilt 배선 승인 여부(§3 후보2) · reward_risk_management (b)처방 순서 승격 여부(§3 후보1, 동결 해제 후)
- 자동 적용 완료 3건: lessons_index 스크립트 codify 탐지기 신설 · lessons 응축 2건 · rule_sunset 만료 판정 5건
