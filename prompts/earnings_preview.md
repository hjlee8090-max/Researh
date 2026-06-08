# Phase 2 — earnings-preview (실적 발표 전 시나리오 + 발표 후 자기채점)

> equity-research 플러그인의 `earnings-preview` 채용. **이벤트 기반** 모듈이라 독립 시각 슬롯이 아니라
> catalysts 의 실적 촉매(`type=earnings_report`)가 임박/통과할 때 **0900·1800 routine 이 이 스펙을 호출**한다.
> 정책 토글: `policy.earnings_preview`. 입력: `config/catalysts.json`(언제) · `state/consensus.json`(예상치) ·
> `config/watchlist.json.stocks[].thesis`(논리) · `state/fundamentals.json`(발표 후 실제값).
> 산출/상태: `state/earnings_preview.json` (active 프리뷰 + scorecard).

본 산출물은 학습·시뮬레이션 용도이며 실제 투자 권유가 아니다.

---

## 0. 언제 동작하나 (트리거)

`config/catalysts.json` 의 `generated_events`+`manual_events` 중 `type=earnings_report`(또는 `earnings`) 이벤트를 보고:

| 단계 | 조건 | 수행 routine | 동작 |
|---|---|---|---|
| **PREVIEW** (D-1) | 이벤트 `date`(또는 `window` 시작)가 **D-`preview_lead_days`(기본 1) 이내** + 아직 `earnings_preview.json.active` 에 없음 | 1800 (주), 0900 (재확인) | §1 시나리오 3종 생성 → `active` 적재 + 리포트 표출 |
| **SCORE** (D+0~D+2) | `active` 항목의 `earnings_date` 가 **오늘 이하**이고 실제 실적이 확보됨 | 1800 (주), 0900 (보강) | §2 실제값 대조 → `scorecard` 적재 + lessons + thesis 갱신 → `active` 에서 제거 |

- 보유 종목은 PREVIEW·SCORE **의무**. 후보 종목은 PREVIEW **권고**(진입 보류 판단 보조), SCORE 는 보유 전환 시만.
- 추정일(`confirmed=false`)은 PREVIEW 를 **잠정**으로 생성하되, 0900 에서 웹검색으로 확정일을 잡으면(`manual_events` 승격) 날짜를 정정한다.
- `policy.earnings_preview.enabled=false` 면 전체 건너뜀.

---

## 1. PREVIEW — 발표 전 시나리오 3종 생성 (D-1)

### 1-1. 기준선(baseline) 확보
`state/consensus.json.tickers.<ticker>` 에서 컨센 기준선을 읽는다:
- `eps_consensus`(주당 추정 EPS, **beat/miss 1차 기준**), `target_price`(컨센 목표주가), `opinion_text`/`opinion_score`(투자의견), `n_estimates`(추정기관수), `consensus_date`(컨센 기준일).
- **신선도 점검**: `consensus_date` 가 2개월 이상 묵었거나 `stale=true` 거나 해당 종목이 없으면 → 웹검색("[종목명] [분기] 영업이익 컨센서스", "[종목명] 실적 전망")으로 보강하고 `baseline.source` 에 출처·관측일을 명시. **출처 없는 추정 금지**(미확보면 `baseline.eps_consensus=null` + low confidence).
- 영업이익(OP) 컨센은 consensus.json 에 없으므로(후속 확장) 웹검색으로 보강 시도하되 없으면 EPS 기준으로 진행.

### 1-2. 시나리오 3종 (beat / inline / miss)
임계는 `policy.earnings_preview.surprise_thresholds`(기본 ±10%) 기준. 각 시나리오에 다음을 채운다:
- **cond**: 컨센 대비 실제 실적 조건 (예 "EPS 컨센 +10%↑").
- **prob**: 확률(합=1.0). **균등 1/3 금지** — `thesis.conviction`·최근 모멘텀(`market_snapshot` 5d/60d)·섹터 상태(`themes.json`)·발표 전 우호/비우호 시그널을 반영해 차등 배분하고, 근거 1줄.
- **price_reaction**: 예상 주가반응 밴드. 기본 휴리스틱(대형주): beat `+3~6%` / inline `±1~2%` / miss `-4~8%`. **변동성 큰 종목**(`market_snapshot.volatility.atr14` 高)이면 밴드를 넓힌다.
- **action**: **사전 확약 액션(플레이북)** — 발표 당일 감정 매매를 막는 핵심. 종가청산 정책에 맞춰 "다음 종가 청산/축소 후보" 형태로.
  - beat: 홀드·목표가 상향 검토(단 **추격매수 금지** — 갭상승 후 진입은 R/R 악화), 트레일링 강화 여지.
  - inline: 홀드 유지, 기존 thesis·손절 그대로.
  - miss: **thesis 의 `earnings_miss` invalidation(가정오류) 발동 점검** → hard 면 청산·축소 1순위, soft 면 weakening.
- **thesis_effect**: 강화 / 유지 / 약화·무효.

### 1-3. thesis 연결 (Part C)
- `watchlist.stocks[].thesis.invalidation[]` 중 `linked_catalyst == 이 이벤트 id` 인 항목(주로 `earnings_miss`)을 찾아 `linked_thesis_invalidation` 에 기록한다. miss 시나리오의 발동 대상이 된다.

### 1-4. 적재 + 표출
- `state/earnings_preview.json.active[]` 에 항목 추가(이미 있으면 갱신). 스키마는 §3.
- 리포트(해당 슬롯)에 **"📑 실적 프리뷰"** 박스: 종목·발표일·기준선(EPS 컨센)·시나리오 3종 표(확률·예상반응·액션) 1개.
- 보유 종목 D-1 이면 1800 §4 `next_day_plan` 에 "발표 D-1 — 추가매수 금지, 시나리오별 플레이북 준비" 1줄. (catalysts 경보와 중복되면 합쳐 1줄)

---

## 2. SCORE — 발표 후 자기채점 (D+0~D+2)

### 2-1. 실제값 확보
- `state/fundamentals.json.tickers.<ticker>` 가 이번 분기로 갱신됐으면 그 `operating_profit`/`earnings_signal` 사용. 아직 후행이면 웹검색("[종목명] [분기] 잠정실적 영업이익", "[종목명] 어닝")으로 실제 발표치를 확보(출처·발표일 명시).
- 실제값 미확보면 SCORE 를 다음 routine 으로 이연하고 `active` 유지(억지 채점 금지).

### 2-2. 판정
- **surprise_pct** = (실제 − 컨센) / |컨센| × 100 (EPS 우선, OP 보강 가능 시 함께).
- **realized_scenario** = surprise_pct 를 §1-2 임계로 분류(beat/inline/miss).
- **price_reaction_actual_pct** = 발표 후 1거래일 종가 변동(웹/스냅샷, 출처 명시).
- **hit 판정**:
  - `scenario_called` = 예측 최고확률 시나리오 == realized_scenario?
  - `price_dir_called` = 예측 price_reaction 방향/밴드에 실제가 들어왔나?

### 2-3. 자기보완 반영 (핵심)
- **lessons.md**: §1 의 컨센/시나리오가 크게 빗나갔으면(특히 우리가 prob 를 잘못 배분했거나 컨센 자체가 틀림) `분류: 가정오류`(컨센·가정 오류) 또는 적절한 4분류로 1줄 기록 + "다음 추천 시 룰". 적중했어도 **누적 hit-rate** 갱신용으로 scorecard 에 남긴다.
- **thesis 갱신(Part C 닫기)**: realized_scenario=miss 이고 `linked_thesis_invalidation` 이 hard 면 → 해당 종목 `thesis.status=invalidated` 로 보고 1800 §2-4·§4 청산·축소 후보 처리. inline/beat 면 thesis 강화/유지로 `last_review_ts` 갱신.
- **scorecard 적재** → `active` 에서 해당 항목 제거.

### 2-4. 누적 메타-학습 (주말)
- `sunday_policy_review` 가 `scorecard` 의 누적 hit-rate(시나리오 적중률·가격방향 적중률)를 점검해, 낮으면 `policy.earnings_preview.surprise_thresholds`·price_reaction 휴리스틱·prob 배분 가이드를 조정 후보로 제안한다.

---

## 3. state/earnings_preview.json 스키마

```jsonc
{
  "version": "1.0",
  "as_of": "ISO8601",
  "active": [
    {
      "id": "005930-2026Half-earnings",        // catalysts 이벤트 id 와 동일
      "ticker": "005930", "name": "삼성전자",
      "earnings_date": "2026-08-14",
      "confirmed": false,                        // catalysts 의 confirmed 복사
      "generated_at": "2026-08-13T18:00:00+09:00",
      "baseline": {
        "eps_consensus": 42998, "op_consensus": null,
        "target_price": 415200, "opinion": "매수",
        "n_estimates": 25, "consensus_date": "2026/06/05",
        "source": "consensus.json", "confidence": "high|medium|low"
      },
      "scenarios": [
        {"name":"beat","cond":"EPS 컨센 +10%↑","prob":0.30,"price_reaction":"+3~6%","action":"홀드·목표 상향 검토·추격매수 금지","thesis_effect":"강화"},
        {"name":"inline","cond":"컨센 ±10%","prob":0.45,"price_reaction":"±1~2%","action":"홀드 유지","thesis_effect":"유지"},
        {"name":"miss","cond":"컨센 -10%↓·가이던스 컷","prob":0.25,"price_reaction":"-4~8%","action":"earnings_miss invalidation 점검→축소/청산 후보","thesis_effect":"약화/무효"}
      ],
      "prob_rationale": "컨빅션 3·5d 모멘텀 약세·반도체 섹터 강세 → miss 소폭 상향",
      "linked_thesis_invalidation": "earnings_miss"
    }
  ],
  "scorecard": [
    {
      "id":"005930-2026Q1-earnings","ticker":"005930","name":"삼성전자",
      "earnings_date":"2026-05-15","scored_at":"2026-05-15T18:00:00+09:00",
      "baseline_eps":40000,"actual_eps":47225,"surprise_pct":18.1,
      "realized_scenario":"beat","top_predicted":"inline",
      "price_reaction_actual_pct":4.2,"price_reaction_predicted":"±1~2%",
      "hit":{"scenario_called":false,"price_dir_called":false},
      "thesis_status_after":"강화","lesson_ref":"lessons.md 2026-05-15 삼성전자",
      "source":"DART 잠정 + 웹"
    }
  ],
  "meta": {"preview_count":0,"scored_count":0,"scenario_hit_rate":null,"price_dir_hit_rate":null}
}
```

규칙: `active` 는 발표 후 SCORE 되면 `scorecard` 로 이동. 파일이 없으면 PREVIEW 시 새로 만든다. 이전 시간대 리포트 파일은 수정 금지 원칙 그대로.

---

## 4. 한계·주의
- **컨센 OP 추정치 미수집**(EPS·목표주가·투자의견만) → beat/miss 1차 기준은 **EPS**. OP 는 웹 보강 또는 후속 확장.
- 한국 컨센은 갱신 빈도·커버리지가 종목마다 달라 `n_estimates` 적고 `consensus_date` 묵으면 confidence 를 낮춘다.
- price_reaction 밴드는 **휴리스틱**이다 — 실제와 다르면 그 자체가 scorecard 학습 재료. 단정하지 말 것.
- 발표 당일 갭·변동성에도 **종가청산 정책 유지**(장중 추격/투매 금지, 다음 종가 기준).
