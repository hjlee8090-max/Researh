# 정책·프롬프트 패치 리뷰 — 2026-07-19 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-07-19 20:00 KST

## ⚠️ 운영 알림 — 지난주 routine 미발화

`audit_pipeline.py` 가 "슬롯 산출물 누락(지난 7일): **2026-07-12: sunday-strategy, policy-review** — 루틴 미발화 의심"을 WARN 으로 표면화했다. `reports/` 에도 2026-07-12 일자 산출물이 전혀 없다(직전 policy-review 는 07-05, 이번이 07-19 — 2주 공백). 이번 리뷰가 지난주 몫까지 소급 처리했으나, **디스패치 자체가 실패**했을 가능성이 있어 `claude.ai/code/routines` 등록 상태(cron/스케줄) 확인이 필요하다 — policy 내용 문제가 아니라 실행 인프라 문제.

## 한눈에 보기
- lessons 총 항목 수: 57 (`build_lessons_index.py`, 07-05 대비 +21 — 2주치 누적)
- 신규 추출 룰 (이번 리뷰 대상 기간, 07-06~07-19): `check_lessons_applied.py` hard=1(패치 완료, 아래 참조)·soft=0
- 반영 완료(이번 리뷰): 1건(신규 코드화) / 부분 반영: 0건 / 관찰 지속: 다수(§2 참조)
- 반복 누적 카운트 ≥ 3: 3건(매크로 5·섹터 7·선제추론오차 13 — 선제추론오차가 07-05 3건→13건으로 급증, §2 참조)
- 자동 적용 완료: 3건(index_snapshot_confirmation 게이트·news_keywords 보강·self_audit disposition) / 사용자 승인 필요: 1건(추정식 파라미터, 백테스트 필요) / 관찰 지속: 3건(dead config·rule_attribution·ratchet shadow)

**전체 판단**: 이번 2주는 자산 -3.195%·KOSPI 대비 +2.19%p 방어(계좌 방어 우위 유지)했으나, 07-13(-8.95%)·07-16(-6.37%) 두 차례 지수 쇼크로 선제추론오차가 3→13건 급증하고 신규 왕복은 1건(07-14 하나금융 목표익절 +33,440)뿐이었다. `self_audit_findings.json` 의 두 finding(`whipsaw-high`·`deployment-below-band`)이 무처분 상태로 이번 주 overdue 게이트(2주)에 도달해 있어 **이번 리뷰의 1차 의무**로 처분을 기입했다(§0). policy v2.22 이후 신규 왕복 0건(직전 감사 기준)이므로 **전략 파라미터 변경은 동결**하고, 이번 패치는 게이트 강화·키워드 보강·명문화로 한정했다(§3).

---

## 0. 주간 자기감사 의무 인용 + findings 처분

`reports/2026-07-19-self-audit.md` (17:00 KST 산출) 인용:

| 항목 | 상태 |
|---|---|
| A. 원장 정합성 | ✅ 일치 |
| B. 계좌 성과 | 왕복 12건 · 승률 33.3% · PF 0.57 · 순실현 -188,494원 |
| C. vs KOSPI (2026-05-20~) | 계좌 -3.195% vs KOSPI -5.39% → 격차 **+2.19%p 방어** |
| D. 스톱 휩쏘 | 손실 스톱 7건 중 t+5 채점 7건 · 휩쏘 5건(71.4%) · 일실 합계 +222,731원 |
| E. 게이트 위반 | 총 0건 |
| F. 패치 vs 검증 | policy v2.22(직전 감사와 동일) · 신규 왕복 0건 — **패치 동결 원칙 유지 확인** |
| G. 배치 | 주식 36.6%(tier bull, 목표 65~80%) · heat 잔여 4,234원(예산 363,020원의 1.2%) |
| H. 오버레이 백테스트(07-08 as_of) | 판정 혼재 — 4개 설정 중 3개서 오버레이가 가치 파괴(주범 트레일링) |

### 처분 (state/self_audit_findings.json 기입 완료)

| id | 경과 | 처분 |
|---|---|---|
| `whipsaw-high` | 2주째 overdue | **observe** — v2.20 breakeven_ratchet shadow·v2.22 index_shock_stop_deferral 이 이미 배치돼 검증 중이나 promotion_criteria 미달(breach 확정 1/3건). backtest_exit_overlay(07-08) 결론 불변. 07-06 패치 이후 신규 왕복 0건 → 패치 동결 원칙상 전략 파라미터 변경 대신 관측 지속. 재심 트리거: ratchet breach 확정 3건 또는 whipsaw율 추가 악화. |
| `deployment-below-band` | 2주째 overdue | **observe** — 히트예산 소진(잔여 4,234원)이 만성 미배치의 직접 병목(07-04 saturday_review 진단과 동일 구조). breakeven_ratchet(shadow)이 구조적 해법이나 미승격. 07-13 지수쇼크 이후 방어적 caution 도 배치 억제 요인 — 과잉교정(추격 진입) 방지 위해 강제 배치 패치는 보류. 재심 트리거: ratchet shadow 승격(§1-8) 또는 heat 여유 회복. |

처분 후 `python scripts/self_audit.py --followup-only` 재실행 결과: **`open=2 overdue=0`** — 이번 주 무처분 FAIL 없음. (참고: 과거 self-audit 리포트에서 동일 finding 의 "N주째" 표시가 회차마다 들쭉날쭉했다(07-14 "6주째"→07-15 "2주째") — `self_audit.py` 의 `weeks_seen` 재계산 로직 자체는 이번 검증에서 정상 동작 확인, 과거 표시 불일치는 낮은 우선순위 조사 후보로만 기록.)

**패치 동결 규칙 적용 확인**: `F. 패치 vs 검증`이 "버전 증가 없음 + 신규 왕복 0건"으로, 엄밀한 동결 트리거(버전 증가+왕복 0)에는 해당하지 않으나 실질은 이미 13일째 무패치·무검증 상태다. 이번 리뷰의 패치를 **버그 수정·게이트 강화·키워드 보강**으로 한정한 이유.

---

## 1. lessons → policy/prompt 반영 매트릭스 (하드 미반영 우선)

`check_lessons_applied.py` 결과: 실행 전 `open_items_hard=1`(아래), 패치 후 재실행 결과 **`hard=0`**.

| lessons 항목 (2026-07-16) | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 09/12/15시가 KOSPI -6.37% 실제 크래시를 '스냅샷 지연 미확정'으로 오판, 방어주 breadth 로만 방향 판정 | 대형 지수 스냅샷 이동(±3%+)은 stale 자동 기각 말고 웹 교차 확정(이벤트일 필수) | `policy.price_data_quality.web_verify_guard.index_snapshot_confirmation`(신설 v2.23) + `prompts/0900_pre_market.md`·`1200_midday.md`·`1500_close.md` | ✅ **반영(이번 리뷰, v2.23)** |
| 07-16 3-miss(개장갭·09시·15시 KOSPI 종가밴드 모두 miss — 매파 정책 확정=하방 증폭 과소평가) | 이벤트일 종가밴드 하방 편중 반영 | `state/inference_checklist.md`(build_inference_checklist.py 가 miss_factors 로 자동 응축, `checklist_sunset_trading_days=5` 회전) | ✅ **반영(비영구 채널)** — 자기보완 체크리스트가 이미 동일 요인을 07-16/07-17 항목으로 담고 있음(라인 34~36). 이 요인이 **3회 이상 반복**되면 다음 리뷰에서 영구 prompt 명문화로 승격 검토(현재 1회 관측 계열). |

이전 리뷰(07-05) 후보 잔존 확인:

| 후보 | 07-05 결정 | 이번 확인 |
|---|---|---|
| 후보 1(금요일 ORANGE 사전청산) | 승인 필요, 미결 | 07-11(금)·07-18(금) 보유 종목 ORANGE 단계 진입 없음(관측 불가) — 승인 대기 계속 |
| 후보 2(confidence=low 방향일치 예외) | 관찰 지속 | 변동 없음 |
| 후보 4(blocked_day_rate 계측 재가동) | 승인 필요, 미결 | **`rule_attribution.json.blocked_day` 여전히 6/3·6/10 2건 고정, 2주 추가 경과에도 변화 없음** — 계측 배선이 실제로 재가동되지 않았음을 재확인(§2-a) |
| 후보 5(뉴스 co-occurrence 매칭) | 승인 필요, 미결 | 변동 없음 — 이번 리뷰는 별도의 단순 키워드 추가(피크아웃, §2-c)만 자동 반영 |
| dead config 3종 | 승인 필요, 미결 | **미해결 재확인**(§4) |

---

## 2. 반복 누적 카운트 ≥ 3 항목

### [선제추론오차] — 13건 (07-05 대비 3→13건, 이번 기간 최대 반복)
- 누적: 07-01~07-14 사이 8개 항목, 이 중 07-13·07-16 지수 쇼크(각 -8.95%·-6.37%) 전후로 6건 집중(급락/반등 폭 반복 과소평가, "삼전닉스" 방향 오판 포함).
- 권장 패치: (a) 지수 스냅샷 지연 오판 → **이번 리뷰에서 codify 완료(§1)**. (b) 급락/반등 폭 과소평가 패턴 자체는 `inference_checklist.md` 가 매주 회전 응축 중 — 영구 규칙화는 반복이 더 누적된 뒤(3회+) 판단.
- 적용 방식: (a) 자동 적용 완료. (b) 관찰 지속(자기보완 루프 정상 작동 확인).

### [섹터 오차] — 7건 (07-05 대비 5→7건)
- 누적: LS ELECTRIC 07-06·07-09(로테이션 아웃 손절), 삼성SDI 07-09(배터리 소외 손절) 신규 3건 추가.
- 권장 패치: 전력기기·배터리→반도체 로테이션은 `sector_rotation_reentry`(v2.8)가 이미 커버하는 구조(반도체 강세 국면의 비반도체 소외는 반대 방향 로테이션으로 자동 해제 대상) — **신규 patch 불필요, 기존 메커니즘이 정상 작동 확인**.
- 적용 방식: 해당 없음(관찰 유지).

### [매크로 오차] — 5건 (변동 없음)
- 권장 패치: 없음 — 관찰 유지.

---

## 2-a. 룰 손익 채점 (rule_attribution)

| 룰 | n | realized_pnl_sum | t5_forgone | 판정 |
|---|---|---|---|---|
| SELL_RESIDUAL_CHANDELIER_STOP (LS 07-09) | 1 | -41,843 | +1,348 | 관찰 (t5 소폭 양수 = 노이즈 수준, whipsaw 아님) |
| SELL_SHOCK_DEFERRAL_STOP (삼성SDI 07-09) | 1 | -102,163 | +34,586 | 관찰 (index_shock_stop_deferral 정상 발동 후 청산 — t5 forgone 존재하나 완전 회피 대비 완화됨) |
| SELL_TRAILING_STOP (LS 07-06 부분익절) | 1 | -12,858 | -33,137 | ✅ 유효 (t5 음수=청산 후 추가 하락, give-back 관리 정당) |
| SELL_TARGET_TAKE_PROFIT (하나금융 07-14) | 1 | +33,440 | 0 | ✅ 유효 (목표 익절 성공) |
| (기타 5건 — TRAILING_STOP·SELL_ORANGE_STOP·SELL_RED_STOP·SELL_GIVE_BACK_STOP·SELL) | 각 1~2 | 07-05 리뷰와 동일 | 동일 | 신규 청산 없음 — 07-05 리뷰 관찰 유지 |

**중요 관찰**: `blocked_day_rate_pct=100%`(2/2일, 6/3·6/10) — **07-05 리뷰에서 지목한 후보4(계측 배선 미가동)가 2주 경과에도 변화 없이 재확인**됐다. `candidates_checked` 필드를 매 OPEN_CHECK 마다 기록하도록 명문화하는 패치는 여전히 사용자 승인 대기 — 스키마 영향 검토가 필요해 이번 리뷰에서도 자동 적용하지 않음(§3 후보 A로 재상정).

---

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)

- 기준: 2026-07-19T20:07:31+09:00 · 추정 로그 27일 / 채점 표본 335건
- 5td: 적중률 43% · 기대 +10.2% vs 실현 -4.2% · 중앙오차 -10.4%p (n=257)
- 20td: 적중률 49% · 기대 +5.8% vs 실현 -20.4% · 중앙오차 -19.4%p (n=57, 최초 채점 가능 표본)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 25건 · fwd20 중앙값 -21.9% · 양수율 0% → **게이트 유효**(차단 종목이 평균적으로 부진, `alpha_block_alert` 미발동 — 현행 유지)

- 뉴스 피드: 분류 126건 / 미분류 1340건 / 해외 38건
- 무음 유형(미매칭): `supply_glut_or_price_drop`

**키워드 보강/승격 실행 내역**: **1건** — `config/news_keywords.json` v1.1, `supply_glut_or_price_drop.any` 에 **"피크아웃"** 추가. 근거: `unclassified_samples` 중 "SK하이닉스 ADR 이틀 새 21% 급락…고개 드는 반도체 '피크아웃' 우려"(2026-07-17)·"SK하이닉스 ADR 이틀째 급락…美·이란 갈등 속 AI 우려에 8%↓" 등이 반도체 사이클 부정 뉴스임에도 기존 키워드("공급과잉"·"가격하락" 등 펀더멘털 어휘)에 매칭되지 않아 27일간 이 유형이 0건으로 silent 상태였다. 매칭 로직 변경 없이 배열에 항목 하나만 추가(저위험·자동 적용). "LG엔솔, 구글 프로젝트 배터리 공급 소식에 상승"(07-16, `[특징주]` 태그) 등 나머지 unclassified 표본은 기존 기준(확정 실적/공급계약 아님)대로 미승격.

**추정식 패치 후보**: **1건(백테스트 필요, 승인 대기)** — 20td `median_realized_minus_expected` -19.4%p, 5td -10.4%p 모두 policy §1-5 임계(±5%p)를 크게 초과. 단 이 채점 기간(07-06~07-19)에 -8.95%·-6.37% 지수 쇼크가 2회 겹쳐 있어 **레짐 자체가 예외적으로 험했을 가능성**이 크고, 20td 표본(n=57)이 이번이 최초 채점(직전 비교 기준 없음)이라 "2주 연속 하락" 판정도 적용 불가하다. 정책 원칙("모델 파라미터 변경은 backtest_target_model 재실행 근거 필수")에 따라 **자동 패치하지 않고, 다음 리뷰에서 쇼크 재발 없이도 오차가 지속되는지 재확인 후 backtest_target_model 실행을 상정**한다.

---

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 A — blocked_day_rate 계측 재가동 (07-05 이관, 2주째 미해결)
- **대상**: `prompts/0900_pre_market.md`(OPEN_CHECK) + `scripts/rule_attribution.py`
- **현재**: `candidates_checked` 필드가 6/3·6/10 두 건에만 존재, 이후 어떤 슬롯도 기록하지 않아 `blocked_day_rate_pct=100%`가 6월 초 값에 박제.
- **자동 적용 가능 여부**: 사용자 승인 필요 — trade_log 스키마 매일 필드 추가가 `check_trade_log_gate.py` CI 계약과 상호작용할 수 있음.
- **부작용 점검**: 필드 optional 유지 확인 필요.

### 후보 B — dead config 3종 활성화/삭제 결정 (07-05 이관, 2주째 미해결)
- §4 참조. 스크립트 코드 변경(정책 필드를 실제로 읽도록 배선)이라 자동 적용 대상 아님.

### 후보 C — 지수 스냅샷 확인 게이트 (신규, 이번 리뷰 자동 적용 완료)
- 이미 반영 — §1·§4 참조. 부작용 점검: 이 게이트는 09/12/15시의 "보고" 규칙(웹 교차확인 후 명시)만 바꾸고 매매 로직(진입/청산 임계)은 변경하지 않음 — 게이트 강화 범주로 패치 동결 예외 적용 정당.

### 후보 D — 뉴스 키워드 "피크아웃" 추가 (신규, 이번 리뷰 자동 적용 완료)
- §2-c 참조. 부작용 점검: 반도체 외 종목 헤드라인에 "피크아웃"이 등장할 경우도 동일 유형으로 분류되나, 이 단어는 통상 사이클 정점 통과 우려 맥락에서만 쓰여 오탐 위험 낮음.

---

## 4. policy.json dead config (참조 없음) — 07-05 이관, 재확인

- **`price_data_quality.max_source_price_gap_pct`(=1.0)** — `fetch_market_data.py` 가 이 필드를 읽지 않고 `gap<=1.0`/`gap<=2.0` 을 하드코딩. 2주 경과 확인 결과 여전히 미배선.
- **`context_budget.retention.*`** — `compact_state.py` 의 `KEEP_COMMENTS`/`KEEP_WATCH_ITEMS`/`KEEP_HISTORY`/`KEEP_CHANGELOG` Python 상수가 policy.json 을 읽지 않음. 값은 우연히 일치하나 여전히 별도 상수.
- **`context_budget.audit_thresholds.*`** — `audit_pipeline.py` 의 `CONTEXT_BUDGET`/`PROMPT_INFO_BYTES`/`PROMPT_WARN_BYTES` 가 동일하게 하드코딩.

**패턴 재확인**: 3건 모두 2주 전과 동일 상태 — 활성화(스크립트가 policy.json 값을 읽도록 수정) 또는 삭제 여부에 대한 사용자 결정이 계속 대기 중이다. 낮은 긴급도지만 반복 재상정 자체가 "결정 없이 방치"의 신호이므로 이번에도 명시적으로 기록한다.

**콘텍스트 예산 초과 (신규 발견, audit_pipeline)**: `config/watchlist.json` 114,425B>100,000B · `config/policy.json` 121,308B>95,000B(이번 리뷰 패치로 +2KB, 기존에도 초과) · `state/lessons.md` 113,546B>60,000B · `prompts/0900_pre_market.md` 64,364B>60,000B(이번 리뷰 패치로 소폭 증가). `state/lessons.md`는 이번 리뷰에서 1건 codify 이관했으나(§1) 전체 초과분은 여전히 크다 — 대규모 이력 다이어트는 07-05 리뷰가 제안한 별도 패스로 남겨둔다. `policy.json`은 changelog 산문이 주 원인 후보이나 자동 압축기가 없어(§0 changelog 배열은 21시 sunday_archive routine의 `compact_state.py` 소관) 이번 리뷰에서는 처리하지 않는다.

---

## 5. 다음 주 routine 적용 우선순위
- **(자동 적용 완료)** index_snapshot_confirmation 게이트(policy v2.23 + 3개 프롬프트) · news_keywords "피크아웃" 추가 · self_audit findings 2건 disposition
- **(사용자 승인 후 다음 주 적용)** 후보 A(blocked_day 계측 재가동) · 후보 B(dead config 3종 활성화/삭제) · 07-05 이관 후보 1(금요일 ORANGE 사전청산)·5(뉴스 co-occurrence 매칭 로직)
- **(다음 archive 까지 관찰만)** whipsaw-high·deployment-below-band(ratchet shadow 승격 대기) · 추정식 패치(backtest_target_model 필요, 쇼크 레짐 영향 배제 후 재평가) · confidence=low 방향일치 예외
- **(운영 확인 필요, 최우선)** 2026-07-12 routine 미발화 원인 — claude.ai/code/routines 등록/스케줄 상태 점검

## 6. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: **2026-07-12 sunday-strategy·policy-review 미발화 원인 확인**(정책 문제 아닌 실행 인프라 문제 의심)
- 검토만 권장 3건: blocked_day 계측 재가동 · dead config 3종(활성화 vs 삭제) · 금요일 ORANGE 사전청산 규칙
- 자동 적용 완료 3건: 지수 스냅샷 확인 게이트(v2.23) · 뉴스 키워드 보강 · self_audit findings 처분(overdue 해소)
