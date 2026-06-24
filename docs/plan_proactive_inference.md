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

---

# 10. 재검토 — "한발 빨리 움직여 돈 버는 구조" 관점 보강 (2026-06-24)

> §0~9 는 안전한 학습 루프를 잘 설계했지만, **"돈을 버는·시장보다 빠른" 목적에는 방어로 치우쳐 있다.**
> 이 레포의 실증 실패는 *예측이 틀려서 잃은 것*이 아니라 **사지 못해 놓친 수익(미배치·기회비용)** 이다
> (lessons: 강세장 2주+ 현금 100%, cash 86% 4일째, 6/23 09시 "신규 진입 상시 봉쇄"). 아래 6개 보강이
> §3 사다리·§7 로드맵보다 **우선**한다 — 이것이 없으면 선제 추론은 작동조차 못 한다.

## 10-A. (P0·최우선) 실행 병목부터 푼다 — 추론보다 먼저
선제 추론의 Tier 2 probe 는 **기존 가격검증 게이트에 똑같이 막힌다**(6/23 09시: 세션 HTTP 403 → `pre_trade_check`
가 `live_verify_required` 발령 → 독립 실시간가 미확보 → 진입 상시 봉쇄). 추론을 아무리 잘해도 **체결 경로가 막혀
있으면 돈을 못 번다.** 따라서 다음을 §7 Phase 1 *앞*에 둔다:
- **`pre_trade_gate` 보정**(lessons 6/23 09시 자기제안 채택): `naver 당일자 + 2출처 일치(gap≤1%) + fresh` 스냅샷은
  yahoo 날짜지연(KST 오전 KRX 종가를 전일자 보고)을 **단독 차단 사유로 쓰지 않고** `ok`(booking 허용)로 판정.
  묵은-가격-선체결 금지 원칙은 유지(fresh·2출처 일치일 때만 완화 — stale·단일출처는 그대로 봉쇄).
- **독립 실시간 시세원 확보**(택1): 작동하는 웹 시세 엔드포인트, 또는 KRX_ID/PW Secret. 이것이 "한발 빨리"의 물리적 전제.
- 검증: 게이트 보정 후 `rule_attribution.json.blocked_day` 비율이 떨어지는지(후보 전원 차단 일수↓)를 audit 가 추적.

## 10-B. 선제 커밋(pre-commitment)을 루프의 *본체*로 승격 — 속도 엣지의 정체
"밤에 여유 있게 결정 → 다음 슬롯/장중이 *검증가격에서 조건 충족 시 기계적 즉시 체결*" 이 **속도와 안전을 동시에**
얻는 유일한 구조다. §3 의 Tier 0 '준비(passive)' 를 **능동 사전주문**으로 끌어올린다:
- 18:00/15:00 이 `state/pending_orders.json` 에 **조건부 주문**을 적재: `{trigger: "삼성전자 종가≤320,000 또는 시초≥363,000",
  action: BUY/SELL, size, valid_until, price_source_required: fresh|web_verified, inference_id}`.
- **`check_intraday_alerts.py` 를 '경보 전용'에서 '조건 평가 + 체결 신호' 로 확장**(현재 L7 "경보만 한다"):
  pending_orders 의 트리거를 장중 30분 간격으로 평가해, 충족 + 가격 fresh/web_verified 면 체결 신호를 낸다.
  실제 trade_log 기록은 다음 routine(또는 별도 execute 스텝)이 게이트 통과 후 수행 — **게이트는 그대로, 의사결정만 앞당김.**
- 효과: **18:00→익일 09:00 이연 구멍**(lessons 반복: 후보가 이연 루프에서 죽음)을 닫는다. 결정은 어제, 실행은 개장 즉시.
- 안전성: 사전주문은 *검증 가능한 수치 조건*에서만 발동하므로 §3 금지선(추측 선체결)을 위반하지 않는다 — 오히려
  개장 직후 감정·deliberation 지연을 제거해 if-then 규율을 강화한다.

## 10-C. 채점을 hit-rate 가 아니라 P&L·EV 로 — `rule_attribution` 에 연결
적중률은 돈과 다르다(방향 60% 맞아도 비대칭 페이오프면 잃는다). **채점의 1차 지표를 손익으로 바꾼다:**
- `score_inferences.py` 는 별도 hit-rate 통계를 만들지 말고 **`rule_attribution.py` 의 `by_rule`·`forgone`·
  `expectancy`·`profit_factor` 를 inference_id 별로 결합**한다. 즉 "이 예측에 근거한 선제 액션이 실제 원화 손익에
  얼마 기여했나 / 안 했으면 얼마 놓쳤나(forgone)" 가 채점의 본문.
- 각 예측에 **`expected_value`**(방향확률 × 예상 페이오프 − 비용) 를 기록하고, 실현 EV 와 대조한다. 사이징은
  EV·confidence 에 비례(heat 예산 내 차등) — 현재의 평면 risk-cap 위에 **edge 비례 가중**을 얹는다(Kelly 분수형, 상한은 기존 2%/heat 6%).
- §7 Phase 3 의 Tier 2 개방 게이트도 "방향적중 ≥60%" 가 아니라 **"선제 probe 의 실현 expectancy > 0 AND PF > 1"** 로 바꾼다.

## 10-D. "안 산 것"을 채점한다 — 미배치(기회비용)를 1급 오차로
이 레포의 진짜 병은 false positive(잃는 매매)가 아니라 **false negative(안 사서 놓친 수익)** 다. 방어만 채점하면
영원히 미배치가 교정 안 된다.
- **그림자 예측(shadow)**: 모든 `보류/HOLD/blocked` 결정을 `inference_log` 에 `action: none, shadow: true` 로 적재하고,
  이후 실측으로 "샀더라면" 손익을 forgone 으로 채점. lessons 에 **`기회비용오차`** 분류 신설(기존 `선제추론오차` 와 병렬).
- audit 의 미배치 감시 강화: `blocked_day_rate` + **현금비중 × 강세장 일수** 가 임계 초과면 WARN(강세장 미참여를 매일 표면화 —
  기존 6/8 v2.7 교훈의 채점화).
- 이로써 시스템이 "안 잃기" 와 "벌기" 를 **대칭으로** 최적화한다.

## 10-E. 학습 주기를 주간→당일로 — 다음 아침에 즉시 반영
"한발 빨리" 는 학습 속도에도 적용된다. §4 의 `build_inference_checklist.py` 를 일요일에만 돌리면 빗나간 교훈이 한 주
늦게 반영된다. → **18:00 §3 직후 당일 재생성**(상한 40줄 유지) 해서 **다음날 00:00/09:00 추론이 어제 miss 를 이미 반영**하게 한다.
주간 sunday_policy_review 는 codify(영구 룰 승격)·tier 강등만 담당.

## 10-F. Tier 2 자격을 paper 로 1일차부터 병렬 누적 — time-to-offense 단축
Tier 2(공격) 를 "적중률 입증까지 봉인" 하면 돈 버는 구조가 몇 주 뒤로 밀린다. 대신:
- **1일차부터 모든 Tier 2 후보를 paper(그림자) 체결**로 병렬 기록·채점한다(실자본 무위험). 실현 expectancy>0·PF>1 가
  `MIN_SAMPLES` 충족되는 즉시 해당 subject 종류에 실 Tier 2 를 개방 — **검증과 수집을 직렬이 아니라 병렬로** 돌려 개방을 앞당긴다.
- 즉 Phase 3 를 기다리지 않고, Phase 2 와 동시에 paper-offense 를 돌려 "벌 자격" 을 최단 시간에 입증한다.

## 10-G. 보강 우선순위 (수정된 로드맵)
| 순위 | 항목 | 근거 |
|---|---|---|
| **P0** | 10-A 실행 게이트 보정 + 실시간 시세원 | 이게 막히면 나머지 전부 무의미(probe dead-on-arrival) |
| **P0** | 10-B 선제 커밋(pending_orders + intraday 체결신호) | 속도 엣지의 본체 + 이연 구멍 차단 |
| **P1** | 10-C P&L·EV 채점(rule_attribution 결합) + 10-D 기회비용 채점 | "벌기" 를 측정 가능하게 — 측정 못 하면 못 번다 |
| **P1** | 10-F paper-offense 병렬 | 공격 개방을 최단화 |
| **P2** | 10-E 당일 체크리스트 재생성 | 학습 속도 |
| **P2** | §0~9 의 안전 사다리·환류(그대로 유효) | P0/P1 의 보호막 |

> **수정된 한 줄 요약**: 돈 버는 구조의 순서는 ①막힌 실행 경로를 먼저 뚫고(10-A) ②결정을 앞당겨 검증가격에서
> 기계 체결하는 선제 커밋을 본체로 삼고(10-B) ③적중률이 아닌 **실현 손익·기회비용**으로 채점하며(10-C/D)
> ④공격 자격을 paper 로 병렬 입증(10-F)하는 것이다. §0~9 의 안전 사다리는 *이 공격 엔진을 감싸는 보호막*이지,
> 그 자체가 목적이 아니다.

---

# 11. 통합 점검 · 하루 시뮬레이션 · 페르소나 리뷰 (2026-06-24)

> 관점: "새 루프가 **기존 파이프라인 배선에 실제로 끼워지는가**, 그리고 **사용자(카톡·HTML)에게 어떻게 보이는가**."
> 추상 설계가 아니라 데이터 흐름·파서 계약·CI·노출 경로로 검증한다.

## 11-A. 연결 지도 — 기존 흐름에 어디서 접붙는가

기존 일일 사이클: `00:00 → 09:00 → 12:00 → 15:00 → 18:00 → (일)20:00/21:00`. 각 슬롯은 git pull→스크립트→리포트→commit/push,
그리고 `build_and_notify.yml` 이 `reports/*.md` → HTML(Pages) + `send_kakao.py`(슬롯 요약) 발송.

| 새 부품 | 접붙는 기존 지점 | 핫패스? | 사용자 노출 |
|---|---|---|---|
| `inference_log.jsonl` | `trade_log.jsonl` 옆 — 같은 commit 에 포함. 전방가격은 **`exit_tracking.json` + `fetch_market_data.collect_tickers` 재사용**(rule_attribution 과 동일 캐시) | ❌ | 직접 노출 안 됨(채점 재료) |
| `inference_checklist.md` | 매 routine §0 "lessons 먼저 읽기" **바로 다음 줄에 끼움** | ✅(신규) | 노출 안 됨(내부 입력) |
| `pending_orders.json` | 18/15시가 작성 → `check_intraday_alerts.py`(intraday_monitor.yml)가 평가 | ❌ | 카톡 장중 경보로 "트리거 임박" 1줄 |
| `score_inferences.py` | `sunday_policy_review` §0-C 옆(0-D 신설). **출력은 `rule_attribution.json` 와 결합** | — | 일요일 리포트만 |
| `build_inference_checklist.py` | 18:00 §3 직후(당일) + 일 20시 | — | 노출 안 됨 |
| lessons `선제추론오차`/`기회비용오차` | 기존 `lessons.md` 분류·카운터·`build_lessons_index` 파서 | ✅ | 18시 "오늘 배운 것" 1줄 |
| 카톡 노출 1줄 | `send_kakao.py` 가 파싱하는 **`### 한눈에 보기` 불릿** | — | `- 선제 추론: [예측] → [먼저 한 행동]` |

**핵심 접붙임 3개**: ①채점 재료 전방추적은 이미 있는 `exit_tracking`/`collect_tickers` 를 그대로 탄다(신규 인프라 0).
②사용자 노출은 새 섹션을 만들지 않고 **기존 `한눈에 보기` 불릿 1줄 + 블로그 산문**에 녹인다(파서 계약 보존).
③학습 입력은 lessons 핫패스에 **줄 단위로만** 추가(체크리스트는 상한·ratchet 으로 예산 방어).

## 11-B. 하루 시뮬레이션 — 예측이 한 바퀴 도는 모습 (그리고 내 폰에 뜨는 것)

시나리오: 6/24(수), 전날 '검은 화요일'(-9.99%) 직후. 현금 100%. 6/25 PCE 분수령.

| 슬롯 | 내부에서 일어나는 일 | **내 카톡에 뜨는 것** |
|---|---|---|
| **00:00** | checklist 읽음("폭락 다음날=추격 금지", "PCE [진행형] ±2.5%"). 미국장 반등 +1.2% 관측 → 예측 적재 `{subject: KOSPI_open_gap, pred: +0.5~1.5% 갭업, conf 0.5, key_uncertainty: PCE 전 눈치, action tier1: 신규진입 보류 유지}` | 🌙 "밤사이 미국 반등. 한국 갭업 예상하나 PCE 전이라 추격은 보류 — 내일 아침 확인." |
| **09:00** | 자정 예측 **채점**: 실제 시가 +0.8% → hit. checklist 재확인 → 비과열 후보 1종 발굴, **conf 0.62 < Tier2 문턱(0.65)** → 실 진입 대신 **paper probe** 기록(10-F). pending_orders 없음 | 🌅 "갭업 적중(+0.8%). 다만 반등 1일차라 실매수는 보류, 후보 1종은 모의로만 담아 검증 시작." |
| **12:00** | 09시 예측("오후 차익실현 되돌림 가능") 중간 점검. paper probe +1.1% 평가 | 🕛 "오전 강세 유지. 모의 후보 +1.1% — 내일도 살아있으면 실매수 검토." |
| **15:00** | 종가·익일 예측. **선제 커밋 작성**: `pending_orders.json` = `{trigger: 6/25 시초 ≥ +0.3% AND PCE 부합, action: BUY 후보, size: probe, price_source_required: web_verified, valid_until: 6/25 09:30}` | 🔔 "내일 PCE 부합 + 갭업이면 후보를 개장 직후 자동 검토하도록 예약해 둠." |
| **18:00** | 당일 전 예측 **일괄 채점**(rule_attribution 결합) → 갭 예측 hit, 되돌림 예측 partial. **paper probe 의 forgone/EV** 기록. miss 없으면 lesson 0건. **checklist 당일 재생성**(10-E) | 📊 "오늘 예측: 갭업 적중·되돌림 절반. 모의 후보로 +X원어치 '벌었을' 기회 확인 — 내일 조건 맞으면 실행." |
| **(다음날) 09:00** | `check_intraday_alerts`/routine 이 pending_orders 트리거 평가 → PCE 부합·시초 +0.5% 충족 + web_verified → **게이트 통과 후 실 probe 체결**(trade_log `execution_venue: regular`, `inference_id` 기록) | 🌅 "어제 예약대로 PCE 통과·갭업 확인 → 후보 OOO 모의검증 끝, 실매수 probe 체결." |

→ 사용자 체감: **"어제 이렇게 예상해서 이렇게 해뒀고, 오늘 맞았는지/틀렸는지"** 가 매 카톡에 1줄 스토리로 누적된다.
숫자(EV·PF·적중률)는 폰에 안 뜨고 **일요일 리포트·state 파일**에만 쌓인다.

## 11-C. 통합 마찰 — 실제로 부딪히는 곳 (구현 전 해결 필수)

| # | 마찰 | 해결 |
|---|---|---|
| 1 | **장중 자동체결 ↔ `trade_timing_gate`·`market_hours`**: intraday cron 이 trade_log 에 체결을 쓰면 정규장 시간/venue 검증과 충돌, 또 cron 은 지금 trade 커밋을 안 한다 | pending_orders 트리거는 **체결 '신호'만** 내고, 실제 booking 은 **다음 routine(09시) 또는 경량 execute 스텝**이 `pre_trade_gate` 통과 후 `execution_venue:regular`·세션시각으로 기록. cron 은 신호+카톡까지 |
| 2 | **핫패스 5→6 파일**(6/12 콘텍스트 예산 계획과 정면) | checklist 를 **독립 파일 대신 lessons.md 최상단 '선제추론 체크리스트' 블록**으로 접붙이거나(읽기 1회로 흡수), 독립 시 상한 40줄+`audit_context_budget` ratchet 의무 |
| 3 | **`send_kakao` 슬롯 요약 과밀**: 한눈에 보기 불릿이 늘면 카톡 본문이 길어지고 detect_slot 라인 규칙과 경쟁 | 선제 추론 줄은 **`- 라벨: 값` 평문 1줄**(굵게 금지·콜론 유지), 한줄평 파서 불변. 슬롯당 최대 1줄 |
| 4 | **CI `check_trade_log_gate`**: 선제 체결 trade_log 의 신규 필드 | `inference_id`·`preemption_tier` 는 **Phase 3 까지 옵션**(누락 허용) → 검증 후 required 승격. price_source/venue 게이트는 불변 |
| 5 | **`auto_merge_routines` 커밋 프리픽스**: 장중 신호/체결 커밋이 main 자동머지·카톡에 걸림 | 신호 전용 프리픽스 추가(예: `signal(`) — **카톡 미발송 목록에 등록**(노이즈 차단), 실체결은 기존 routine 커밋에 포함 |
| 6 | **그림자/미배치 채점 입력**: 보류 결정을 일일이 수기 적재하면 누락 | 09시 `candidate_scores.json.ranked` 의 `block_reasons` 보유 항목을 **자동으로 shadow 예측화**(수기 0) |

→ 6개 모두 **기존 메커니즘 재사용 또는 단계적 옵션화**로 풀린다. 새 인프라가 필요한 곳은 #1 의 경량 execute 스텝 하나뿐.

## 11-D. 페르소나 리뷰

**① 초보 구독자 '민지' (카톡만 봄)** — ★★★★☆
- 좋음: "어제 예상→오늘 결과" 1줄 스토리가 흐름을 잡아준다. 빗나가도 솔직히 적으니 신뢰가 간다.
- 우려: 예측이 자주 빗나가면 "맞추지도 못하면서" 피로. EV·PF 숫자가 새어 나오면 바로 이탈.
- **합격 조건**: 카톡엔 *스토리 1줄만*, 빗나감은 "다음엔 □□까지 본다" 로 끝맺어 **학습하는 모습**으로 보이게.

**② 계좌 주인(나) — 통제권·돈** — ★★★☆☆
- 좋음: 결정을 밤에 미리 내려 개장 즉시 실행 → 내가 장 못 봐도 기회를 안 놓침. 미배치 채점이 "왜 안 샀나"를 매일 따짐.
- 우려: **자동 선제 체결이 내 승인 없이 손실**나는 것. Tier 경계가 무너지는 것.
- **합격 조건**: Tier 1(리스크 감소)·pending_orders 청산 트리거는 자동, **Tier 2 실매수는 paper 입증 전까지 '카톡 승인 요청' 후 체결**(반자동). 내가 한 줄로 끌 수 있는 kill-switch.

**③ 파이프라인 엔지니어 'K' — 계약·예산** — ★★★☆☆
- 좋음: 전방추적·노출·학습이 전부 기존 파일에 접붙어 신규 인프라 최소. 파서 계약 존중.
- 우려: #1(장중 체결 게이트)·#2(핫패스 6번째)가 진짜 위험. 여기서 무너지면 6/12 예산 회귀·CI red.
- **합격 조건**: checklist 는 lessons 블록으로 흡수(파일 안 늘림), 장중은 신호만·체결은 routine. `build_lessons_index`/`check_lessons_applied` 출력 diff 검증.

**④ 퀀트/리스크 'Q' — 엣지의 실재성** — ★★★☆☆
- 좋음: hit-rate 대신 EV·PF·forgone(rule_attribution) 로 채점하는 방향이 옳다. edge 비례 사이징.
- 우려: **소표본 overfitting**, paper 와 실거래의 슬리피지·체결가정 괴리(낙관 편향).
- **합격 조건**: `MIN_SAMPLES≥5`·confidence 구간별 채점, paper 체결가에 **실제 슬리피지/세금·보수적 체결가정** 적용, Tier2 개방은 expectancy>0 **AND** PF>1 **둘 다**.

**⑤ 회의적 감사자 '보안관' — 실패·게이밍** — ★★☆☆☆ (가장 깐깐)
- 우려 1: **그림자 채점 사후편향** — "샀더라면 다 올랐다" 식 낙관. 하락장 미배치는 오히려 옳았는데 기회비용오차로 과벌점.
- 우려 2: **예측 sandbagging** — 모호하게("시장 변동성 유의") 적어 채점 회피.
- 우려 3: 빗나간 뒤 즉석 룰이 checklist 에 영구 적체.
- **합격 조건**: ①forgone 은 실제 관측 종가로만·**레짐 보정**(하락장 미배치는 감점 면제) ②예측은 **falsifiable 수치+horizon 필수**, audit 가 모호예측 거부 ③checklist 항목도 `lessons_rule_sunset`(5거래일) 적용.

### 종합 판정
- **방향(돈 버는 구조로의 재정렬)**: 5/5 페르소나 동의.
- **즉시 막는 쟁점**: #1 장중 체결 게이트(엔지니어·감사자), Tier 2 자동성(계좌주인) → **"신호는 장중, 체결은 게이트 통과 routine, Tier2는 paper 입증+승인"** 로 셋 다 닫힌다.
- **권고 시작점**: §10-G 의 P0(10-A 게이트 보정 + 10-B 신호/사전주문)부터. 단 **체결은 routine, Tier2는 반자동**을 못으로 박고 출발.
