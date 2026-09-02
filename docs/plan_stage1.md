# Stage 1 — 실행의 코드화 (dry-run → cutover) · 2026-09-02

> 상위 문서: `reports/2026-09-02-pipeline-review.md` §6-1. Stage 0(정책 동결·그림자 계좌)과 병행한다.
> 정책 파라미터는 `state/policy_freeze.json` 동결 그대로 — 이 단계는 **룰의 역할(주문 vs 관측)과 실행 소유권**만 바꾼다.

## 0. 경고 — 왜 지금 cutover 가 아니라 dry-run 인가
Stage 0 이 오늘 시작됐다(그림자 대조 표본 1일). 진단 리포트가 사전 등록한 Stage 0→1 기준(그림자 대조 20거래일)은 아직 미충족이다.
그래서 Stage 1 은 **두 단계**로 나눈다. ①지금: 코드가 주문 의도를 쓰고 LLM 이 집행/거부를 기록하는 dry-run — 라이브 계좌의 행동은 바뀌지 않으므로 Stage 0 측정을 오염시키지 않는다.
②cutover: 아래 §3 기준을 넘긴 뒤 사람이 `state/stage.json.execution_owner` 를 `code` 로 바꾼다. 지금 cutover 하면 "무엇이 효과였는지 영원히 알 수 없다"는 실패를 반복한다.

## 1. 무엇 (What)
| 구성 | 파일 | 역할 |
|---|---|---|
| 실행 소유권 | `state/stage.json` | `execution_owner: llm`(dry-run) / `code`(cutover). 하드 룰·그림자 룰 목록. 리밸런스 anchor |
| 주문 의도 | `scripts/build_order_intents.py` → `state/order_intents.json`, `order_intents_log.jsonl` | 명세가 시키는 주문을 결정론 산출. 진입=검증 엔진 바스켓·리밸런스일·빈 슬롯. 청산=hard_stop·trend_break·rebalance_rotation 만. 나머지 청산 룰은 `shadow_signals`(관측) |
| 거부권 채점 | `scripts/score_order_intents.py` → `state/intent_scorecard.json` | 의도 vs 원장: executed / vetoed / expired / ignored. 거부·무시의 t+5 효과, 의도 밖 매매 사유 유무 |
| EOD 백스톱 | `scripts/eod_backstop.py` + `.github/workflows/eod_backstop.yml` (평일 19:15 KST) | 18시 루틴 미발화 시 EOD_MARK 기록 + 내일 의도 산출. 이미 기록돼 있으면 무동작 |
| 루틴 역할 | `prompts/0900_pre_market.md` §0-I (구 §0-M 대체), `prompts/1800_report.md` §4 | 집행이 기본, 거부는 근거 필수, 무기입=무시. 의도 밖 매매는 `off_intent_reason` |
| 감사 | `audit_pipeline.audit_order_intents` | 의도 신선도·무기입·사유 없는 의도 밖 매매 WARN |

## 2. 왜 (Why)
- **A. 단일 결정 소스**: 지금까지 "무엇을 살지"가 프롬프트 67KB 안의 게이트 사다리와 LLM 판단에 흩어져 있었다. 의도 파일 하나가 "명세가 시키는 것"을 매일 고정하면 LLM 의 가감이 처음으로 측정 가능해진다.
- **B. 거부권은 데이터가 된다**: 거부 사유와 t+5 효과가 쌓이면 "LLM 판단이 계좌를 지키는가, 깎는가"를 표본으로 답한다. 이것이 cutover 심사의 재료다.
- **C. 청산 오버레이의 강등**: 자체 백테스트(2026-07-08)가 트레일링·하드스톱 오버레이를 가치 파괴로 판정했다. 의도는 하드 룰 3개만 쓰고 나머지는 그림자로 내려 "발동했더라면"을 기록한다. 정책 파일은 손대지 않는다(동결) — 역할만 바뀐다.
- **D. 원장이 닫히는 날**: 18시 결측 2회가 EOD 공백을 만들었다. 결정론 부분(마크·하드 룰 판정)을 Actions 가 맡으면 실계좌에서 "손절이 사라지는 날"이 없다.

## 3. cutover(execution_owner=code) 심사 기준 — 사전 등록 (유력안, 확정은 사용자)
모두 **20거래일 연속** 충족:
1. `intent_scorecard.adherence_pct ≥ 80` AND `ignored = 0` AND `off_intent_without_reason = 0`
2. 거부 표본 ≥ 10 이면 `veto_effect.sum_krw_t5 > 0` (LLM 거부가 계좌를 지켰다는 증거) — 아니면 거부권도 축소 대상
3. Stage 0 그림자 대조: 라이브 − 그림자(spec_live) ≥ −1%p (진단 리포트 §6-2 Stage 1→2 행과 동일 지표를 앞당겨 관측)
4. EOD 백스톱 발동 0회 또는 발동 시 원장 정합(reconcile) 이상 0건
5. 정책 동결 위반 0건
cutover 후에도 LLM 거부권은 유지된다(사유 필수). 브로커 연결은 Stage 2.

## 4. 이번에 하지 않은 것 (Open Issues)
- **O-1 실투입 자본·유니버스 정합(P5)**: 첫 의도 산출에서도 검증 엔진의 1순위(SK하이닉스)는 1주가 슬롯 예산을 넘어 제외됐다. 자본 규모가 정해져야 top_n·유니버스 결정이 가능 — 동결 해제 후 첫 안건.
- **tracked_only 의 과거 복원 불가**: 그림자 계좌 spec_live 는 tracked_only 미적용. 의도 산출은 현재 candidates 로 적용(momentum_signal 그대로).
- **의도 ↔ pending_orders 이원화**: 기존 `pending_orders.json`(선제 커밋)은 그대로 둔다. cutover 시 pending_orders 는 의도의 트리거 표현으로 흡수 검토.

## 5. Decision Log
- 2026-09-02 D-3(부분): 체결 결정권 이전을 dry-run 으로 착수. cutover 는 §3 기준 충족 후 사람이 stage.json 으로 결정.
- 2026-09-02 D-4: 청산 오버레이를 의도에서 제외(그림자 관측). 정책 파일 무변경.
