# 정책·프롬프트 패치 리뷰 — 2026-06-28 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-06-28 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 30 (지난 주 27 → +3 신규: 검은 화요일 매크로, ATH권 금요일 관찰, 트레일링 오인 루틴 오차)
- 신규 추출 룰 (이번 주): 2 (스크립트 추출; 이번 주 신규 lessons 룰 2건 별도 확인 — 트레일링 분리는 이미 v2.15 codify, ATH+금요일·폭락다음날 2건 미반영 → 자동 패치)
- 반영 완료: 2 / 부분 반영: 0 / 미반영 (이번 주 신규): 2 → **자동 패치 완료**
- 반복 누적 카운트 ≥ 3: 2건 (매크로 오차 5건, 섹터 오차 5건)
- 자동 적용 권장 패치: 4건 (이번 리뷰 적용 완료) / 사용자 승인 필요: 3건

---

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-05-22 09:05 / 갭다운 폭 과소 추정 | KOSPI 절댓값 ≥+7% 시 갭다운 예측 +2%p 하향 버퍼 | `policy.entry_filters.overnight_gap_prediction_buffer` + `prompts/0000_global.md §2-1` | ✅ 반영 |
| 2026-05-20 12:00 / 기아(000270) RED 손절 | structural_bear_keywords·5일 추세필터·tiered_alerts·lessons_logging·함정패턴 | `policy.entry_filters`, `risk.tiered_alerts`, `lessons_logging`, `prompts/1200_midday.md §2` | ✅ 반영(v1.1~v2.5) |
| 2026-06-18 18:00 / 트레일링 활성화≠부분익절 | 09/12/15시 활성화와 부분익절 분리 서술, 금지 문구 명시 | `prompts/1200_midday.md §2 v2.15`, `prompts/1500_close.md §2` | ✅ 반영(v2.15) |
| 2026-06-19 18:00 / ATH권+금요일 목표선 일시상회 | ATH·VKOSPI 고공·금요일 목표권 ±2% 시 종가 트리거 재확인 1줄 의무 | `prompts/1200_midday.md v2.16` | ✅ **이번 리뷰 자동 패치** |
| 2026-06-23 18:00 / 검은 화요일 — 폭락 다음날 교훈 | 전일 KOSPI −8% 이하 시 신규 진입 기본값=보류, 2거래일 안착 요구 | `prompts/0900_pre_market.md §1-4` | ✅ **이번 리뷰 자동 패치** |
| 2026-06-21~28 / 뉴스 키워드 리뷰 | analyst_target_upgrade "줄상향" 키워드 구멍 보강 | `config/news_keywords.json analyst_target_upgrade.any` | ✅ **이번 리뷰 자동 패치** |

---

## 2. 반복 누적 카운트 ≥ 3 항목

### [매크로 오차] — 5건 (+1 이번 주: 검은 화요일)
- 누적 라인: KB금융 5/22·HD조선 5/28·삼성전자 6/5 Broadcom shock·삼성전자 6/8 RED·**삼성전자 6/23 KOSPI −9.99% 서킷브레이커**
- 공통 구조: 반도체 보유 중 외부 매크로 충격(지수 대규모 폭락·PCE·실적 guidance) → 손절 가격 선 도달
- 권장 패치: **신규 교훈(3) — 폭락 다음날 진입 보류 룰** 이번 리뷰 자동 패치 완료. ATH권 보호손절 진입가 위 규칙은 현행 `trailing_stop` 운용에서 이미 구현 중(6/23 종가 310K 청산 시 실현이익 +25,369원으로 검증됨). 추가 룰 불필요 — **이번 리뷰: 폭락다음날 게이트 자동 패치 + 관찰 유지**
- 적용 방식: 자동 (패치 완료) + 관찰 지속
- 근거: lessons.md 매크로 오차 카운터 5건

### [섹터 오차] — 5건 (지난 주와 동일)
- 누적 라인: 기아 5/20·KB금융 5/26·KB금융 5/27·HD조선 5/29·HD조선 6/1 — 반도체 장세 소외 비주도섹터(금융·자동차·조선) 손실
- 권장 패치: 조선(HD한국조선해양·삼성중공업) **avoid_sectors 정식 등록** — 현재 w/list에서 avoid 플래그만 존재, candidates.json/policy의 공식 섹터 차단 리스트에 없음. 5거래일 −17.6%(6/23 폭락 포함) 추세 필터 자동 차단 중이나, **구조적 재진입 엔진(v2.8) 해제 조건이 충족되지 않은 상태에서 추세 필터 만료 시 재진입 위험** 존재.
- 적용 방식: **사용자 승인 필요** (섹터 차단 리스트 추가)
- 근거: lessons.md 섹터 오차 카운터 5건, 조선 섹터 avoid_sectors 마크 6/1 등록

---

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)

- 기준: 2026-06-28T20:03:26+09:00 · 추정 로그 12일 / 채점 표본 103건
- 5td: 표본 부족(<5) — 채점 보류 (n=0)
- 20td: 표본 부족(<5) — 채점 보류 (n=0)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 49건 — 표본 부족(<5) — 채점 보류

- 뉴스 피드: 분류 36건 / 미분류 925건 / 해외 58건
- 무음 유형(미매칭): earnings_miss_or_guidance_cut
- 검토 의무: unclassified 표본 → manual_news 승격 또는 키워드 보강 (estimate_scorecard.json 의 review_checklist)

**키워드 보강/승격 실행 내역**: 1건 — `analyst_target_upgrade.any` 에 "줄상향" 추가
- 근거: unclassified 표본 "SK하이닉스 목표주가 400만원대로 줄상향" — 부분일치(공백 제거) 방식에서 "목표주가400만원대로줄상향"이 "목표주가상향"을 포함하지 않아 미매칭. "줄상향" 추가로 "목표주가 X만원대로 줄상향" 형태 캡처.
- `earnings_miss_or_guidance_cut` silent type: unclassified 표본 대조 결과 **뉴스 부재** 확인 (Q2 실적발표 전 시즌, 키워드 구멍 아님).
- 이번 주 유의미 manual_news 승격 대상 없음(인사·ESG·채용 배경기사가 대부분).

**추정식 패치 후보**: 없음 — 모든 horizon 채점 보류(표본 n<5). 백테스트 근거 없이 보정 금지(목표가 인플레 재발 방지 원칙 준수).

**lessons.md 기록**: 2026-06-28 / 시스템 — 뉴스 키워드 리뷰 1줄 추가 완료.

---

## 2-b. 룰 손익 채점 (rule_attribution — v2.11)

`state/rule_attribution.json` 기준 (현행 6건 청산):

| 청산 룰 | n | 실현손익 | t5 일실(forgone) | 평균보유 | 진단 |
|---|---|---|---|---|---|
| TRAILING_STOP | 2 | **+192,878** | −105,814 | 1.5일 | ✅ 유효 (t5 음수=청산 후 하락, 익절 관리 정상) |
| SELL_GIVE_BACK_STOP | 1 | −13,598 | **+164,798** | 8.0일 | ⚠️ **패치 후보** — t5 일실 +164,798원(조기청산 비용 매우 큼) |
| SELL_ORANGE_STOP | 2 | −76,619 | +30,398 | 3.0일 | 관찰 (t1 음수=청산 후 하락=유효, t5 소폭 양수 노이즈) |
| SELL | 1 | −144,141 | +76,941 | 0.0일 | 관찰 (n=1 소표본) |
| SELL_RED_STOP | 1 | −48,959 | +24,738 | 4.0일 | 관찰 (n=1 소표본) |

**blocked_day_rate = 100%** (2/2일) — ⚠️ **래칫 경고 2주 연속**: 지난 주와 동일 100%(2/2). 
- 원인 진단: 6/23 검은 화요일 폭락 후 09시 신규 진입 게이트 구조적 블로커(세션 인프라 HTTP 403 + pre_trade_check yahoo 전일자 차단)가 W26 4영업일째 지속.
- 통계적 결론 불가(소표본)이나 인프라 병목이 결합돼 차단 래칫 효과 — **사용자 승인 후 진단·완화 필요**: `pre_trade_check` 의 yahoo 날짜지연 단독 차단 여부 재검토(v2.17 세션 웹검증 차단 시 snapshot_fresh 폴백 적용 검토 — lessons.md 2026-06-23 09:00 항목 참조).

**lessons_rule_sunset 점검**: 현재 lessons.md 내 임시 차단 룰 만료 대상 없음 — 조선 avoid는 구조적(v2.8 재진입 엔진 미해제), 폭락다음날 보류 룰은 이번 리뷰에서 policy prompt에 정식 명문화.

---

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 A — SELL_GIVE_BACK_STOP 조건 완화 (지난 주 이월, 승인 대기)
- **대상**: `policy.risk` 내 give_back_stop 임계 또는 `prompts/1500_close.md·1800_report.md` §give-back 판정 조건
- **현재**: give-back 손절 — KB금융 5/28 패턴(반도체 장세 소외 4일 누적 + KOSPI 급락) 기반. 임계 조건 불명확.
- **변경 후 제안**: give_back_stop 발동 전 "최소 보유 5거래일 + 손실 −8% 이상" 이중 조건 추가 — 단기 변동성으로 조기청산되는 패턴 차단.
- **근거 lessons 라인**: SELL_GIVE_BACK_STOP t5 forgone +164,798원 (KB금융 5/28). 패턴 반복 시 추가 손익 근거.
- **자동 적용 가능 여부**: 사용자 승인 필요 (손익 분기·임계 변경)
- **부작용 점검**: 이중 조건 추가 시 실제 give-back 패턴에서 청산 지연 위험 — 5거래일 이내 give-back(예: 급락 후 익일 추가 급락)에서 손실 확대 가능.

### 후보 B — 조선 섹터 avoid_sectors 정식 등록 (지난 주 이월, 승인 대기)
- **대상**: `config/policy.json §sector_rotation_reentry.avoid_sectors` 또는 별도 필드
- **현재**: watchlist/candidates.json 에서 avoid 플래그 존재, policy의 공식 섹터 차단 리스트 없음
- **변경 후 제안**:
```diff
- "avoid_sectors": []
+ "avoid_sectors": ["조선", "HD한국조선해양", "삼성중공업"]
```
  재진입 조건: 수주 신규 뉴스 + KOSPI 섹터 RS score ≥ 0.7 + 추세 필터 통과 3거래일 연속.
- **근거 lessons 라인**: 섹터 오차 5건 (기아·KB금융·HD조선 반복), 조선 avoid 6/1 등록 후 6/23 −17.6% 추가 확인
- **자동 적용 가능 여부**: 사용자 승인 필요 (신규 섹터 차단 리스트)
- **부작용 점검**: 정식 차단 시 v2.8 섹터 로테이션 재진입 엔진이 조선 해제 조건 달성 시에도 차단 유지 → 재진입 엔진 우선순위 정책 명확화 필요.

### 후보 C — pre_trade_check 야후 날짜지연 단독 차단 완화 (신규, 승인 대기)
- **대상**: `scripts/pre_trade_check.py` + `policy.price_data_quality` §web_verify_unavailable_fallback
- **현재**: yahoo가 KST 오전 KRX 종가를 전일자로 보고할 때 `prices_last_date_today=false` 단독으로 `live_verify_required` 발령 → naver 당일자+fresh 스냅샷이 있어도 신규 진입 봉쇄(4영업일째).
- **변경 후 제안**: naver 당일자 + 2출처 일치 + fresh(≤20분) 조건 충족 시 yahoo 날짜지연을 단독 차단 사유에서 제외 → `web_verify_unavailable_fallback=true` 자동 적용.
- **근거 lessons 라인**: 2026-06-23 09:00 09시 신규진입 게이트 구조적 블로커 (4영업일째)
- **자동 적용 가능 여부**: 사용자 승인 필요 (가격 검증 게이트 조건 변경 — 실자본 매매 영향)
- **부작용 점검**: yahoo 날짜지연이 실제 전일 종가인 경우(당일 장 폐장 전)를 false positive로 통과시킬 위험 → naver 수집 시각 `last_date_today=true` 조건을 반드시 병행.

---

## 4. policy.json dead config (참조 없음)

다음 3개 최상위 필드가 `prompts/*.md` 및 `scripts/*.py` 에서 참조되지 않음:
- `policy.json §weekly_cycle` — 삭제 또는 활성화 결정 필요 (어떤 routine 도 이 키를 조회하지 않음)
- `policy.json §rebalance_rules` — 삭제 또는 활성화 결정 필요
- `policy.json §disclaimers` — 법적 면책 문구. 리포트에 하드코딩으로 이미 존재; 중복 dead config.

---

## 5. 선제 추론 루프 채점 (§1-7, inference_scorecard)

`state/inference_scorecard.json` 기준:
- 전체 적중률 43% (부분 57%, n=7) — **동전던지기 수준**
- high 구간: n=2 (표본 부족, 채점 보류)
- miss_factors: 없음 (아직 반복 빗나감 패턴 미식별)
- opportunity_cost: shadow probe 0건 (Phase 1 — 아직 그림자 배치 미실행)

**Tier 2(공격) 개방 게이트**: paper expectancy 및 PF 데이터 없음 → **개방 불가(Phase 1 관측 유지)**. high 구간 적중률이 동전던지기 수준이므로 선제 액션 권한 동결 유지.
**체크리스트 위생**: `inference_checklist.md` — 만료 항목 없음, 체크리스트 항목 0건(Phase 1). 정상.

---

## 6. prompt 간 일관성 (§1-4)

신뢰도 출처 규칙 일관성 점검 (00/09/12/15/18·주말 prompt):
- `0000_global.md`: ✅ stale≠low + confidence 1순위 + 레거시 이월 금지
- `0900_pre_market.md`: ✅ 동일
- `1200_midday.md`: ✅ 동일
- `1500_close.md`: ✅ 동일
- `1800_report.md`: ✅ 동일
- `saturday_review.md`: ✅ 동일
- `sunday_archive.md`: ⚠️ stale≠low + market_snapshot 기준 명시 있으나 "1순위" 표현 없음 — 실질적으로 동일 의미, 표현 경미 차이. **이번 리뷰: 관찰 유지** (지난 주에도 동일 판단, 실제 동작 모순 없음)
- `sunday_strategy.md`: ✅ 동일
- `weekend_report.md`: ⚠️ 동일 패턴 (레거시 이월 금지 명시이나 "1순위" 표현 없음) — 관찰 유지

---

## 7. 자동 패치 적용 내역 (이번 리뷰 실행 완료)

| # | 패치 내용 | 적용 파일 | 조건 |
|---|---|---|---|
| 1 | `analyst_target_upgrade.any` += "줄상향" | `config/news_keywords.json` | 키워드 구멍 보강 |
| 2 | 폭락 다음날 신규 진입 보류 룰 명문화 (KOSPI −8% 이하 시) | `prompts/0900_pre_market.md §1-4` | 2026-06-23 검은 화요일 교훈 |
| 3 | ATH권+금요일 목표선 일시상회 종가트리거 재확인 v2.16 | `prompts/1200_midday.md §2` | 2026-06-19 ATH 패턴 교훈 |
| 4 | 뉴스 키워드 리뷰 루틴 항목 추가 | `state/lessons.md` | 주간 루틴 |

---

## 8. 다음 주 routine 적용 우선순위

- **즉시 (자동 적용 완료)**: 폭락다음날 게이트 패치, ATH권 금요일 목표선 종가트리거 패치, 뉴스 키워드 "줄상향" 추가
- **다음 주 사용자 승인 후 적용**: SELL_GIVE_BACK_STOP 조건 완화, 조선 섹터 정식 차단, pre_trade_check yahoo 날짜지연 완화
- **다음 archive 까지 관찰**: blocked_day_rate 2주 연속 100% — W27에서 3주 연속이면 게이트 래칫 진단 긴급 상정

---

## 9. 사용자 액션 요약 (3줄 이내)
- **즉시 결정 필요 1건**: pre_trade_check yahoo 날짜지연 단독 차단 완화 (후보 C) — W26 4영업일 블로킹이 W27도 이어지면 삼성전자/SK하이닉스 1,000조 재진입 기회를 또 놓친다
- **검토 권장 2건**: 조선 섹터 정식 차단(후보 B), SELL_GIVE_BACK_STOP 조건 완화(후보 A)
- **자동 적용 완료 4건**: 키워드 보강·폭락다음날 게이트·ATH금요일 룰·lessons 루틴 항목
