# 정책·프롬프트 패치 리뷰 — 2026-07-12 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-07-12 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 48 (지난 리뷰 36 → +12, 대부분 W28 급락장 사후분석·토요일 리뷰 항목)
- 다음 적용 룰 추출: 36건 (`build_lessons_index.py` 정규식이 "다음 추천 시 반영할 교훈" 라벨을 못 잡던 버그를 이번 리뷰에서 수정 — 2건→36건, §4 참조)
- 반영 완료: 1건(이번 리뷰 신규 codify) / 부분 반영: 3건(§3 후보 C·D·G) / 미반영(승인 대기): 4건(§3 후보 C·D·E·F) / 관찰 지속: 다수(§2, §1-8)
- 반복 누적 카운트 ≥ 3: 3건 (매크로 오차 5·섹터 오차 7[+2]·선제추론오차 6, 지난주 대비 섹터+2)
- 자동 적용 완료: 2건(00시 갭 밴드 서술 확장 + `build_lessons_index.py` 정규식 버그 수정) / 사용자 승인 필요: 5건 / 처분(defer) 완료: 2건(self-audit findings)

**전체 판단**: §0-0 의무 인용 결과 `whipsaw-high`·`deployment-below-band` 두 finding 이 **4주 연속 무처분(overdue)** 상태였다 — 이번 리뷰가 disposition 체계 가동 후 첫 회차라 처음으로 기입한다(v2.22 자체가 지난주 리뷰 이후인 07-06 배포). 둘 다 근본 원인이 진행 중인 `risk.breakeven_ratchet`(v2.20) 그림자 검증으로 수렴하므로 `defer` 처분 + 명확한 재심사 트리거를 부여했다(§0-0 처분 섹션). 지난주(07-05) "자동 적용 가능, 미실행" 상태로 남아있던 00시 갭 밴드 서술 규칙을 이번 리뷰에서 실제로 적용했고, `check_lessons_applied.py`/`build_lessons_index.py` 조사 과정에서 정규식이 최근 우세해진 "다음 추천 시 반영할 교훈" 라벨을 놓쳐온 진짜 탐지 버그를 발견·수정했다(다음 적용 룰 추출 2→36건, 순수 탐지 정확도 개선·매매 로직 무영향).

---

## 0. self-audit findings 처분 (§0-0)

| id | 제목 | 경과 | 처분 |
|---|---|---|---|
| `whipsaw-high` | 스톱 휩쏘율 75.0% — 노이즈 저점 매도 반복 | 4주째 overdue | **defer** — 오버레이 백테스트(H) 혼재 판정(4구성 중 3개 가치파괴), `breakeven_ratchet` 그림자 검증 결론 대기. 재심사: 20거래일 도달(~07-29) 또는 breach 3건 중 먼저 오는 시점 |
| `deployment-below-band` | 주식비중 41.6% < 목표 하한 65% | 4주째 overdue | **defer** — 히트 예산 90.4% 소진(잔여 34,148원)이 병목, `breakeven_ratchet` 승격이 해방 경로. heat_budget_pct 자체 상향은 backtest 검증 전 동결 원칙(P2 연구) 준수 |

`python scripts/self_audit.py --followup-only` 재확인: `open=2 overdue=0` — 처분 반영 확인.

---

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 | 다음 적용/진입 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-07-04 (토요일 사후분석) 00시 갭 폭 저정확도 | 지정학 무관 전체 갭 예측 방향+밴드(±2~3%) 서술 | `prompts/0000_global.md` §0-C.4(신설) | ✅ **반영 완료(이번 리뷰)** — codify·archive 이관 |
| 2026-06-08 12:10 삼성전자 RED / 2026-07-05 후보1 | 금요일 ORANGE 잔여 포지션 50% 사전 청산 | `prompts/1500_close.md` (미착수) | ❌ **미반영** — 사용자 승인 필요(§3 후보 C, 5주째 대기) |
| 2026-06-05 12:00 삼성전자 ORANGE | confidence=low + 방향일치 시 체결 허용 예외 | `policy.price_data_quality` | ⚠️ **부분 반영** — 임계 재조정만 반영, 방향일치 예외 미구현(§3 후보 D) |
| 2026-06-14 rule_attribution blocked_day_rate | 매 OPEN_CHECK 후보 스크리닝을 `candidates_checked` 로 매일 기록 | `prompts/0900_pre_market.md`(미기록) | ❌ **미반영** — 3주 연속 동일 지적, blocked_day_rate_pct=100%가 6/3·6/10 단 2건짜리 박제값(§3 후보 E) |
| 2026-07-03 SK하이닉스 "목표가 상향" 뉴스 누락 | 뉴스 키워드 co-occurrence 매칭 | `scripts/fetch_news.py`/`config/news_keywords.json` | ❌ **미반영** — 이번 주 신규 사례 추가 발견(HD한국조선해양 "PC선 N척 계약"류, §3 후보 F) |
| 2026-07-11 (토요일) TRAILING_STOP 승자 조기절단 | 트레일 배수 확대 또는 ratchet 승격 검토 | `risk.breakeven_ratchet`(shadow, 심사 진행) | ⚠️ **부분 반영** — 구조적 해법(ratchet) 설계·그림자 검증 진행 중, 표본 미달로 승격 보류(§1-8) |
| 2026-07-04/07-11 히트 예산 편중(2회 연속) | ratchet 승격 재심사 의무 | `risk.breakeven_ratchet`(§1-8) | ⚠️ **부분 반영** — 이번 리뷰에서 재심사 완료(§1-8), 표본 미달로 관측 연장 |
| 2026-06-12 카톡 오발송 / 2026-06-11 지정학 3회 반복 | 각각 반영 완료(지난 리뷰) | `send_kakao`/`0000_global.md §0-C` | ✅ 반영 (기존 확정) |

`check_lessons_applied.py` 재확인 결과 `open_items_hard=1` 이 남지만, 원문 대조 결과 **오탐**이다 — preamble 블록의 서술문 "…2차 매도 사이드카·패닉셀(종가 -5.35%) **미반영**…"이 정책 미반영 자백이 아니라 "예측에 반영 못함"이라는 서술적 용법인데 `UNRESOLVED_MARKERS`가 그대로 매칭했다. 실제 액션 아이템 아님 — `check_lessons_applied.py`의 마커 매칭이 서술 문맥을 구분 못하는 낮은 우선순위 개선 후보로만 기록(§4).

---

## 2. 반복 누적 카운트 ≥ 3 항목

### [매크로 오차] — 5건 (변동 없음)
- 6/23 '검은 화요일' 이후 신규 매크로 이벤트 없음. `tiered_alerts.atr_adaptive`(v2.11)+`breakeven_ratchet`(v2.20 shadow)로 이미 구조적 대응 중.
- 권장 패치: 없음. 적용 방식: 해당 없음(관찰 유지).

### [섹터 오차] — 7건 (+2, LS ELECTRIC 7/6 give-back·7/9 residual chandelier — 전력기기 로테이션 아웃)
- 조선(3회)은 이미 `watchlist.json.avoid_sectors` 등록 완료. 전력기기(LS ELECTRIC)는 이번 주 2회로 아직 **3회 미달**(단일 티커, 조선 등록 기준은 3회+복수종목) — avoid_sectors 신규 등록은 시기상조.
- 권장 패치: 없음(관찰 지속). 다음 주 전력기기/배터리 섹터에서 3번째 손실 발생 시 avoid_sectors 등록 검토.
- 적용 방식: 해당 없음.

### [선제추론오차] — 6건 (변동 없음, 이번 주 신규 편입 없음)
- 07-04 항목(00시 갭 폭 저정확도 구조 진단)의 대책을 이번 리뷰에서 실행(§1 매트릭스 1행) — **codify 완료·archive 이관**.
- 적용 방식: 자동 적용 완료.

---

## 2-a. 룰 손익 채점 (rule_attribution — v2.11/v2.20)

| 룰 | n | realized_pnl_sum | t1_forgone | t5_forgone | 판정 |
|---|---|---|---|---|---|
| TRAILING_STOP | 2 | +192,878 | +232,186 | -105,814 | 관찰 — t1 큰 양수(조기청산), t5 반전(5일 뒤 하락) → lessons 07-11 "너무 이른 1차 청산" 재확인. 승자 조기절단은 파라미터가 아니라 ratchet 구조 문제로 이관(§1-8) |
| SELL_ORANGE_STOP | 2 | -76,619 | -31,602 | +30,398 | 변동 없음(3주째 동일 표본), 관찰 |
| SELL_RED_STOP | 1 | -48,959 | +9,738 | +24,738 | 변동 없음, 관찰 |
| SELL_GIVE_BACK_STOP | 1 | -13,598 | +20,798 | +164,798 | 변동 없음, §1-8 ratchet 승격 심사로 이관(개별 튜닝 보류) |
| SELL_STOP | 1 | +25,369 | — | — | ✅ 유효(6/23 보호손절) |
| SELL_TRAILING_STOP(신규) | 1 | -12,858 | -11,637 | 0(n=0) | 신규(7/6 LS ELECTRIC) — t1 음수(보호적), 표본 1건 관찰만 |
| SELL_RESIDUAL_CHANDELIER_STOP(신규) | 1 | -41,843 | +13,848 | 0(n=0) | 신규(7/9 LS ELECTRIC) — t5 미도래, 관찰만 |
| SELL_SHOCK_DEFERRAL_STOP(신규) | 1 | -102,163 | +34,086 | 0(n=0) | 신규(7/9 삼성SDI, index_shock_stop_deferral v2.22 실증 첫 사례) — 표본 1건, 2주 연속 판정 불가 |

**blocked_day_rate_pct = 100%(2/2일, 6/3·6/10) — 여전히 3주째 동일 박제값.** `candidates_checked` 필드가 어떤 prompt 에도 매일 기록 의무로 명문화되지 않아(§1 매트릭스 참조) 데이터 공급이 끊긴 채다. §3 후보 E로 3연속 이관.

---

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)
- 기준: 2026-07-12T20:27:18+09:00 · 추정 로그 22일 / 채점 표본 257건
- 5td: 적중률 43% · 기대 +10.4% vs 실현 -4.6% · 중앙오차 -12.0%p (n=197)
- 20td: 적중률 56% · 기대 +5.6% vs 실현 -14.5% · 중앙오차 -18.5%p (n=25, **처음으로 채점 가능**)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 11건 · fwd20 중앙값 -19.3% · 양수율 0% → **게이트 유효** — 차단 종목이 평균적으로 부진(차단 정당, alpha_block_alert 미발동)

- 뉴스 피드: 분류 135건 / 미분류 1352건 / 해외 40건
- 무음 유형(미매칭): supply_glut_or_price_drop
- 신규 키워드 갭 발견: HD한국조선해양 "OOO억원 PC선 N척 계약" 류 헤드라인이 `supply_contract_major`(공급계약/납품계약/수주계약 등)·`order_backlog_surprise`(수주잔고/대규모수주 등) 어느 쪽에도 매칭되지 않음 — "N척 계약" 형태의 조선업 특유 수주 표현이 키워드 리스트에 없음. §3 후보 F에 병합.

**키워드 보강/승격 실행 내역**: 0건(정책/config 변경 없음, 발견만 — 사용자 승인 필요).

**추정식 패치 후보**: 20td 중앙오차 -18.5%p 가 임계(±5%p)를 초과했으나 **이번이 20td 최초 채점(n=25, 이전 주 전부 표본 부족)이라 "2주 연속" 추세 판정 불가**. 단독 초과 자체는 트리거 조건이나, 정책 원칙("모델 파라미터 변경은 백테스트 재실행 근거 필수 — 주간 노이즈로 보정 금지")에 따라 **이번 주는 관찰로 유지하고 다음 주 20td 재채점으로 추세 확인 후 패치 여부 결정**. `backtest_target_model` 재실행은 다음 주 표본 확보 후 상정.

**estimate_gate 손익(v2.12)**: `alpha_block_alert` 미발동 — 현행 유지.

---

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 A(적용 완료) — 00시 일반 갭 예측 밴드 서술 확장
- **대상**: `prompts/0000_global.md` §0-C(신설 4항) + 리포트 템플릿 갭 예상 줄
- **변경**: 지정학 이슈 유무와 무관하게 모든 00시 갭 예측을 "방향+광역 밴드(±2~3%)"로 서술 의무화(기존 v2.5는 지정학 [진행형]에만 적용).
- **근거**: 2026-07-04 토요일 사후분석(00:00 슬롯 적중률 14.3%, n=14, 전 슬롯 최저) — 지난주(07-05) 리뷰에서 이미 자동 적용 후보로 확정됐으나 미실행 상태였던 것을 이번 리뷰에서 실제 적용.
- **자동 적용 여부**: 자동 적용 완료(순수 서술 규칙, 매매 로직 무영향).
- **부작용 점검**: 없음.

### 후보 B(적용 완료) — `build_lessons_index.py` 다음 적용 룰 탐지 정규식 버그 수정
- **대상**: `scripts/build_lessons_index.py`
- **현재였던 문제**: `NEXT_RULE_RE`가 라벨이 `**볼드**`로 감싸인 경우만 매칭했는데, 최근 lessons 항목의 지배적 표현("다음 추천 시 반영할 교훈:")은 라벨이 평문이고 내용만 볼드라 전혀 매칭되지 않았다 — `next_rules` 추출이 2건으로 심각하게 과소 집계되고 있었다(실제 33개 라인 존재).
- **변경**: 라벨 앞뒤 `**`를 선택적으로 허용하고 "다음 추천 시 반영할 교훈"·"다음 routine 반영할 룰" 패턴을 추가.
- **효과**: `state/lessons_index.json.next_rules` 2건 → 36건(entries=48·repeated_3plus 불변 확인).
- **자동 적용 여부**: 자동 적용 완료(탐지 스크립트 버그 수정, 매매 로직 무영향).
- **부작용 점검**: 없음 — 순수 리포팅 정확도 개선.

### 후보 C — 금요일 ORANGE 잔여 포지션 사전 청산 (2026-06-08 lessons, 5주째 미반영)
- **대상**: `prompts/1500_close.md`
- **현재**: ORANGE 액션은 원인별 조건부 50% 축소/트레일링 전환만 있고 요일(금요일) 특칙 없음.
- **변경 후 제안**:
```diff
+ 금요일 15시 마감 처리 시 보유 종목 중 ORANGE 단계(atr_adaptive 유효임계 기준)인 종목은
+ 주말 갭 리스크를 이유로 잔여 물량의 50%를 종가 기준 선제 청산한다(RED 도달 대기 금지).
+ 단, 매크로 단독 원인+thesis intact 로 판단된 경우 trailing 전환으로 대체 가능.
```
- **자동 적용 가능 여부**: 사용자 승인 필요 — 체결 트리거 신설.
- **부작용 점검**: 금요일 오후 반등 시 불필요 조기청산 가능성.

### 후보 D — confidence=low + 방향 일치 시 체결 허용 예외 (2026-06-05 lessons, 부분반영)
- **대상**: `config/policy.json §price_data_quality`
- **자동 적용 가능 여부**: 사용자 승인 필요 — 손절·청산 타이밍 규칙 실질 변경.
- **부작용 점검**: 저신뢰 구간 청산 앞당김 시 노이즈 체결 리스크.

### 후보 E — blocked_day_rate_pct 계측 재가동 (3주 연속 동일 지적, 06-14 패치의 데이터 공급 누락)
- **대상**: `prompts/0900_pre_market.md` + `scripts/rule_attribution.py`(구현 완료, 입력 데이터만 부재)
- **현재**: `blocked_day_rate_pct=100%`가 6/3·6/10 단 2건짜리 박제값 — 40% 래칫 경보가 살아있는 신호가 아님.
- **변경 후 제안**: 09/12/15시 OPEN_CHECK 로그에 그날 스크리닝 후보·BLOCKED/DEFERRED 여부를 `candidates_checked` 배열로 매일 기록.
- **자동 적용 가능 여부**: 사용자 승인 필요 — 데일리 trade_log 스키마 영향, `check_trade_log_gate.py` CI 계약과 상호작용 가능.
- **우선순위**: 3연속 이월 — 다음 리뷰까지 미승인 시 §5 우선순위 상향 권고.

### 후보 F — 뉴스 키워드 보강 2건 (co-occurrence + 조선 수주 표현)
- **대상**: `scripts/fetch_news.py`(`classify()`) 또는 `config/news_keywords.json`
- ①"목표가 X원 상향" co-occurrence 매칭(2026-07-03 SK하이닉스 3건, 지난 리뷰 이월)
- ②"OOO억원 PC선 N척 계약"류 조선업 수주 표현이 `supply_contract_major`/`order_backlog_surprise` 어느 쪽에도 미매칭(이번 주 신규 발견, HD한국조선해양 2026-07-10)
- **자동 적용 가능 여부**: 사용자 승인 필요 — 매칭 로직/키워드 변경, 오탐 검증 필요.

### 후보 G — TRAILING_STOP 승자 조기절단 (2026-07-11 lessons, 부분반영·구조 해법 진행 중)
- **대상**: `risk.breakeven_ratchet`(shadow) 승격 심사 또는 `trailing_stop` 배수 직접 조정
- **현재**: t1 forgone +232,186(조기청산 비용), t5 반전 -105,814(1차 청산이 옳았을 수도) — 신호가 엇갈려 파라미터를 바로 바꾸기엔 근거 약함.
- **판단**: §1-8에서 ratchet 승격 재심사 완료 — 표본 미달(7/10일·breach 0/3건)로 아직 결론 불가. **트레일 배수 직접 확대는 이번 리뷰에서 보류**(백테스트 재실행 근거 없이 파라미터 변경 금지 원칙).
- **자동 적용 가능 여부**: 해당 없음(관찰 지속, 다음 §1-8 재심사로 이관).

---

## 4. policy.json dead config (참조 없음) — 지난주 대비 변동 없음(재확인)
- `price_data_quality.max_source_price_gap_pct`(=1.0) — `fetch_market_data.py`가 `gap<=1.0`/`gap<=2.0` 하드코딩, 필드 미참조.
- `context_budget.retention.*` — `compact_state.py`의 `KEEP_COMMENTS` 등 Python 상수가 하드코딩, policy.json 미참조.
- `context_budget.audit_thresholds.*` — `audit_pipeline.py`의 `CONTEXT_BUDGET` 딕셔너리 하드코딩, policy.json 미참조.
- 패턴 동일: 정책 필드는 최신값 유지되나 스크립트가 별도 상수를 가짐 — 활성화(스크립트가 policy.json 읽도록 배선) 권장, 사용자 승인 후 처리 제안(스크립트 코드 변경).

**신규 발견(§1 매트릭스)**: `check_lessons_applied.py`의 `UNRESOLVED_MARKERS`가 "미반영"을 서술적 용법(예측이 실제를 "반영 못함")과 정책 자백("policy 미반영")을 구분 못해 이번 주 open_items_hard 오탐 1건 발생 — 낮은 우선순위 개선 후보(문맥 판별 로직 추가).

---

## 5. 콘텍스트 예산 점검 (§1-6)
`state/lessons.md` 97,428B(60,000B 초과) — 이번 리뷰에서 codify 확정된 1건(00시 갭 밴드)을 `state/lessons_archive.md`로 전문 이관·4줄 요약 교체. 나머지 항목은 명시적 ✅ codify 태그 없이 진행 중(§1-8 ratchet 심사 등 미종결)이라 보수적으로 유지 — 미종결 규칙을 지울 위험 방지.
`config/policy.json` 117,574B(95,000B 초과)·`config/watchlist.json` 111,767B(100,000B 초과)·`prompts/0900_pre_market.md` 63,603B(60,000B 초과) — `compact_state.py` 소관(일요일 21시 sunday_archive routine), 본 리뷰(20시)에서는 미실행. 단 lessons.md 07-11 항목이 "compact_state 미실행으로 5거래일 연속 파일 크기 초과 누적"을 별도 구조 문제로 지적했다 — 21시 routine 실행 여부를 다음 감사에서 확인 필요.
condense 후 `build_lessons_index.py` 재실행: entries=48·rules=36(정규식 수정 반영)·repeated_3plus 불변 확인.

---

## 6. 다음 주 routine 적용 우선순위
- **(자동 적용 완료)** 00시 갭 밴드 서술 확장 · `build_lessons_index.py` 정규식 버그 수정 · lessons.md 1건 condense
- **(사용자 승인 후 다음 주 적용, 우선순위순)** 후보 E(blocked_day 계측, 3연속 이월 — 최우선) → 후보 C(금요일 ORANGE 사전청산, 5주째) → 후보 F(뉴스 키워드 2건) → 후보 D(confidence=low 예외)
- **(다음 archive 까지 관찰만)** whipsaw-high·deployment-below-band(§0-0, ratchet 승격 재심사 대기) · 후보 G(TRAILING_STOP, 동일 사유) · 20td 추정 오차(다음 주 추세 확인 후 판단) · dead config 3종

## 7. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: **후보 E — blocked_day_rate_pct 계측 재가동**(3주 연속 동일 지적, 40% 래칫 경보가 6/3·6/10 박제 데이터에 근거해 죽은 신호로 방치 중)
- 검토만 권장 4건: 금요일 ORANGE 사전청산(5주째) · confidence=low 방향일치 예외 · 뉴스 키워드 co-occurrence 2건 · policy.json↔스크립트 배선 누락 3종
- 자동 적용 완료 2건: 00시 갭 밴드 서술 확장 · lessons 탐지 스크립트 버그 수정(다음 적용 룰 2→36건 커버리지 개선)
