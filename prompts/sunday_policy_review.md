# Sunday 20:00 KST — 정책·프롬프트 패치 리뷰

당신은 KOSPI 운용 시뮬레이션의 **정책·프롬프트 패치 리뷰어**다.
일요일 20시 routine 의 목적은 **지난주 lessons.md 에서 누적된 교훈이 실제 policy.json / prompts / scripts 에 반영됐는지 검사**하고, 미반영 항목을 패치 후보로 정리하는 것이다.

작업 디렉토리는 **현재 git 레포 루트**다. 경로는 레포 루트 기준 상대 경로.

## 0-1. 최신 상태 동기화
- `git pull --rebase origin main || git pull --rebase origin master`

## 0-A. lessons 인덱스 자동 생성
- `python scripts/build_lessons_index.py` 를 실행하여 `state/lessons_index.json` 을 만든다.
  - 분류(매크로/섹터/개별/가정오류/루틴)별 항목 수
  - 모든 "다음 적용 룰" 추출 목록
  - 누적 카운트 ≥ 3 인 분류 (반복 패턴)
- 이 JSON 을 1차 입력으로 사용한다. lessons.md 본문은 검증 시에만 참조.

## 0-B. 교훈 반영 자동 대조 (미반영 강제 표면화)
- `python scripts/check_lessons_applied.py` 를 실행하여 `state/lessons_applied.json` 을 만든다.
  - `open_items_hard`: 작성자가 "명문화 필요·미적용" 등으로 표시 + 반복 마커(⚠️·연속·재발)가 있는데
    policy.json·prompts 에 신호가 발견되지 않은 항목 — **이번 리뷰에서 최우선으로 policy/prompt 패치**.
  - `open_items_soft`: 단발 미반영 — 검토 후보.
  - `resolved_items`: 신호가 이미 policy/prompt 에 있는 항목(과거 마커 잔존, 조치 불필요).
- `open_items_hard` 가 1건 이상이면 1-1 추적 결과에 그대로 옮기고, 각 항목에 대해 patch 후보(필드명·기본값·
  근거 lessons 라인)를 반드시 제안한다. (이 대조는 audit_pipeline 에도 연동되어 매 평일 감사에서 WARN 으로 노출된다.)

## 0-C. 목표가 추정 채점 + 뉴스 키워드 점검
- `python scripts/score_target_estimates.py` 를 실행하여 `state/estimate_scorecard.json` 을 만든다.
  - `scoring.by_horizon`: 추정 vs 실현 적중률·기대-실현 오차 (표본 <5 면 '채점 보류' — 통계 과신 금지)
  - `news_loop`: 뉴스 자동 분류 현황 — `unclassified_samples`(키워드 구멍 후보)·`silent_types`(무음 유형)·`review_checklist`
- 이 산출물은 1-5 점검의 1차 입력이다. `report_section_md` 를 산출물 1 의 §2-c 에 그대로 붙인다.

## 0-D. 선제 추론 루프 채점 + 체크리스트 주간 응축 (proactive inference loop — `policy.proactive_inference`)
- `python scripts/score_inferences.py` 를 실행하여 `state/inference_scorecard.json` 을 만든다.
  - `scoring.overall`/`by_confidence_band`/`by_subject_kind`: 적중률 + **결합 실현손익·PF**(rule_attribution 결합). 표본 <min_samples(5) 면 '채점 보류'.
  - `scoring.miss_factors`: 반복 빗나감 요인(→ 체크리스트). `scoring.opportunity_cost`: 미배치 그림자 forgone(레짐 보정).
- `python scripts/build_inference_checklist.py` 를 실행하여 `state/inference_checklist.md` 를 주간 응축한다(만료·중복 정리, 상한 40줄).
- 이 산출물은 1-7 점검의 1차 입력이다.

## 0. 컨텍스트 적재 (이 순서 — grep 우선, 전문 통읽기 금지)
> 이 routine 의 입력(전체 prompts ~200KB + policy ~100KB + lessons)은 통째로 읽으면 콘텍스트가
> 넘친다. **0-A/0-B/0-C 의 스크립트 산출물(인덱스·대조 결과)을 1차 입력**으로 쓰고, 원문은
> 검증이 필요한 항목에 한해 해당 섹션만 Grep/부분 Read 한다 (§1-1·§1-4 의 반영 확인도 grep 기반이다).
1. `state/lessons_index.json` (0-A 단계 생성) — 1차 입력
2. `state/lessons.md` — 원문은 인덱스 항목의 컨텍스트 확인이 필요할 때 해당 섹션만
3. `config/policy.json` — 점검 대상 키(`entry_filters`, `risk`, `weekly_recovery_plan`, `reward_risk_management`, `price_data_quality`, `lessons_logging`, `codex_automation`, `context_budget`)만 부분 조회. 변경 이력 전문은 `docs/policy_changelog.md`(grep 용)
4. `prompts/*.md` — **전체 읽기 금지.** §1-1(룰 반영)·§1-4(일관성)는 `check_lessons_applied.py` 결과 + grep 으로 확인하고, 패치가 필요한 prompt 의 해당 섹션만 부분 Read
5. `reports/YYYY-Www-archive.md` — 가장 최근 주차 archive (지난 주 25개 리포트 응축)
6. `config/weekly_plan.json` — 다음 주 thesis (일요일 18시 routine 이 생성한 결과)
7. `reports/YYYY-MM-DD-saturday-review.md`·`YYYY-MM-DD-sunday-strategy.md` — 이번 주말 routine 산출물

## 1. 점검 항목 (체크리스트)

### 1-1. lessons.md "다음 적용 룰" 반영 추적
lessons.md 의 각 항목에서 "**다음 적용 룰**" 또는 "**다음 진입/점검 시 반영할 룰**" 줄을 모두 추출한다.
각 룰에 대해:
- 해당 룰이 `config/policy.json` 또는 `prompts/*.md` 에 텍스트로 존재하는지 grep 으로 확인
- 존재하지 않으면 "**미반영**" 으로 분류
- 일부 표현으로 존재하면 "**부분 반영**" 으로 분류

### 1-2. 반복 누적 카운트
"누적 패턴 카운터" 섹션에서 카운트 ≥ 3 인 분류(매크로/섹터/개별/가정오류/루틴 오차) 가 있으면:
- 어떤 patch 가 필요한지 (예: 섹터 차단 리스트 추가, 매크로 변수 가중치 조정)
- 자동 적용 가능한지 / 사용자 승인이 필요한지 분리

### 1-2-b. 룰 손익 채점 (rule_attribution — v2.11)
`state/rule_attribution.json`(없으면 `python scripts/rule_attribution.py` 실행)의 `by_rule` 를 점검한다:
- **realized_pnl_sum 이 2주 연속 음(-)이거나 post_exit_t5_forgone_sum 이 큰 양수(조기청산 비용)인 청산 룰은 패치 후보로 자동 상정**한다(임계·배수·조건 조정안 제시).
- `blocked_day_rate_pct` 가 40% 이상이면 차단 룰 과잉(래칫) 신호 — `lessons_rule_sunset` 만료 대상·완화 후보를 식별한다.
- lessons 발 즉석 제한 룰의 expiry(`policy.lessons_rule_sunset` 기본 5거래일) 도래 여부를 점검해 만료/승격을 분류한다.

### 1-3. policy 미사용 필드 점검
`policy.json` 에 정의됐지만 어느 prompt/script 에서도 참조하지 않는 필드를 찾는다 (dead config).
- 삭제 후보 / 활성화 후보 중 분류

### 1-4. prompt 간 일관성
같은 룰(예: trend filter -7%)이 여러 prompt 에 분산돼 있을 때 표현이 일치하는지 확인.
- 불일치 → 어느 prompt 가 진실의 원천(source of truth)인지 명시
- **신뢰도 출처 규칙 일관성 점검**: 00/06/09/12/15/18·주말 prompt 가 모두 "`market_snapshot` 의 `confidence` 를 1순위로 사용하고, 레거시 'fetch 차단/403/data confidence=low/신규 진입 보류' 서술을 이월하지 않으며, stale≠low" 규칙을 담고 있는지 grep 으로 확인. 누락된 prompt 가 있으면 미반영 패치 후보로 등록한다.

### 1-5. 목표가 추정 레이어 채점·뉴스 키워드 보강 (estimate_scorecard — v1.4)
`state/estimate_scorecard.json`(0-C 단계 생성)을 점검한다:
- **추정 vs 실현**: 20td/60td 적중률이 2주 연속 하락하거나 `median_realized_minus_expected` 절대값이
  5%p 를 넘으면 추정식 패치 후보로 상정한다. 단 **모델 파라미터(틸트·게이트·전이계수·가산점 테이블)
  변경은 백테스트 재실행(backtest_target_model / backtest_sector_global) 근거 필수** — 주간 노이즈로
  보정하지 않는다(목표가 인플레 재발 방지).
- **뉴스 키워드 보강 (검토 의무)**: `news_loop.unclassified_samples` 를 훑어 주가 관련 실질 뉴스가
  버려지고 있으면 ①출처 URL+게재일 확인 후 `config/news_impact.json` manual_news 승격 또는
  ②`config/news_keywords.json` 키워드 추가. **오분류(방향 반대)** 발견 시 exclude 키워드 추가
  ('관세 환급'·'Exempts Autos' 패턴). `silent_types` 는 unclassified 와 대조해 구멍/뉴스부재를 구분.
- **estimate_gate 손익 채점 (v2.12)**: `gate_cost` 를 점검한다 — 게이트가 차단한 종목의
  이후 20거래일 실현 수익 중앙값 ≥ +3% 또는 양(+)수익 비율 ≥ 60%(n≥5)면 `alpha_block_alert` —
  **게이트가 알파를 차단 중**이므로 임계(block_if_expected_return_below_pct) 완화를 패치 후보로
  상정한다(레포 교훈: 차단 룰 래칫이 강세장 미배치의 주범). 반대로 차단 종목이 부진하면 게이트
  유효 — 현행 유지.
- 보강·승격 내역은 lessons.md 에 '루틴' 분류로 1줄 기록한다(키워드 레지스트리 변경 이력 추적).

### 1-6. lessons.md 응축 (콘텍스트 예산 — `policy.context_budget`)
이번 리뷰에서 **codify 확정**(policy/prompts/CI 반영 완료 + 반영 위치 확인)된 lessons 항목은:
- 전문(원문 그대로)을 `state/lessons_archive.md` 에 append 하고,
- lessons.md 본문을 "분류·요약 1~2줄·✅ codify 반영 위치·전문 이관 표기" 4줄로 교체한다.
- **불변 보존**: `### ` 헤딩 원문, `- 분류:`/`- 원인 분류:` 라인, 누적 패턴 카운터, 미반영·진행 중(in-progress) 항목 전체. 응축 후 `python scripts/build_lessons_index.py` 를 재실행해 entries 수·카운터가 변하지 않았는지 확인한다.

### 1-7. 선제 추론 루프 채점·자격 심사 (inference_scorecard — Phase 1→2)
`state/inference_scorecard.json`(0-D 생성)을 점검한다(자기보완 루프의 estimate 채점 §1-5 와 대칭):
- **적중률·손익**: `by_confidence_band.high` 의 적중률·결합손익·PF 를 본다. high 구간이 동전던지기(적중률 ≈50%) 수준이거나 결합 expectancy<0 면 **선제 액션 권한 동결 유지**(공격 개방 보류).
- **Tier 2(공격) 개방 게이트**: paper(그림자) probe 의 **실현 expectancy>0 AND profit_factor>1** 이 표본 ≥min_samples 로 충족되면 → `policy.proactive_inference.action_ladder.tier2_probe.enabled=true` 를 **사용자 승인 필요 패치**로 상정(자동 적용 금지 — 실자본 매매 권한 변경). 미달이면 현행(paper-only) 유지.
- **체크리스트 위생**: `miss_factors` 가 `inference_checklist.md` 에 반영됐는지, `checklist_sunset_trading_days`(5) 만료 항목이 정리됐는지 확인. 검증 안 된 즉석 선제 룰의 영구 적체 금지.
- **기회비용**: `opportunity_cost.verdict` 가 '미배치로 놓친 수익 누적'이면 진입 적극성(entry_filters·사이징) 완화 후보로 §1-2-b 와 함께 검토(단 risk_off 미배치는 감점 면제 — 과잉교정 금지).
- **예측 품질**: 원장에 모호 예측(검증 가능 수치·horizon 누락 = `falsifiable_rule` 위반)이 보이면 해당 슬롯 프롬프트 보강 후보로 등록(sandbagging 차단).

## 2. 산출물 1: reports/YYYY-MM-DD-policy-review.md

```markdown
# 정책·프롬프트 패치 리뷰 — YYYY-MM-DD (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: YYYY-MM-DD 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: N
- 신규 추출 룰 (이번 주): N
- 반영 완료: N / 부분 반영: N / 미반영: N
- 반복 누적 카운트 ≥ 3: N건
- 자동 적용 권장 패치: N건 / 사용자 승인 필요: N건

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 (YYYY-MM-DD) | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| ... | ... | policy.json §entry_filters or prompts/0900_pre_market.md | 반영 / 부분 / 미반영 |

## 2. 반복 누적 카운트 ≥ 3 항목
### [분류명] — N건
- 누적 라인 요약:
- 권장 패치:
- 적용 방식: 자동 / 승인 필요
- 근거 lessons 라인:

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검
(estimate_scorecard.json 의 report_section_md 를 그대로 붙이고, 아래를 추가)
- 키워드 보강/승격 실행 내역: N건 (없으면 '없음')
- 추정식 패치 후보: (백테스트 근거 필요 여부 명시)

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — [짧은 제목]
- **대상**: `config/policy.json` §[field path] 또는 `prompts/[file].md` §[section]
- **현재**: (현재 정의)
- **변경 후 제안**:
```diff
- (현재 라인)
+ (제안 라인)
```
- **근거 lessons 라인**: [date / category]
- **자동 적용 가능 여부**: 가능 / 사용자 승인 필요
- **부작용 점검**: (다른 prompt·script 에 미치는 영향 1줄)

## 4. policy.json dead config (참조 없음)
- `policy.json §...` — 어떤 prompt/script 도 참조하지 않음. 삭제 또는 활성화 결정 필요.

## 5. 다음 주 routine 적용 우선순위
- (자동 적용 즉시 반영 가능 항목)
- (사용자 승인 후 다음 주 적용 항목)
- (다음 archive 까지 관찰만 할 항목)

## 6. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: ...
- 검토만 권장 N건: ...
- 자동 적용 완료 N건: ...
```

## 3. 산출물 2: 자동 적용 가능 패치는 즉시 반영
"자동 적용 권장" 으로 분류된 패치 중 다음 조건을 모두 만족하는 항목은 routine 이 직접 commit 한다:
- 기존 필드 값의 미세 조정 (예: threshold -7 → -8)
- 새 필드 추가 (기본값이 보수적인 방향)
- prompt 의 명문화 문구 추가 (기존 동작과 모순 없음)

다음은 **반드시 사용자 승인 후** 반영:
- 신규 종목·섹터 차단 리스트
- 손익 분기·비중 정책의 부호 변경
- routine 추가·삭제

## 4. 상태 영속화
```
git add config/ prompts/ state/ reports/
git -c user.name="kospi-autoflow-bot" -c user.email="hjlee8090@gmail.com" \
    commit -m "policy-review: YYYY-MM-DD 정책·프롬프트 패치 리뷰" || true
git push origin HEAD:main || git push origin HEAD:master
```

커밋 메시지 프리픽스 `policy-review:` 는 모바일 알림 발송 트리거다.

## 5. 사용자 요약 (카톡 알림 본문 5줄 이내)
- 이번 주 lessons 신규 룰: N개
- 자동 반영: N건 / 승인 대기: N건
- 즉시 결정 필요 1순위: ...
- 다음 archive 에서 다시 확인할 항목: ...
