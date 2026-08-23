# 정책·프롬프트 패치 리뷰 — 2026-08-23 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-08-23 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: **195건**(`### ` 헤딩 기준). 이번 주(신규) **36건**.
- 신규 추출 룰 (이번 주): 173건 누적 추출 중 최근 7일 유입 36건(`lessons_index.throughput`).
- 반영 완료: **0건**(자동대조 hard=0/soft=0, 신규 codify 없음) / 부분 반영: **0건** / 미반영: **1건**(스크립트 버그 — `compute_dynamic_bands` 밸류에이션 캡, 자동대조가 놓친 것을 직접 검증으로 발견) — 별도로 **재심사 트리거 충족 1건**(estimate tilt 배선 verdict=wire, §1-5)
- 반복 누적 카운트 ≥ 3: **5개 분류**(매크로 오차 10 · 섹터 오차 26 · 가정오류 14 · 선제추론오차 44 · 루틴 오차(지정학 속보 당일 역전) 3 — 전부 기존 codify 로 이미 커버, 신규 패치 불요)
- 자동 적용 권장 패치: **5건**(dead-config 처분 3건 + lessons_rule_sunset 등록/만료 처분 2건, policy v2.35) / 사용자 승인 필요: **2건**(compute_dynamic_bands 캡 버그 수정 · estimate tilt score_candidates 배선)

**전체 판단**: 이번 리뷰는 08-16 회차가 발화하지 않아(archive 부재로 확인) 08-09 이후 2주치 누적을 한 번에 처리했다. 핵심 성과 셋 — ①§0-0 처분 의무를 지켜 overdue 5건(3주 dead-config + 만성 미배치 + lessons-balance)을 전부 처분해 `self_audit.py --followup-only` overdue=0 을 만들었다(policy v2.35: dead config 3종 처분). ②lessons 2026-08-14 가 "8/16 policy_review 안건으로 확정 이관"이라 못박은 `compute_dynamic_bands` 밸류에이션 캡 버그가 그 8/16 회차 유실로 **9일째 미착수 상태**임을 재확인 — 코드 수정은 이 routine 의 커밋 범위(config/prompts/state/reports) 밖이라 직접 고치지 못하고 최우선 사용자 액션으로 격상한다. ③estimate tilt 재심사 사전 등록 조건(≥45거래일 표본)이 이번 주 충족돼 `backtest_estimate_tilt.py` 를 재실행한 결과 판정이 07-21 **hold → wire** 로 뒤집혔다 — score_candidates 배선은 전략 랭킹 변경이라 자동 적용하지 않고 사용자 승인 안건으로 상정한다. lessons-balance(390KB→60KB 예산 초과)는 이번 주도 이관 0건 — archive_candidates 가 구조적으로 항상 비어 있는 원인(어떤 routine 도 ✅codify 마커를 남기지 않음)을 처음으로 진단했다.

## 0. 주간 자기감사 의무 인용 + findings 처분

최신 자기감사: `reports/2026-08-23-self-audit.md` · `state/self_audit_findings.json`(as_of 2026-08-23). open 6건 · 처분 전 overdue 5건 → 처분 후 overdue **0건**(`self_audit.py --followup-only` 재확인 완료).

| finding | 심각도 | 경과 | 이번 처분 | 근거 요약 |
|---|---|---|---|---|
| `whipsaw-high` — 스톱 휩쏘율 71.4% | warn | 7주째 | **observe** | ratchet_shadow breach 확정 2/3건·관측 34거래일(08-09 대비 거래일만 진전, 확정 breach 불변). net 보호 -50,000원·noise율 100% 불변. H 오버레이 결론도 불변(트레일링 룰 자체가 원인). 3건째 breach 시 즉시 심사. |
| `deployment-below-band` — 주식비중 48.8% < 목표 65% | warn | 7주째 🔴overdue→처분 | **observe** | 진단 갱신 — heat 잔여 46.3%(8/9 이후 회복), `recommendation.action="deploy"` 1,111,828원(vacant_slots=1)이 이미 켜져 있어 능동적 봉쇄가 아니라 슬롯 회전 대기로 보인다. 강제 배치 패치는 보류, 08/24~08/28 실제 체결 여부로 재검증. |
| `policy-dead-config-disclaimers` | warn | 2주째 🔴overdue→처분 | **patch** | 삭제. 11개 prompt 에 이미 하드코딩(wiring 없던 그랜드파더 필드). policy v2.35. |
| `policy-dead-config-rebalance_rules` | warn | 2주째 🔴overdue→처분 | **patch** | `_doc_rebalance_rules` 로 개명(문서 전용). 스왑 판정은 risk 손절·momentum_signal·lessons_rule_sunset 로 이미 구현. policy v2.35. |
| `policy-dead-config-weekly_cycle` | warn | 2주째 🔴overdue→처분 | **patch** | 삭제. weekend_report_output 경로가 현재 산출물 명명과 불일치하는 구식 스킴. 로직은 weekly_plan.json·각 prompt 0단계로 대체됨. policy v2.35. |
| `lessons-balance` — lessons.md 390,977B > 60,000B | warn | 2주째 🔴overdue→처분 | **defer** | 원인 진단: `archive_candidates`(✅+codify 마커 AND 30일+)가 이번에도 0건 — 상류 어떤 routine 도 codify 마커를 남기지 않아 이관 파이프라인이 구조적으로 항상 비어 있다. 유일한 구체 후보(2026-08-13 target_gap 종결)를 직접 검증했으나 실제로는 미해결이라 codify 불가. 근본 해법(태깅 프로세스 설계)은 여러 prompt 에 걸친 변경이라 다음 리뷰 사용자 승인 안건으로 상정. |

`python scripts/self_audit.py --followup-only` → **open=6 · overdue=0** 확인 완료.

**패치 동결 규칙 점검**: `state/self_audit.json` F 항목 — policy v2.34(직전 감사도 v2.34, 버전 불변) · 신규 왕복 2건. "버전 증가 + 신규 왕복 0건" 발동 조건 미충족 — **동결 미발동**. 다만 이번 리뷰의 policy v2.35 패치도 전부 dead-config 정리(전략 파라미터 무변경)이며, estimate tilt 배선은 검증 자체가 목적인 사용자 승인 안건으로 상정해 동결 원칙과 무관하게 처리한다.

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 (YYYY-MM-DD) | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-08-14 가정오류(운영) — target_gap 재출력(가정오류) | `compute_dynamic_bands` 캡을 `verdict=="cap_target"` 일 때만 적용 | `scripts/compute_dynamic_bands.py` (line 156-163) | **미반영** — 8/16 리뷰 안건 이관이 유실돼 9일째 미착수. routine 커밋 범위 밖(scripts/), §6 최우선 사용자 액션 |
| 2026-07-21 estimate-tilt 재심사 등록 | 표본 ≥45거래일 도달 시 사전 등록 기준(C1~C3/T1~T3)으로 재심사 | `scripts/backtest_estimate_tilt.py` → `state/backtest_estimate_tilt.json` | **재심사 완료, verdict=wire** — score_candidates 배선은 사용자 승인 필요(§3 후보 1) |
| 2026-08-22 은행 3종 — 세 번째 종목은 증액 계산 | 8/26~8/27 금통위·잭슨홀 구간 은행 축 추가매수 금지 | `state/lessons.md` §2026-08-22 (expiry 등록) | **반영**(lessons_rule_sunset 등록, expiry 2026-08-28) |
| 2026-08-14 카카오 — 방아쇠 지표 급락 시 추가매수 금지 | 진입 3거래일 내 방아쇠 지표 반토막 시 추가매수 금지 | `state/lessons.md` §2026-08-14 | **만료 처분**(expiry 2026-08-21 도래, n=1 재발 0건, 정책 승격 근거 미달) |
| 2026-08-21 하나금융지주 — 추정 기대수익 연속 음수 시 손절 상향 | 목표가 하향 대신 손절 상향으로 대응 | (해당없음 — 리스크관리 원칙 서술, `policy.reward_risk_management` 기존 R/R 하한 규정과 중복) | **부분 반영**(신규 policy 필드 불요 판단) |
| 2026-08-20 LIG넥스원 — 전일 방어 종목 익일 반등일 자금이탈 | 예측 밴드 형성 규칙(저자 자체 표기: "일몰 대상 아님") | `prompts/*` 예측 서술 관행 | **해당없음**(진입제한 아님, self-declared 비일몰) |
| 2026-08-18 KB금융 — 괴리 수준·변화 분리 표기(Δ) | 오차 항목에 당일 확대분(Δ) 병기 | 서술 관행(리포트 작성 규칙) | **부분 반영**(운영 서술 규칙, policy 필드 불요) |
| 2026-08-13/14 은행 열위 — 일수 vs 폭 분리 표기 | 축소 집행 방아쇠는 폭 기준, 일수는 관측 기록 | `state/lessons.md` §2026-08-13(하나·KB) 8/12 규칙 재확인 | **반영**(8/12 기존 규칙 재확인, 신규 아님) |
| 2026-08-13 선제추론오차 — if-then 지표 통칭 금지 | `파일명.필드명` 형식으로 지표 고정 표기 | 예측문 작성 형식(선제추론 원장) | **부분 반영**(원장 작성 규칙, `inference_checklist.md` 가 흡수) |
| 매크로/섹터/가정오류/선제추론오차 (반복 ≥3, 누적) | 각 카테고리 다수 세부 룰 | `policy.*`(과거 v2.5~v2.34 다회 반영) + `docs/policy_rationale.md` | **반영**(기존 codify, §2 참조) |

## 2. 반복 누적 카운트 ≥ 3 항목

### 매크로 오차 — 10건 / 섹터 오차 — 26건 / 가정오류 — 14건 / 선제추론오차 — 44건 / 루틴 오차(지정학 속보 당일 역전) — 3건
- 누적 라인 요약: 5개 분류 모두 08-09 리뷰 대비 건수가 늘었다(예: 매크로 5→10, 섹터 8→26 — 08-16 미발화로 2주치 누적). 그러나 세부 내용은 대부분 기존 codify 규칙(`web_verify_guard`·`index_snapshot_confirmation`·분류축 판정 순서·트레일링 규칙 등)의 반복 적용 사례이지 새로운 패턴이 아니다.
- 권장 패치: 신규 없음. 선제추론오차(44건, 최대 분류)의 반복 미흡 요인은 `state/inference_scorecard.json.miss_factors` → `state/inference_checklist.md` 로 이미 매주 응축되는 중(§1-7).
- 적용 방식: 해당없음(기존 codify 유지, 관측 지속)
- 근거 lessons 라인: 카운터 원문 `state/lessons.md` §16-22(누적 패턴 카운터)

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)

- 기준: 2026-08-23T20:09:57+09:00 · 추정 로그 54일 / 채점 표본 810건
- 5td: 적중률 49% · 기대 +8.6% vs 실현 -0.8% · 중앙오차 -6.9%p (n=700)
- 20td: 적중률 55% · 기대 +9.0% vs 실현 -6.2% · 중앙오차 -9.5%p (n=415)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 100건 · fwd20 중앙값 -12.0% · 양수율 21% → 게이트 유효 — 차단 종목이 평균적으로 부진(차단 정당)

- 뉴스 피드: 분류 236건 / 미분류 1631건 / 해외 44건
- 무음 유형(미매칭): 없음
- 검토 의무: unclassified 표본 → manual_news 승격 또는 키워드 보강 (estimate_scorecard.json 의 review_checklist)

- 키워드 보강/승격 실행 내역: **없음** — `unclassified_samples`(15건) 직접 검토 결과 부동산·주말 칼럼·타사 MOU 등 노이즈성 항목이며, 방향 반전을 만들 만한 실질 촉매(관세환급류 오분류 패턴 포함)는 발견되지 않았다. HD한국조선해양 "인도 코친조선소 합작투자 중단"(2건 중복)은 경계선이나 임팩트가 작아 보류.
- 추정식 패치 후보: `median_realized_minus_expected` 가 5td −6.86%p·20td −9.53%p 로 5%p 임계를 초과(08-09 회차에도 초과 상태였음 — -7.2%p/-18.1%p 대비 20td 는 오히려 개선). **백테스트 재실행 근거 필요 — 이번 리뷰에서 파라미터 변경 없음**, 대신 §1-5 에 명시된 estimate tilt 재심사(45거래일 표본 조건)가 이번 주 충족돼 별도로 실행(§3 후보 1).

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — estimate tilt score_candidates 배선 (verdict: hold → wire)
- **대상**: `scripts/score_candidates.py` (틸트 가중 배선) + `config/policy.json` §momentum_strategy/score_blend_weights
- **현재**: 2026-07-21 1차 백테스트(22거래일)는 IC 양(+)이나 픽 개선 무해성 기준 미달로 배선 보류(`reports/2026-07-21-estimate-tilt-research.md`).
- **변경 후 제안**: 표본 45거래일(06-11~08-13) 도달 후 사전 등록 기준(C1~C3/T1~T3) 전부 pass — verdict=**wire**, tiebreak_verdict=**wire_tiebreak**, 권장 margin=0.03. `state/backtest_estimate_tilt.json`(2026-08-23 재실행) 근거로 score_candidates 에 틸트 가중을 배선하는 안.
```diff
- (미배선 상태 — score_candidates 는 틸트 미반영 proxy 스코어만 사용)
+ (제안, 미적용) score_candidates.py 에 tilt_bands(±15%/5~15%/0~5%/<0, A/B 만) × w=0.03~0.08 가중 추가
```
- **근거 lessons 라인**: 2026-07-21 estimate-tilt-research 재심사 경로 등록 §5 (사전 등록 기준 그대로 재실행)
- **자동 적용 가능 여부**: **사용자 승인 필요** — 랭킹 알고리즘 변경(전략 파라미터), scripts/ 는 이 routine 커밋 범위 밖이기도 함
- **부작용 점검**: 배선 시 momentum_signal 기반 픽 순서가 바뀔 수 있음 — 백테스트는 무해성(top1 무악화) 확인됐으나 실거래 표본은 아직 0. 승인 시 그림자(shadow) 배선으로 먼저 검증 권장.

### 후보 2 — compute_dynamic_bands 밸류에이션 캡 verdict 무관 적용 버그
- **대상**: `scripts/compute_dynamic_bands.py` (line 156-163, `build_ticker` 함수)
- **현재**: `valuation_ceiling`(=`valuation_check.tickers.*.valuation_ceiling_price`)이 존재하면 verdict 과 무관하게 target_band.ref/high 를 캡한다. `check_valuation_guard.py` 는 verdict 가 `cap_target`이 아니어도(`overheat_entry` 등) ceiling 값 자체는 항상 채운다.
- **변경 후 제안**: 캡 적용 조건에 `valuation_check.tickers.<t>.verdict == "cap_target"` 를 추가.
```diff
-    if valuation_ceiling:
+    if valuation_ceiling and verdict == "cap_target":
         if ref > valuation_ceiling:
             ref = valuation_ceiling
```
- **근거 lessons 라인**: 2026-08-12(최초 진단)·2026-08-13(선행조건 이행·종결 기록)·2026-08-14("8/16 policy_review 실행 안건으로 확정 이관") — 3회 연속 같은 결함을 "기각"만 하고 수정하지 않은 사례로 8/14 항목이 직접 지적.
- **자동 적용 가능 여부**: **사용자 승인 필요**(정확히는 스크립트 코드 수정 — 이 routine 의 커밋 범위(config/prompts/state/reports) 밖. 다음 코드 세션에서 최우선 처리 권고)
- **부작용 점검**: 수정 시 `overheat_entry` verdict 종목(현재 하나금융지주·KB금융)의 target_band.ref/high 가 캡 해제로 상승 — 재산정 신호(target_gap) 오발생이 사라짐. 수정 전까지는 8/14 lessons 가 재산출한 캡 제외 참조선(하나 143,167·KB 186,334)을 판정 기준으로 계속 인용할 것.

### 후보 3 — dead-config 처분 3건 (자동 적용 완료)
- **대상**: `config/policy.json` §disclaimers(삭제)·§weekly_cycle(삭제)·§rebalance_rules(→`_doc_rebalance_rules` 개명)
- **현재**: 3필드 모두 2주 연속 `check_policy_hygiene.py` dead_configs — 참조 없음.
- **변경 후 제안**: 적용 완료(policy v2.35). `check_policy_hygiene.py` 재실행으로 `dead_configs=[]`·`unregistered_new=0` 확인.
- **근거 lessons 라인**: 해당없음(§1-3 policy hygiene 원장 규약)
- **자동 적용 가능 여부**: **자동 적용 완료**(§1-3 처분 3택 실행은 routine 의무, 전략 파라미터 무변경)
- **부작용 점검**: `disclaimers`·`weekly_cycle` 는 11개 prompt 에 이미 하드코딩된 내용이라 삭제해도 동작 무변화 확인. `rebalance_rules` 는 개명만(값 보존).

### 후보 4 — lessons_rule_sunset 등록/만료 처분 2건 (자동 적용 완료)
- **대상**: `state/lessons.md` §2026-08-22(은행 3종)·§2026-08-14(카카오)
- **현재**: 11건 unregistered 중 진짜 진입차단·비중상한 신규 룰은 1건(은행 3종)뿐 — 나머지 10건은 SUNSET_KEYWORDS(차단/보류/금지/상한/캡/축소/냉각/제한) 오탐(서술 규칙·기존 정책 인용·자체 비일몰 선언 등)으로 판단해 등록하지 않았다.
- **변경 후 제안**: 은행 3종 룰에 `(expiry: 2026-08-28)` 추가. 카카오 룰(expiry 2026-08-21 도래)에 만료 처분 1줄 추가.
- **근거 lessons 라인**: 2026-08-22 / 2026-08-14 각 항목
- **자동 적용 가능 여부**: **자동 적용 완료**
- **부작용 점검**: 은행 3종 룰은 8/26~8/27 금통위·잭슨홀 구간 한정 — 신규 종목 차단 리스트가 아니라 시한부 진입 이연 서술이라 "신규 종목·섹터 차단 리스트" 사용자 승인 대상에 해당하지 않는다고 판단(경계선 항목 — 이견 있으면 즉시 재분류 요청).

## 4. policy.json dead config (참조 없음)
- 이번 리뷰에서 3건 전부 처분 완료(§3 후보 3) — 현재 `check_policy_hygiene.py` 결과 `dead_configs=[]`.

## 5. 다음 주 routine 적용 우선순위
- (자동 적용 즉시 반영 가능 항목) — 없음(이번 주 자동 적용분은 이미 반영 완료).
- (사용자 승인 후 다음 주 적용 항목) ① `compute_dynamic_bands` 밸류에이션 캡 verdict 게이팅 버그 수정(코드) ② estimate tilt score_candidates 배선(verdict=wire, 권장 margin 0.03 — 승인 시 shadow 우선 권고) ③ lessons-balance 근본 해법(✅codify 태깅 프로세스 설계) 안건 상정.
- (다음 archive 까지 관찰만 할 항목) whipsaw-high(ratchet breach 3건째 대기) · deployment-below-band(08/24~08/28 실제 배치 체결 여부) · 선제 추론 Tier2 게이트(high band pnl_linked_n=0, 미충족 유지) · 본전 래칫 승격 심사(breach 2/3건, 채점 보류).

## 6. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: **`compute_dynamic_bands` 밸류에이션 캡 버그**(2026-08-16 이관 유실로 9일 방치) — verdict=cap_target 게이팅 코드 수정 승인.
- 검토만 권장 2건: estimate tilt score_candidates 배선(verdict=wire, shadow 우선 권고) · lessons-balance 근본 해법(✅codify 태깅 프로세스 설계).
- 자동 적용 완료 5건: policy v2.35 dead-config 처분 3건 + lessons_rule_sunset 등록/만료 처분 2건 + self_audit_findings 6건 처분(overdue 5→0).
