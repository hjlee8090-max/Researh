# 연구 — 파이프라인의 제거·배제 설계 (2026-08-13)

> 질문: "현재 파이프라인이 누적만 설계되고, 제거·배제는 설계가 안 된 것 아닌가?"
> 판정: **대체로 맞다.** 정확히는 계층에 따라 다르다 — 매매(엔티티) 계층은 제거·배제가 이미 촘촘하고,
> 데이터 계층은 설계는 있으나 커버리지·집행이 유입을 못 따라가며, **지식 계층(룰·교훈·산문)은 제거 경로가
> 사실상 없다.** 그 결과 2026-08-12 감사 기준 핫패스 예산 5개 항목 전부가 초과 상태로 WARN만 반복되고 있다.
> 콘텍스트 오버 → 규칙 누락·판단 열화는 이 레포 자신의 진단(2026-06-12)이므로, 이 문제는 곧 수익 문제다.

---

## 1. 계층별 판정

| 계층 | 누적 경로 | 제거·배제 경로 | 판정 |
|---|---|---|---|
| **엔티티** (종목·후보·섹터) | 신규 진입, 후보 승격, 테마 추가 | 손절·time_stop·회전아웃(momentum 단일 권위, `rotate_score_max`)·avoid_sectors(재무장 + cooldown 10일)·재진입 냉각 2거래일·estimate_gate 음수 차단·촉매 블랙아웃 | ✅ **설계 완료.** 제안(rotate_out)→처분 연결도 동작 중 (7/30 시프트업 time_stop 판정, W33 thesis가 rotate_out 제안 인용) |
| **데이터** (상태 파일 크기) | 매 슬롯 자동 append (일 6회+) | compact_state.py(주 1회) + weekly_compact.yml 이중화 + audit WARN | ⚠️ **설계 있음, 실효 부족.** 압축기가 커버하는 필드와 실제 성장원이 어긋난다. 아래 §2 실측 |
| **지식** (policy 룰·prompts·lessons·키워드·용어) | 매주 policy 패치(v1.0→v2.31, changelog 35건 전부 추가 계열)·lessons 매일 적재·키워드 보강(재현율 우선) | lessons_rule_sunset(임시 룰 5거래일)·§1-3 dead config 점검·§1-6 codify 이관 — **셋 다 실행이 막혀 있음** (§2-B) | ❌ **여기가 진짜 공백.** 제도는 종이 위에 있으나 등록·처분·처리량이 없다 |

핵심 재해석: 사용자의 문제의식은 "제거 장치가 하나도 없다"가 아니라
**"누적은 자동인데 제거는 수동·주 1회·재량이라 균형이 깨졌다"**로 옮기는 것이 정확하다.
그리고 이 불균형이 손익을 훼손한 선례가 레포 안에 이미 있다 — v2.11 ⑤ "차단 룰 래칫 해소":
손실 직후 즉석 신설된 제한 룰이 일몰 없이 누적돼 강세장 미배치(평균 주식비중 20.2% vs KOSPI +11.3%)를
만들었고, 그때 매매 룰에는 일몰을 도입했다. **같은 처방이 데이터·지식 계층에는 아직 도달하지 않았다.**

---

## 2. 실측 근거

### 2-A. 데이터 계층 — 예산 초과 현황과 압축기 커버리지 구멍

2026-08-12 audit 실측 (`reports/2026-08-12-audit.md`):

| 파일 | 실측 | 예산 | 배율 | 압축기 커버리지 |
|---|---|---|---|---|
| `state/lessons.md` | 279,268B | 60,000B | **4.7×** | 갱신 체인만 압축. 본문 이관(§1-6)은 LLM 재량 — 141개 항목 중 archive 이관 6건뿐 |
| `config/watchlist.json` | 145,300B | 100,000B | 1.5× | stocks[].comments(각 12개)만 커버. **상위 필드 cross_check_notes 35건(7/31~8/12 무보존창)·상위 comments는 미커버** |
| `config/policy.json` | 139,096B | 95,000B | 1.5× | changelog(5건)만 커버. **본문 압축기 없음** — 감사 처방 문구 자체가 "자동 압축기 없음 — 수동". 산문성 문자열이 전체의 50%(42,174자, 180개 필드) |
| `config/weekly_plan.json` | 44,564B | 35,000B | 1.3× | watch_items(≤15)만 커버 — 지금 watch_items는 2.8KB뿐이고, weekly_thesis 14.5KB 등 산문 필드가 성장원 |
| `state/inference_checklist.md` | 14,644B | 4,000B | **3.7×** | 빌더가 **줄 수(40)만 캡** — 줄당 수백 바이트라 바이트 캡은 구조적으로 위반. 캡 단위 불일치 |
| `prompts/0900_pre_market.md` | 67,370B | 60,000B | 1.1× | 압축기 없음. 2026-06-12 수동 감량(54,853→49,218B) 후 **+37% 재비대** — 1회성 수술은 유지되지 않는다 |

압축기가 전혀 없는 누적원 (예산 감시 대상도 아님):

| 파일 | 실측 | 내용 |
|---|---|---|
| `state/pending_orders.json` | 131KB | orders 101건 중 **expired 82·filled 6·cancelled 2·resolved_hold 1 = 종결 상태 90%가 잔존.** 활성은 10건뿐 |
| `config/catalysts.json` manual_events | 32KB | 42건 중 **과거일 33건(79%)**. generated_events는 스크립트가 매주 재생성해 과거분 0건 — 소유권에 따라 유계/무계가 갈리는 전형 |
| `state/inference_log.jsonl` | 800KB·820줄 | 보존창 없음. 6월의 스키마 위반 라인도 핫 파일에 그대로 (target_estimate_log는 90일 이관이 생겼는데 이 원장은 미적용) |
| `state/glossary.md` | 38KB·용어 ~135개 | 설계 자체가 append-only("기등재 재정의 금지 + 신규 1줄 등재"), 캡·이관 없음 |
| `state/estimate_scorecard.json` 등 파생 산출물 | 192KB | 원장이 자라면 같이 자란다 — 원장 보존창이 곧 파생물 캡 |

### 2-B. 지식 계층 — 제거 제도가 있는데 왜 안 도는가

1. **lessons_rule_sunset (v2.11, 임시 룰 5거래일 일몰)** — 2026-08-09 policy-review 실측:
   *"lessons.md에 활성 expiry 등록 항목 없음 — 만료·승격 판정 대상 없음."*
   일몰은 등록된 expiry가 전제인데, **등록 단계를 아무도 강제하지 않아 일몰 대상이 0건**이다.
   출구는 만들었는데 입구에서 표를 안 끊어주는 구조.
2. **§1-3 dead config 점검** — 미참조 3종(`weekly_cycle`·`rebalance_rules`·`disclaimers`)을
   **6주째 식별만 반복**("이번 주도 일괄 삭제하지 않는다… 6주째 미착수"). 식별→처분을 잇는 강제 루프가 없다.
   대조: self_audit findings는 14일 무처분 시 워크플로 FAIL로 압박하는 닫힌 루프가 있고, 실제로 돈다.
3. **§1-6 codify 이관** — lessons 141개 항목 중 codify 표기 22건, archive 이관은 6건.
   유입(매일 여러 건)보다 이관(주 1회 LLM 재량)이 느려서 **처리량 격차가 그대로 279KB가 됐다.**
4. **policy.json은 원웨이 래칫** — changelog 35건이 전부 신설·추가·강화 계열. 필드 은퇴는 v1.5의
   max_new_entries_per_day 폐지 등 손에 꼽고, 그마저 "다른 룰로 대체"였다. 룰마다 note·origin·
   structural_note 산문이 붙어 **정책 파일이 절반은 역사책**이 됐다(50%). 역사는 이미
   `docs/policy_changelog.md`라는 전용 장부가 있는데도 본문에 중복 축적된다.
5. **리포트 계층에는 이미 "순증 금지" 원칙이 있다** — report_contract §8: "새 섹션 추가 시 대체·은퇴되는
   기존 요소를 같은 변경에서 명시". **이 원칙이 정책·프롬프트·상태 계층에는 없다.** 확장하면 된다.

### 2-C. 잘된 선례 (배울 내부 사례)

- `fetch_news.py`: max_age_days 14 + unclassified_keep 10 — **수집 스크립트가 보존창을 내장.** 245KB지만 유계.
- `catalysts.generated_events`: 매주 전체 재생성(소유권: 스크립트) — 과거분 자동 소멸.
- `build_inference_checklist.py`: 상한 도달 시 "무엇을 몇 건 생략했는지" 사실대로 표기 — 침묵 절단 금지.
- `weekly_compact.yml`: 아카이브 루틴 3주 미발화(W24~26) 사후, 압축을 Actions cron으로 이중화 — 담체 분리 선례.
  (단 W32(8/9)엔 아카이브 루틴이 또 미발화 — 리포트 응축 쪽은 여전히 단일 담체다.)

---

## 3. 구조 원인 (왜 이렇게 됐나)

1. **대역폭 비대칭** — 누적은 자동·일 6회(매 슬롯 append), 제거는 수동·주 1회·LLM 재량.
   유입 속도 > 제거 속도면 발산은 필연이다. 성실히 운영할수록 더 빨리 비대해진다.
2. **소유권 비대칭** — 스크립트 소유 파일(재생성·보존창)은 자연히 유계, LLM 소유 파일(append)은 무계.
   같은 catalysts.json 안에서도 generated(0% 잔존) vs manual(79% 잔존)로 갈린 것이 증거.
3. **집행 강도 비대칭** — 매매에는 하드 게이트(trade_log gate FAIL), 콘텍스트·지식 위생에는 WARN뿐.
   WARN이 수 주째 만성화되며 신호 가치를 잃었다. "경보 피로 → 진짜 경고 매몰"은 레포가 이미 아는
   실패 모드인데(2026-06-12 진단), 콘텍스트 예산에서 재발했다.
4. **제거 경로의 전제 미충족** — 일몰은 expiry 등록이 전제(등록 0건), dead config 처분은 "사용자 승인
   대기"로 무한 이월. 식별→처분→검증의 닫힌 루프(self_audit식)가 지식 위생에는 없다.
5. **캡 설계 결함** — 캡은 파일 단위(바이트), 성장은 필드 단위(watchlist 상위 필드·weekly_plan 산문).
   압축기는 "그때 컸던 필드"에 고정돼 있고, 새 성장원은 감시 밖에서 자란다. 캡 단위 불일치(줄 vs 바이트)도 있다.

---

## 4. 설계 원칙 (제거·배제의 헌법 — policy.context_budget에 명문화할 것)

- **P1. 누적 채널마다 등록된 제거 채널** — "evictor 없는 accumulator 금지". 새 파일·필드·원장을 만드는
  변경은 소유자(script/LLM)·보존창·이관 목적지를 함께 명기해야 통과된다. report_contract §8의
  "순증 금지"를 상태·정책 계층으로 확장한 것.
- **P2. 누적이 자동이면 제거도 자동** — 결정적·멱등 압축은 주 1회가 아니라 평일 감사 캐던스로 돌린다.
  compact_state는 멱등이라 중복 실행이 무해하다(weekly_compact.yml 주석이 이미 보증).
- **P3. 일몰이 기본값** — 임시 룰·체크리스트 항목·avoid 항목은 생성 시 expiry(기본 5거래일) 없이는
  등록되지 않게 스키마로 강제한다. 연장은 근거를 적는 명시 행위(누적 2회+ → policy 승격)로만.
- **P4. 삭제가 아니라 강등의 계단** — 레포 원칙("학습 재료는 삭제하지 않는다")은 유지한다.
  핫패스(매 슬롯 읽음) → 웜(archive, grep 가능) → git 히스토리의 3단 계단에서 "제거"란
  **핫패스에서의 배제**를 뜻한다. 이관 시 원본 자리에는 참조 스텁 1줄을 남긴다(기존 §1-6 관례 그대로).
- **P5. 채점이 나쁘면 배제 후보** — 이미 있는 채점 인프라를 제거 트리거에 연결한다:
  rule_attribution(2주 연속 손익 음수 룰)·silent_types(27일+ 무매칭 키워드)·미참조 스캔(dead config)·
  blocked_day_rate(차단 과잉). 엔티티 계층의 회전아웃과 동형의 "지식 회전아웃".

---

## 5. 적용안 (우선순위·구현 스케치)

### A. compact_state.py 커버리지 확장 — P0, 스크립트만·매매 행동 무변경

| # | 대상 | 규칙 | 예상 효과 |
|---|---|---|---|
| A-1 | pending_orders.json | status ∈ {expired, filled, cancelled, resolved_*} → `state/pending_orders_archive.jsonl` 이관 (트리거 평가 대상은 active뿐 — check_intraday_alerts 확인 후) | 131KB → ~15KB |
| A-2 | catalysts.manual_events | 이벤트일 D+7 경과분 이관 (supersedes 체인은 최신 1개 유지). annual_preload(통화정책 연간 선등재)는 미래분이라 무관 | 32KB → ~10KB |
| A-3 | watchlist 상위 필드 | cross_check_notes·comments(상위) 최근 12건 유지, 초과분 watchlist_archive로 — per-stock comments와 동일 관례 | 성장원 봉합 |
| A-4 | weekly_plan | week_id가 지난 주인 산문 필드(weekend_review·daily_bridge 이월분) 이관. sunday_strategy의 "재작성(대체)" 명문화를 산문 필드에도 확장 | 44KB → 예산 내 |
| A-5 | inference_log.jsonl | 채점 완료(outcome 확정) + 90일 경과 라인 이관 — compact_target_estimate_log와 동일 패턴 재사용 | 800KB 발산 정지 |
| A-6 | inference_checklist | 빌더 캡을 줄+바이트 이중으로 (줄당 바이트 상한 또는 총 바이트 예산으로 절단, 절단 사실 표기 관례 유지) | 4KB 캡 실효화 |

### B. 집행 캐던스·담체 — P0

- B-1. `weekly_compact.yml` → **daily로 승격** (평일 19:30 pipeline_audit 직후 또는 별도 cron).
  compact는 멱등·결정적이라 무해. "주 1회 이벤트에 걸린 위생"을 "매일 도는 위생"으로.
- B-2. 아카이브 루틴 미발화 시 리포트 응축(YYYY-Www-archive.md)도 Actions 폴백으로 소급 생성 검토
  (W32 미발화 실측 — 압축은 이중화됐는데 응축은 아직 단일 담체).

### C. 지식 일몰의 닫힌 루프 — P1, 이번 연구의 핵심

- C-1. **등록 게이트**: lessons에 "다음 적용 룰"을 적을 때 진입 차단·비중 상한 류는
  `(expiry: YYYY-MM-DD)` 표기를 의무화. check_lessons_applied가 표기 누락을 WARN으로 표면화하고,
  build_lessons_index가 expiry를 파싱해 만료 목록을 §1-2-b에 자동 상정한다.
  **일몰 제도에 대상을 공급하는 것** — 지금은 출구만 있고 입구 등록이 0건이다.
- C-2. **dead config를 findings 루프에 편입**: §1-3 식별 항목을 `state/self_audit_findings.json`에
  finding으로 적재 → 기존 14일 무처분 FAIL 루프가 그대로 처분을 강제한다. 새 메커니즘 불요,
  기존 루프 재사용. 6주 이월 3종(weekly_cycle·rebalance_rules·disclaimers)이 첫 대상.
- C-3. **룰 원장(rule ledger)**: 신규 policy 룰부터 `{added, evidence, last_validated, review_by}`
  메타를 붙인다(스키마 게이트 warn 모드 — 기존 필드 소급 없음). review_by 경과 + rule_attribution
  손익 음수·무발동이면 §1-2-b가 일몰·완화 후보로 자동 상정. 엔티티 계층의 "채점 기반 회전아웃"을
  지식 계층에 이식하는 것.
- C-4. **키워드·용어 위생**: silent_types(장기 무매칭 키워드)는 분기마다 배제 후보로 상정(재현율
  우선 원칙과 충돌하지 않게 "삭제"가 아니라 비활성 표기). glossary는 200용어 캡 + 초과 시
  사용 빈도 하위부터 archive.

### D. policy.json 다이어트 — P1

note·origin·structural_note 산문(50%, 42K자)을 `docs/policy_rationale.md`(근거 장부)로 이관하고
본문에는 `{rule, params, ref}`만 남긴다. changelog 분리(2026-06-12)와 동일 패턴이므로 관례가 이미 있다.
조건도 동일: check_lessons_applied haystack에 rationale 파일 추가(미반영 오탐 방지).
"자동 압축기 없는 유일한 핫패스"를 해소하는 작업이며, 룰 의미는 1글자도 바꾸지 않는다.

### E. lessons 처리량 균형 — P1

§1-6 이관을 재량에서 **수지 균형 의무**로: 매주 policy-review는 "이관 건수 ≥ 지난주 신규 유입 건수"
또는 "lessons.md ≤ 60KB" 중 하나를 충족해야 한다. build_lessons_index가 이관 후보(codify 완료 +
30일 경과 + 카운터 무관 항목)를 자동 목록화해 리뷰의 판단 비용을 낮춘다.
불변 보존(헤딩·분류 라인·누적 카운터·미반영 항목)은 기존 §1-6 규칙 그대로.

### F. WARN 에스컬레이션 — P2

audit_context_budget이 **같은 항목으로 10영업일 연속 WARN이면 FAIL로 승격**한다.
schema_gate의 "10영업일 연속 위반 0건이면 strict 승격"과 대칭 구조(같은 상수 재사용).
하드 게이트는 trade_log만이라는 레포 원칙에 대한 예외이므로 사용자 승인 후 적용한다.
승격 전이라도 audit 리포트 "내가 지금 할 일"에 연속 위반 일수를 표기해 만성화를 가시화한다.

### G. 프롬프트 순증 금지 — P2

sunday_policy_review 패치 관례에 1줄 추가: "prompts에 룰·섹션을 추가하는 패치는 은퇴·통합되는
기존 문구를 같은 diff에서 명시한다(순증 금지 — report_contract §8과 동형)."
audit은 프롬프트 크기의 **전주 대비 순증**을 INFO로 추적한다(절대 상한만으로는 재비대를 못 잡는다 —
0900 재비대 +37% 실측).

---

## 6. 자기보완 루프 부합성 점검 (레포 관례)

| 항목 | 매매 행동 변화 | 판정 |
|---|---|---|
| A-1 pending_orders 종결분 이관 | 없음 — check_intraday_alerts는 active만 평가. 이관 전 소비자 확인 조건부 | ✅ 조건부 |
| A-2 과거 촉매 이관 | 없음 — D-day 경보는 미래 이벤트만 본다. supersedes 최신 유지 조건부 | ✅ 조건부 |
| A-3~4 watchlist·weekly_plan 필드 | 없음 — 의사결정 신호(최근분)는 유지, 초과분만 이관. 2026-06-12와 동일 원칙 | ✅ |
| A-5 inference_log 이관 | 없음 — 채점 완료분만. score_inferences의 채점 지평 확인 조건부 | ✅ 조건부 |
| C-1 expiry 등록 강제 | 있음(의도된 것) — 임시 차단 룰이 5거래일 뒤 실효. v2.11 일몰 설계의 원래 의도를 실행하는 것 | ✅ 루프 강화 |
| C-3 룰 원장·일몰 심사 | 조건부 — 일몰 "자동 실행"이 아니라 "자동 상정"(처분은 리뷰·사용자). 차단 룰 완화는 미배치 교훈과 정방향 | ✅ |
| D policy 산문 이관 | 없음 — 룰 의미 불변. haystack 추가 조건부(2026-06-12 changelog 분리와 동일 조건) | ✅ 조건부 |
| F WARN→FAIL 승격 | 없음(운영 게이트) — 단 "하드 게이트는 trade_log만" 원칙 예외라 사용자 승인 필요 | ⚠️ 승인 필요 |

전 항목에서 "학습 재료 전문 보존(git+archive)" 원칙은 유지된다. 바뀌는 것은 **핫패스 체류 자격**뿐이다.

## 7. 검증 계획

1. compact_state.py 확장 후 2회 연속 실행 — 멱등성(2회차 변경 0) 확인, --dry-run 변경량 리포트.
2. 소비자 무결성: check_intraday_alerts(active 주문)·score_inferences(채점 지평)·
   estimate_target_price(촉매 근접가중)·send_kakao가 이관 후에도 동일 출력을 내는지 전후 diff.
3. build_lessons_index / check_lessons_applied — lessons 편집 전후 entries·카운터 불변 확인(기존 관례).
4. audit_pipeline 실행 — 콘텍스트 예산 5항목 WARN 소멸 확인이 1차 성공 지표.
5. C-1은 1주 관측(WARN만) 후 강제 — 기존 lessons 작성 흐름이 깨지지 않는지 policy-review 1회분으로 확인.
6. D(policy 다이어트)는 전후로 전 스크립트 grep — policy 키를 참조하는 코드가 산문 키를 읽지 않는지 확인.

## 8. 적용 순서 제안

1. **1주차 (P0)**: A-1~A-6 + B-1 — 스크립트·워크플로만, 행동 무변경. 예산 WARN 5건 중 3건+ 소멸 목표.
2. **2주차 (P1)**: C-2(findings 편입)·E(lessons 수지 균형) — 기존 루프 재사용이라 저위험.
   C-1(expiry 등록)은 WARN 모드로 시작.
3. **3주차+ (P1~P2)**: D(policy 다이어트 — 큰 diff라 별도 커밋)·C-3(룰 원장, 신규 룰부터)·
   F·G(사용자 승인 항목 포함) — sunday_policy_review 안건으로 상정.

> 본 문서는 설계 연구이며, 구현 커밋은 포함하지 않는다. 산출물: `docs/plan_removal_exclusion.md`.
