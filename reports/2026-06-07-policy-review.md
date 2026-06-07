# 정책·프롬프트 패치 리뷰 — 2026-06-07 (일)

> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
> 마지막 갱신: 2026-06-07 20:00 KST

---

## 한눈에 보기
- lessons 총 항목 수: **19**
- 신규 추출 룰 (전체 누적): **6**
- 반영 완료: **5** / 부분 반영: **0** / 미반영: **1**
- 반복 누적 카운트 ≥ 3: **2건** (매크로 오차 3건, 섹터 오차 5건)
- 자동 적용 권장 패치: **1건** / 사용자 승인 필요: **2건**
- 수동 검토 항목: **1건** (자동 대조 불가 — 이미 반영 확인)
- 이번 주말 리포트: saturday_review·sunday_strategy 미실행 (W23 주말 루틴 비발화)

---

## 1. lessons → policy/prompt 반영 매트릭스

| lessons 항목 | 다음 적용 룰 | 반영 위치 | 상태 |
|---|---|---|---|
| 2026-05-22 / 갭다운 폭 과소 추정 | KOSPI 전일 ±7% 이상 시 갭다운 예측에 +2%p 추가 버퍼 | — | **미반영** |
| 2026-05-20 / 기아(000270) 손절 | 구조적 악재 노출 종목 비중 15% 강제 축소 | `policy.json §entry_filters.on_structural_bear_match.max_position_weight_pct_override: 15.0` | ✅ 반영 |
| 2026-05-20 / 기아(000270) 손절 | 진입 직전 5거래일 누적 -7% 이하면 진입 보류 | `policy.json §entry_filters.block_if_cumulative_return_below_pct: -7.0` | ✅ 반영 |
| 2026-05-20 / 기아(000270) 손절 | 장중 단계 경보(yellow/orange/red) + 원인 3가지 검색 의무 | `policy.json §risk.tiered_alerts` + `prompts/1200_midday.md §2·§3` | ✅ 반영 |
| 2026-05-20 / 기아(000270) 손절 | orange/red 진입 시 lessons.md 즉시 기록 | `policy.json §lessons_logging.log_immediately_on_tier_change_to_orange_or_red` + `prompts/1200_midday.md §5` | ✅ 반영 |
| 2026-05-20 / 기아(000270) 손절 | yellow 이상 → 함정패턴 cross-check 의무 | `policy.json §lessons_logging.cross_check_other_holdings_on_macro_or_sector_cause` + `prompts/1200_midday.md §4` | ✅ 반영 |

### 수동 검토 항목
| lessons 항목 | 마커 | 상태 |
|---|---|---|
| 2026-05-28 / HD조선 장중 orange 미대응 | 장중 실시간 비상 대응 절차 명문화 | ✅ 반영됨 — `policy.json §entry_filters.intraday_breach_contingency` + `.github/workflows/intraday_monitor.yml` 신설(v2.5) 확인 |

---

## 2. 반복 누적 카운트 ≥ 3 항목

### [섹터 오차] — 5건 (기아 5/20, KB금융 5/26·5/27, HD조선 5/29·6/1)
- **누적 라인 요약**: 반도체·AI 주도 장세에서 조선·금융 섹터 수급 소외 5회 반복. KOSPI 대비 초과 하락이 시스템적 패턴임.
- **대응 현황**: 조선 섹터 → `watchlist.json.avoid_sectors` 에 HD조선(009540)·삼성중공업(010140) 등록 ✅ (2026-06-01 적용). KB금융 등 금융주 섹터 로테이션 할인은 watchlist 코멘트에 언급만 되고 **policy.json 필드는 없음**.
- **권장 패치**: `policy.json §entry_filters` 에 `semiconductor_led_market_financial_discount` 필드 추가 (금융주 목표가 설정 시 반도체 주도 3일+ 구간 -5%p 할인 의무). **사용자 승인 필요** — 목표가 계산 로직 변경.
- **적용 방식**: 사용자 승인 후 반영
- **근거 lessons 라인**: 2026-05-26 KB금융 / 2026-05-27 KB금융 / 2026-05-28 KB금융 give-back

### [매크로 오차] — 3건 (KB금융 5/22, HD조선 5/28, 삼성전자 6/5 Broadcom shock)
- **누적 라인 요약**: 글로벌 AI 칩 섹터 guidance 충격(Broadcom 6/5), 역대 최고 경신 후 차익실현(5/22·5/28). 서로 다른 매크로 트리거지만 "보유 기간 중 글로벌 반도체 섹터 악재 이벤트 일정 미파악"이 공통 패턴.
- **권장 패치**: `prompts/0900_pre_market.md` §1 웹 검색 항목에 "보유 종목 관련 글로벌 반도체 guidance 발표 일정(Broadcom/NVIDIA 실적 발표일) D-1 사전 파악·기록 의무" 추가. **사용자 승인 필요** — 실행 의무 항목 추가.
- **적용 방식**: 사용자 승인 후 반영
- **근거 lessons 라인**: 2026-06-05 삼성전자 ORANGE (Broadcom shock 사전 미파악)

---

## 3. 미반영·부분반영 패치 후보 (실행 plan)

### 후보 1 — [KOSPI 전일 급등 시 갭다운 예측 버퍼 +2%p] ✅ **자동 적용 완료**

- **대상**: `config/policy.json §entry_filters` + `prompts/0000_global.md §2-1`
- **현재**: 갭다운 예측 기준치 관련 명시적 버퍼 정책 없음
- **변경 후 제안**:

```diff
# config/policy.json §entry_filters (overnight_gap_prediction_buffer 신설)
+   "overnight_gap_prediction_buffer": {
+     "purpose": "codify — lessons.md 2026-05-22 루틴 오차(KOSPI 역대 최대 급등 다음날 갭다운 예측 -1~-2.5% vs 실제 -4.21%). 표준 버퍼(±1%)로 추정해 2%p 과소 추정.",
+     "trigger_abs_change_pct": 7.0,
+     "additional_downside_buffer_pct": 2.0,
+     "applies_to": "prompts/0000_global.md §2-1 갭다운 예측"
+   }

# prompts/0000_global.md §2-1 (갭다운 예측 주석 추가)
+   - **갭다운 버퍼 룰 (policy.entry_filters.overnight_gap_prediction_buffer)**: 전일 KOSPI 등락률 절댓값이 +7% 이상이면 기본 갭다운 예측치에 **+2%p 추가 하향 버퍼** 적용 (예: -1.5% 기본 → -3.5% 조정). lessons.md 2026-05-22 근거.
```

- **근거 lessons 라인**: 2026-05-22 / 시스템 — 갭다운 폭 과소 추정 (루틴 오차)
- **자동 적용 가능 여부**: **자동 적용** (새 필드 추가, 보수적 방향, 기존 동작 모순 없음)
- **부작용 점검**: 0000_global.md의 갭 예측 텍스트에만 반영 — 다른 script 수치 계산에 영향 없음. 자정 routine이 이 버퍼를 참고해 예측 범위를 넓히는 텍스트 가이드 역할.

---

### 후보 2 — [금융주 반도체 주도 장세 목표가 할인] ⚠️ **사용자 승인 필요**

- **대상**: `config/policy.json §entry_filters` 또는 `prompts/0900_pre_market.md §2`
- **현재**: 금융주 목표가 설정 시 섹터 로테이션 할인 관련 명시적 필드 없음 (watchlist 코멘트에만 언급)
- **변경 후 제안**:

```diff
# config/policy.json §entry_filters (semiconductor_rotation_period_discount 신설)
+   "semiconductor_rotation_period_discount": {
+     "purpose": "lessons.md KB금융 3회 연속 목표가 미달(5/22·5/26·5/27) — 반도체 AI 주도 장세(KOSPI 일간 +2%+ 연속 3일 이상)에서 금융주·산업재 섹터 목표가 설정 시 추가 할인 의무.",
+     "trigger": "KOSPI 최근 3거래일 평균 등락률 ≥ +1.5% (반도체 주도 강세 신호)",
+     "target_price_haircut_pct": -5.0,
+     "applies_to": "finance, industrial sectors 신규 진입 시 목표가 계산"
+   }
```

- **근거 lessons 라인**: 2026-05-26 / 2026-05-27 KB금융 섹터 오차
- **자동 적용 가능 여부**: **사용자 승인 필요** — 목표가 산출 로직(score_candidates·1800_report)에 연동 필요, 수치(-5%p) 결정 필요
- **부작용 점검**: score_candidates.py·1800_report.md 목표가 계산 로직에 추가 구현 필요

---

### 후보 3 — [보유 기간 중 글로벌 반도체 guidance 발표 일정 사전 파악] ⚠️ **사용자 승인 필요**

- **대상**: `prompts/0900_pre_market.md §1-1 미국 시장 검색`
- **현재**: 보유 종목 관련 Broadcom/NVIDIA 실적 발표 일정 사전 파악 의무 없음
- **변경 후 제안**:

```diff
# prompts/0900_pre_market.md §1-1
+   - **반도체 글로벌 peer guidance 발표 일정 (보유 기간 중 의무)**: 삼성전자 등 반도체 종목 보유 시 `Broadcom earnings calendar`, `NVIDIA earnings date`, `TSMC earnings date` 를 검색해 D-14 이내 발표 예정이면 "AI guidance 이벤트 D-N" 을 watchlist.next_day_plan 에 기록한다. D-1~당일은 손절선 근접 시 선제 부분청산 검토 (lessons.md 2026-06-05 교훈 ①).
```

- **근거 lessons 라인**: 2026-06-05 삼성전자 ORANGE / Broadcom shock 사전 미파악
- **자동 적용 가능 여부**: **사용자 승인 필요** — 신규 검색 의무 항목 추가(루틴 부하 증가)
- **부작용 점검**: 0900_pre_market.md §1 검색 항목 1개 추가, 매주 실적 발표 시즌 외에는 "D-14 이내 없음" 1줄로 처리 가능

---

## 4. policy.json dead config (참조 없음)

| 필드 | 상태 |
|---|---|
| `policy.json §weekly_cycle.weekend_report_output` (`"reports/YYYY-MM-DD-weekend.md"`) | 어떤 prompt·script도 참조하지 않음. weekend_report.md 출력 경로와도 불일치. **삭제 또는 활성화 결정 필요** |
| `policy.json §weekly_cycle.required_weekend_sections` (5개 섹션 목록) | 어떤 prompt·script도 이 필드를 읽지 않음. **삭제 또는 saturday_review.md 에 명시적 링크 추가 필요** |

> 참고: `policy.json §rebalance_rules.swap_when` 은 `1200_midday.md` 에서 간접 언급(no_swap_when 참조) — 삭제 불필요.

---

## 5. prompt 간 일관성 점검

### 신뢰도 출처 규칙 (stale≠low · market_snapshot confidence 1순위)

| prompt | stale≠low 명시 | 레거시 이월 금지 | 상태 |
|---|---|---|---|
| `prompts/0000_global.md` | ✅ (§0-A 명시) | ✅ | ✅ |
| `prompts/0900_pre_market.md` | ✅ (0-B 명시) | ✅ | ✅ |
| `prompts/1200_midday.md` | ✅ (0-B 명시) | ✅ | ✅ |
| `prompts/1500_close.md` | ✅ (0-B 명시) | ✅ | ✅ |
| `prompts/1800_report.md` | ✅ (0-B 명시) | ✅ | ✅ |
| `prompts/weekend_report.md` | ✅ (명시적 블록) | ✅ | ✅ |
| `prompts/saturday_review.md` | ⚠️ 미명시 | ✅ 있음 | **부분 반영** (매매 미수행 루틴, 위험도 낮음) |
| `prompts/sunday_archive.md` | ⚠️ 미명시 | ✅ 있음 | **부분 반영** (매매 미수행 루틴, 위험도 낮음) |
| `prompts/sunday_strategy.md` | ⚠️ 미명시 | ✅ 있음 | **부분 반영** (주로 weekly_plan 작성, 위험도 낮음) |

> 주말 3개 prompt(saturday_review·sunday_archive·sunday_strategy)는 매매를 집행하지 않으므로 stale≠low 미명시의 즉각 리스크는 낮다. 다만 weekly_plan.json 작성 시 잘못된 신뢰도 서술이 이월될 위험이 있으므로 레거시 이월 금지 문구는 이미 존재함.

### 추가 이슈
- 이번 주말(W23) saturday_review·sunday_strategy 리포트가 생성되지 않았음 (`reports/` 에 2026-05-23·05-24 이후 없음). 루틴 비발화 가능성 — 다음 weekly_plan에 루틴 실행 체계 점검 액션 추가 권고.

---

## 6. 다음 주 routine 적용 우선순위

### 즉시 자동 반영 (이번 커밋)
- ✅ `policy.json §entry_filters.overnight_gap_prediction_buffer` 신설 (KOSPI ±7% 이상 → 갭다운 +2%p 버퍼)
- ✅ `prompts/0000_global.md §2-1` 에 갭다운 버퍼 룰 명문화

### 사용자 승인 후 다음 주 반영
- ⏳ **금융주 반도체 주도 장세 목표가 -5%p 할인** — score_candidates·1800_report 연동 구현 필요
- ⏳ **보유 기간 중 글로벌 반도체 guidance 발표 일정 사전 파악 의무** — 0900_pre_market §1-1 추가

### 다음 archive 까지 관찰
- 📌 섹터 오차 조선 avoid_sectors — watchlist.json에 등록됨, 조선 수급 복귀 시 재진입 조건 재검토
- 📌 dead config (weekend_report_output·required_weekend_sections) — 주말 루틴 재편 후 정리

---

## 7. 사용자 액션 요약 (3줄 이내)

- **즉시 결정 필요 1건**: 금융주 섹터 로테이션 할인(-5%p)·글로벌 반도체 guidance 일정 파악 의무 추가 승인 여부 결정 (2건)
- **검토만 권장 2건**: dead config(weekend_report_output·required_weekend_sections) 삭제 여부 / 주말 루틴(saturday_review·sunday_strategy) W23 비발화 원인 확인
- **자동 적용 완료 1건**: KOSPI 전일 급등 시 갭다운 +2%p 버퍼 (policy.json + 0000_global.md 패치 커밋됨)
