# 정책·프롬프트 패치 리뷰 — 2026-07-05 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-07-05 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 36 (build_lessons_index.py 재계산 기준)
- 신규 추출 룰 (이번 주): 0 (신규 "다음 적용 룰" 없음 — `check_lessons_applied.py` open_items_hard/soft 모두 0건)
- 반영 완료: 2건(이번 리뷰 신규 codify 확정·condense) / 부분 반영: 3건 / 미반영: 2건
- 반복 누적 카운트 ≥ 3: 3건 (매크로 오차 5, 섹터 오차 5, 선제추론오차 3 — 지난주 대비 매크로 5(동일)·섹터 5(동일)·선제추론오차 신규 진입)
- 자동 적용 완료: 2건(lessons.md 응축) / 사용자 승인 필요: 4건 / 관찰 지속: 3건

**전체 판단**: 이번 주는 `open_items_hard=0`·`open_items_soft=0`(check_lessons_applied.py) — 명문화가 시급한 미반영 룰은 없다. 대신 조사 과정에서 **정책 필드와 실제 실행 스크립트 사이의 배선 누락(dead config)** 패턴이 여러 건 확인됐다 — policy.json 수치를 바꿔도 스크립트가 하드코딩값을 그대로 쓰는 구조. §4 참조.

---

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 | 다음 적용/진입 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-05-22 09:05 갭다운 폭 과소 추정 | KOSPI 절댓값≥7% 시 갭다운 +2%p 하향 버퍼 | `policy.entry_filters.overnight_gap_prediction_buffer` | ✅ 반영 |
| 2026-05-20 기아 RED 손절 | 구조적 악재 축소·5일 추세필터·tiered_alerts·lessons_logging·cross-check | `entry_filters.structural_bear_keywords`, `risk.tiered_alerts`, `lessons_logging` | ✅ 반영(v1.1~v2.5) |
| 2026-06-08 (정책) 강세장 미배치 | 진입필터·사이징 레짐연동 + universe screening | `block_if_cumulative_return_below_pct_by_tier` 등 (v2.7) | ✅ 반영 |
| 2026-06-08 (정책) 섹터 로테이션 재진입 | avoid_sectors 해제 엔진 | `sector_rotation_reentry` + `screen_universe.py` (v2.8) | ✅ 반영 |
| 2026-06-10 청산 룰 변동성 부정합 | ATR 연동 경보·2단 트레일링·재진입 규율·rule_attribution | `risk.tiered_alerts.mode=atr_adaptive`, `trailing_stop`, `rule_attribution.py` (v2.11) | ✅ 반영 |
| 2026-06-11 지정학 속보 3회 반복 | 자정 갭 예측 [진행형] 태그+불확실도 병기 | `prompts/0000_global.md §0-C` (v2.5) | ✅ 반영 — **이번 리뷰에서 condense·archive 이관** |
| 2026-06-12 카톡 오발송 3건 | detect_slot 제목줄 한정·폴백 제거·날짜가드·push가드 | `send_kakao`/`build_and_notify` | ✅ 반영 — **이번 리뷰에서 condense·archive 이관** |
| **2026-06-08 12:10 삼성전자 RED — 룰 1** | "금요일 장마감 전 ORANGE 잔여 포지션 전량 청산 의무화" | `prompts/1500_close.md` | ❌ **미반영** (§3 후보 1) |
| **2026-06-05 12:00 삼성전자 ORANGE — confidence 예외** | 2출처 방향 일치 시 gap>2%(low)여도 보수가 채택·체결 허용 검토 | `policy.price_data_quality` | ⚠️ **부분 반영** — confidence 임계 자체는 재조정(1%/2%)됐으나 방향-일치 예외는 미구현 (§3 후보 2) |
| **2026-05-28 KB금융 give-back — 여유폭 3%p** | ATH 다음날 give-back 여유 ≥3% 유지 | (없음 — 필드 자체 부재) | ⚠️ **부분 반영** — 개별 give-back 마진 조정 대신 `risk.breakeven_ratchet`(v2.20)가 동일 문제(이익 반납)를 구조적으로 해결하는 방향으로 대체 설계 중, 현재 shadow 채점 중(§1-8) |
| 2026-06-08 web_verify 출처 게재일 | source_date_verification + CI gate | `web_verify_guard` + `check_trade_log_gate.py` (v2.6) | ✅ 반영 |
| 2026-06-02/05-29/06-11 자정 지정학 역전 3건 | [진행형] 게이트 | `0000_global.md §0-C` (v2.5) | ✅ 반영 |
| 2026-06-14 rule_attribution blocked_day_rate 필드 | 청산 룰 차단일 비율 집계 | `rule_attribution.py.by_rule.blocked_day` | ✅ 반영(스크립트 존재) — 단 **입력 데이터가 끊김**(§2-b 참조) |

플레이스홀더 항목("YYYY-MM-DD HH:MM / 종목명(티커)…")은 실제 데이터가 아닌 작성 템플릿 — 닫는 HTML 주석(`-->`)만 있고 여는 주석이 없어 `build_lessons_index.py`가 매주 이를 "가정오류" 항목으로 오분류해왔다. 이번 리뷰에서 여는 `<!--` 태그를 보강했다(§4 참조, 카운터·entries 수 불변 확인).

---

## 2. 반복 누적 카운트 ≥ 3 항목

### [매크로 오차] — 5건 (변동 없음, 지난주와 동일)
- 누적: 기아 5/20 일부·KB금융 5/22·HD조선 5/28·삼성전자 6/5 Broadcom·삼성전자 6/8 RED·삼성전자 6/23 검은 화요일(6건 언급되나 카운터 정의상 5건 산입)
- 권장 패치: 신규 매크로 사건 없음(6/23 이후 신규 편입 없음) — `tiered_alerts.atr_adaptive`(v2.11) + `breakeven_ratchet`(v2.20 shadow)로 이미 구조적 대응 중. **이번 리뷰: 관찰 유지, 추가 패치 불필요**
- 적용 방식: 해당 없음

### [섹터 오차] — 5건 (변동 없음)
- 누적: 기아 5/20·KB금융 5/26·KB금융 5/27·HD조선 5/29·HD조선 6/1 — 조선 3회로 `avoid_sectors` 등록 완료, `sector_rotation_reentry`(v2.8) 해제 엔진 가동 중
- 권장 패치: 이미 codify 완료. **관찰 유지**
- 적용 방식: 해당 없음

### [선제추론오차] — 3건 (신규 반복임계 도달)
- 누적: 6/29 삼성 1,000조 발표 sell-the-news·6/30 미국 반도체 야간강세 종가 직선외삽·7/1 KOSPI 안착선 유지 예측 miss — 전부 "숫자 하나로 단정" 계열 오차
- 권장 패치: `state/inference_scorecard.json` 상 00:00 슬롯 적중률 14.3%(전 슬롯 최저)로 구조적 확인됨(2026-07-04 토요일 사후분석에서 이미 lessons 공식화). **v2.5 지정학 [진행형] 게이트를 일반 갭 예측(방향+±2~3% 밴드 서술)으로 확장** — §3 후보 3
- 적용 방식: prompt 명문화 문구 추가(00시 프롬프트) — **자동 적용 가능**(기존 동작과 모순 없음, 숫자 단정을 밴드 서술로 순화하는 것뿐)

---

## 2-a. 룰 손익 채점 (rule_attribution — v2.11/v2.14)

| 룰 | n | realized_pnl_sum | t1_forgone | t5_forgone | 판정 |
|---|---|---|---|---|---|
| TRAILING_STOP | 2 | +192,878 | +232,186 | -105,814 | ✅ 유효 (t5 음수=청산 후 추가 하락, 타이밍 적절) |
| SELL_ORANGE_STOP | 2 | -76,619 | -31,602 | +30,398 | 관찰 (t1 음수=손절 정당, t5 소폭 양수는 노이즈 수준) |
| SELL_RED_STOP | 1 | -48,959 | +9,738 | +24,738 | 관찰 (n=1, 3주 연속 동일 표본 — 아래 참고) |
| SELL_GIVE_BACK_STOP | 1 | -13,598 | +20,798 | +164,798 | ⚠️ t5 forgone 큰 양수 — **단, 아래 참고** |
| SELL_STOP (6/23 보호손절) | 1 | +25,369 | — | — | ✅ 유효 — '검은 화요일' 폭락서 이익 확정, tiered_alerts 실증 |

**중요 관찰**: TRAILING_STOP·SELL_ORANGE_STOP·SELL_RED_STOP·SELL_GIVE_BACK_STOP 의 n·금액이 **06-14/06-21/07-05 세 차례 리뷰에서 완전히 동일**하다 — 6/8 이후 이 유형의 신규 청산이 한 건도 발생하지 않았기 때문(round_trips 로그 확인, 최근 청산은 6/23 SELL_STOP 뿐). 즉 정책 §1-2-b의 "2주 연속 음(-)" 판정 기준은 **신규 데이터가 없어 적용 불가** — 06-14/06-21 리뷰가 두 차례 "표본 n=1, 다음 주 추가 관측 후 재심"으로 미룬 SELL_GIVE_BACK_STOP 패치는 3주째 표본이 그대로다. **패치 강행 대신 §1-8 breakeven_ratchet 그림자 승격 심사로 이관 판단**(동일 문제를 구조적으로 다루는 신규 메커니즘이 이미 그림자 검증 중이므로 개별 룰 튜닝보다 그쪽 결론을 기다리는 것이 합리적).

**blocked_day_rate_pct = 100%(2/2일, 6/3·6/10)** — 이 값도 3주째 불변이다. 원인 확인: `rule_attribution.py`의 `blocked_days()`는 trade_log 의 `candidates_checked` 필드를 스캔하는데, **이 필드는 전체 trade_log.jsonl 중 6/3·6/10 딱 2건에만 존재**하고 어떤 prompt 도 이를 매 OPEN_CHECK 마다 기록하도록 지시하지 않는다(grep 확인, `prompts/*.md` 전체에 `candidates_checked` 언급 0건). 즉 **40% 래칫 경보 자체가 살아있는 신호가 아니라 6월 초 이틀치 데이터에 박제된 값** — §3 후보 4.

---

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)

- 기준: 2026-07-05T20:03:31+09:00 · 추정 로그 17일 / 채점 표본 182건
- 5td: 적중률 55% · 기대 +7.2% vs 실현 -3.0% · 중앙오차 -9.3%p (n=120)
- 20td: 표본 부족(<5) — 채점 보류 (n=0)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 61건 — 표본 부족(<5) — 채점 보류

- 뉴스 피드: 분류 323건 / 미분류 1212건 / 해외 43건
- 무음 유형(미매칭): earnings_miss_or_guidance_cut, supply_glut_or_price_drop
- 검토 의무: unclassified 표본 → manual_news 승격 또는 키워드 보강 (estimate_scorecard.json 의 review_checklist)

**키워드 보강/승격 실행 내역**: 0건(정책 변경 없음). 다만 **구체적 키워드 갭 1건 확인**: SK하이닉스 관련 3건("목표가 '420만원' 상향" 계열) 헤드라인이 `analyst_target_upgrade` 에 매칭되지 않음 — `fetch_news.py`의 `classify()`는 정규화(공백 제거) 후 순수 부분문자열 매칭이라 "목표가"와 "상향" 사이에 구체 목표주가 숫자(`'420만원'`)가 끼어들면 실패한다. 단순 phrase 추가로 해결 불가(숫자가 가변) — **co-occurrence 매칭(제목 내 "목표가"+"상향" 별도 존재만 확인) 로직 보강이 필요**(§3 후보 5, 스크립트 변경 — 승인 권장). 삼성전자 "2분기 메모리 실적 사상 첫 110조" 등 나머지 unclassified 표본은 예상치·배경성 기사로 지난주와 동일 기준(확정 실적 아님) 미승격 유지. silent_types 2종은 unclassified 대조 결과 뉴스 부재 확인(키워드 구멍 아님).

**추정식 패치 후보**: 없음 — 5td 채점은 가능하나(n=120) 20td/60td 표본 부족으로 종합 결론 보류. 백테스트 근거 없이 보정 금지 원칙 준수.

**estimate_gate 손익(v2.12)**: `gate_cost.n_scored_20td=0` — 채점 보류. `alpha_block_alert` 미발동.

---

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — 금요일 ORANGE 잔여 포지션 사전 청산 (2026-06-08 lessons, 미반영)
- **대상**: `prompts/1500_close.md` (§ 마감 처리)
- **현재**: ORANGE 액션은 `risk.tiered_alerts.orange_action`(원인별 조건부 50% 축소/트레일링 전환)만 있고, 요일(금요일) 특칙은 없음. 6/5(금) ORANGE 잔여 1주가 주말을 넘겨 6/8(월) 갭다운으로 RED 청산된 사례가 재발 근거.
- **변경 후 제안**:
```diff
+ 금요일 15시 마감 처리 시 보유 종목 중 ORANGE 단계(atr_adaptive 유효임계 기준)인 종목은
+ 주말 갭 리스크를 이유로 잔여 물량의 50%를 종가 기준 선제 청산한다(RED 도달 대기 금지).
+ 단, 매크로 단독 원인+thesis intact 로 판단된 경우 trailing 전환으로 대체 가능.
```
- **근거 lessons 라인**: 2026-06-08 12:10 삼성전자 RED, 룰 1
- **자동 적용 가능 여부**: **사용자 승인 필요** — 기존 orange_action 로직(조건부 50%/트레일링)과 상호작용하며, 주말 보유 리스크 관리 정책의 실질적 변경(체결 트리거 추가)이라 승인 대상으로 분류
- **부작용 점검**: 금요일 오후 orange 종목이 이후 반등하는 경우(예: 6/19 사례처럼 오전 급등 후 되돌림) 불필요한 조기 청산 가능성 — 트레일링 대체 옵션과 병행 검토 필요

### 후보 2 — confidence=low + 방향 일치 시 체결 허용 예외 (2026-06-05 lessons, 부분반영)
- **대상**: `config/policy.json §price_data_quality`
- **현재**: `confidence_levels`(high≤1%, medium 1~2%, low>2%)는 재조정됐고 `medium_new_entry_rule`(v2.0)로 medium 진입 비대칭은 해소됐으나, **EXIT(orange 대응) 시 실제 confidence=low(2출처 gap>2%)이면서 두 출처 방향이 동일(둘 다 orange)**인 경우의 예외는 없음 — 여전히 EVAL/HOLD만 허용.
- **변경 후 제안**: 신중 검토 필요(청산 타이밍 지연 리스크 vs 오체결 리스크의 트레이드오프) — 구체 임계값 확정 전 사용자 결정 필요
- **근거 lessons 라인**: 2026-06-05 12:00 삼성전자 ORANGE
- **자동 적용 가능 여부**: **사용자 승인 필요** — 손절·청산 타이밍 규칙의 실질 변경
- **부작용 점검**: 저신뢰 구간에서 청산을 앞당기면 노이즈 체결(가짜 orange) 리스크 증가 — 두 조건(방향 일치 + 보수적 가격) 동시 충족 시로 좁혀야 함

### 후보 3 — 00시 일반 갭 예측에 방향+밴드 서술 의무화 (2026-07-04 토요일 사후분석, 신규 패턴 공식화)
- **대상**: `prompts/0000_global.md` (§0-C 확장)
- **현재**: [진행형] 지정학 이슈에 한해서만 ±1.5~2.5% 불확실도 병기 의무(v2.5). 일반 갭 예측(지정학 이슈 없어도)은 숫자 하나로 단정 — `KOSPI_open_gap` 적중률 20%(n=10), 00:00 슬롯 전체 적중률 14.3%(n=14, 채점 가능 슬롯 중 최저)로 확인.
```diff
- (v2.5) 지정학 [진행형] 이슈에서만 ±1.5~2.5% 불확실도 병기
+ (v2.5 확장) 지정학 여부와 무관하게 모든 00시 개장 갭 예측은 "방향 판단 + 광역 밴드(±2~3%)"로
+ 서술하고, 단일 숫자 단정을 금지한다.
```
- **근거 lessons 라인**: 2026-07-04 (토요일 사후분석) 00시 개장갭 폭 저정확도 패턴 공식화
- **자동 적용 가능 여부**: **자동 적용 가능** — 기존 v2.5 게이트의 적용 범위 확장이며 서술 방식만 순화(밴드 표기), 매매 로직·임계값 변경 없음
- **부작용 점검**: 없음 — 순수 서술 규칙

### 후보 4 — blocked_day_rate_pct 계측 재가동 (2026-06-14 패치의 데이터 공급 누락)
- **대상**: `prompts/0900_pre_market.md`(주 OPEN_CHECK) + `scripts/rule_attribution.py`
- **현재**: `rule_attribution.py`는 이미 `candidates_checked` 필드를 집계하도록 구현됐으나(06-14 리뷰 패치), 어떤 prompt 도 매 OPEN_CHECK 에 이 필드를 기록하라고 지시하지 않아 6/3·6/10 단 2건 이후 데이터가 끊겼다. 현재 표시되는 "blocked_day_rate_pct=100%" 는 살아있는 경보가 아니라 6월 초 이틀치 값이 고정된 것.
- **변경 후 제안**: 09시(및 12/15시 재확인) OPEN_CHECK 로그에 그날 스크리닝한 후보 리스트와 BLOCKED/DEFERRED 여부를 `candidates_checked` 배열로 매일 기록하도록 명문화
- **근거**: §2-a 관찰, `docs/policy_changelog.md` 06-14 패치 기록
- **자동 적용 가능 여부**: **사용자 승인 필요** — 데일리 trade_log 스키마에 필드를 매일 추가하는 것은 `check_trade_log_gate.py` CI 계약과 상호작용할 수 있어 스키마 영향 검토 후 반영 권장
- **부작용 점검**: 필드 누락 시 CI 실패 여부 확인 필요(현재는 optional 필드로 보임)

### 후보 5 — 뉴스 키워드 co-occurrence 매칭 보강 ("목표가 X원 상향" 계열 누락)
- **대상**: `scripts/fetch_news.py`(`classify()`) 또는 `config/news_keywords.json`
- **현재**: `analyst_target_upgrade` 매칭이 인접 부분문자열만 확인 — "목표가"·구체 수치·"상향"이 분리된 헤드라인(SK하이닉스 사례 3건)을 놓침.
- **변경 후 제안**: phrase 리스트 확장이 아니라 "제목에 '목표가'류 토큰과 '상향'류 토큰이 모두 존재하면 매칭"하는 co-occurrence 규칙 추가 검토
- **근거**: §2-c news_loop.unclassified_samples 3건(SK하이닉스, 2026-07-03)
- **자동 적용 가능 여부**: **사용자 승인 필요** — 스크립트 매칭 로직 변경(오탐 가능성 검증 필요)
- **부작용 점검**: co-occurrence 방식은 "상향" 단독 키워드보다 오탐률이 낮으나, "목표가 하향" 오분류 방지를 위해 기존 exclude 리스트(`하향`,`매도의견`) 그대로 유지 필요

---

## 4. policy.json dead config (참조 없음)

체계적 확인(leaf key grep, `entry_filters`/`risk`/`weekly_recovery_plan`/`reward_risk_management`/`price_data_quality`/`lessons_logging`/`codex_automation`/`context_budget` 대상) 결과, 다수는 상위 객체 전체가 참조되는 서술형 하위 필드(오탐)였다. **실제로 확인된 배선 누락 3건**:

- **`price_data_quality.max_source_price_gap_pct`(=1.0)** — `scripts/fetch_market_data.py`가 이 값을 읽지 않고 `gap<=1.0`/`gap<=2.0`을 직접 하드코딩(L267-269). 필드를 바꿔도 실제 confidence 판정에 영향 없음. **활성화 후보**(스크립트가 이 필드를 읽도록 배선) 또는 **삭제 후보**(하드코딩이 의도된 것이면 필드 제거).
- **`context_budget.retention.*`**(watchlist_comments_per_held_stock=12, weekly_plan_watch_items_max=15, portfolio_history_in_config=10, policy_changelog_in_config=5) — `scripts/compact_state.py`가 동일 값을 `KEEP_COMMENTS`/`KEEP_WATCH_ITEMS`/`KEEP_HISTORY`/`KEEP_CHANGELOG` **Python 상수로 하드코딩**, policy.json 을 읽지 않음. 현재는 우연히 값이 일치하나, 정책 필드를 바꿔도 실제 압축 동작은 안 바뀐다.
- **`context_budget.audit_thresholds.*`**(전 필드) — `scripts/audit_pipeline.py`의 `CONTEXT_BUDGET`/`PROMPT_INFO_BYTES`/`PROMPT_WARN_BYTES` 딕셔너리가 동일 값을 하드코딩(L804-812), policy.json 미참조.

**패턴 진단**: 세 사례 모두 "정책 필드는 최신값으로 유지되지만 실행 스크립트는 별도 상수를 갖는다"는 동일 구조 — policy.json 을 문서화 스펙으로만 쓰고 스크립트가 이를 실제로 로드하지 않는 배선 누락이 반복된다. **삭제보다 활성화 권장**(스크립트가 policy.json 값을 읽도록 수정하면 필드가 실질적 단일 진실 소스가 됨) — 단 스크립트 코드 변경이라 자동 적용 대상이 아니며 사용자 승인 후 다음 주 처리를 제안한다.

기타: lessons.md 신규 항목 작성 템플릿(플레이스홀더)이 닫는 HTML 주석만 있어 `build_lessons_index.py`가 매주 실제 데이터로 오분류해왔다 — 이번 리뷰에서 여는 `<!--` 태그를 추가해 원문 하이재닝은 막았으나, 스크립트 자체가 HTML 주석을 인식하지 않아 entries 카운트에는 영향 없음(36 유지, 확인됨). 스크립트에 HTML 주석 스트립 로직을 추가하는 것은 낮은 우선순위 개선 후보.

---

## 5. 콘텍스트 예산 점검 (§1-6)

`audit_pipeline.py` 실행 결과 핫패스 3개 파일이 예산 초과:
- `state/lessons.md` 72,837B → **이번 리뷰에서 2건 codify 확정 항목(2026-06-12 카톡 오발송, 2026-06-11 지정학 3회 반복)을 `state/lessons_archive.md` 로 전문 이관·4줄 요약으로 교체** → 70,873B (여전히 60,000B 초과). 나머지 항목(05/22~06/08 개별 거래 기록 다수)은 명시적 ✅ codify 태그가 없어 이번 리뷰에서는 보수적으로 유지 — 반영 확인 없이 응축하면 미반영 규칙을 지울 위험이 있어, 개별 항목별 반영 확인이 필요한 별도 "이력 다이어트" 패스를 다음 리뷰 후보로 제안.
- `config/policy.json` 106,639B, `portfolio.history` 24건(>20건) — `scripts/compact_state.py`(changelog·history 트림)의 소관이나, 이 스크립트는 정책상 **일요일 21시 sunday_archive routine**이 실행하는 것으로 지정돼 있어(§`context_budget.compactor`) 본 리뷰(20시)에서는 실행하지 않음. 21시 routine에서 처리될 것으로 확인.
- 응축 후 `build_lessons_index.py` 재실행 — entries=36, rules=2, repeated_3plus=[매크로 오차, 섹터 오차, 선제추론오차] **불변 확인** (요구사항 충족).

---

## 6. 다음 주 routine 적용 우선순위
- **(자동 적용 완료)** lessons.md 2건 응축·archive 이관, 템플릿 주석 태그 보강
- **(자동 적용 즉시 반영 가능, 미실행 — 다음 세션 처리 제안)** 후보 3 — 00시 갭 예측 밴드 서술 확장(v2.5 게이트 범위 확장, 순수 서술 규칙)
- **(사용자 승인 후 다음 주 적용)** 후보 1(금요일 ORANGE 사전청산) · 후보 4(blocked_day 계측 재가동) · 후보 5(뉴스 키워드 co-occurrence)
- **(다음 archive 까지 관찰만)** 후보 2(confidence=low 방향일치 예외) · SELL_GIVE_BACK_STOP 패치(§1-8 ratchet 승격 심사로 이관, 개별 조정 보류) · dead config 3종(활성화 여부 결정 대기)

## 7. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: **후보 1 — 금요일 ORANGE 잔여 포지션 사전 청산 규칙 신설 여부**(6/8 RED 손절 재발 방지, 주말 갭 리스크 관리)
- 검토만 권장 4건: confidence=low 방향일치 예외 · blocked_day 계측 재가동 · 뉴스 키워드 co-occurrence 매칭 · policy.json↔스크립트 배선 누락 3종(활성화 vs 삭제)
- 자동 적용 완료 1건: lessons.md 응축 2건(콘텍스트 예산 부분 개선, 여전히 초과 — §5)
