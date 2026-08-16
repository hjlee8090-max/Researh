# 정책·프롬프트 패치 리뷰 — 2026-08-16 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-08-16 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 159 (신규 33건/7일)
- lessons "다음 적용 룰" 자동 대조(check_lessons_applied): hard 미반영 0 / soft 미반영 0 / 기존 반영 확인 4 — 이번 주 강제 상정 항목 없음
- 반복 누적 카운트 ≥3: 매크로 오차 5 · 섹터 오차 20 · 가정오류 9 · 선제추론오차 39 · 루틴 오차(지정학 속보 당일 역전) 3 — 전부 기존 대응(v2.5/v2.7/v2.11) 범위 내, 신규 패치 없음
- 자동 적용 완료 패치: **7건**(전부 버그수정·위생·문서정합 — 전략 파라미터 변경 0건)
- 사용자 승인 필요 패치: **0건** — 랭킹 tilt 배선(§2-c)은 verdict=wire 이나 사전 등록된 표본 게이트(45거래일) 미달로 상정 보류
- 자기감사 findings 처분: 6/6 완료(무처분 overdue였던 `deployment-below-band` 포함) — `python scripts/self_audit.py --followup-only` 확인 `overdue=0`

## 0. §0-0 자기감사 findings 처분 요약
`reports/2026-08-16-self-audit.md` + `state/self_audit_findings.json` 인용. 처분 전 상태: open 6건 중 `deployment-below-band` 가 **무처분 6주째(overdue)**.

| id | 처분 | 요지 |
|---|---|---|
| `whipsaw-high` | observe | ratchet_shadow breach 확정 2/3건 불변(3주째 신규 breach 없음), noise율 100%·net -50,000원 불변. 승격 미달 지속. |
| `deployment-below-band` | observe (overdue 해소) | 08-09 universe theme 버그 수정의 실효성 확인 — 주식비중 35.4%→57.1%(+21.7%p), NAVER·카카오 신규 진입 2건이 그 수정 덕. 잔여 갭은 버그가 아니라 overheat_entry·추격임계·chase_blocked 게이트가 정상 작동해 자격 후보가 없었던 결과(08-12 로그 직접 확인). 추격 강제는 금지. |
| `policy-dead-config-disclaimers` | patch | `_doc_disclaimers` 개명 완료 |
| `policy-dead-config-rebalance_rules` | patch | 삭제 완료(ATR 손절·섹터 로테이션 엔진으로 기능 대체 확인) |
| `policy-dead-config-weekly_cycle` | patch | `_doc_weekly_cycle` 개명 + 내용 정정 완료 |
| `lessons-balance` | defer | archive_candidates=0(이관 후보 없음) — 진단 결과와 다음 단계는 §1-6 참조 |

## 1. lessons → policy/prompt 반영 매트릭스

`check_lessons_applied.py` 자동 대조(전체 139개 룰 중 반복/강조 마커가 있는 4개 대표 항목 표본 검사): **hard 0 · soft 0 · 기존 반영 확인 4** — 이번 주 강제 상정 대상 없음.

| lessons 항목 | 다음 적용 룰(요지) | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-07-19 지수 스냅샷 지연 오판 | 웹 2출처 교차확인 의무·breadth로 지수 반증 금지 | `policy.price_data_quality.web_verify_guard.index_snapshot_confirmation` + 0900/1200/1500 | 반영 |
| 2026-08-04 선제추론 채점 백로그 재발 | 18시 채점은 '오늘 생성분'이 아니라 '미채점 전량' | `prompts/1800_report.md` §3-1(운영 관행, 코드 강제 아님) | 반영(관행) |
| 2026-06-12 카톡 오발송 | send_kakao 가드 3종 | `scripts/send_kakao.py` | 반영 |
| §1-2-b rule_sunset(v2.32 C-1) | 차단·상한 류 룰 expiry 미표기 촉구 | 이번 리뷰에서 등록 3건·면제 4건 실행(§1-2-b 참조) | 반영(이번 주 실행) |

이번 주 §1-2-b/§1-3 실행 전에는 unregistered rule_sunset 7건이 있었으나, 개별 검토 후 3건은 실제 임시 판단 규칙으로 확인해 expiry 등록, 4건은 진입 차단·비중 상한이 아닌 방법론/형식/버그수정 기록(오탐)으로 확인해 `(expiry 없음 — ...)` 면제 표기를 추가했다(build_lessons_index.py 에 이 표기를 인식하는 `exempted` 버킷 신설). 재실행 결과 `unregistered=0`.

## 2. 반복 누적 카운트 ≥ 3 항목

### [섹터 오차] — 20건 (07-26 대비 12건 증가) / [매크로 오차] — 5건 (변동 없음)
- 누적 라인 요약: 이번 주 증가분은 대부분 은행 3종(하나금융지주·KB금융, 비보유 신한지주 교차확인) 동반 열위 — 반도체 주도 로테이션의 소외 국면이 08-10부터 5거래일 연속. 비보유 종목 동행으로 매크로/섹터 축 교차확인이 매일 이뤄지고 있어 분류 자체는 정확하다.
- 권장 패치: 없음 — v2.11(ATR 연동 경보·rule_attribution 채점) 로 이미 커버되는 구조. thesis weakening 플래그가 정상 작동 중(하나·KB 2건 weakening).
- 별도 관찰: 08-12~08-14 사이 반복된 "가정오류(운영) — target_gap 결함 재출력" 3연속(08-12/08-13/08-14)은 섹터 오차 카운터가 아니라 별도로 `compute_dynamic_bands` 캡 버그가 원인이었다 — **§3 후보1에서 이번 리뷰가 수정**. 버그가 lessons.md 볼륨에 3일치 중복 기록을 만든 부작용도 함께 해소된다.
- 적용 방식: 관찰 지속.

### [가정오류] 9건 · [선제추론오차] 39건 · [루틴 오차(지정학 속보 당일 역전)] 3건
- 매주 반복되는 구조적 관측 카테고리로, 각각 v2.5(지정학 진행형 게이트)·기존 채점 파이프라인(score_inferences)으로 이미 대응 중. 신규 패치 없음 — 관찰 지속.

## 1-2-b. 룰 손익 채점 (rule_attribution)
- 청산 14건(승 5/패 9, 승률 35.7%) · PF 0.51 · expectancy -19,380원/건 · 순실현 -271,317원 — **08-09 리뷰와 완전 동일 수치**. 이번 주 신규 청산 0건(5거래일 전부 EOD_HOLD)이라 by_rule 표본이 갱신되지 않았다. `n=1` 표본이 대부분이라 "2주 연속 음" 판정 요건(반복 관측) 자체가 없음 — **통계 과신 금지 원칙에 따라 신규 패치 상정 없음**(08-09와 동일 결론).
- `blocked_day_rate_pct` 100%(days_with_candidates=2, 2026-06-03·06-10) — 6월 이후 갱신되지 않은 정보성 낮은 표본, 액션 없음.
- `lessons_rule_sunset`: 등록 3건(만료 2026-08-21×2·2026-08-24) · 면제 4건 · 만료 도래 0건. `state/policy_hygiene.json` 의 `review_due` 도 0건.

## 1-3. policy 미사용 필드 점검 (check_policy_hygiene)
- `dead_configs`: disclaimers·rebalance_rules·weekly_cycle **3건 전부 이번 리뷰에서 처분**(§0 표 참조). 6주째 "식별만 반복"되던 항목의 첫 실제 처분.
- `unregistered_new_rules`: 처분 과정에서 키 개명(`_doc_` 접두)이 발생해 일시적으로 6건 발생 → `state/policy_keys_baseline.json` 을 수동 갱신(신규 정책 은닉이 아니라 리네임임을 확인)해 0건으로 해소.
- `review_due`: 0건.

## 1-4. prompt 간 일관성
신뢰도 출처 규칙("`market_snapshot.confidence` 1순위·레거시 서술 이월 금지·stale≠low")을 00/0630/0900/1200/1500/1800·saturday_review·sunday_strategy·sunday_archive **8개 활성 prompt 전원**에서 확인(grep). **`weekend_report.md`(레거시 호환용, 스케줄 미등록) 1건만 "stale≠low" 명시 문구 누락** — §3 후보2로 반영.

## 1-5. 목표가 추정 채점 + 뉴스 키워드 점검 (estimate_scorecard)
- 기준: 추정 로그 48일 / 채점 표본 700건
- 5td 적중률 51%(기대 +8.9% vs 실현 -0.6%, 중앙오차 -6.7%p, n=628) · 20td 적중률 53%(기대 +9.3% vs 실현 -7.5%, 중앙오차 -11.8%p, n=351) — 08-09 대비 20td 적중률 44%→53% 개선, 중앙오차도 축소. **2주 연속 하락 없음 → 추정식 패치 후보 없음**.
- estimate_gate: 차단표본 88건 · fwd20 중앙값 -15.1% · 양수율 20% → **게이트 유효**(알파 차단 경보 없음).
- 뉴스 unclassified 15개 표본 검토 — 삼성전자·SK하이닉스·HD조선·LG에너지솔루션 관련 일반 뉴스 위주로 **현재 보유 5종(LIG넥스원·하나금융지주·KB금융·NAVER·카카오)과 무관**. manual_news 승격·키워드 보강 후보 없음. silent_types 없음.
- **랭킹 편입(틸트/타이브레이크) 재심사**: 추정 로그가 45거래일 임계에 근접(48일)해 `scripts/backtest_estimate_tilt.py` 를 사전 등록 기준대로 재실행했다. 결과 **verdict=wire · tiebreak_verdict=wire_tiebreak**(C1~C3·T1~T3 전부 pass, 권장 margin=0.03) — 2026-07-21 연구의 "hold"에서 처음으로 바뀐 판정이다. 그러나 실제 백테스트 창은 **41거래일**(t0 2026-06-11~08-07)로 사전 등록한 45거래일 게이트에 아직 못 미치고, 대안 기준인 타이브레이크 변경일 표본도 margin=0.03 기준 **7건**(임계 10건 미달)이다. **기준 사후 변경 금지 원칙**에 따라 이번 리뷰에서는 patch 후보로 상정하지 않고 관찰을 유지한다 — 창이 45거래일에 도달하는 다음 리뷰(약 1주 후)에 동일 기준으로 재실행해 그때도 wire 면 그때 `score_candidates` 배선을 사용자 승인 patch 후보로 상정한다.

## 1-6. lessons.md 응축 (수지 균형 의무)
- `lessons_index.archive_candidates` = **0건**(codify+✅ 마커 존재 · 섹션 30일+ 경과 · 본문 8줄 초과 미응축 3조건 동시충족 항목 없음). 30일+ 경과한 과거 codify 항목을 직접 대조한 결과 전부 이미 4~5줄로 응축 완료 상태 — 응축 배치가 밀린 것이 아니라, lessons.md 320,565B의 실체는 최근(30일 미만) in-progress·미반영 항목의 순수 신규 유입(33건/7일, §1-6 불변보존 대상)이다.
- 수지 균형 두 조건(이관≥신규유입 33건, 또는 ≤60KB) 모두 이번 주 기계적으로 충족 불가 — **defer 처분**(§0 표). 다음 리뷰까지 검토할 구조적 대안: ① `ARCHIVE_AFTER_DAYS`(현 30일) 단축 ② `lessons_max_bytes`(60KB) 예산 자체의 현실성 재평가 ③ 선제추론오차·사전 경보처럼 당일 종결되는 관측성 카테고리의 별도 단기 롤오프 규칙 신설.

## 1-7. 선제 추론 루프 채점 (inference_scorecard)
- 전체: 적중률 58.8%(부분 21.3%, n=427) · 결합손익 -239,687원 · PF 0.1 — **08-09와 수치 동일**(신규 청산 0건이라 pnl_linked_n 갱신 없음, n=5 불변).
- `by_confidence_band.high`: n=8(08-09 대비 n=5→8 증가) · 적중률 75% — 그러나 `pnl_linked_n=0`(결합손익 매칭 0건)이라 Tier 2 개방 게이트(expectancy>0 AND PF>1) **여전히 판정 불가**. **Tier 2 동결 유지**(paper-only).
- 체크리스트: `inference_checklist.md` 15/40줄·3941/4000B로 여전히 TRUNCATED 근접 — 구조적 이슈, 관찰 지속.
- 기회비용: `n_shadow=0` — 채점 보류.

## 1-8. 본전 래칫 스톱 승격 심사 (ratchet_shadow_scorecard)
- `verdict`: **채점 보류** — breach 확정 2/3건(3주째 신규 breach 없음, 관측만 25→30거래일 진전) · noise율 100% · net 보호 -50,000원(불변). 승격 기준 미달 지속 — 체결 변화 금지.
- §0-0 `whipsaw-high` 처분과 동일 근거.

## 3. 실행된 패치 (자동 적용 완료 — 7건)

### 후보 1 — `compute_dynamic_bands` 밸류에이션 캡 오적용 버그 수정 (최우선)
- **대상**: `scripts/compute_dynamic_bands.py` (`build_ticker`/`compute`)
- **현재(수정 전)**: `valuation_ceiling_price` 가 존재하면 `valuation_check.verdict` 와 무관하게 target_band ref/상단을 캡. `policy.valuation_anchor` 정본은 verdict=`cap_target` 일 때만 캡을 요구하는데, verdict=`ok`/`overheat_entry` 종목(하나금융지주·KB금융)에도 캡이 적용돼 08-12~08-14 사흘 연속 존재하지 않는 `target_gap` 신호를 만들었다(lessons.md 3건 연속 "가정오류(운영)" 기록, 8/16 실행 안건으로 명시적 이관됨).
```diff
- if valuation_ceiling:
+ if valuation_ceiling and valuation_verdict == "cap_target":
```
- **근거 lessons 라인**: 2026-08-14 "가정오류(운영) — 결함이라고 확정한 신호가 사흘째 같은 자리에서 다시 나왔다"
- **자동 적용 가능 여부**: 가능(버그 수정 — 전략 파라미터 변경 아님, 패치 동결 규칙과 무관)
- **부작용 점검**: `--selftest` 통과 확인(신한지주 8/5 재현 케이스는 valuation 데이터 미전달이라 캡 경로 자체를 타지 않아 영향 없음). 실제 상태로 재실행 결과 하나금융지주 ref=143,167(cap_applied=False)·KB금융 ref=186,334(cap_applied=False) — 8/14 수기 재산출값과 정확히 일치. `state/dynamic_bands.json` 재생성 완료(target_gap 신호 2→0).

### 후보 2 — `weekend_report.md` 신뢰도 규칙 문구 정합
- **대상**: `prompts/weekend_report.md` §6
- **현재**: 레거시 이월 금지·confidence 참조 규칙은 있었으나 "1순위" 명시·"stale≠low" 문장이 없어 §1-4 grep 기준 유일하게 누락.
- **변경 후**: 다른 8개 prompt와 동일한 "stale ≠ low" 문장 추가.
- **자동 적용 가능 여부**: 가능(명문화 문구 추가, 기존 동작과 모순 없음).
- **부작용 점검**: 이 prompt는 saturday_review/sunday_strategy 로 대체된 레거시·스케줄 미등록 파일이라 실질 영향 없음.

### 후보 3 — `build_lessons_index.py` rule_sunset 오탐 완화
- **대상**: `scripts/build_lessons_index.py` (`build_rule_sunset`)
- **현재**: SUNSET_KEYWORDS(차단·보류·금지·상한·캡·축소·냉각·제한)가 방법론/형식/버그수정 기록까지 오탐지해 저자가 "(expiry 없음 — ...)"으로 명시한 항목도 매주 `unregistered` 로 재상정됐다.
- **변경 후**: `NO_EXPIRY_RE`(`\(expiry 없음`) 인식 추가, `exempted` 버킷 신설.
- **순증 금지 관례(v2.33 G) 대조**: 이 패치는 lessons.md 의 룰·섹션을 추가하는 게 아니라 스크립트의 오탐 인식 로직을 보강하는 것이라 해당 관례의 적용 대상이 아니다.
- **자동 적용 가능 여부**: 가능(스크립트 버그 완화).
- **부작용 점검**: 재실행 결과 unregistered 7→0, 진짜 위험한 미등록 차단 룰이 숨겨지지 않는지 개별 확인 완료(§1-2-b).

### 후보 4~6 — dead config 처분 3건 (§0-0/§1-3 표 참조)
- `_doc_disclaimers` 개명 · `rebalance_rules` 삭제 · `_doc_weekly_cycle` 개명+내용정정. `state/policy_keys_baseline.json` 동반 갱신.

### 후보 7 — lessons.md rule_sunset 메타 등록/면제 7건 (§1-2-b 참조)

## 4. 사용자 승인 필요 패치 — 0건
- 이번 리뷰에서 상정 유보: 랭킹 tilt/tiebreak 배선(§1-5) — verdict=wire 이나 사전 등록 표본 게이트 미달로 다음 리뷰까지 관찰.
- `deployment-below-band`·`whipsaw-high`(ratchet 승격)·Tier2 개방(§1-7) 모두 게이트 미충족으로 액션 없음 — 강제 진입·체결 변화는 정책상 금지 경로.

## 5. 다음 주 routine 적용 우선순위
- (즉시 반영 완료) compute_dynamic_bands 버그 수정 → 다음 18시 routine부터 하나금융지주·KB금융 target_gap 오탐 소멸 확인.
- (다음 리뷰 8/23 재판정) 랭킹 tilt 배선 — 45거래일 표본 도달 시 동일 기준 재실행.
- (계속 관찰) ratchet_shadow breach 3건째 도달 여부, deployment 갭에서 자격 후보가 있는데도 heat만으로 막히는 사례 발생 여부, lessons.md 수지 균형 구조적 대안.

## 6. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: 없음 — 이번 리뷰는 버그수정 7건 자동 적용으로 완결, 전략 파라미터 변경 없음.
- 검토만 권장: lessons-balance 구조적 예산 재검토(§1-6), 랭킹 tilt 배선 다음 리뷰 재판정(§1-5).
- 자동 적용 완료 7건: compute_dynamic_bands 캡 버그 수정 · weekend_report.md 정합 · rule_sunset 오탐 완화 · dead config 3건 처분 · rule_sunset 메타 7건.
