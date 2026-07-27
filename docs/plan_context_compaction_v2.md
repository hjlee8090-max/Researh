# 콘텍스트 압축 계획 v2 (2026-07-27)

선행 문서: `docs/plan_context_compaction.md` (2026-06-12, v1 — 압축기 최초 도입)

---

## 1. 지금 상태

09시 routine 이 §0 컨텍스트 적재에서 읽는 파일을 전부 더한 실측이다.

| 파일 | 크기 | 예산 | 초과 |
|---|---|---|---|
| `config/watchlist.json` | 133.6KB | 100KB | +34% |
| `config/policy.json` | 126.8KB | 95KB | +33% |
| `state/lessons.md` | 125.1KB | 60KB | **+108%** |
| `prompts/0900_pre_market.md` | 63.9KB | 60KB | +7% |
| `state/candidate_scores.json` | 62.7KB | — | — |
| `state/market_snapshot.json` | 47.4KB | — | — |
| `config/catalysts.json` | 44.1KB | — | — |
| `config/portfolio.json` | 26.7KB | — | — |
| `config/weekly_plan.json` | 19.0KB | 35KB | 정상 |
| `state/momentum_signal.json` | 14.7KB | — | — |
| `config/candidates.json` | 13.1KB | — | — |
| `state/inference_checklist.md` | 10.3KB | 4KB | **+158%** |
| 리포트 4종(자정·06시·전일18시·주말) | 45.9KB | — | — |
| **합계** | **733.3KB** | | **약 234K 토큰** |

일하기 전에 234K 토큰을 읽는다. 이 상태로는 규칙이 뒤로 밀려 누락된다.

## 2. 기존 압축기는 이미 소진됐다

`python scripts/compact_state.py --dry-run` 결과다.

```
watchlist:           코멘트 3건 트림, 종목 이관 0
watch_items:         이관 0 (13/15)
portfolio_history:   1건 병합
policy_changelog:    2건 이관
target_estimate_log: 이관 0 (371건 전부 90일 이내)
lessons_update_chain: 이관 0 (체인 3개 ≤ 상한 3)
```

돌려도 회수량이 거의 없다. **압축을 안 해서 큰 게 아니라, 압축기가 못 잡는 형태로 컸다.**

## 3. 근본 원인 — 개수 상한만 있고 크기 상한이 없다

압축기의 보존 정책은 전부 "몇 개를 남길까"다. "얼마나 클 수 있나"를 정한 곳이 없다. 그래서 항목 수는 상한 안에 있는데 항목 하나가 무한히 자란다.

**① 개수 상한을 지키면서 크기가 폭증한 사례**

`KEEP_UPDATE_CHAIN = 2`, 현재 체인 항목 3개 → `3 <= 1+2` 이라 트림 대상이 아니다. 그런데 그 한 줄이 **6,582바이트**다. 항목당 2,200B 짜리 서사가 들어앉았다.

같은 파일의 `선제추론오차` 카운터 한 줄은 **6,866바이트**다. 1KB 넘는 라인이 9개, 합계 23.8KB.

**② 섹션 크기에 상한이 없다**

`lessons.md` 섹션 65개, 합계 95.4KB. 최대 섹션 하나가 **11,470바이트**(2026-06-29 선제추론오차)다. 반면 이미 `전문: state/lessons_archive.md` 스텁이 적용된 섹션이 12개 있다 — **관행은 있는데 강제가 없다.**

**③ 압축기 사각지대 — watchlist 최상위 배열**

| 필드 | 크기 | 건수 | 기간 | 압축기 |
|---|---|---|---|---|
| `watchlist.comments` | **80.9KB** | 68건 | 6/16~7/24 | **미처리** |
| `watchlist.cross_check_notes` | 12.6KB | 25건 | 5/20~7/24 | **미처리** |
| `watchlist.stocks[].comments` | 20.4KB | 종목당 13건 | | 처리(12건 상한) |

`compact_watchlist` 는 `stock.comments` 만 트림한다. 파일의 61%를 차지하는 최상위 `comments` 는 손대지 않는다. 보유 종목이 3종뿐인데 파일이 133KB 인 이유가 이것이다.

**④ 생성물을 통째로 적재한다**

| 파일 | 내용 | 실제 필요분 |
|---|---|---|
| `candidate_scores.json` 62.7KB | ranked 15건 (건당 1,960B) | 상위 5건 + 나머지는 요약 |
| `catalysts.json` 44.1KB | 이벤트 54건 (11월까지) | D+45 이내 |
| `market_snapshot.json` 47.4KB | 19종목 전량 | 보유 3 + 후보 상위 5 |

**⑤ policy.json 의 46%가 산문**

125.2KB 중 58.7KB 가 `note`·`purpose`·`rule` 장문이다. 상위 3개 키(`price_data_quality` 21.4KB, `risk` 20.8KB, `entry_filters` 13.9KB)가 파일의 45%다. `changelog` 9.2KB 는 `docs/policy_changelog.md` 에 이미 전문이 있는데 5건을 본문에 중복 보관한다.

---

## 4. 계획

원칙은 v1 과 같다. **학습 재료는 지우지 않고 archive 로 옮긴다.** 핫패스에는 판단에 쓰이는 것만 남긴다.

### Phase 1 — 압축기 사각지대 (코드만 고치면 됨, 학습 손실 0)

가장 큰 효과가 가장 적은 위험으로 나온다. 전부 기존 archive 로 이관이라 정보가 사라지지 않는다.

| 조치 | 대상 | 절감 |
|---|---|---|
| `watchlist.comments` 최근 12건 유지, 초과분 → `watchlist_archive.json` | 68건 → 12건 | **~68KB** |
| `watchlist.cross_check_notes` 최근 8건 유지 | 25건 → 8건 | ~9KB |
| `candidate_scores.ranked` 상위 5건 + 나머지 티커·점수만 | 15건 → 5건 | **34KB** |
| `catalysts` D+45 초과 이벤트 → `events_archive` | 54건 → 38건 | 13KB |
| `market_snapshot.tickers` 보유+후보 상위 5 외 요약 | 19종 → 8종 | ~17KB |

**소계 약 141KB.** `watchlist.json` 133.6 → **약 57KB**(예산 충족), `candidate_scores` 62.7 → 28KB.

구현: `compact_state.py` 에 `compact_watchlist_toplevel()` 추가, 나머지는 생성 스크립트(`score_candidates.py`·`fetch_catalysts.py`·`fetch_market_data.py`)가 쓸 때부터 핫패스본을 슬림하게 내보내고 전체본은 `state/` 에 별도 보관.

### Phase 2 — 크기 상한 도입

`policy.context_budget.retention` 에 개수 상한과 나란히 **바이트 상한**을 넣는다. 압축기가 개수·크기 둘 다 보게 만든다.

**lessons.md** — 세 조치를 함께 적용한다.

| 조치 | 절감 |
|---|---|
| 카운터 블록 라인당 800B 상한 (초과 서사 → archive) | 16.7KB |
| 2026-07-10 이전 섹션 → 260B 스텁(요약 3줄 + `전문: archive` 포인터) | 51.6KB |
| 이후 섹션 1,200B 상한 | 잔여분 |

결과: **125.1KB → 54.2KB** (예산 60KB 충족).

스텁 기준일을 7/1 로 잡으면 66.1KB 로 6.1KB 초과한다. **7/10 컷이 필요하다.** 이미 12개 섹션이 같은 형식의 스텁이라 새 관행이 아니다.

**policy.json**

| 조치 | 절감 |
|---|---|
| 300B 초과 문자열 → `docs/policy_notes.md` 이관, 본문엔 `note_ref` 키만 | 20.9KB |
| `changelog` 본문 보관 5건 → 0건 (`docs/policy_changelog.md` 에 이미 전문 존재) | 9.2KB |

결과: **126.8KB → 약 97KB**. 예산 95KB 에 2KB 남는다. 200B 상한으로 조이면 82KB 까지 내려간다.

주의: `note` 산문은 규칙의 근거이자 재발 방지 기록이다. 이관하되 `note_ref` 로 찾아갈 수 있어야 하고, `check_lessons_applied.py` 가 policy 본문을 grep 해 교훈 반영을 판정하므로 **haystack 에 `docs/policy_notes.md` 를 추가해야 한다.** 안 하면 반영된 교훈이 미반영으로 오탐된다.

### Phase 3 — 나머지

| 대상 | 조치 | 비고 |
|---|---|---|
| `inference_checklist.md` 10.3KB → 4KB | `checklist_sunset_trading_days=5` 일몰을 실제로 집행 | v2.25 상충 교훈 탐지와 함께 하면 자연 감소 |
| `prompts/0900` 63.9KB → 60KB 이하 | 규칙 산문 압축 | 슬롯 프롬프트 간 공통 라인이 2개뿐이라 **공통 블록 추출은 효과 없음**(측정 완료, 1.9KB) |
| 리포트 4종 45.9KB | 흡수 범위를 섹션 단위로 명시 | 전문 대신 "한눈에 보기 + 액션" 만 |

---

## 4-A. Phase 1 실행 결과 (2026-07-27, policy v2.26)

| 파일 | 이전 | 이후 | 변화 |
|---|---|---|---|
| `config/watchlist.json` | 133.6KB | **57.6KB** | -76.0KB |
| `state/market_snapshot_brief.json` (신규, 프롬프트용) | 47.4KB | **19.6KB** | -27.8KB |
| `state/candidate_scores.json` | 62.7KB | **35.7KB** | -27.0KB |
| `config/catalysts.json` | 44.1KB | **33.9KB** | -10.2KB |
| `config/portfolio.json` | 26.7KB | 24.4KB | -2.3KB |
| `config/policy.json` | 126.8KB | 129.5KB | +2.7KB |
| **09시 핫패스 총계** | **733.3KB** | **593.1KB** | **-19.1%** |

토큰 추정 234K → 189K. `watchlist.json` 이 예산(100KB) 안으로 들어와 초과 파일이 5개에서 3개로 줄었다.

`policy.json` 이 2.7KB 늘어난 것은 이번에 추가한 보존 규칙·관리 대상 등재분이다. Phase 2 의 산문 이관 대상이다.

### 구현 내역

- `compact_state.compact_watchlist_toplevel()` 신설 — 최상위 `comments` 12건·`cross_check_notes` 8건·항목당 1,200B 상한. 초과분 56건과 잘린 원문 4건 모두 `watchlist_archive.json` 으로 이관(학습 재료 보존).
- `score_candidates` — 핫패스는 `ranked` 상위 5건만 전문, 6위 이하는 티커·점수·차단사유만. 전문은 `candidate_scores_full.json`.
- `fetch_catalysts` — D+45 밖 `generated_events` 를 `state/catalysts_future.json` 으로 분리. 지평에 들어오면 다음 실행이 승격.
- `fetch_market_data` — `market_snapshot_brief.json` 생성(`five_day_history`·`sources` 제외). **전문은 `score_candidates` 의 입력이라 축소하지 않는다.**
- 프롬프트 §0 컨텍스트 적재를 요약본으로 전환(00·06·09·12·15시). **18시는 전문 유지** — 종가 확정에 `sources[*].last_date` 검증이 필요하다.

### 구현 중 잡은 문제 3가지

1. **멱등성 파괴.** 항목을 1,200B 로 자른 뒤 " …(archive 전문)" 접미사를 붙여 결과가 상한을 넘겼고, 재실행이 같은 항목을 계속 다시 자르며 archive 에 중복 이관했다. 접미사 길이를 미리 빼고 `_truncated` 마커로 재처리를 막았다. 2회 연속 재실행에서 변화량 0·archive 중복 0 확인.
2. **수집 실패 경로에서 요약본 미갱신.** `fetch_market_data` 는 모든 출처가 실패하면 직전 스냅샷을 보존하고 조기 반환하는데, 그 경로가 `write_brief` 앞에 있었다. 프롬프트가 요약본을 1순위로 읽으므로 "전문은 stale 표시인데 요약본은 아닌" 불일치가 생긴다. 조기 반환 경로에도 요약본 갱신을 넣었다.
3. **지평 밖 촉매 날짜 유실.** 카드의 `checkpoints` 는 3분기 실적(11/14)처럼 D+45 밖을 가리킨다. 촉매를 분리하면 `check_thesis_cards` 가 `evaluate_after` 를 못 얻어 invalidation 이 조기 격발한다. 판정기가 `catalysts_future.json` 도 함께 읽도록 고쳤다.

### 재발 방지 — 압축기 커버리지 대조

`audit_pipeline.audit_compactor_coverage` 를 신설했다. 핫패스 파일의 최상위 누적 배열(20건 이상)이 `policy.context_budget.managed_hotpath_arrays` 에 관리 주체와 함께 등재돼 있는지 대조하고, 미등재면 WARN 을 낸다.

처음에는 `compact_state.py` 소스를 grep 하는 방식으로 짰는데 `catalysts.json` 을 오탐했다 — 그 파일은 `fetch_catalysts.py` 가 관리한다. 소유자가 여럿이라 소스 grep 으로는 안 되고, 정책에 명시적으로 등재하는 방식이 맞다. 현재 11건 등재.

미등재 배열을 주입해 검사가 실제로 잡는지 확인했다.

---

## 5. 예상 결과

| 단계 | 09시 핫패스 | 토큰 |
|---|---|---|
| 현재 | 733KB | 약 234K |
| Phase 1 후 | 약 592KB | 약 189K |
| Phase 2 후 | 약 490KB | 약 157K |
| Phase 3 후 | 약 465KB | 약 149K |

**36% 감축.** 예산 초과 5개 파일이 전부 예산 안으로 들어온다.

## 6. 순서와 근거

1. **Phase 1 먼저.** 절감 141KB 중 학습 손실이 0이다. 전부 이관이고 판단 로직을 건드리지 않는다.
2. **Phase 2 의 lessons 부터, policy 는 나중.** lessons 는 초과율 108% 로 가장 심하고 스텁 관행이 이미 있다. policy 산문 이관은 `check_lessons_applied` haystack 을 같이 고쳐야 해서 회귀 위험이 있다.
3. **Phase 3 은 마지막.** 효과 대비 손이 많이 간다.

## 7. 재발 방지

이번 진단의 교훈은 "압축을 안 했다"가 아니라 **"개수만 세고 크기를 안 쟀다"** 다. 같은 실수를 막으려면:

- `policy.context_budget.retention` 의 모든 항목에 개수 상한과 바이트 상한을 쌍으로 둔다.
- `compact_state.py` 가 처리하지 않는 핫패스 배열이 생기면 audit 이 잡도록, 압축기 처리 대상 목록과 실제 핫패스 파일의 최상위 배열 목록을 대조하는 검사를 넣는다. `watchlist.comments` 80.9KB 가 한 달 넘게 무관리로 자란 것을 아무도 못 본 이유가 이 대조의 부재다.
- 핫패스 예산 초과 경보는 v2.25 `alert_expiry` 의 추적 대상이다. 13 감사일 연속 미결정 상태이며, 이 계획의 Phase 1 실행이 그 강제 결정에 해당한다.
