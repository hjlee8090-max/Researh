# 정책·프롬프트 패치 리뷰 — 2026-06-14 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-06-14 20:00 KST

## 한눈에 보기
- lessons 총 항목 수: 25
- 신규 추출 룰 (이번 주): 0건 (지난주 이후 신규 "다음 적용 룰" 없음 — 기존 2건 모두 반영 완료)
- 반영 완료: 2 / 부분 반영: 0 / 미반영: 0
- 반복 누적 카운트 ≥ 3: 2건 (매크로 오차 4건, 섹터 오차 5건) — 이미 v2.7~v2.11 codify
- 자동 적용 권장 패치: 1건 (뉴스 키워드 보강 2종) / 사용자 승인 필요: 1건 (dead config 삭제)

---

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 (날짜) | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-05-22 / 갭다운 폭 과소 추정 (루틴 오차) | KOSPI 전일 등락률 ≥+7% 시 갭다운 예측에 +2%p 추가 하향 버퍼 | `policy.entry_filters.overnight_gap_prediction_buffer` + `prompts/0000_global.md §entry_filters 갭다운 버퍼 룰` | ✅ 반영 완료 |
| 2026-05-20 / 기아(000270) RED 손절 (가정오류) | 구조적 악재·5일추세·단계경보·orange/red 즉시 기록·함정패턴 cross-check | `policy.entry_filters.structural_bear_keywords` + v1.1~v2.5 전반 | ✅ 반영 완료 |
| 2026-06-11 / 지정학 속보 당일 역전 3번째 (루틴) | 0000 §0-C 지정학 진행형 확인 게이트·±2.5%p 불확실도 병기 의무 | `prompts/0000_global.md §0-C` (v2.5 codify) | ✅ 반영 완료 |
| 2026-06-12 / 카톡 알림 오발송 3건 (기타) | detect_slot 제목 줄 한정·슬롯 폴백 발송 제거·오늘 날짜 가드·push 변경파일 가드 | `scripts/send_kakao.py` + `scripts/build_html.py` (v2.12 codify) | ✅ 반영 완료 |
| 2026-06-10 / 청산 룰 변동성 부정합 (구조 진단) | ATR 연동 경보·2단 트레일링·재진입 규율·룰 일몰·valuation_anchor + rule_attribution 채점 | `policy` v2.11 전반 | ✅ 반영 완료 |
| 2026-06-08 / 강세장 미배치 구조 교정 (v2.7/v2.8) | 진입필터·사이징 레짐연동 + 섹터 로테이션 재진입 엔진 | `policy.entry_filters.block_if_cumulative_return_below_pct_by_tier` + `policy.sector_rotation_reentry` | ✅ 반영 완료 |
| 2026-06-08 / web_verify 출처 게재일 미검증 | source_date_verification 게이트 (v2.6) | `policy.codex_automation.web_verify_guard` + CI `check_trade_log_gate.py` | ✅ 반영 완료 |
| YYYY-MM-DD (템플릿) | (미기입 — 템플릿 항목) | — | — |

---

## 2. 반복 누적 카운트 ≥ 3 항목

### 매크로 오차 — 4건
- 누적 라인 요약: Broadcom shock(6/5·6/8) + 이란 지정학 역전 3건 + NFP 서프라이즈 발 금리 상승 복합
- 권장 패치: v2.5~v2.11 이미 다중 대응(지정학 게이트·ATR 손절·Broadcom 비중 캡 일몰). 추가 패치 불필요 — W25 FOMC 이벤트 중 동일 패턴 재발 시 재검토.
- 적용 방식: 관찰 유지 (신규 패치 불필요)
- 근거 lessons 라인: lessons.md §누적 패턴 카운터 "매크로 오차"

### 섹터 오차 — 5건
- 누적 라인 요약: 조선(HD조선 3회 연속 소외·orange 청산) + 금융(KB금융 3회 연속 목표가 미달) + 반도체 주도장세 섹터 수급 편중 구조
- 권장 패치: avoid_sectors.조선 등록(6/1) + sector_rotation_reentry(v2.8) 이미 적용. 재진입 조건(몰입 발자국 ≥1신호) W25 주간 점검 의무.
- 적용 방식: 관찰 유지 — avoid_sectors 조선의 몰입 발자국 확인 후 해제 여부는 06-15 09시 routine에서 검토
- 근거 lessons 라인: lessons.md §누적 패턴 카운터 "섹터 오차", §2026-05-28~06-01 HD조선 항목

---

## 2-b. 룰 손익 채점 (rule_attribution — v2.11)

| 청산 룰 | n | realized_pnl | t1_forgone | t5_forgone | 판정 |
|---|---|---|---|---|---|
| TRAILING_STOP | 2 | +192,878원 | +232,186원 | -105,814원 | ✅ 수익 룰·t5 음수(청산 후 추가 하락 → 타이밍 적절) |
| SELL_ORANGE_STOP | 2 | -76,619원 | -31,602원 | -5,200원 | ✅ 방어 룰·t1·t5 모두 음수(청산 후 추가 하락 → 손절 정당) |
| SELL_RED_STOP | 1 | -48,959원 | +9,738원 | 0 | ⚠️ t1 양수(청산 후 소폭 반등) — 표본 n=1, 2주 연속 판단 불가 → 패치 보류, W25 재확인 |
| SELL_GIVE_BACK_STOP | 1 | -13,598원 | +20,798원 | 0 | ⚠️ t1 양수(청산 후 상승) — 표본 n=1, 연속 판단 불가 → 패치 보류 |
| SELL (구조적 악재) | 1 | -144,141원 | +13,941원 | 0 | △ 기아 즉시 손절, t1 소폭 양수 — 구조적 차단 기준이므로 기대 손실 허용 범위 내 |

**blocked_day_rate_pct**: `policy.json`에 미구현. rule_attribution.py 의 by_rule 에 `blocked_day_rate_pct` 필드가 없어 40% 임계 감시 불가 → **패치 후보로 등록** (사용자 확인 후 script 추가)

**lessons_rule_sunset 만료 점검**: Broadcom D-1~D+2 "15% 캡"은 v2.11에서 "비중 50% 축소 + expiry=D+2"로 이미 완화됐고, 6/10 기준 만료 완료. 현재 활성 즉석 룰 없음.

---

## 2-c. 목표가 추정 채점 + 뉴스 키워드 점검

### 목표가 추정 채점 + 뉴스 키워드 점검 (score_target_estimates)

- 기준: 2026-06-14T20:04:11+09:00 · 추정 로그 2일 / 채점 표본 17건
- 5td: 표본 부족(<5) — 채점 보류 (n=0)
- 20td: 표본 부족(<5) — 채점 보류 (n=0)
- 60td: 표본 부족(<5) — 채점 보류 (n=0)
- estimate_gate 손익: 차단표본 7건 — 표본 부족(<5) — 채점 보류

- 뉴스 피드: 분류 57건 / 미분류 753건 / 해외 40건
- 무음 유형(미매칭): analyst_target_upgrade, earnings_miss_or_guidance_cut
- 검토 의무: unclassified 표본 → manual_news 승격 또는 키워드 보강 (estimate_scorecard.json 의 review_checklist)

**키워드 보강/승격 실행 내역 (이번 리뷰 자동 적용)**:
- `labor_or_litigation_resolved.any` ← '특허승소', '특허분쟁승리', '특허완승' 추가 (LG에너지솔루션 특허 분쟁 승리 3건 미분류 대응)
- `tech_breakthrough.any` ← 'AI성능두배', 'AI성능향상' 추가 (삼성전자 엑시노스 2600 AI 성능 기사 미분류 대응)
- 자동 보강 총 2종 / 5개 키워드

**silent_types 판정**:
- `analyst_target_upgrade`: 현재 시장 뉴스 부재로 판단 (최근 2주 analyst 하향 집중 시기 — 상향 보고서 드묾). 키워드 구멍 아님.
- `earnings_miss_or_guidance_cut`: 6월은 실적 발표 비수기, 뉴스 부재로 판단. 키워드 구멍 아님.

**SK하이닉스 화재 (2026-06-12) — 사용자 검토 권장**:
- "청주 SK하이닉스 M15X 화재, 1명 부상·4천명 대피" — 현재 분류 카테고리 없음.
- 옵션 A: `manual_news` 수동 등록 (단발 사고)
- 옵션 B: `supply_risk` 또는 `production_disruption` 신규 유형 추가 (사용자 결정 필요)

**추정식 패치 후보**: 표본 부족으로 패치 불필요 — 추정 로그 ≥5일 누적 후 재평가.

---

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — [자동 적용] 뉴스 키워드 2종 보강

- **대상**: `config/news_keywords.json` §type_keywords.labor_or_litigation_resolved, §type_keywords.tech_breakthrough
- **현재**:
  - labor_or_litigation_resolved.any: `["파업철회", ..., "제재해제"]` (13개)
  - tech_breakthrough.any: `["양산개시", ..., "차세대공정"]` (10개)
- **변경 후 제안**:
```diff
- "labor_or_litigation_resolved": { "any": ["파업철회","파업유보","잠정합의","임단협타결","찬반투표가결","노사합의","소송승소","무혐의","합의타결","분쟁종결","과징금감경","관세환급","제재해제"] }
+ "labor_or_litigation_resolved": { "any": ["파업철회","파업유보","잠정합의","임단협타결","찬반투표가결","노사합의","소송승소","무혐의","합의타결","분쟁종결","과징금감경","관세환급","제재해제","특허승소","특허분쟁승리","특허완승"] }

- "tech_breakthrough": { "any": ["양산개시","양산돌입","양산성공","세계최초","개발성공","수율개선","신기술","기술확보","전고체","차세대공정"] }
+ "tech_breakthrough": { "any": ["양산개시","양산돌입","양산성공","세계최초","개발성공","수율개선","신기술","기술확보","전고체","차세대공정","AI성능두배","AI성능향상"] }
```
- **근거 lessons 라인**: 루틴 — estimate_scorecard.json unclassified_samples (LG에솔 특허 분쟁 승리 3건, 삼성전자 엑시노스 AI 성능)
- **자동 적용 가능 여부**: ✅ 가능 (기존 키워드와 충돌 없는 확장)
- **부작용 점검**: `특허승소`·`특허완승` 은 기존 `exclude` 키워드에 해당 없음. `AI성능향상`은 spec 홍보 기사에 매칭 가능 — `tech_breakthrough` 가산점(+8%)이 다소 과대 적용될 리스크가 있으나 제품 로드맵 관련 정보므로 허용 범위 내.

---

### 후보 2 — [사용자 승인 필요] policy.json `disclaimers` dead config 삭제

- **대상**: `config/policy.json` §disclaimers
- **현재**: `disclaimers` 최상위 필드가 policy.json 에 정의되어 있으나 어느 prompt/script 에서도 참조 없음 (전체 소스 grep 결과 0건)
- **변경 후 제안**: 해당 필드 삭제 또는 `# DEPRECATED` 주석 처리
- **근거**: §1-3 dead config 점검
- **자동 적용 가능 여부**: ❌ 사용자 승인 필요 (삭제 시 복구 어려움, 의도적 보존일 수 있음)
- **부작용 점검**: policy.json 어느 prompt 에서도 이 필드를 읽지 않으므로 삭제해도 동작 변경 없음.

---

### 후보 3 — [사용자 승인 필요] rule_attribution.py `blocked_day_rate_pct` 필드 추가

- **대상**: `scripts/rule_attribution.py` + `state/rule_attribution.json`
- **현재**: `by_rule` 에 `blocked_day_rate_pct` 필드 없음 — 차단 룰 과잉(래칫) 신호 감시 불가
- **변경 후 제안**: 각 청산 룰에 대해 해당 룰이 발동된 날 비율(blocked_day_rate = n_days_triggered / total_holding_days)을 집계해 by_rule 에 추가 → 40% 이상 시 sunday_policy_review 에서 WARN 표시
- **근거**: lessons.md §1-2-b 점검 기준 (policy_review prompt §1-2-b)
- **자동 적용 가능 여부**: ❌ 사용자 승인 필요 (스크립트 수정 포함)
- **부작용 점검**: 집계 방식(보유일수 정의)에 따라 수치가 달라져 과다경보 위험 있음 — 명세 확정 후 구현.

---

## 4. policy.json dead config (참조 없음)

- `policy.json §disclaimers` — 어느 prompt/script 도 참조하지 않음. 삭제 또는 활성화 결정 필요.
  - 내용: 면책 문구 텍스트 블록 (학습·시뮬레이션 목적 고지)
  - 권장: §3 후보 2 참조 — 사용자 결정 대기

---

## 5. 다음 주 routine 적용 우선순위

**자동 적용 즉시 반영 완료 (이번 리뷰)**:
- `config/news_keywords.json`: 키워드 보강 2종 5개 (특허승소·특허분쟁승리·특허완승 + AI성능두배·AI성능향상)
- `state/lessons.md` 루틴 기록 1줄: 키워드 보강 이력

**사용자 승인 후 다음 주 적용 항목**:
1. `policy.json §disclaimers` 삭제 여부 결정 (dead config)
2. `rule_attribution.py` `blocked_day_rate_pct` 필드 추가 (집계 명세 합의 필요)
3. SK하이닉스 화재 뉴스 처리 방침 결정 (manual_news 등록 or 신규 supply_risk 카테고리)

**다음 archive 까지 관찰만 할 항목**:
- SELL_RED_STOP / SELL_GIVE_BACK_STOP: t1 양수이나 n=1 — W25 추가 데이터 누적 후 재심
- 매크로/섹터 오차 반복 카운터 — W25 FOMC 이벤트에서 동일 패턴 발생 여부 모니터링
- 목표가 추정 채점: 표본 ≥5 도달 시 next_sunday 재채점

---

## 6. 사용자 액션 요약 (3줄 이내)
- 즉시 결정 필요 1건: SK하이닉스 화재 뉴스 분류 방침 (manual_news vs supply_risk 신규 유형)
- 검토 권장 2건: ①`policy.json §disclaimers` 삭제 여부 ②`rule_attribution.py` blocked_day_rate 필드 추가
- 자동 적용 완료 1건: news_keywords 보강 2종 (labor_or_litigation_resolved 3개 + tech_breakthrough 2개)
