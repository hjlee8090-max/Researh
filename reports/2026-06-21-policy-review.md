# 정책·프롬프트 패치 리뷰 — 2026-06-21 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-06-21 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 27
- 신규 추출 룰 (이번 주): 2 (갭다운 버퍼·기아 교훈 — 두 건 모두 기존 codify 확인)
- 반영 완료: 2 / 부분 반영: 3 (saturday/sunday_archive/sunday_strategy stale≠low 미명시 → 이번 리뷰 자동 패치) / 미반영: 0
- 반복 누적 카운트 ≥ 3: 2건 (매크로 오차 4건, 섹터 오차 5건)
- 자동 적용 권장 패치: 3건 (prompt 명문화 문구 추가 — 이미 적용 완료) / 사용자 승인 필요: 2건

---

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-05-22 09:05 / 갭다운 폭 과소 추정 | KOSPI 절댓값 ≥+7% 시 갭다운 예측 +2%p 하향 버퍼 | `policy.overnight_gap_prediction_buffer` + `prompts/0000_global.md §2-1` | ✅ 반영 |
| 2026-05-20 12:00 / 기아(000270) RED 손절 | 구조적 악재 비중 강제 축소·5일 추세필터·tiered_alerts·원인 의무·lessons_logging·함정패턴 cross-check | `policy.entry_filters.structural_bear_keywords`, `risk.tiered_alerts`, `lessons_logging`, `prompts/1200_midday.md §2` | ✅ 반영(v1.1~v2.5) |
| 신뢰도 출처 규칙 — saturday_review.md | `market_snapshot.confidence` 1순위 + stale≠low 명시 | `prompts/saturday_review.md` | ⚠️ → ✅ 이번 리뷰 자동 패치 |
| 신뢰도 출처 규칙 — sunday_archive.md | stale≠low 명시 | `prompts/sunday_archive.md` | ⚠️ → ✅ 이번 리뷰 자동 패치 |
| 신뢰도 출처 규칙 — sunday_strategy.md | stale≠low 명시 | `prompts/sunday_strategy.md` | ⚠️ → ✅ 이번 리뷰 자동 패치 |

---

## 2. 반복 누적 카운트 ≥ 3 항목

### [매크로 오차] — 4건
- 누적 라인 요약: KB금융 5/22·HD조선 5/28·삼성전자 6/5 Broadcom shock·삼성전자 6/8 RED 청산 — 외부 매크로 충격(반도체 guidance·지정학·지수 급락)에 의한 예상 외 급락
- 권장 패치: 지정학 속보 당일 역전 3건은 v2.5 §0-C 게이트로 이미 codify. 나머지 Broadcom/반도체 guidance 충격 — `policy.entry_filters.post_surge_cooldown` 및 `lessons_rule_sunset` 체계 이미 반영. 추가 룰 불필요 — **이번 리뷰: 관찰 유지**
- 적용 방식: 해당 없음 (기존 codify로 흡수)
- 근거: lessons.md 매크로 오차 카운터 4건 (5/22, 5/28, 6/5, 6/8)

### [섹터 오차] — 5건
- 누적 라인 요약: 기아 5/20·KB금융 5/26·KB금융 5/27·HD조선 5/29·HD조선 6/1 — 반도체 장세 국면에서 비주도 섹터(금융·자동차·조선) 진입 후 소외 손실
- 권장 패치: `avoid_sectors` (조선 3회 반복 ⚠️), `entry_filters.relative_strength` 점수화(v2.5·v2.7 codify), `reentry_discipline`(v2.11) 이미 반영. 조선 repeat_warning 이 candidates.json/watchlist에 flagged 중 — 이번 리뷰: **신규 섹터 차단 리스트 확대 여부 사용자 승인 필요**
- 적용 방식: 사용자 승인 필요 (조선 avoid_sectors 정식 등록)
- 근거: lessons.md 섹터 오차 카운터 5건

---

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)

- 기준: 2026-06-21T20:03:45+09:00 · 추정 로그 7일 / 채점 표본 57건
- 5td: 표본 부족(<5) — 채점 보류 (n=0)
- 20td: 표본 부족(<5) — 채점 보류 (n=0)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 25건 — 표본 부족(<5) — 채점 보류

- 뉴스 피드: 분류 28건 / 미분류 651건 / 해외 53건
- 무음 유형(미매칭): buyback_cancellation, earnings_miss_or_guidance_cut, supply_glut_or_price_drop
- 검토 의무: unclassified 표본 → manual_news 승격 또는 키워드 보강

**키워드 보강/승격 실행 내역**: 0건 — unclassified 표본 대조 결과 silent_types 3종 모두 **뉴스 부재** 확인(키워드 구멍 아님). SK하이닉스 ADR 상장·HD한국조선해양 SMR/LNG 뉴스는 배경기사 수준으로 manual_news 승격 기준(주가 방향성 판단에 직결) 미충족.

**추정식 패치 후보**: 없음 — 모든 horizon 채점 보류(표본 n<5). 백테스트 근거 없이 보정 금지(목표가 인플레 재발 방지 원칙 준수).

**lessons.md 기록**: 2026-06-21 / 시스템 — 뉴스 키워드 리뷰(루틴) 1줄 추가 완료.

---

## 2-b. 룰 손익 채점 (rule_attribution — v2.11)

`state/rule_attribution.json` 기준:

| 청산 룰 | n | 실현손익 | t1 일실 | t5 일실 | 평균보유 | 진단 |
|---|---|---|---|---|---|---|
| SELL | 1 | -144,141 | +13,941 | +76,941 | 0일 | 패치 검토 보류 (n=1, 소표본) |
| TRAILING_STOP | 2 | **+192,878** | +232,186 | **-105,814** | 1.5일 | ✅ 유효 (t5 음수=청산 후 하락, v2.14 1.5×ATR 효과 확인) |
| SELL_GIVE_BACK_STOP | 1 | -13,598 | +20,798 | **+164,798** | 8.0일 | ⚠️ **패치 후보** — t5 일실 +164,798원(조기청산 비용 매우 큼), 사용자 승인 후 조건 완화 검토 |
| SELL_ORANGE_STOP | 2 | -76,619 | -31,602 | +30,398 | 3.0일 | 관찰 (t1 음수=청산 후 하락=유효, t5 소폭 양수는 노이즈 수준) |
| SELL_RED_STOP | 1 | -48,959 | +9,738 | +24,738 | 4.0일 | 관찰 (n=1 소표본) |

**blocked_day_rate_pct = 100%** (2/2일) — ⚠️ **래칫 경고**: candidates가 있던 날 6/3·6/10 모두 entry_filter 차단. 40% 임계(policy §1-2-b) 대비 극단. 소표본이므로 통계적 결론 불가하나, 차단 룰 복잡도 점검 필요 — **사용자 승인 후 진단**.

**lessons_rule_sunset 점검**: lessons.md 내 임시 룰 — `Broadcom D-1~D+2 반도체 비중 50% 축소` (expiry: guidance 발표 D+2까지) — 6/21 기준 해당 guidance 이벤트 없음, 자동 실효. 별도 승격 불필요.

---

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — saturday_review / sunday_archive / sunday_strategy stale≠low 명시 【자동 적용 완료】

- **대상**: `prompts/saturday_review.md` §0-A / `prompts/sunday_archive.md` §2-3 / `prompts/sunday_strategy.md` §0-A
- **현재**: 레거시 서술 이월 금지는 명시, stale≠low 규칙 미명시
- **변경 후**: `stale` 키는 직전 정기 수집본 보존을 뜻할 뿐 그 자체로 low가 아니다 — **stale ≠ low.** 신뢰도 판단은 `market_snapshot.confidence` 기준
- **근거 lessons 라인**: policy §1-4 신뢰도 출처 규칙 일관성 점검
- **자동 적용 가능 여부**: ✅ 가능 (기존 동작과 모순 없는 명문화 추가) — **이번 리뷰에서 적용 완료**
- **부작용 점검**: 3개 주말 prompt의 판단 로직 변경 없음. 기존 weekday prompt와 동일 표현으로 일관성 향상.

---

### 후보 2 — SELL_GIVE_BACK_STOP 조건 완화 【사용자 승인 필요】

- **대상**: `config/policy.json` §entry_filters 또는 관련 스크립트
- **현재**: KB금융 5/28 give-back 손절 체결(-1.17% 폭) — t5 +164,798원 일실
- **변경 후 제안**: give-back 손절 여유를 KOSPI 역대 최고 경신 다음날 기준 최소 -3% 이상 유지. 반도체 장세 지속 시 금융주 give-back 선 -1.5%p 추가 상향. 단 **n=1 소표본** — 아래 diff는 관찰 후 다음 리뷰에서 수치 확정 권장.
```diff
- (현재: give-back 손절 여유 약 -1.17%, 명시 정책 없음)
+ "give_back_stop_floor_pct_on_ath_day": -3.0,  // KOSPI 신고가 당일 다음날 최소 give-back 여유
+ "give_back_extra_sector_lag_pct": -1.5          // 반도체 랠리 3일+ 지속 시 금융주 추가 상향
```
- **근거 lessons 라인**: 2026-05-28 12:00 KB금융 give-back 손절 / 다음 진입 시 반영할 룰
- **자동 적용 가능 여부**: 사용자 승인 필요 — 손익 분기 조건 변경
- **부작용 점검**: n=1로 통계 불충분. 차기 give-back 발동 사례(n≥3) 누적 후 최종 수치 결정 권장.

---

### 후보 3 — 조선 섹터 avoid_sectors 정식 등록 【사용자 승인 필요】

- **대상**: `config/policy.json` 또는 `config/universe.json`
- **현재**: 조선 반복 손실 3건 ⚠️ 플래그 (lessons.md 동일 섹터 반복 손실 카운터), 공식 차단 없음
- **변경 후 제안**: 조선(HD한국조선해양 009540, 삼성중공업 010140)을 `avoid_sectors` 또는 `universe.sector_block_list`에 추가 — 단 **대형 수주 촉매(web_verify 조건부)** 확인 시 자동 해제 허용
```diff
+ "avoid_sectors_soft": ["shipbuilding"],
+ "avoid_sectors_soft_lift_condition": "major_order_catalyst_web_verified"
```
- **근거 lessons 라인**: HD조선 5/29·6/1 섹터 오차 + lessons.md "동일 섹터 반복 손실: 조선 3회 ⚠️ avoid_sectors 등록" 카운터
- **자동 적용 가능 여부**: 사용자 승인 필요 — 신규 섹터 차단 리스트
- **부작용 점검**: sunday_strategy.md 이미 "조선 촉매 web_verify 대기 중" 으로 사실상 운영 중. 정식 등록 시 audit_pipeline WARN 체계와 연동 필요.

---

## 4. policy.json dead config (참조 없음)

자동 검색(prompts/*.md + scripts/*.py + docs/*.md 전체) 결과:

- `policy.weekly_cycle` — 어떤 prompt/script 도 참조하지 않음. **삭제 또는 codex_automation 으로 통합 결정 필요**
- `policy.rebalance_rules` — 어떤 prompt/script 도 참조하지 않음. **삭제 또는 활성화 결정 필요**
- `policy.disclaimers` — 어떤 prompt/script 도 참조하지 않음. **삭제 후보** (리포트 헤더에 직접 표기됨)

> 단, top-level grep 기반이므로 동적 참조(`p[key]` 형태)로 사용 중일 수 있음. 삭제 전 scripts/ 내 eval 패턴 재확인 권장.

---

## 5. 다음 주 routine 적용 우선순위

- **(자동 적용 완료)** saturday_review / sunday_archive / sunday_strategy stale≠low 명시 — commit 포함
- **(사용자 승인 후 다음 주 적용)** SELL_GIVE_BACK_STOP 조건 완화 — n=1 소표본, W26 실사례 1건 더 누적 후 수치 결정
- **(사용자 승인 후 다음 주 적용)** 조선 섹터 avoid_sectors_soft 정식 등록
- **(다음 archive까지 관찰만)** blocked_day_rate_pct = 100% 진단 — W26 차단 사례 기록 후 W27 리뷰에서 래칫 해소 여부 판단
- **(다음 archive까지 관찰만)** dead config 3종(weekly_cycle·rebalance_rules·disclaimers) — 스크립트 동적 참조 재확인 후 삭제

---

## 6. 사용자 액션 요약 (3줄 이내)

- **즉시 결정 필요 1건**: 조선 섹터 avoid_sectors_soft 정식 등록 여부 — 3회 반복 손실, 이미 sunday_strategy에서 사실상 운영 중이므로 policy 정식화 권장
- **검토 권장 2건**: ①SELL_GIVE_BACK_STOP 완화(n=1, W26 추가 관찰 후 수치 확정) ②dead config 3종 삭제(weekly_cycle·rebalance_rules·disclaimers)
- **자동 적용 완료 3건**: saturday_review·sunday_archive·sunday_strategy stale≠low 명시 추가 (commit 포함)
