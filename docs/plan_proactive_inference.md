# 계획서 — 선제적 추론 루프 (Proactive Inference Loop, 2026-06-24)

> 목적: 현재 파이프라인은 **결과가 나온 뒤 반응**(종가 확정→오차 분류, 단계 진입→경보)하는 구조다.
> 여기에 **"종합적인 상황·환경을 추론해 결과를 미리 예측하고, 그 예측에 근거해 (보수적으로) 먼저 액션"** 하는
> 레이어를 더한다. 빗나간 예측은 **무엇이 미흡했는지·다음엔 무엇까지 고려할지**를 구조화해 `lessons.md` 에 적고,
> 그 학습이 **다음 추론 직전에 강제로 참조**되게 한다.
> 핵심 원칙: 기존 "자기보완 루프"를 대체하지 않고 **형제 루프**로 추가하며, 기존 보수성(묵은 가격 선체결 금지·
> 출처 게재일 게이트·heat 예산·콘텍스트 예산)을 **하나도 깨지 않는다.**

---

## 0. 현재 구조 진단 — "예측"은 이미 흩어져 있다

선제 추론의 부품이 이미 곳곳에 존재하지만, **기록·채점·환류가 연결돼 있지 않다.**

| 기존 예측 행위 | 위치 | 검증 | 학습 환류 | 빈 곳 |
|---|---|---|---|---|
| 자정 개장 갭 예측 (±X%, [진행형] 태그) | `0000_global.md` §2-1 | 09시 §1-0 야간 갭 검증 (서술) | 빗나가면 lessons "루틴 오차" **수기** 산입 | 구조화된 예측 원장 없음 — 적중률 통계 불가 |
| 내일 시나리오 if-then 표 | `1800_report.md` §4 | 09시가 조건 판정·실행 | 발동/불발 1줄 메모 | "조건→행동"은 있으나 **예측 빗나감의 사유 채점**이 없음 |
| 목표주가 추정 (estimate) | `estimate_target_price.py` | `score_target_estimates.py` (주간) | `estimate_scorecard.json`→sunday_policy_review | **유일하게 채점되는 예측.** 단 가격 한 축만 — 상황 추론은 미채점 |
| thesis 무효화 예측 | `watchlist.thesis.invalidation[]` | 09/18시 thesis-tracker | lessons 1줄 | 사후 판정이지 사전 예측 채점 아님 |

**결론**: 이미 검증된 패턴(`*_log.jsonl` 원장 → `score_*.py` 채점 → `*_scorecard.json` → 일요일 리뷰)이
목표주가에만 적용돼 있다. 이 패턴을 **"상황 추론 + 선제 액션"** 전체로 일반화하면 사용자가 원하는 루프가 된다.

### 왜 "그냥 더 공격적으로 매매" 가 아닌가 (보수성 가드의 이유)
기존 파이프라인은 의도적으로 보수적이다 — `new_entry_freshness_rule`(묵은 가격 선체결 후 재확인 금지),
`source_provenance_gate`(묵은 기사 시세 도용 차단), `portfolio_heat_budget`(합산 손절위험 6% 상한),
`context_budget`(핫패스 비대화 방지). 6/8 RED 청산·6/12 카톡 오발송 등 **사고의 다수가 "성급한 선행 행동"
에서 나왔다.** 따라서 "먼저 액션"은 **추측에 전액 베팅**이 아니라 **되돌릴 수 있거나 리스크를 줄이는
방향의, probe 크기로 제한된, 기존 게이트를 전부 통과하는 선제 행동**으로 정의해야 한다(§3 액션 사다리).

---

## 1. 자기보완 루프 부합성 점검 (설계 전 게이트)

| 설계 요소 | 부합 판정 | 코드 레벨 근거 |
|---|---|---|
| 예측 원장 `state/inference_log.jsonl` (핫패스 아님) | ✅ | `target_estimate_log.jsonl`·`trade_log.jsonl`·`audit_log.jsonl` 와 동형. 채점 스크립트만 읽음, routine 의무 적재 아님 → 콘텍스트 예산 무영향 |
| 채점기 `score_inferences.py` (의존성 0) | ✅ | `score_target_estimates.py`(L20 "의존성 0") 패턴 그대로 복제 — 표준 라이브러리만, `MIN_SAMPLES` 소표본 과신 방지 동일 |
| 응축 체크리스트 `state/inference_checklist.md` (핫패스, 상한 둠) | ✅ 조건부 | `lessons.md` 가 이미 42KB·핫패스. 새 핫패스 추가는 예산 위배 → **체크리스트는 build 스크립트가 lessons 에서 파생, 상한(예: 40줄/4KB) 두고 audit 가 크기 래칫 감시** |
| 선제 액션을 probe·리스크감소로 제한 | ✅ 수익 직결 | `reentry_discipline`(probe=축소비중 50%)·`valuation_anchor`(overheat→probe)·`trailing_stop`(선제 익절보호) 와 동일 철학 — "추격·전액 베팅 금지"의 연장 |
| 선제 매매도 `pre_trade_gate`·`trade_provenance_gate` 전부 통과 | ✅ 필수 | 선제 진입이라도 `price_source`·`execution_venue` 기록 의무 — `check_trade_log_gate.py` 하드 차단 유지. **추론은 "무엇을 살지"를 앞당길 뿐, "검증 없이 체결"을 허용하지 않는다** |
| lessons 스키마에 `다음 추론 시 고려` 필드 추가 | ✅ 조건부 | `build_lessons_index.py:26` 의 `NEXT_RULE_RE` 가 `**다음 적용 룰**`·`**다음 진입 시 반영할 룰**` 을 파싱 중 → 신규 라벨 **`**다음 추론 시 고려**`** 를 정규식에 추가(파서 계약 보존) |
| 예측 미반영 감시는 기존 `check_lessons_applied.py` 재사용 | ✅ | "미반영 마커→haystack grep" 메커니즘이 그대로 적용됨. 신규 스크립트 불필요 |

**판정: 전 항목 부합.** 단 "조건부" 3건(체크리스트 크기 상한·파서 정규식 확장·선제매매 게이트 불변)을 구현에 포함한다.

---

## 2. 핵심 설계 — 선제적 추론 루프 4단계

자기보완 루프(종가 오차→분류→lessons→다음 회피)와 **대칭**으로 도는 사이클:

```
①추론(INFER)  →  ②선제 액션(ACT)  →  ③검증·채점(SCORE)  →  ④학습·환류(LEARN)
   ↑                                                                    │
   └──────────── inference_checklist.md (다음 추론 직전 강제 읽기) ◀────┘
```

### ① 추론 (INFER) — 각 routine 의 새 단계 §X-INFER
종합 상황을 읽어 **검증 가능한 예측**을 1~3개 만든다. 단순 시황 서술이 아니라 다음 스키마로 `inference_log.jsonl` 에 적재:

```json
{
  "ts": "2026-06-24T00:00:00+09:00",
  "slot": "00:00",
  "id": "inf-2026-06-24-0000-1",
  "subject": "KOSPI_open_gap | ticker:005930 | sector:반도체 | macro:PCE",
  "prediction": "KOSPI 개장 -1.0~-2.5% 갭다운",
  "horizon": "09:00",                          // 언제 검증되는가 (검증 슬롯)
  "confidence": 0.55,                          // 0~1
  "factors_considered": ["미장 마감 -1.2%", "원달러 1,553", "외국인 매도 우위"],
  "assumptions": ["PCE 컨센 부합", "이란 협상 진전 없음"],
  "key_uncertainty": "지정학 [진행형] — 05:00까지 역전 가능",
  "preemptive_action": {"tier": 1, "what": "삼성전자 손절 이격 재확인·트레일링 한 칸 타이트", "trade_logged": false},
  "checklist_refs": ["갭다운 버퍼 룰", "지정학 진행형 ±2.5%"]   // ④에서 읽은 항목 — 실제 적용 증빙
}
```

- **반드시 `inference_checklist.md` 를 먼저 읽고** 과거에 빗나간 요인을 `factors_considered`/`assumptions` 에 반영한다(`checklist_refs` 로 증빙). 이것이 "다음 추론 때 참고" 의 실행부.
- 자정 갭 예측·18시 if-then 은 **이 스키마로 흡수**된다(중복 신설 아님 — 기존 서술을 구조화).

### ② 선제 액션 (ACT) — 액션 사다리 (§3 상세)
예측의 `confidence` 와 데이터 품질에 따라 **허용되는 선행 행동 등급**을 정한다. 0~2 tier + 금지선.

### ③ 검증·채점 (SCORE) — `score_inferences.py` + routine 내 즉시 판정
- **즉시 판정**: 예측의 `horizon` 슬롯 routine 이 실측과 대조해 `outcome`(hit/partial/miss)+`miss_attribution` 을 같은 로그 줄에 patch(append-only면 결과 줄 추가).
- **주간 채점**: `score_inferences.py`(일 20시 `sunday_policy_review` §0-D 신설)가 적중률을 **슬롯별·subject 종류별·confidence 구간별·선제액션 tier별 손익**으로 집계 → `state/inference_scorecard.json`. `MIN_SAMPLES`(5) 미만이면 채점 보류 명시.
- 채점의 핵심 산출: **빗나간 예측의 `miss_attribution`** — "어떤 요인을 안 봤나/가정이 왜 틀렸나"의 분류.

### ④ 학습·환류 (LEARN)
- miss → `lessons.md` 에 **신규 분류 `선제추론오차`** 항목 + **`**다음 추론 시 고려**`** 필드(놓친 요인을 다음 체크리스트로).
- `build_inference_checklist.py` 가 lessons 의 `선제추론오차` 항목 + `inference_scorecard.json` 의 반복 miss 요인을 **응축**해 `state/inference_checklist.md`(상한 40줄) 재생성 → ①이 다음 회차에 읽음.
- 적중률이 구조적으로 낮은 subject/요인은 sunday_policy_review 가 **policy 패치 또는 액션 tier 강등**으로 codify(자기보완 루프의 codify 와 동일 절차).

---

## 3. 선제 액션 사다리 (가장 중요 — 보수성 보존의 핵심)

`policy.proactive_inference.action_ladder` 신설. **예측만으로 올라갈 수 있는 천장**을 못박는다.

| Tier | 허용 행동 | 조건 | 되돌림성 | 기존 게이트 |
|---|---|---|---|---|
| **0 — 준비(항상 허용)** | if-then 조건부 트리거 작성, 후보 사전 스테이징, 추론 기록 | 없음 | 완전 | (현행과 동일) |
| **1 — 리스크 감소(허용)** | 예측된 **악재** 앞에서 손절 타이트닝·트레일링 강화·부분 익절·신규 진입 보류 | `confidence ≥ 0.5` | 높음(리스크만 감소) | 청산은 `pre_trade_gate` 통과. 가격 fresh/web_verify |
| **2 — 기회 probe(게이트)** | 예측된 **호재/촉매** 앞에서 **probe 진입(축소비중 50%·ATR 타이트 손절)** | `confidence ≥ 0.65` **AND** 데이터 fresh 또는 web_verified **AND** heat 잔여 충분 **AND** 레짐 bull↑ | 보통(probe=소액) | **전부 통과 필수**: `new_entry_freshness_rule`·`trade_provenance_gate`·`reentry_discipline`·`portfolio_heat` |
| **금지선** | 미검증·묵은 가격 선체결, 전액 사이즈 추측 베팅, 게이트 우회 '예외 자가면제' | — | — | 6/5·6/8 사고 재발 방지 — `source_provenance_gate` 가 하드 차단 |

핵심: **Tier 2조차 "추측으로 산다"가 아니다.** 추론은 _후보 우선순위와 타이밍_ 을 앞당기지만, 체결가는 여전히
fresh/검증 가격이어야 하고 사이즈는 probe 다. "먼저 액션"의 공격성은 **Tier 1(선제 방어)** 에서 가장 크게 발휘된다 —
이쪽은 리스크를 줄이는 방향이라 빗나가도 손실이 작다(틀린 방어의 비용 = 약간의 기회비용, 틀린 공격의 비용 = 원금).

---

## 4. 신규/변경 산출물

### 신규 파일
| 파일 | 역할 | 패턴 출처 |
|---|---|---|
| `state/inference_log.jsonl` | 예측 원장(라인당 1예측, 결과 patch 줄 포함) | `target_estimate_log.jsonl` |
| `state/inference_scorecard.json` | 주간 채점 통계 + 리뷰 체크리스트 + 리포트 MD | `estimate_scorecard.json` |
| `state/inference_checklist.md` | 다음 추론 직전 읽는 **응축 체크리스트**(상한 40줄, 핫패스) | `lessons_index.json`(파생물 개념) |
| `scripts/score_inferences.py` | 예측 vs 실측 채점기(의존성 0) | `score_target_estimates.py` |
| `scripts/build_inference_checklist.py` | lessons+scorecard → checklist 응축(의존성 0) | `build_lessons_index.py` |

### 변경 파일
| 파일 | 변경 |
|---|---|
| `config/policy.json` | `proactive_inference` 블록 신설: `action_ladder`(tier 조건), `confidence_thresholds`, `min_samples`, `checklist_max_lines`, `inference_logging`(어느 슬롯이 무엇을 예측 의무) |
| `state/lessons.md` | 분류 체계에 **`선제추론오차`** 추가, 누적 카운터에 1행, 항목 스키마에 **`**다음 추론 시 고려**`** 필드 |
| `scripts/build_lessons_index.py` | `NEXT_RULE_RE` 에 `다음 추론 시 고려` 추가(파서 계약 확장) |
| `scripts/audit_pipeline.py` | `inference_checklist.md` 크기 래칫 감시 + `inference_log` 적재 누락 WARN(예측 의무 슬롯이 안 적었을 때) + **적중률 모니터**(주간 적중률 임계 하회 시 WARN) |
| `prompts/*.md` | 각 슬롯에 §X-INFER(추론·기록)·§X-SCORE(직전 슬롯 예측 채점) 단계 삽입(§5) |
| `prompts/sunday_policy_review.md` | §0-D 신설: `score_inferences.py`·`build_inference_checklist.py` 실행 → 적중률 리뷰·tier 강등·codify |
| `scripts/check_trade_log_gate.py` | (옵션) 선제 매매 trade_log 에 `inference_id`·`preemption_tier` 필드 기록 강제(추적성) |
| `README.md`·`docs/file_references.md` | 선제 추론 루프 문서화 |

---

## 5. 프롬프트별 변경 (슬롯 매핑)

선제 추론은 "예측→검증" 사이클이므로 **앞 슬롯이 예측, 뒤 슬롯이 채점** 하도록 배치한다.

| 슬롯 | INFER(예측) | SCORE(직전 예측 채점) | 주 액션 tier |
|---|---|---|---|
| **00:00** | 개장 갭·야간 영향 예측(기존 §2-1 흡수) + checklist 읽기 | — (전일 18시 예측은 09시가 채점) | Tier 0~1 (장 마감 — 코멘트·경보만) |
| **09:00** | 장중 흐름·종가 방향 예측 | **자정 갭 예측 채점**(기존 §1-0 구조화) + 전일 18시 if-then 판정 | Tier 0~2 (정규장) |
| **12:00** | 마감 방향 재추론(오전 흐름 반영) | 09시 예측 중간 점검 | Tier 0~1 |
| **15:00** | 종가·익일 갭 예측 | 12시 예측 점검 | Tier 0~1 (종가청산만) |
| **18:00** | **내일 시나리오 if-then**(기존 §4 흡수, 스키마化) | **당일 전 예측 채점** → miss→lessons `선제추론오차`+`다음 추론 시 고려` | Tier 0 (마감 후) |
| **일 20:00** | — | `score_inferences.py`+`build_inference_checklist.py` 실행·주간 적중률 리뷰·codify | (정책 패치) |

**18:00 §3 자기보완 확장** (현행 종가 오차 분류 옆에 추가):
- 당일 `inference_log` 의 `horizon≤오늘` 예측을 전부 실측 대조 → `outcome`/`miss_attribution` patch.
- miss 1건당 lessons 신규 항목:
  ```
  ### YYYY-MM-DD HH:MM / [subject] — 선제추론 빗나감
  - 분류: 선제추론오차
  - 예측: ... / 실제: ... (적중도: miss/partial)
  - 미흡했던 부분: (어떤 요인을 안 봤나 / 어떤 가정이 왜 틀렸나 — 1~2줄)
  - **다음 추론 시 고려**: (다음 체크리스트에 올릴 구체 요인 — build 스크립트가 수집)
  - 선제 액션 결과: tier N 행동이 도움/무해/유해였나 1줄 (tier 강등 근거)
  - 분류 신뢰도: [높음|보통|낮음]
  ```

**00:00/09:00 §X-INFER 머리에 강제 1줄** (자기보완 루프의 "lessons 먼저 읽기" 와 대칭):
> "추론 직전 `state/inference_checklist.md` 를 읽고, 과거 빗나간 요인을 이번 `factors_considered`/`assumptions` 에 반영했음을 `checklist_refs` 로 증빙한다."

---

## 6. 리포트 노출 (사용자가 보는 면)

운영 지표 나열 금지 원칙(기존)을 지키면서 **선제 추론을 사람 말로** 드러낸다:
- **한눈에 보기**에 1줄: `선제 추론: [예측 한 줄] (확신 중간) → [먼저 한 행동]`. (예측이 없으면 생략)
- 09시 "📝 오늘의 이야기" 1문단: "자정에 -1~2% 갭다운을 예상해 어제 삼성 손절을 한 칸 당겨뒀는데, 실제로는 ○○로 빗나갔다 — 다음엔 □□까지 본다." → **빗나감의 자기고백이 곧 학습 증빙.**
- 18시 "오늘 배운 것"에 선제 추론 적중/빗나감 1줄(기존 "오늘 판단을 바꾼 교훈" 줄과 병렬).
- 적중률 통계·scorecard 수치는 리포트에 나열하지 않는다(일요일 리뷰·state 파일에만).

---

## 7. 단계별 구현 로드맵

**Phase 1 — 원장·스키마 (행동 변화 0, 관측만)**
1. `inference_log.jsonl` 스키마 확정 + `policy.proactive_inference.inference_logging`(어느 슬롯이 예측 의무).
2. 00:00·09:00·18:00 프롬프트에 §X-INFER 기록 단계만 추가(기존 갭 예측·if-then 을 스키마로 적재). **액션 tier 0만** — 아직 새 매매 없음.
3. lessons 분류·카운터·스키마 필드 추가 + `build_lessons_index.py` 정규식 확장(+출력 diff 검증).
→ 1~2주 예측이 쌓인다(채점 표본 확보).

**Phase 2 — 채점·환류 (학습 루프 가동)**
4. `score_inferences.py` + `build_inference_checklist.py` 작성, sunday_policy_review §0-D 연결.
5. 18:00 §3 에 즉시 채점·`선제추론오차` 기록 추가.
6. `inference_checklist.md` 생성 → 00:00/09:00 INFER 단계가 읽기 시작(환류 폐곡선 완성).
7. audit 에 checklist 크기·적재 누락·적중률 WARN 추가.

**Phase 3 — 선제 액션 (보수적 개방)**
8. `action_ladder` Tier 1(리스크 감소) 먼저 허용 — 빗나가도 손실 작은 쪽부터.
9. 표본 누적·적중률이 임계(예: confidence≥0.65 구간 방향적중 ≥60%) 충족 확인 후 **Tier 2 probe** 개방. 미달이면 Tier 0~1 유지.
10. CI 게이트에 `inference_id`/`preemption_tier` 추적 필드(옵션).

> **게이트 원칙**: Phase 2 의 적중률이 "동전 던지기 수준"이면 Phase 3 를 열지 않는다 — 채점이 선제 액션의 자격을 통제한다(`score_target_estimates` 가 추정식 패치를 통제하는 것과 동일).

---

## 8. 리스크 · 완화

| 리스크 | 완화 |
|---|---|
| 추측 매매로 손실(가장 큼) | 액션 사다리 천장·probe 사이즈·전 게이트 통과·Tier 2는 적중률 입증 후 개방(Phase 3 게이트) |
| 콘텍스트 예산 위배(핫패스 비대화) | 원장은 jsonl(핫패스 아님), 체크리스트만 핫패스+상한 40줄+audit 크기 래칫 |
| 예측 과신(소표본) | `MIN_SAMPLES=5`·confidence 구간별 채점·"채점 보류" 명시 |
| 빗나감 후 즉석 룰 래칫 | 체크리스트 항목도 `lessons_rule_sunset`(기본 5거래일) 적용 — 검증 안 된 선제 룰 영구화 금지 |
| 파서 계약 깨짐 | `build_lessons_index`/`check_lessons_applied` 편집 전후 출력 diff 검증(콘텍스트 압축 계획서와 동일 안전절차) |
| 선제 방어가 승자 조기 절단(6/10 교훈 재발) | Tier 1 트레일링은 `trailing_stop` 2단 구조 준수 — '활성=즉시 매도' 금지(6/18 교훈) |

---

## 9. 한 줄 요약

기존 "종가 오차 → 자기보완" 루프와 **대칭**으로 "상황 추론 → 선제 액션 → 채점 → 학습(다음 추론 체크리스트)"
루프를 **검증된 패턴(jsonl 원장·채점 스크립트·scorecard·lessons codify·CI 게이트)으로** 추가한다.
"먼저 액션"은 **probe·리스크감소로 제한된, 전 게이트를 통과하는** 행동으로 정의하고, **채점 적중률이 그 공격성의
자격을 통제**한다 — 빗나간 예측은 "다음 추론 시 고려" 로 구조화돼 다음 회차 추론 직전에 강제 참조된다.
