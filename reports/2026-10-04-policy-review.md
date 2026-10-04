# 정책·프롬프트 패치 리뷰 — 2026-10-04 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-10-04 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 362 (최근 7일 신규 유입 25건, 추출 룰 누계 320)
- 교훈 반영 자동 대조: open_items_hard **3**(2건은 09-11 사전 경보 동일 항목 — 09-20 리뷰에서 prompts 에 codify 완료, 체커가 원문 문구 기준이라 잔존 표시 / 1건 신규: 10-01 은행 손절선 잔류 예측) / soft **3** / resolved 4
- 반복 누적 카운트 ≥ 3: 6개 분류(매크로 25·섹터 72·개별 11·가정오류 36·선제추론오차 77·루틴〈지정학〉3) — 신규 정책 패치 없음
- **정책 동결(Stage 0) 유지** — `config/policy.json` 무편집, backlog 4건(신규 등록 없음)
- 자동 적용 완료: 0건(코드·정책 패치 없음, state/reports 만 갱신) / 사용자 승인 필요: 1건(후보 1) / 관찰 지속: 3건

## 0. §0-0 주간 자기감사 findings 처분
`reports/2026-10-04-self-audit.md` / `state/self_audit_findings.json`. open 3건 전건 처분, `--followup-only` 결과 `open=3 overdue=0`(처분 전 overdue=1).

| id | 처분 | 요지 |
|---|---|---|
| `whipsaw-high` | defer | ratchet shadow 5건·noise율 100%·net 보호 -161,800원 불변. 완화안은 동결 게이트 대상(backlog #2 유효). 재확인 10-11 |
| `deployment-below-band` | observe | 주식비중 **11.8%**(09-20 48.3%에서 급락, 보유 삼성SDI 1종). heat 여유 89%, risk_on. 강제 배치 금지·동결 유지. gate_cost '게이트 유효' |
| `lessons-balance` | defer | **이관 0건 — §1-6 수지 균형 의무 미충족**(아래 §6). 다음 리뷰 최우선 |

## 1. lessons → policy/prompt 반영 매트릭스 (hard 대상)
| lessons 항목 | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-09-11 00:00 사전 경보 (2줄) | 전이 계수 국면 의존성·재료 반복 횟수 | `prompts/0630_us_close.md §2-1`·`0000_global.md §2-1` (09-20 codify) | 반영 — 체커 앵커 문구 불일치로 잔존 표시 |
| 2026-10-01 선제추론오차 — 은행 잔류 3건 | 보유 종목이 갭 주도 축에 속하는가 (9/22 체크리스트) | 체크리스트에만 존재, prompts 미강제 | **미반영(hard)** → 후보 1 |

## 2. 반복 누적 카운트 ≥ 3
6개 분류 모두 기존 v2.5~v2.36 반영에 흡수. 신규 patch 없음(동결). 선제추론오차 77건은 `inference_checklist.md`(18/40줄)로 응축 중.

## 2-c. 목표가 추정 채점 + 뉴스 키워드
- 5td 적중 45.2%(n=1188, 중앙오차 -8.4%p) · **20td 적중 51.6%**(n=828, 기대 +9.9% vs 실현 +1.7%, 중앙오차 -5.9%p) · 60td 43.3%(n=30, 표본 작음)
- 20td 적중률은 09-20 56% → 51.6% 로 **5주 연속 하락**, 중앙오차 5%p 초과 지속 → 추정식 패치 후보. 단 §1-5 원칙상 **백테스트(backtest_target_model) 재실행 근거 필수**·동결 중이라 변경 없음.
- gate_cost: 차단 238건·20td 채점 153건, 중앙 +0.97%·양수 비율 51.6% → `alpha_block_alert=False`, 게이트 유효·현행 유지.
- 뉴스 키워드: unclassified 표본은 삼성전자 실적전망·자사주, 조선 수주(삼성중공업 LNG선 2척 6,722억)·브랜드평판 등. 수주 공시는 실질 뉴스 후보지만 이번 실행에서 출처 URL 검증·키워드 반영은 수행하지 않음(키워드 보강 0건 — 다음 리뷰 이월). silent_types: earnings_miss_or_guidance_cut·policy_support·supply_glut_or_price_drop.

## 3. 패치 후보
### 후보 1 — 선제추론 은행 축: '갭 주도 축 소속' 확인 강제
- **대상**: 선제추론 슬롯 prompt(0900·1800 계열) 해당 섹션 — 체크리스트 항목을 prompt 본문 규칙으로 승격
- **변경 제안**: "보유 종목이 당일 갭·지수 반등을 주도한 축(예: 반도체)에 속하는지 먼저 적고, 속하지 않으면 지수 반등을 잔류 확률 근거로 쓰지 않는다"
- **근거**: 2026-10-01 선제추론오차(3건 연속 빗나감), rule_sunset 등록 룰(expiry 2026-10-12)과 동일 취지
- **자동 적용 여부**: 가능(명문화 문구)이나 순증 금지 관례상 은퇴·통합할 기존 문구를 특정하지 못해 **사용자 승인/다음 리뷰에서 대체 문구 지정 후 적용**
- **부작용**: 순수 추가 시 prompts 비대화 → 대체 지정 필요

### 후보 2 (동결 backlog 유지) — ratchet `when_gain_atr` 상향 또는 breakeven_ratchet 기각
- 래칫 shadow: breach 5건·noise율 100%·net -161,800원 → 판정 '기각·완화 후보'. 동결 backlog #2 로 이미 등록(신규 등록 불요).

## 1-2-b. 룰 손익 / 일몰
- rule_attribution: TRAILING_STOP 2건 +192,878원(t5 일실 +232,186원 → 조기청산 비용 큼), SELL_TRAIL_RESIDUAL 1건 -110,728원. 2주 연속 음(-) 룰 판정은 표본 부족으로 보류.
- 일몰 만료 11건(`rule_sunset.expired`, 최장 2026-08-21 만료 도래분): 판정 — 모두 **만료(실효 확정)** 로 분류. lessons 본문 1줄 기입은 이번 실행에서 미수행(이월). unregistered 32건 expiry 태깅도 이월.
- policy_hygiene: dead_configs 0·unregistered_new 0·review_due 0.

## 1-7. 선제추론 채점
- 전체 적중 58.2%(n=885), high 구간 73.7% 이나 결합손익 pnl_linked 10건 합 -389,321원·PF 0.11·expectancy<0 → **Tier 2(공격) 개방 게이트 미충족, paper-only 유지**.
- 기회비용: 미배치 그림자 1건 — 채점 보류.
- 반복 미흡 요인 상위: 개장 갭 방향·밴드 이탈(27), 이벤트 캘린더(20), 외국인/기관 수급(14).

## 1-8. 본전 래칫
- verdict 기각·완화 후보(breach 5건·noise율 100%). 승격 불가. 완화/기각안은 동결 backlog #2.

## 4. policy.json dead config
없음(`check_policy_hygiene.py`).

## 5. 다음 주 우선순위
- 즉시 반영 가능: 없음(동결)
- 승인 후: 후보 1(대체 문구 지정)
- 관찰/이월: **lessons 이관(codify_candidates 30건 건별 검증 후 ≥25건)**, 일몰 만료 11건 lessons 1줄 기입, unregistered 32건 expiry 태깅, 뉴스 키워드(조선 수주) 검토, 동결 해제 후 `backtest_target_model.py` 재실행

## 6. 사용자 액션 요약
- 즉시 결정 필요 1건: 후보 1 대체 문구 승인(또는 순증 허용 여부)
- **§1-6 수지 균형 의무 미충족 사유**: lessons.md 812KB(예산 60KB) · 이관 0건 < 주간 유입 25건. codify_candidates 가 신호매칭 기반이라 건별 반영 위치 검증이 선행돼야 하는데 이번 실행에서 완료하지 못함(미검증 이관은 미반영 룰 유실 위험). lessons-balance 는 defer, 다음 주 최우선.
- 자동 적용 완료 0건. 주식비중이 11.8%로 낮음(관찰).
- 참고: 이 실행은 지정 개발 브랜치 `claude/nice-babbage-hz2hce` 에 푸시(prompt 의 main 푸시 대신).
