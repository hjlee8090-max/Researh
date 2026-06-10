# 파이프라인 보강 작업 지시서 (UPGRADE WORKORDER)

> **이 문서는 1회용 작업 지시서다.** `reports/2026-06-10-pipeline-research.md`(진단 리포트)의 권고 P1~P7 + 밸류에이션 앵커(P8)를 실제 코드·정책에 반영하기 위한 실행 순서를 담는다.
> 모든 STEP 완료 후 **STEP 9(기록·폐기)**를 수행하고 이 파일을 삭제한다 — 영구 지식은 policy.json changelog·lessons.md·프롬프트 본문에 남긴다.
> 본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아니다.

---

## 사용법·원칙

1. **STEP 0 → 9 순서대로** 실행한다. STEP 1~5(정책)와 STEP 6~8(코드)은 서로 독립이라 분리 커밋 가능.
2. 각 STEP 은 ▸목적 ▸변경 파일 ▸정확한 변경 내용 ▸검증 ▸완료 기준(DoD) 으로 구성된다.
3. 모든 JSON 수정 후 `python3 -c "import json;json.load(open('<파일>'))"` 로 문법 검증한다.
4. 커밋 프리픽스: 정책 변경 `policy-review:`, 스크립트 신설 `feat:`, 프롬프트 수정 `chore(prompts):`.
5. 기존 **무결성 게이트(source_provenance_gate·web_verify_guard·trade_timing_gate·pre_trade_gate)는 절대 건드리지 않는다** — 검증된 안전장치다.

### 변경 총괄표

| STEP | 내용 | 대상 파일 | 종류 |
|---|---|---|---|
| 1 | 단계경보·손절 ATR 연동 | policy.json, check_intraday_alerts.py, prompts/1200·1500·1800 | 정책+코드 |
| 2 | 트레일링 ATR화 + 50% 부분익절 | policy.json, prompts/0900·1500·1800 | 정책 |
| 3 | 재진입 규율(추격 차단) | policy.json, prompts/0900 | 정책 |
| 4 | 주간 목표 현실화(KOSPI+α) | policy.json, prompts/sunday_strategy·weekend_report | 정책 |
| 5 | 차단 룰 일몰·이벤트 축소·고가주 probe | policy.json, prompts/0900, lessons.md | 정책 |
| 6 | rule_attribution(의사결정 채점) 신설 | scripts/rule_attribution.py(신규), fetch_market_data.py, pipeline_audit.yml, prompts/saturday_review·sunday_policy_review | 코드 |
| 7 | 가격 출처 3원화(pykrx) | fetch_market_data.py, fetch_prices.yml | 코드 |
| 8 | 밸류에이션 앵커(PER/PBR 목표가 상한) | config/valuation.json(신규), scripts/check_valuation_guard.py(신규), policy.json, prompts/0900·1800·sunday_strategy | 정책+코드 |
| 9 | changelog/lessons 기록 → 본 문서 폐기 | policy.json, lessons.md | 마무리 |

---

## STEP 0. 준비·기준선 기록

```bash
git pull --rebase
python3 scripts/audit_pipeline.py            # 시작 전 PASS 확인
python3 scripts/check_trade_log_gate.py      # PASS 확인
python3 scripts/reconcile_portfolio.py       # 정합 확인
```

기준선(변경 전 상태, 검증 비교용): 누적 -0.772% / 실현 -90,439 / PF 0.68 / 평균 주식비중 20.2% / 강제청산 6건·목표도달 0건. *(근거: reports/2026-06-10-pipeline-research.md)*

- [ ] 3개 스크립트 모두 PASS

---

## STEP 1. 단계경보·손절을 ATR 연동으로 (P1)

**목적**: 고정 -5/-7/-10% 경보가 ATR 6% 장세에서 1.2×ATR 노이즈 청산을 유발(손실 4건 전부). 변동성이 클 때만 임계가 자동으로 넓어지게 한다. 평시(ATR 2%대)에는 현행과 동일.

### 1-A. `config/policy.json` — §risk.tiered_alerts 교체

현행 블록:
```json
"tiered_alerts": {
  "yellow_pct": -5.0,
  "orange_pct": -7.0,
  "red_pct": -10.0,
  "yellow_action": "원인 3가지 검색·기록 의무, 함정패턴 cross-check, 비중 유지",
  "orange_action": "보유 비중 50% 즉시 축소 (가상 부분매도)",
  "red_action": "전량 가상 청산"
},
```
아래로 교체:
```json
"tiered_alerts": {
  "mode": "atr_adaptive",
  "yellow_pct": -5.0,
  "orange_pct": -7.0,
  "red_pct": -10.0,
  "atr_multiples": {"yellow": 1.5, "orange": 2.0, "red": 2.5},
  "atr_threshold_hard_floor_pct": -20.0,
  "effective_threshold_rule": "v2.11 — 유효 임계 = max(atr_threshold_hard_floor_pct, min(고정값, -(atr_multiples[tier] × atr_pct))). atr_pct 는 market_snapshot.tickers.<t>.volatility.atr_pct. 예: ATR 6% → orange 유효 임계 = min(-7, -12) = -12%. ATR 2% → min(-7, -4)…가 아니라 min()은 '더 깊은(보수적이지 않은) 쪽'이 아닌 더 음수인 쪽이므로 -7% 유지(평시 현행 동일). atr_pct 결측 시 고정값 폴백. 근거: 2026-05-20~06-09 손실 4건 전부 고정 % 임계의 매크로 노이즈 체결(목표 도달 0건, reports/2026-06-10-pipeline-research.md §1-2).",
  "yellow_action": "원인 3가지 검색·기록 의무, 함정패턴 cross-check, 비중 유지",
  "orange_action": "원인 분류 후 조건부 — (a)개별·섹터 원인 또는 thesis weakening/invalidated 면 보유 비중 50% 축소(가상 부분매도). (b)매크로 단독 원인 + thesis intact 면 매도 대신 타이트 트레일링(고점 -1.0×ATR%) 전환을 기록하고 다음 routine 재평가. 판단 불가 시 (a) 보수 적용.",
  "red_action": "전량 가상 청산 (유효 임계 기준 — ATR 연동으로 변동성 장에서 자동 확대)"
},
```

### 1-B. `config/policy.json` — §risk.volatility_sizing.stop_rule 의 캡 역설 제거

현행 `stop_rule` 문자열에서 `단, 단계경보 red(-10%)보다 깊을 수 없고,` 를
`단, tiered_alerts 의 '유효 red 임계'(atr_adaptive — 변동성 연동으로 자동 확대)보다 깊을 수 없고,` 로 교체.
→ 고변동 종목이 "좁은 손절 + 작은 수량"을 이중으로 받던 역설 해소. 리스크 총량은 기존 tier별 사이징 캡이 그대로 통제(손절이 넓어지면 수량이 자동 감소).

### 1-C. `scripts/check_intraday_alerts.py` — compute_tier ATR 반영

현행(라인 ~45-57) `compute_tier(pct, alerts)` 함수를 교체:
```python
def effective_threshold(fixed: float, mult: float, atr_pct, hard_floor: float) -> float:
    if atr_pct is None:
        return fixed
    return max(hard_floor, min(fixed, -(mult * float(atr_pct))))

def compute_tier(pct: float, alerts: dict, atr_pct=None) -> str:
    mults = alerts.get("atr_multiples", {}) if alerts.get("mode") == "atr_adaptive" else {}
    floor = float(alerts.get("atr_threshold_hard_floor_pct", -20.0))
    red = effective_threshold(float(alerts.get("red_pct", -10.0)), float(mults.get("red", 0) or 0) or 0, atr_pct if mults else None, floor)
    orange = effective_threshold(float(alerts.get("orange_pct", -7.0)), float(mults.get("orange", 0) or 0) or 0, atr_pct if mults else None, floor)
    yellow = effective_threshold(float(alerts.get("yellow_pct", -5.0)), float(mults.get("yellow", 0) or 0) or 0, atr_pct if mults else None, floor)
    if pct <= red: return "red"
    if pct <= orange: return "orange"
    if pct <= yellow: return "yellow"
    return "green"
```
호출부(보유 종목 루프)에서 스냅샷의 `tickers[t].volatility.atr_pct` 를 읽어 `compute_tier(pct, alerts_cfg, atr_pct)` 로 전달하도록 수정.

### 1-D. 프롬프트 반영 (1200·1500·1800)

`grep -n "orange\|red" prompts/1200_midday.md prompts/1500_close.md prompts/1800_report.md` 로 단계 판정·ORANGE/RED 체결 지시 문단을 찾아, 각 파일의 해당 §(1200 §2, 1500 §2, 1800 §1) 도입부에 1줄 추가:

> **단계 임계는 `policy.risk.tiered_alerts`(atr_adaptive)의 '유효 임계'로 계산한다**: 유효 = max(-20%, min(고정%, -(배수×ATR%))). ATR% 는 스냅샷 `volatility.atr_pct`. ORANGE 종가 확정 시 즉시 50% 매도가 아니라 `orange_action` 의 (a)/(b) 조건 분기를 따른다(매크로 단독+thesis intact → 타이트 트레일링 전환).

### 1-E. 검증

```bash
python3 -c "import json;json.load(open('config/policy.json'))"
python3 scripts/check_intraday_alerts.py        # 보유 1종목 기준 정상 종료
python3 scripts/audit_pipeline.py               # PASS 유지
```
리플레이 확인(수계산): 삼성전자 6/4 진입(ATR 6.0%) → 유효 orange -12%/red -15% → 6/5 -8.94% 는 yellow 경계(유효 -9%)로 **강제매도 미발생**, 6/8 -13.22% 는 orange(매크로 단독+thesis intact → 트레일링 전환) → 6/9 +8.75% 반등을 포지션 보유로 통과. 실제 결과(-82,480 실현)와 비교해 개선 방향 일치하면 합격.

- [ ] policy.json 1-A·1-B 반영 + JSON 유효
- [ ] check_intraday_alerts.py 수정 + 정상 실행
- [ ] 프롬프트 3개 반영
- [ ] 리플레이 수계산 일치

---

## STEP 2. 트레일링스톱 ATR화 + 50% 부분익절 (P2)

**목적**: 고점 -3% 고정 트레일(0.5×ATR)이 승자를 조기 절단(5/22 +4.8% 익절 후 +20% 추가상승 일실 +236,000원 = 실현손실의 2.6배). 폭을 변동성에 맞추고, 전량 청산 대신 절반만 잠그고 나머지는 추세를 따르게 한다.

### 2-A. `config/policy.json` — §risk.trailing_stop 교체

현행: `"trailing_stop": "목표가 70% 도달 후 -3% 트레일링 허용",`
교체:
```json
"trailing_stop": {
  "activate_at_target_progress_pct": 70,
  "first_trail_rule": "트레일 폭 = -max(3.0, 1.0×ATR%) (고점 대비). 이탈 시 전량이 아니라 50% 부분익절.",
  "residual_trail_rule": "잔여 50% 는 샹들리에 트레일 -2.0×ATR%(최고 종가 기준)로 추세 추종. 이탈 시 잔여 전량 청산.",
  "note": "v2.11 — 고정 -3%(0.5×ATR) 전량 청산이 승자를 조기 절단하던 구조 교정(2026-05-22 삼성전자 +4.84% 익절 후 +20.3% 추가 상승 일실 +236,000원). 평시 ATR 2~3% 에선 first trail -3% 로 현행과 동일."
},
```

### 2-B. 프롬프트 반영

`grep -rn "0\.97\|고점.*-3%\|트레일링" prompts/*.md` 결과 중 **체결 규칙을 서술하는 곳**(1800 §1 종가 청산, 0900/1200/1500 의 트레일링 갱신 문구)과 **학습 포인트 설명**(1500_close.md:134·140, 1800_report.md:246)을 새 규칙으로 갱신:
- `고점×0.97` / `-3% 트레일링` → `고점×(1−max(3,1.0×ATR%)/100), 이탈 시 50% 부분익절 → 잔여분 샹들리에 -2.0×ATR%`
- watchlist 코멘트 작성 지시가 있는 곳은 `trailing_first_level`·`trailing_residual_level` 두 레벨을 기록하도록 명시.

### 2-C. 검증

리플레이 수계산: 삼성#1(5/21 고점 299,500, ATR≈3%) first trail = 299,500×0.97=290,515 → 5/22 갭다운 290,000 체결은 **50%만** 익절, 잔여 2주는 -2×ATR 샹들리에로 6/1 의 349,000 구간까지 동행 → 기존 +49,018 대비 대폭 개선 확인.

- [ ] policy.json 반영 + JSON 유효
- [ ] 프롬프트 내 -3%/0.97 잔존 0건 (`grep -rn "0\.97" prompts/` 빈 결과)
- [ ] 리플레이 수계산 일치

---

## STEP 3. 재진입 규율 신설 (P3)

**목적**: 6/4 @361,221 재진입(직전 청산가 +2%, 52주 신고점 -2.4%)이 -82,480원 — 추격 재진입을 막는 룰이 전무. 과거 거래로 검증된 비대칭 규율을 추가한다.

### 3-A. `config/policy.json` — §entry_filters 에 신설 (post_surge_cooldown 다음에 추가)

```json
"reentry_discipline": {
  "purpose": "v2.11 — 동일 종목 재진입 추격 차단. 2026-06-04 삼성전자 재진입(직전 익절 청산가 354,290 대비 +2.0% 위·52주 신고점 97.6% 위치)이 -82,480원 — 익절 후 더 비싸게 다시 사는 buy-high 루프를 게이트한다. 반대로 2026-06-09 저점 복원 진입(직전 손절가 대비 -5.2%)은 유효했다 — 아래 면제 조항이 이를 허용한다.",
  "after_profit_exit": {
    "rule": "트레일링/목표 익절 청산 후 동일 종목 재진입은 (a)청산 체결가 이하 가격, 또는 (b)5거래일 베이스(청산 후 고점 미경신 횡보) 후 신고 돌파 시에만 기본 비중 허용. 둘 다 아니면 reduced_entry_weight_pct 의 50%(probe)로만.",
    "max_chase_above_exit_pct": 0.0
  },
  "after_stop_exit": {
    "cooldown_trading_days": 2,
    "exemption": "재진입가가 직전 손절 체결가 대비 -3% 이상 낮으면 cooldown 면제(저점 복원 진입 허용 — 2026-06-09 사례). 또는 손절 체결가 +3% 재탈환 종가 확인 시 해제."
  },
  "high_52w_chase_guard": {
    "pct_of_52w_high_min": 97.0,
    "action": "진입가가 52주 고점의 97% 이상이면 신규/재진입 비중 50% 축소(probe) + ATR 타이트 손절. post_surge_cooldown 의 strong_bull 예외보다 이 가드가 우선한다."
  }
},
```

### 3-B. `prompts/0900_pre_market.md` — §2 신규 진입 공통 규칙에 게이트 1줄 추가

> **재진입 게이트(`policy.entry_filters.reentry_discipline`)**: 동일 종목 직전 청산 기록(trade_log 최근 SELL)을 확인해 ①익절 후 청산가 위 추격 금지(베이스/probe 예외) ②손절 후 2거래일 냉각(저점 -3% 복원 진입은 면제) ③52주 고점 97%+ 추격은 probe 사이즈. 위반 진입은 booking 금지.

### 3-C. 검증 — 과거 7건 리플레이

| 사례 | 새 규칙 판정 | 기대 일치 |
|---|---|---|
| 6/4 재진입(익절가 354,290 → 361,221 추격, 52w 97.6%) | probe 50% 축소 또는 차단 | ✅ (-82,480 의 절반 이하로 축소) |
| 6/9 재진입(손절가 312,262 → 296,091, -5.2%) | cooldown 면제 → 허용 | ✅ (좋은 진입 보존) |
| 6/1 재진입(익절가 288,855 → 317,634) | 5거래일 경과 + 베이스 후 돌파 → 허용 | ✅ (+143,860 보존) |

- [ ] policy.json 반영 + JSON 유효
- [ ] 0900 프롬프트 반영
- [ ] 리플레이 3건 판정 일치

---

## STEP 4. 주간 목표 현실화 — 목표가 인플레 제거 (P4)

**목적**: 주 +10% 목표가 동적 목표가를 +15~25%로 인플레시켜 '목표 도달 0/6'의 직접 원인. 상대(알파) 목표로 전환한다.

### 4-A. `config/policy.json` — §risk 수정

`"weekly_account_target_return_pct": 10.0,` → 아래로 교체:
```json
"weekly_account_target_return_pct": 1.0,
"weekly_target_mode": "relative_to_kospi",
"weekly_alpha_target_pct": 0.5,
"weekly_target_note": "v2.11 — 주간 목표 = KOSPI 주간수익률 + 0.5%p(알파), 절대 하한 +1.0%. 기존 절대 +10%/주는 연환산 불가능한 목표로 ①목표가 인플레(도달 0/6) ②R/R 허수 ③'부족 X%' 추격 압박을 유발했다. audit 스크립트 호환을 위해 weekly_account_target_return_pct 키는 유지(절대 하한으로 재해석).",
```
*(주의: `scripts/audit_pipeline.py:124`·`scripts/write_audit_report.py:104` 가 이 키를 숫자로 읽으므로 키 삭제 금지 — 값만 교체.)*

### 4-B. `config/policy.json` — §risk.dynamic_exit_model.target_price_rule 수정

문자열 앞부분 `고정 +10%가 아니라 weekly_plan.remaining_required_return_pct, 종목 변동성, 저항선/뉴스 촉매를 함께 반영한다.` 에서 **`weekly_plan.remaining_required_return_pct,` 를 삭제**하고 `종목 변동성, 저항선/뉴스 촉매, 그리고 STEP 8 의 밸류에이션 상한(valuation_anchor)을 함께 반영한다.` 로 교체. (목표가가 주간 부족분을 메우도록 부풀려지는 경로 차단.)

### 4-C. 프롬프트 수정

- `prompts/sunday_strategy.md:83` / `prompts/weekend_report.md:81` 의
  `다음 주 목표 자산 = 시작 자산 × policy.risk.weekly_account_target_return_pct` →
  `다음 주 목표 자산 = 시작 자산 × (1 + max(KOSPI 직전 주간수익률 + policy.risk.weekly_alpha_target_pct, policy.risk.weekly_account_target_return_pct)/100)` 로 교체.
- sunday_strategy 에 1줄 추가: "weekly_plan.objective 의 `gap_to_target`·`required_return_from_now_pct` 는 정보로만 기록하고, **watch_items 에 '부족 X% — deploy 의무' 류의 추격 압박 문구를 쓰지 않는다.**"

### 4-D. 검증

```bash
python3 scripts/audit_pipeline.py && python3 scripts/write_audit_report.py
```
- [ ] policy 반영 + audit 2종 정상
- [ ] 프롬프트 2곳 교체

---

## STEP 5. 차단 룰 일몰·이벤트 사이즈 축소·고가주 probe (P5)

**목적**: 평균 주식비중 20%(목표 80~95%)의 주범인 '차단 룰 래칫' 해소. 6/10 후보 7종목 전원 차단, SK하이닉스(점수 1위) 영구 매수불가 상태.

### 5-A. `config/policy.json` — §catalysts.alert_rules 완화 (차단→축소)

- `"candidate_action": "신규 진입 보류 — 이벤트 통과 후 09시 재검토. ..."` → `"candidate_action": "신규 진입 비중 50% 축소(probe) — confirmed=true 고중요도 D-1 만 보류 의무, 그 외(추정일·D-2)는 축소 진입 허용. 이벤트 통과 후 09시 정상 사이즈 재검토."`
- `"macro_action": "... 신규 진입 신중 + 개장 갭 불확실도 확대."` → `"macro_action": "affects_sectors 보유 종목 추가매수 금지 + 신규 진입 비중 50% 축소(차단 아님) + 개장 갭 불확실도 확대."`

### 5-B. `config/policy.json` — 루트에 신설 (sector_rotation_reentry 다음)

```json
"lessons_rule_sunset": {
  "purpose": "v2.11 — 손실 직후 즉석 신설되는 제한 룰(예: 'Broadcom D-1~D+2 반도체 15% 캡')이 일몰 없이 누적돼 미배치를 악화시키는 래칫 차단.",
  "default_expiry_trading_days": 5,
  "rule": "lessons.md 의 '다음 진입 시 반영할 룰' 중 진입 차단·비중 상한 류는 등록 시 expiry(기본 5거래일)를 명기한다. 연장은 sunday_policy_review 가 누적 근거(동일 패턴 2회+)를 확인해 policy.json 정식 필드로 승격할 때만 — 승격 전 임시 룰은 만료 시 자동 실효.",
  "review_owner": "sunday_policy_review §체크리스트"
},
```

### 5-C. `config/policy.json` — §position_sizing.single_trade_risk_cap 에 추가

```json
"one_share_probe_exception": "v2.11 — 1주 리스크(진입가−동적손절가)가 단일거래 ceiling 을 초과해 영구 매수불가가 되는 고가·고ATR 종목(예: SK하이닉스 — 점수 1위·60일 +106% 인데 1주 risk 320,142 > ceiling 173,648)은, ①score 상위 2위 이내 ②tier strong_bull/bull ③손절을 ATR 대신 red 유효임계 캡으로 타이트하게 ④최대 1주 probe — 4조건 동시 충족 시 ceiling 의 200% 까지 예외 허용한다. heat 예산·비중 35% 캡은 그대로 적용."
```

### 5-D. lessons.md 의 기존 즉석 룰에 일몰 소급

`state/lessons.md` 2026-06-08 항목의 룰 2("Broadcom/NVIDIA guidance 주간 반도체 15% 상한")에 추기:
`→ (v2.11 sunset 적용) '15% 차단 캡'을 '비중 50% 축소'로 완화, expiry: guidance 발표 D+2 까지만. 상시 룰 승격은 sunday_policy_review 재심.`

### 5-E. `prompts/0900_pre_market.md` — 후보 차단 로직에 1줄 추가

> 후보 평가 시 차단 사유가 '이벤트 캘린더(FOMC/CPI/guidance)' 단독이면 **차단이 아니라 비중 50% 축소**로 처리한다(policy.catalysts.alert_rules v2.11). 당일 후보 전원이 차단되면 리포트 한눈에 보기에 `⚠️ blocked-day` 플래그를 명시한다.

- [ ] policy 3곳 반영 + JSON 유효
- [ ] lessons 추기 + 0900 반영

---

## STEP 6. rule_attribution — 자기보완 루프에 '의사결정 채점' 추가 (P6)

**목적**: 현행 루프는 목표가 예측 오차만 채점 → 청산 룰의 실손익 비용(승자 절단 +236k 일실, 바닥 매도 등)이 3주간 미표면화. 룰별 손익 기여를 매주 자동 집계한다.

### 6-A. 신규 `scripts/rule_attribution.py` — 사양

- **입력**: `state/trade_log.jsonl`, `state/market_snapshot.json`, `state/exit_tracking.json`(자체 생성·관리)
- **출력**: `state/rule_attribution.json` + stdout 마크다운 섹션(주말 리포트 붙여넣기용)
- **의존성 0** (표준 라이브러리만 — audit_pipeline 패턴 동일)

처리 로직:
1. **라운드트립 재구성**: trade_log 의 BUY/SELL 계열을 티커별 FIFO 매칭 → `{ticker, entry_ts, entry_px, shares, exit_ts, exit_px_net, realized_pnl, exit_rule(action 명), hold_days}`
2. **exit_tracking 갱신**: SELL 계열마다 `{ticker, exit_date, exit_px, rule, shares, t1/t5/t10: null}` 등록(이미 있으면 skip). 매 실행 시 스냅샷의 해당 티커 close 로 경과 거래일에 맞는 t1/t5/t10 슬롯을 채움(최대 10거래일 추적 후 종결).
3. **룰별 집계**: exit_rule 별 `{건수, realized_pnl 합, post_exit_t5_미실현차익 합(=(t5−exit_px)×shares, 양수=조기청산 비용), 평균보유일}`
4. **계좌 지표**: PF(이익합/손실합), expectancy, 회전대금, 마찰비용(슬리피지+세금+수수료 합산), 보유기간 중앙값
5. **벤치마크 3종**: 분석 구간 ①KOSPI 수익률(EOD_EVAL 의 kospi_close 시계열) ②진입종목 단순보유(각 첫 진입가→최신 close, no-stop 가정) ③실제 equity — 3개 나란히 출력
6. **blocked-day rate**: OPEN_CHECK 항목의 `candidates_checked` 에서 전원 BLOCKED/DEFERRED 인 날 비율(주간)

`state/rule_attribution.json` 스키마:
```json
{"as_of": "...", "window_days": 30,
 "round_trips": [...],
 "by_rule": {"TRAILING_STOP": {"n":2,"pnl":192878,"post_exit_t5_forgone":...,"avg_hold_days":1.5}, "SELL_ORANGE_STOP": {...}, "SELL_RED_STOP": {...}, "SELL_GIVE_BACK_STOP": {...}},
 "account": {"profit_factor":..., "expectancy":..., "turnover_krw":..., "friction_krw":..., "median_hold_days":...},
 "benchmarks": {"kospi_pct":..., "buy_and_hold_pct":..., "actual_pct":...},
 "blocked_day_rate_pct": ...}
```

### 6-B. `scripts/fetch_market_data.py` — collect_tickers() 확장

`collect_tickers()`(라인 ~376)에 `state/exit_tracking.json` 의 미종결(t10 미충족) 티커를 수집 대상에 추가 — 청산 후에도 10거래일간 가격 추적 유지.

### 6-C. 워크플로·프롬프트 연결

- `.github/workflows/pipeline_audit.yml` 의 `Write audit report` 스텝 앞에 추가:
  ```yaml
  - name: Rule attribution
    run: python scripts/rule_attribution.py || true
  ```
  (커밋 스텝이 state/ 변경분을 함께 커밋하는지 확인 — 안 하면 git add 경로에 `state/rule_attribution.json state/exit_tracking.json` 추가)
- `prompts/saturday_review.md`: 사후분석 §에 "`state/rule_attribution.json` 의 by_rule·benchmarks 표를 그대로 인용하고, **post_exit_t5_forgone 이 가장 큰 룰 1개에 대해 개선 가설 1줄**을 의무 기록" 추가.
- `prompts/sunday_policy_review.md` 체크리스트에 "rule_attribution 의 by_rule 손익이 2주 연속 음(-)인 룰은 패치 후보로 자동 상정" 추가.

### 6-D. 검증

```bash
python3 scripts/rule_attribution.py
python3 -c "import json;d=json.load(open('state/rule_attribution.json'));print(d['account'],d['benchmarks'])"
```
기대값(현재 데이터): PF≈0.68, 마찰≈36,700, kospi≈+11.3%, actual≈-0.77% — 진단 리포트 수치와 일치해야 함.

- [ ] 스크립트 신설 + 산출 일치
- [ ] collect_tickers 확장
- [ ] 워크플로 + 주말 프롬프트 2개 연결

---

## STEP 7. 가격 출처 3원화 — pykrx 폴백 (P7)

**목적**: naver/yahoo HTTP 403 동시 차단(5/26~29, 6/3, 6/10 재발)으로 진입 불가일·stale 운용이 반복. KRX 공식 데이터를 3번째 출처로 추가해 'EOD 확정치는 항상 있는' 상태를 만든다.

### 7-A. `scripts/fetch_market_data.py`

`fetch_yahoo()` 아래에 추가:
```python
def fetch_krx(ticker: str) -> list[dict]:
    """pykrx 폴백 — EOD 확정치 전용(장중 실시간 아님). 미설치/실패 시 빈 리스트."""
    try:
        from pykrx import stock as krx
        import datetime as dt
        end = dt.date.today(); start = end - dt.timedelta(days=400)
        df = krx.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
        return [{"date": idx.strftime("%Y-%m-%d"), "open": float(r["시가"]), "high": float(r["고가"]),
                 "low": float(r["저가"]), "close": float(r["종가"]), "volume": float(r["거래량"])}
                for idx, r in df.iterrows()]
    except Exception:
        return []
```
`build_ticker_snapshot()` 에서 naver·yahoo **둘 다 실패(또는 last_date≠오늘)일 때만** `fetch_krx()` 호출 → 성공 시 `source_method` 에 `krx_eod` 명기, confidence 는 "단일 공식출처 EOD" 로 medium. (장중 실시간성은 naver 가 1순위 유지 — KRX 는 '차단일의 EOD 백스톱'.)

### 7-B. `.github/workflows/fetch_prices.yml`

`Fetch market data` 스텝 앞에:
```yaml
- name: Install deps
  run: pip install --quiet pykrx || true
```
(다른 가격 수집 워크플로 fetch_fundamentals.yml 등은 대상 아님. `|| true` 로 설치 실패 시에도 기존 2출처 동작 보존.)

### 7-C. 검증

```bash
pip install pykrx && python3 scripts/fetch_market_data.py && python3 -c "
import json;s=json.load(open('state/market_snapshot.json'));print({t:v.get('source_method') for t,v in s['tickers'].items()})"
```
403 환경이 아니면 naver/yahoo 정상 경로 유지 확인. (로컬 차단 시 워크플로 실행 로그로 확인.)

- [ ] fetch_krx 추가 + 폴백 체인 동작
- [ ] 워크플로 pip 스텝 추가

---

## STEP 8. 밸류에이션 앵커 — PER/PBR 기반 냉정한 목표가 상한 (P8, 신규)

**목적·설계 원칙**: 목표가 도달 0/6 의 한 원인은 모멘텀·ATR 만으로 부풀린 목표가다. 기업가치(PER/PBR)로 **목표가의 천장과 진입 과열 경고**를 만든다. 단 밸류에이션은 *후행·저속 신호*이므로 **타이밍 신호가 아니라 가드(상한·경고·틸트)로만** 쓴다 — 기존 policy 철학("타이밍은 regime·momentum, 펀더멘털은 확신 레이어")과 동일 위계. 반도체·조선 같은 **사이클 업종은 PER 함정(피크 실적에 PER 최저)** 이 있으므로 PBR 우선.

### 8-A. 신규 `config/valuation.json`

```json
{
  "as_of": null,
  "update_cadence": "sunday_strategy 주간 갱신(분기 실적 후 필수). 모든 값은 출처 URL+게재일 동반(web_verify 규칙 동일 적용).",
  "tickers": {
    "005930": {
      "name": "삼성전자",
      "preferred_metric": "PBR",
      "bps": null, "eps_fwd": null,
      "pbr_band_5y": [null, null], "per_band_5y": [null, null],
      "source_url": null, "source_date": null
    }
  }
}
```
(보유+후보 전 종목으로 확장. 초기 시드는 sunday_strategy 가 FnGuide/웹에서 web_verify 해 채운다 — `state/consensus.json` 의 eps_consensus 를 eps_fwd 1차 소스로 재사용 가능.)

### 8-B. 신규 `scripts/check_valuation_guard.py` — 사양 (의존성 0)

- 입력: `config/valuation.json`, `config/watchlist.json`(보유 target), `state/candidate_scores.json`(후보), `state/market_snapshot.json`(현재가)
- 출력: `state/valuation_check.json` — 종목별:
```json
{"ticker": "005930",
 "current_multiple": {"pbr": 1.42},
 "target_implied_multiple": {"pbr_at_target": 1.63},
 "valuation_ceiling_price": "= pbr_band_5y[1] × bps (preferred_metric=PER 면 per_band[1] × eps_fwd)",
 "verdict": "ok | cap_target(목표가>ceiling → 상한 적용 권고) | overheat_entry(현재가 멀티플>밴드 상단 → probe 사이즈) | deep_value(밴드 하단 미만 — sector_rotation_reentry 후보 컨텍스트) | skip(데이터 결측/stale)",
 "note": "..."}
```
- 결측·source_date 90일 초과 시 verdict=skip (consensus.target_cross_check 의 skip_when 패턴 동일 — **데이터 없으면 아무것도 막지 않는다**).

### 8-C. `config/policy.json` — §consensus 다음에 신설

```json
"valuation_anchor": {
  "enabled": true,
  "purpose": "v2.11 — PER/PBR 밴드 기반 '냉정한 목표가 상한'과 진입 과열 가드. 모멘텀·ATR 목표가가 기업가치에서 과도하게 이탈하는 것을 캡한다(2026-05-20~06-09 목표 도달 0/6 — 목표가 인플레가 원인 중 하나). 밸류에이션은 후행·저속 신호이므로 진입 타이밍 신호로 쓰지 않는다 — 상한(ceiling)·과열 경고(overheat)·확신 틸트로만 사용. 사이클 업종(반도체·조선·자동차)은 PER 함정(피크 실적=최저 PER) 때문에 preferred_metric=PBR.",
  "config": "config/valuation.json (sunday_strategy 주간 갱신, 출처 URL+게재일 의무)",
  "script": "scripts/check_valuation_guard.py → state/valuation_check.json",
  "target_ceiling_rule": "최종 목표가 = min( 동적목표가(max(진입가×1.12, 진입가+2.5×ATR14, 52주고점)), 컨센서스×1.15(consensus.target_cross_check), valuation_ceiling_price ). 초과분은 캡 — 캡 사유를 watchlist 코멘트에 1줄 기록. verdict=skip 이면 이 항 생략.",
  "overheat_entry_rule": "현재가 멀티플이 5y 밴드 상단 초과(overheat_entry)면 신규/재진입 비중 50% 축소(probe) — reentry_discipline.high_52w_chase_guard 와 중복 시 한 번만 적용.",
  "deep_value_link": "밴드 하단 미만(deep_value)은 단독 매수 신호가 아니다(밸류트랩) — sector_rotation_reentry 의 촉매+몰입 게이트를 통과할 때 probe 사이징 근거로만 참조.",
  "score_tilt": "score_candidates 의 fundamental_tilt 와 동일 패턴 valuation_tilt: deep_value +0.03 / ok 0 / overheat −0.03 (확신 틸트, 가중 축 아님)."
},
```

### 8-D. 연결

- `scripts/score_candidates.py`: `FUND_TILT` 패턴 그대로 `VAL_TILT = {"deep_value": +0.03, "overheat_entry": -0.03}` 추가, `state/valuation_check.json` 읽어 합산(결측 시 0). 출력 항목에 `valuation_tilt` 필드.
- `prompts/0900_pre_market.md` §2 목표가 세팅: "산정 목표가는 `state/valuation_check.json` 의 `valuation_ceiling_price` 로 캡한다(verdict=cap_target 시). overheat_entry 면 probe 사이즈."
- `prompts/1800_report.md` §2-2 목표가 재조정: 동일 캡 적용 1줄.
- `prompts/sunday_strategy.md`: "주간 의무 — config/valuation.json 갱신(BPS/eps_fwd/밴드, 출처 URL+게재일). `python3 scripts/check_valuation_guard.py` 실행 후 cap_target/overheat 종목을 weekly_plan 에 표시."
- `scripts/audit_pipeline.py`: consensus 대조 WARN 패턴과 동일하게 "watchlist 목표가 > valuation_ceiling" WARN 1건 추가(선택).

### 8-E. 검증

```bash
python3 scripts/check_valuation_guard.py   # 시드 전: 전 종목 verdict=skip 정상
python3 scripts/score_candidates.py        # valuation_tilt=0 으로 기존 점수 불변 확인
```
시드 후(일요일): 삼성전자 목표가 370,000 의 implied PBR 이 밴드 상단 대비 어디인지 1건 수기 검증.

- [ ] valuation.json·check_valuation_guard.py 신설
- [ ] policy §valuation_anchor + score tilt + 프롬프트 3개 연결
- [ ] 시드 전 무영향(skip) 확인

---

## STEP 9. 기록 → 본 문서 폐기

1. `config/policy.json` 의 `version` 을 `"2.11"` 로 올리고 changelog 맨 앞에 1줄 추가:
   > "2.11: 손익구조 보강 6종 — ①단계경보·손절 ATR 연동(atr_adaptive, red 캡 역설 제거) ②트레일링 ATR화+50% 부분익절 ③재진입 규율(추격 차단·저점 복원 면제) ④주간 목표 KOSPI+0.5%p 상대화(목표가 인플레 제거) ⑤이벤트 룰 차단→축소·즉석 룰 일몰 5거래일·고가주 1주 probe 예외 ⑥valuation_anchor(PER/PBR 목표가 상한·과열 가드, 사이클 업종 PBR 우선). + rule_attribution(룰별 손익 채점·벤치마크 3종·blocked-day) 및 pykrx EOD 백스톱 신설. 근거: reports/2026-06-10-pipeline-research.md (PF 0.68·마찰 41%·강제청산 6/6·목표도달 0건·평균비중 20.2% vs KOSPI +11.3%)."
2. `state/lessons.md` 누적 패턴 카운터 아래에 1줄:
   > **⚠️ 청산 룰 변동성 부정합 + 미배치(구조 진단)**: 3주 손실의 본질은 예측 실패가 아니라 ①고정 % 청산 룰의 노이즈 체결 ②강세장 미참여 ③회전 마찰(실현손실의 41%). ✅ codify(v2.11) — 이후 rule_attribution 이 룰별 손익을 매주 채점.
3. 전 단계 커밋·푸시 후 검증 일괄 실행:
   ```bash
   python3 scripts/audit_pipeline.py && python3 scripts/check_trade_log_gate.py && python3 scripts/reconcile_portfolio.py && python3 scripts/rule_attribution.py
   ```
4. **본 문서 삭제**: `git rm docs/UPGRADE_WORKORDER.md && git commit -m "chore: 보강 작업 완료 — workorder 폐기 (v2.11)"`
   *(진단 근거인 `reports/2026-06-10-pipeline-research.md` 는 사후 검증용으로 보존 권장 — 4주 뒤 rule_attribution 수치와 비교.)*

- [ ] changelog v2.11 + lessons 기록
- [ ] 최종 검증 4종 PASS
- [ ] 본 문서 삭제 커밋
