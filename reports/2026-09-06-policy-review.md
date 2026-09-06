# 정책·프롬프트 패치 리뷰 — 2026-09-06 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-09-06 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 267 (신규 추출 룰 최근 7일 유입: 37건)
- 교훈 반영 자동 대조(`check_lessons_applied.py`): open_items_hard **0** / open_items_soft **1** / resolved(이미 반영) **4**
- 반복 누적 카운트 ≥ 3: 6개 분류(매크로20·섹터37·개별5·가정오류26·선제추론오차52·루틴〈지정학〉3) — 전부 기존 policy v2.5~v2.36 에 흡수, 신규 패치 불요
- **정책 동결(Stage 0) 유지 중** — `config/policy.json` 무편집. 패치 후보 3건은 등록만(backlog)
- 자동 적용 완료: **2건**(스크립트 버그 수정 1 · lessons 응축 시범 1) / 동결 backlog 등록: **3건** / 사용자 승인 대기(이월): **1건**

## 0. §0-0 주간 자기감사 findings 처분 (기계 강제)

`reports/2026-09-06-self-audit.md`(오늘 `scripts/self_audit.py` 직접 실행 생성 — 17시 `weekly_self_audit.yml` 산출물 부재) / `state/self_audit_findings.json` 인용. open finding 3건 전건 처분 완료, `python scripts/self_audit.py --followup-only` 재확인 결과 `open=3 overdue=0`.

| id | 경과 | 이번 리뷰 처분 |
|---|---|---|
| `whipsaw-high` | 9주째 🔴(재발) | **defer**(동결 backlog #2 등록) — §1-8 재심: breach 확정 5건(08-30 4건→+1), noise율 100%(불변), net 보호 -161,800원(08-30 -114,800원 대비 악화). 08-30 patch(when_gain_atr 1.0→1.5) 효과 없음 확인 — 처분 자동 무효화·재상정됐으나 추가 완화는 policy.json 수정이라 동결에 걸림. mode=shadow 불변(실제 체결 무변화). |
| `deployment-below-band` | 9주째 | **observe** — 배치 8.5%(09-01 43.5%→9/2 지정학 매크로 충격 이후 급락). 게이트 3종 정당 작동·국면 의존 진단(08-30) 유지. 동결 중이라 목표·임계 변경 애초 상정 범위 밖. |
| `lessons-balance` | 4주째 | **patch**(부분) — 08-30 이 요구한 "최소 임시 조치 시범" 실행: codify 확정 lessons 1건을 §1-6 절차대로 전문 이관+4줄 응축(아래 §1-6 참조). 수지 균형 의무는 여전히 미충족(이관 1건 ≪ 유입 37건, lessons.md 581,374B ≫ 예산 60,000B) — 구조적 해법은 다음 리뷰에 재상정. |

## 1. lessons → policy/prompt 반영 매트릭스

§1-1 은 `check_lessons_applied.py` 산출물(`state/lessons_applied.json`)을 1차 입력으로 사용(267항목 통읽기는 콘텍스트 예산 위반).

| lessons 항목 | 다음 적용 룰(요지) | 반영 위치 | 상태 |
|---|---|---|---|
| 반복 6분류(매크로/섹터/개별/가정오류/선제추론오차/루틴〈지정학〉) | 각 카테고리 세부 룰 다수 | `policy.json`(v2.5~v2.36 다회) + `docs/policy_rationale.md` | **반영**(기존 codify) |
| 2026-07-16 지수 급락 데이터지연 오판 | 대형 지수 스냅샷 ±3% 초과 이동 시 web_verify_guard | `policy.price_data_quality.web_verify_guard.index_snapshot_confirmation` | **반영**(기존) |
| 루틴(선제추론 채점 백로그 방치, 재발 4회) | 소급 채점 절차 | `order_intents`/`inference_log.jsonl` 절차 신호 확인 | **반영**(기존 — 단, 재발 4회째로 근본 해소는 아님, 관찰 지속) |
| **2026-08-13/14 가정오류(운영) — compute_dynamic_bands 캡 verdict 무관 적용** | `target_band` 캡을 `valuation_check.verdict=="cap_target"` 일 때만 | `scripts/compute_dynamic_bands.py` (오늘 수정) | **반영(신규, 이번 리뷰)** — 아래 §3 후보 1 |
| 2026-08-31 선제추론오차 — 잭슨홀 "확정 재료" 오독(1건, soft) | 확정 재료라도 개장 갭에 값이 이미 지불됐는지 먼저 확인 | 없음 | **미반영**(단발 — 검토 후보, 반복 마커 없음이라 최우선 아님) |
| 08-23 estimate tilt score_candidates 배선 (verdict=wire, 08-23 확정) | tilt_bands × w=0.03~0.08 가중 배선 | 미배선 | **미반영 — 08-30 리뷰에서 재확인 없이 누락됨(추적 실패, 이번 리뷰에서 재발견)** — 동결 backlog #3 등록 |
| 08-30 "측정창 미도래" 라벨링 (사용자 승인 대기, 08-30 이월) | 목표가 오차 판정에 지평(horizon) 라벨 별도 집계 | 미반영 | **이월**(승인 대기 — 변화 없음) |

## 2. 반복 누적 카운트 ≥ 3 항목

### 매크로20 · 섹터37 · 개별5 · 가정오류26 · 선제추론오차52 · 루틴오차(지정학)3
- 권장 패치: 없음 — `check_lessons_applied` 대조 결과 6개 분류 세부 룰은 이미 policy v2.5~v2.36 다회 반영에 흡수됨. 카운터는 일별 목표가 오차 누적 총계이지 미반영 신호가 아니다(08-23·08-30과 동일 결론).
- 적용 방식: 해당 없음(기 반영)
- 근거: `state/lessons_index.json` repeat_counter, `state/lessons_applied.json` summary

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)
- 기준: 2026-09-06T20:08:47+09:00 · 추정 로그 66일 / 채점 표본 1050건
- 5td: 적중률 48% · 기대 +9.8% vs 실현 -0.8% · 중앙오차 -7.6%p (n=950)
- 20td: 적중률 58%(08-23 55%→08-30 59%→09-06 58%, 2주 연속 하락 아님) · 기대 +9.0% vs 실현 -2.1% · 중앙오차 -6.4%p (n=592)
- 60td: 적중률 56% · 기대 +6.6% vs 실현 -12.7% · 중앙오차 -16.3%p (n=9, 이번 주 최초로 채점 가능 표본 확보)
- estimate_gate 손익: 차단표본 225건(scored 124) · fwd20 중앙값 -7.51% · 양수율 28.2% → `alpha_block_alert=false`, 게이트 유효(차단 정당)
- **추정식 패치 후보: 없음** — 20td 2주 연속 하락 아님, 중앙오차가 5%p 임계를 계속 초과하나(6.4%p·16.3%p) 백테스트 재실행 없이는 파라미터 변경 금지 원칙 유지(관찰만 지속, 08-23·08-30 동일 결론). 60td 신규 표본(n=9)은 단일 관측치라 트렌드 판단 보류.
- **뉴스 키워드 보강**: 이번 주 unclassified 15건 전건 검토 — 삼성전자 노조 송치 기사·HD한국조선해양 공시 정정 기사·투자분석 사이트 자동생성 글 등 노이즈성이며, 방향 반전을 만들 실질 촉매(관세환급류 오분류 패턴 포함)는 발견되지 않음. silent_type(`earnings_miss_or_guidance_cut`)도 이번 주 대응 뉴스 없음 → **보강/승격 실행 내역: 없음**.
- **랭킹 편입(estimate tilt) 재심사**: §1 매트릭스 참조 — verdict=wire(08-23) 확정 후 배선이 08-30 리뷰에서 누락됐던 것을 이번 리뷰에서 재발견. 동결 backlog #3 등록(§3 후보 3).

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — compute_dynamic_bands 밸류에이션 캡 버그 수정 (자동 적용 완료)
- **대상**: `scripts/compute_dynamic_bands.py` `build_ticker()`/`compute()`
- **현재(수정 전)**: `valuation_ceiling_price` 가 존재하면 `valuation_check.verdict` 값과 무관하게 target_band 참조·상단을 캡했다 — overheat_entry/ok 종목도 cap_target 종목과 동일하게 캡이 걸려 존재하지 않는 target_gap 재산정 신호를 반복 생성(2026-08-13/14 lessons, 08-16 이관 후 3주째 미착수 확인 — 08-23·08-30 self_audit 에서도 "코드 수정 보류, 사용자 액션 최우선 상정"으로만 반복 이월됐다).
```diff
-    if valuation_ceiling:
+    if valuation_ceiling and valuation_verdict == "cap_target":
         if ref > valuation_ceiling:
             ref = valuation_ceiling
```
(+ `build_ticker`/`compute` 시그니처에 `valuation_verdict` 인자 추가, 호출부에서 `val.get("verdict")` 전달)
- **근거 lessons 라인**: 2026-08-13(종결 기록, `state/lessons_archive.md` 이관) · 2026-08-14(가정오류(운영), "다음 routine 에 반영할 룰")
- **자동 적용 가능 여부**: 가능 — **scripts/*.py 버그 수정은 정책 동결 예외 허용 항목**(수치·룰 불변, 산출 로직만 verdict 조건 정합화)
- **검증**: `python scripts/compute_dynamic_bands.py --selftest` PASS(신한지주 8/5 재현 사례 불변) · 프로덕션 실행(`python scripts/compute_dynamic_bands.py`) 정상 종료, `state/dynamic_bands.json` 갱신 확인(현재 verdict=ok/deep_value 뿐이라 이번 실행에서 캡 미적용 0건 — cap_target 종목 등장 시 회귀 확인 필요)
- **부작용 점검**: `build_ticker`/`compute` 를 호출하는 다른 스크립트 없음(grep 확인) — 영향 범위는 이 파일 내부로 한정

### 후보 2 — breakeven_ratchet stage1 문턱 추가 완화 또는 기각 (동결 backlog 등록)
- **대상**: `config/policy.json` §risk.breakeven_ratchet.steps[0].when_gain_atr
- **현재**: 1.5 (v2.36, 08-30 상향)
- **변경 후 제안**: 2.0 로 추가 상향 또는(noise 억제 실패 지속 시) mode=shadow 관측 중단·기각
- **근거 lessons 라인**: `state/ratchet_shadow_scorecard.json`(09-06, breach 5건·noise율 100%·net -161,800원) · `self_audit_findings.json` whipsaw-high 이력
- **자동 적용 가능 여부**: **불가 — 정책 동결(Stage 0) 대상.** `state/policy_freeze.json.backlog` 에 등록만(등록 완료, 이번 리뷰).
- **부작용 점검**: mode=shadow 이므로 등록 지연 자체는 실체결에 영향 없음

### 후보 3 — estimate tilt score_candidates 배선 (동결 backlog 등록, 08-30 누락분 재상정)
- **대상**: `scripts/score_candidates.py` + `config/policy.json` §momentum_strategy/score_blend_weights
- **현재**: 미배선(fundamental_tilt·valuation_tilt 만 존재, estimate tilt 없음)
- **변경 후 제안**: `state/backtest_estimate_tilt.json`(2026-08-23, verdict=wire·tiebreak_verdict=wire_tiebreak) 근거로 tilt_bands × w=0.03~0.08 배선
- **근거**: `reports/2026-07-21-estimate-tilt-research.md`(1차 보류) → 08-23 재검증(45거래일 표본 충족, 사전 등록 기준 전부 pass)
- **자동 적용 가능 여부**: 사용자 승인 필요(랭킹 로직 변경) **+ 정책 동결 대상** — 등록 완료(이번 리뷰). **주의**: 08-23 에 사용자 승인 후보로 상정된 뒤 08-30 리뷰가 이를 언급 없이 누락했다 — 승인도 기각도 없이 조용히 사라진 항목이라 이번 리뷰에서 재발견해 복원했다. 다음 리뷰부터는 §3 이월 후보를 명시적으로 캐리포워드할 것.
- **부작용 점검**: 동결 해제 시점까지는 어차피 실행 불가 — 우선순위만 확정해둠

### 후보 4 (이월, 08-30 그대로) — 목표가 오차 "측정창 미도래" 라벨 신설
- **대상**: `prompts/*.md`(목표가 오차 판정 섹션) + 관련 지표 표기
- **현재**: 밸류에이션 밴드 상단형 목표가는 구조적으로 큰 괴리로 시작하는데 이를 일반 오차와 동일하게 취급
- **변경 후 제안**: 08-30 제안 그대로 이월(변경 없음) — 사용자 승인 대기
- **자동 적용 가능 여부**: 사용자 승인 필요

## 4. policy.json dead config (참조 없음)
- 없음 — `scripts/check_policy_hygiene.py` 결과 `dead=[] unregistered_new=0 review_due=0`.

## 5. lessons.md 응축 (§1-6, 수지 균형 의무)
- 이번 리뷰 이관: **1건**(2026-08-13 가정오류(운영) — compute_dynamic_bands target_gap 종결, 후보 1 codify 확정에 따라 전문을 `state/lessons_archive.md` 로 이관하고 lessons.md 를 분류·요약·✅codify 반영 위치·전문 이관 표기 4줄로 교체). 2026-08-14 항목(같은 결함의 원 제안)에도 ✅codify 마커 추가(전문 이관은 다음 회차로 유보).
- 결과: lessons.md 582,624B → **581,374B**(-1,250B). `build_lessons_index.py` 재실행으로 entries=267 불변(카운터·미반영 항목 원문 불변 보존) 확인.
- **수지 균형 판정: 미충족** — 이관 1건 ≪ 신규 유입 37건, 잔여 581,374B ≫ 예산 60,000B. 08-30 이 요구한 "최소 임시 조치 시범"은 이행했으나 구조적 해법(어느 routine 이 매일 codify 마커를 남길지 절차 설계, 08-30 §3 후보 1)은 여전히 미승인 — 다음 리뷰(09-13)에 재상정.

## 6. 다음 주 routine 적용 우선순위
- (즉시 반영 완료) `scripts/compute_dynamic_bands.py` — valuation 캡 verdict 게이팅 버그 수정
- (즉시 반영 완료) `state/lessons.md`/`state/lessons_archive.md` — codify 이관 1건 시범
- (동결 backlog 등록, 해제 후 최우선) breakeven_ratchet 추가 완화/기각(backlog #2) · estimate tilt 배선(backlog #3, 08-30 누락분 복원)
- (사용자 승인 대기, 이월) 측정창 미도래 라벨링(§3 후보 4) · lessons codify 마커 절차 설계(§5)
- (다음 archive 까지 관찰만) whipsaw-high 09-13 재확인 · deployment-below-band 국면 해소 여부 · 20td/60td 추정 오차 추이

## 7. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: 없음(자동 적용 범위 내 처리 완료, 나머지는 정책 동결로 등록만)
- 검토만 권장 2건: estimate tilt 배선 승인 여부(§3 후보 3, 08-30 에 누락됐던 안건) · lessons codify 절차 공식화(§5)
- 자동 적용 완료 2건: compute_dynamic_bands 버그 수정 · lessons 응축 시범 1건
