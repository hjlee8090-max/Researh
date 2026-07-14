# 파이프라인 정밀 검사 종합 검토 (2026-07-08)

> 서브에이전트 5개(데이터 수집 / 의사결정·점수화 / 상태 정합성·원장 / 프롬프트·문서 / CI·인프라)가 병렬로
> 전 계층을 정밀 검사한 보고를 종합한 문서. 모든 항목은 파일:라인 또는 실행 출력 근거가 있으며,
> 추정 항목은 별도 표기. 검사 과정에서 원본 레포는 무변경(실행 검증은 스크래치 사본에서 수행).

---

## 총평

파이프라인은 매일 발화·커밋·발송이 돌아가고 있고 데이터 위생(JSON 파싱·중복 키·음수 잔고) 자체는 양호하다.
그러나 **세 가지 구조적 균열**이 확인됐다:

1. **감시 시스템이 자기 자신의 실패를 보지 못한다** — 감사 스크립트가 크래시해도 "정상(OK)" 리포트가
   커밋·발송되고, 실패 통지 채널(카톡)의 토큰 만료 경보는 구조적으로 절대 울리지 않으며,
   감사의 관측 창(7일) 밖으로 밀려난 실패(주간 아카이브 4주 사망)는 영구 실종 처리된다.
2. **단일 상태(state)의 정본이 여러 곳에 흩어져 서로 어긋나 있다** — watchlist·portfolio·exit_levels의
   손절/목표가가 6종목 전부 불일치, `shares_held=null`로 보유 판정이 계층마다 갈리고, trade_count 원장
   불일치(21 vs 22)가 현존한다.
3. **안전 게이트의 절반이 프롬프트 신뢰에만 의존한다** — 코드/CI로 강제되는 게이트와 "LLM이 기억해야만
   지켜지는" 게이트가 섞여 있고, 후자 목록이 11개에 달한다.

여기에 **시한폭탄 3개**(8/14 펀더멘털 분기 역전, 8/17·10/5 휴장일 캘린더 누락, 카카오 토큰 60일 만료)가
날짜를 정해 놓고 대기 중이다.

---

## A. 치명 — 시한폭탄·감시 무력화 (즉시 조치 필요)

| # | 문제 | 근거 | 발현 시점 |
|---|------|------|-----------|
| A-1 | **감사 크래시 = "정상" 보고**. `write_audit_report.py:367`이 audit_pipeline의 exit code를 버리고 `[FAIL]/[WARN]` 태그 라인 수만 셈 → 크래시 시 태그 0개 = status OK. `pipeline_audit.yml:57`의 `\|\| true`로 워크플로도 항상 초록. 사본에서 실증 재현됨 | write_audit_report.py:367, pipeline_audit.yml:57 | 언제든 (감사 시스템이 죽는 날 무증상) |
| A-2 | **2026 하반기 대체공휴일 2건 누락** — 8/17(광복절 대체), 10/5(개천절 대체)이 market_calendar.json에 없어 휴장일에 `is_open: true / live` 판정 실증. 전례: 6/3 지방선거일도 캘린더에 없어 정규 모드로 발화, 전 소스 403 속에서 미확인 시세로 진입 검토한 흔적 존재 | config/market_calendar.json:17-31 (last_updated 06-02), check_market_open.py 실행 증거 | **2026-08-17** |
| A-3 | **fetch_fundamentals가 8/14 이후 1분기 실적을 "최신"으로 수집** — `REPORT_ORDER`가 주석("최신→과거")과 반대로 1Q→반기→3Q→사업 순. 첫 매칭 반환이라 반기보고서 제출(8/14) 후 연말까지 2분기 뒤처진 값으로 earnings_signal·YoY 산출, fetched_at은 신선하게 찍혀 하류 감지 불가. 지금은 1Q가 실제 최신이라 우연히 무증상 | fetch_fundamentals.py:48-51, 131 | **2026-08-14** |
| A-4 | **exit_tracking.json 이중 쓰기 규약 모순** — rule_attribution.py:334는 무조건 덮어쓰기(장중 실행 시 장중가를 "확정 종가"로 기록), update_exit_tracking.py:76-77은 기존 값 불변 원칙이라 18시 EOD가 정정 불가. 보유 중인 010120이 exited_tickers에 등재돼 있어(7/6 부분익절) 오염 시 트레일링 1차선·샹들리에(pending SELL 트리거)가 실제보다 높게 산출 → 조기 청산 격발 경로 | rule_attribution.py:334, update_exit_tracking.py:76-77, compute_exit_levels.py:94-109 | 주말 슬롯 rule_attribution 실행 시점부터 잠재 |
| A-5 | **self_audit `weeks_seen`이 주차가 아니라 실행 횟수** — 실행할 때마다 +1이라 수동 dispatch 1회만으로 "2주째 overdue" 오탐 승격, AUDIT_ENFORCE=1 게이트 exit 1 실증. 이대로면 7/12(일) 워크플로가 처분 기회(20시 policy_review) 이전에 FAIL 가능 | self_audit.py:315 | **2026-07-12** |
| A-6 | **카카오 refresh_token 만료 무경보 + 신규 토큰 평문 노출** — ①만료 30일 전부터 매 발송마다 token_refresh가 찍혀 `age≥53` 경보 조건이 영원히 미충족, 60일차에 전 슬롯 발송 사망(실패 통지 채널이 카톡 자체라 인지 불가) ②갱신 토큰이 CI 로그에 평문 print(add-mask 미구현 — 계획 문서에만 존재) | audit_pipeline.py:1082-1094, send_kakao.py:733-740, docs/plan_hourly_report_gap_fix.md:85 | 토큰 발급 +30일부터 노출, +60일 사망 |

## B. 현재 이미 발생 중인 실데이터 문제

| # | 문제 | 근거 |
|---|------|------|
| B-1 | **watchlist 손절/목표가가 portfolio·exit_levels와 6/6종목 전부 불일치** — 한미반도체 stop 243,000(watchlist) vs 199,143(정본): watchlist 기준으론 현재가가 이미 깊은 이탈. 삼성SDI도 동일 패턴. 신한지주 target은 watchlist 기준 이미 도달. check_valuation_guard가 watchlist 값을 읽어 verdict 산출 — v2.21 ⑦이 금지한 "제3값" 재발 토양 | config/watchlist.json vs config/portfolio.json·state/exit_levels.json, check_valuation_guard.py:115-118 |
| B-2 | **`shares_held=null` → 보유 판정 균열** — watchlist 6종목 전부 null(채우는 스크립트가 레포에 없음). `shares_held > 0`으로 보유를 판정하는 4곳(fetch_news.py:243, estimate_target_price.py:852, audit_pipeline.py:367·413)이 전부 오판 → **신한지주·하나금융이 뉴스 수집·목표가 추정에서 통째로 누락** (news_feed·target_estimate 실파일 확인) | 좌기 |
| B-3 | **컨센서스 전면 결측** — 07-04 FnGuide 파싱 오염(17종목 동일 target 복제) → 07-06 퍼지 후 재수집 없음. fetched_ok 0/17, 다음 자동 수집은 07-12. earnings-preview·목표가 교차검증 입력 공백. workflow_dispatch 수동 재수집 즉시 가능 | state/consensus.json, fetch_consensus.yml:15 |
| B-4 | **trade_count 원장 불일치 (21 vs 22)** — reconcile은 docstring으로 검증을 주장하나 compare()에 해당 비교 없음. 독립 재계산: 매수 13+매도 9=22 vs portfolio 21 (7/6 SELL_TRAILING_STOP 미반영 추정). 현금·realized_pnl·포지션·cash_after 체인 71라인은 오차 0으로 정상 | reconcile_portfolio.py:8·103-131 |
| B-5 | **portfolio.current_price=null → heat·비중이 진입가 기준으로 왜곡** — compute_allocation이 스스로 "버그"라 적시한 진입가 폴백이 필드 부재로 재현. MTM equity 4,791,556 vs 장부 4,879,056 = **-87,500 과대계상**이 어떤 감사 경로에도 표면화 안 됨(reconcile warnings를 audit_pipeline이 안 읽음) | compute_allocation.py:41-58, audit_pipeline.py:215 |
| B-6 | **allocation 내부 모순** — heat 예산 초과(481,883 > 370,302)·remaining 0인데 recommendation은 deploy 854,163원. heat 하드캡 미반영 | state/allocation.json, compute_allocation.py:307-348 |
| B-7 | **주간 아카이브 4주 연속 사망 (W24~W27)** + 감사 관측창 7일이라 W24~W26은 이미 감사 시야에서 실종. 슬롯 누락도 지속: 00시(6/16·6/21·6/30), 06시(7/2·7/6), 토요일 리뷰(6/27), policy-review(6/28) | reports/ 실측, audit_pipeline.py:816 |
| B-8 | **콘텍스트 예산 실측 초과** — 09시 의무 적재 합계 ~710KB. policy.json 117KB(임계 95KB)·lessons.md 78KB(임계 60KB)·0900 프롬프트 63KB(임계 60KB) 초과. 처방으로 안내되는 compact_state는 policy 본문·lessons를 다루지 않아 **실행해도 해소 불가능한 처방**. lessons.md의 "최종 갱신" 라인은 "이전 갱신:" 체인이 무한 연결돼 한 줄 ~8KB | 실측(du/wc), policy.context_budget, compact_state.py |
| B-9 | **valuation 시드 8/17종목뿐 + 10일 stale** — fetch_valuation 루프가 기존 티커만 갱신하고 신규 추가 없음(보유 6 중 5종목 시드 부재). as_of 06-28 — 07-05 주간 갱신 1회 무산 추정. 삼성전자·SK하이닉스는 band_quality=inconsistent로 anchor 사용 불가 | fetch_valuation.py:205, config/valuation.json |
| B-10 | **뉴스 분류율 15.8%** — 별칭 레지스트리 7종목 누락 + `norm()` 대소문자 미정규화로 NAVER·카카오·LIG넥스원 등 분류 0건, llm_review_queue 80건 포화 | fetch_news.py:58-60·271, config/news_keywords.json |
| B-11 | **일일 audit 카톡이 self-audit 리포트로 오발송 (7/7 실증)** — `*-audit.md` 글롭이 `-self-audit.md`도 매칭, sorted 마지막 선택 | send_kakao.py:622, notify_log.jsonl 증거 |

## C. 게이트·검증의 구조적 허점

### C-1. 코드 강제 없이 프롬프트 신뢰에만 의존하는 게이트 (LLM이 깜빡하면 뚫림)
1. §PRE 게이트(pre_trade_check) 실행 자체 — price_source는 자기신고 필드
2. 신규 진입 R/R 하한(레짐 적응) — 차단 스크립트 없음 (현재 보유 3종목 R/R 미달 WARN 8일 연속 방치 중)
3. 사이징 min(리스크상한·목표비중·히트잔여) 초과 체결 차단 없음
4. earnings_blackout — 검사 스크립트 0건
5. reentry_discipline(익절 후 추격·손절 후 냉각 2일) — live 게이트 없음
6. orange/red 단계 대응 집행 — 신호만 있고 실행은 재량
7. 트레일/손절 이탈 시 실제 SELL booking — 잊으면 미체결로 통과
8. 장중 트리거 터치 즉시 체결 금지(no_intraday_fill) — timing_gate는 09:00~15:30 내 어떤 SELL도 허용
9. kill_switch — 신호 생성만 차단, 체결측 검사 부재
10. Tier2 신규매수 카톡 승인 — 코드 검증 없음
11. closing_auction 예외가 ts=15:30인지 미검증 — venue 라벨만 붙이면 아무 시각이나 통과 (check_trade_log_gate.py:138-140)

### C-2. 검사기가 검사한다고 주장하지만 안 잡는 것
- check_state_schema: tail 30 창 밖(inference_log 88라인 중 L1~58) 영구 무검사 + 키 존재만 보고 **null 통과** — 과거 WARN이 `confidence: null` "보정"으로 은폐된 사례 실존 (check_state_schema.py:56·121)
- reconcile warnings(stale 평가 4건)가 audit_pipeline에서 증발 (audit_pipeline.py:215)
- self_audit findings 자동 resolved가 "입력 파일 부재/stale"과 구분 안 됨 — rule_attribution이 비면 whipsaw finding이 조용히 해소 처리 (self_audit.py:335-338)
- compact_state의 portfolio_history dedup이 date 문자열 원문 비교 — date-only와 ISO 혼용으로 18일치 중복이 영구 우회, 스키마도 equity/equity_snapshot 양분(31 vs 25건) (compact_state.py:159-164)
- 연도 키 부재 시 휴장 판정 무음 무력화 — 2027-01-01이 "정규 영업일" exit 0 실증 (check_market_open.py:28-32)
- 초기자본을 portfolio.json 자체에서 읽는 자기참조 검증 (reconcile·audit 공통)

### C-3. 인프라 경합·조용한 실패
- auto_merge 동시성 그룹이 pending run을 취소 — 루틴 3개 근접 push 시 가운데 산출물 무음 고립(이 워크플로가 고치려던 P6 재도입) (auto_merge_routines.yml:24-26)
- 봇 커미터 가드 무력(`*users.noreply.github.com` = 전 GitHub 사용자 매칭) — `chore(...)` head 커밋이면 임의 WIP도 자동 머지 (auto_merge_routines.yml:62-67)
- fetch_history 부분 실패 시 정상 이력을 `bars: []`로 덮어씀, exit 1 판정이 파일 쓰기 뒤 (fetch_history.py:125-133·152-156)
- build_html: portfolio.cumulative_return_pct가 null이면 TypeError → build→deploy→notify 전체 중단 (build_html.py:451-453)

## D. 프롬프트·문서 정합성 (LLM 판단 오염원)

| # | 문제 | 근거 |
|---|------|------|
| D-1 | **1800_report.md가 폐기된 트레일 배수(1.0×ATR) 지시** — 정책·타 슬롯·exit_levels는 전부 1.5×ATR. 18시는 부분익절 실체결 슬롯 — 7/1 "ATR 배수 오기입 유통 사고"와 동형의 재발 씨앗 | 1800_report.md:99 vs policy risk.trailing_stop |
| D-2 | **1500_close.md 자기모순** — §0-B "신규 진입 09시 규칙으로 체결" vs §0-C "원칙적 체결 비권유" vs §4 "체결 권유하지 않는다" 3중 공존 → 세션마다 15시 매수 여부 비결정 | 1500_close.md:21·30·170 |
| D-3 | max_positions 프롬프트 하드코딩 4 vs 정책 6 (재가동 경로) | 0900_pre_market.md:234 |
| D-4 | **프롬프트 지시를 따를수록 계약 위반 재생산** — estimate_target_price 산출 헤더의 "v1.5" 토큰을 "그대로 붙여넣기" 지시 → report_contract §3 위반 WARN 매일 발생 (7/6~7/7 4건 실증) | 0900:367, 1200:137, docs/report_contract.md §3 |
| D-5 | README 정책 요약 4곳 구식(3종목/30%/현금10%/수수료 누락), 파일 트리에 06 슬롯·0630 프롬프트 누락 | README.md:3·15·16·46-67 |
| D-6 | file_references.md 광범위 드리프트 — 스크립트 7개 항목 부재, 12/15시 입출력 누락, 내부 모순(gitignored 표기) | docs/file_references.md:48·125-135·241·308 |
| D-7 | sunday_archive 양식에 06:00 슬롯 누락 → 주간 아카이브에서 06시 상습 탈락 위험 | prompts/sunday_archive.md:78-84 |
| D-8 | momentum_signal 하드코딩(현금10%·캡30%) vs 정책(5%·35%) + orders가 보유분 미차감 제로베이스(보유 중인 종목을 신규 매수로 지시) | momentum_signal.py:213 |

## E. 정상 확인된 것 (이상 없음)

- 전 스크립트 py_compile 통과, 전 JSON/JSONL 파싱 정상, 중복 키·음수 잔고 0
- 현금·realized_pnl·포지션·cash_after 체인(71라인) 독립 재계산 완전 일치
- universe 30종목 ↔ price_history ↔ fundamentals 완전 일치, 죽은 티커 없음
- 전 워크플로 12개 cron UTC→KST 변환 전수 일치
- auto_merge·카톡 발송 최근 2주 실동작 정상(고립 브랜치 0, 발송 원장 대사 ok)
- compute_exit_levels 산식 수기 재검증 일치, pending SELL 트리거 바인딩 올바름
- 시간감쇠·momentum_tilt 구현이 백테스트 문서와 일치
- 리포트 실물의 섹션 구조·파서 앵커 계약 준수 (check_report_contract violations 0)

---

## 우선 조치 권고 (순서)

**즉시 (이번 주)**
1. A-2: market_calendar에 8/17·10/5 추가 (1줄×2)
2. A-5: self_audit weeks_seen을 날짜 기반으로 — **7/12 전 필수**
3. A-1: write_audit_report에 returncode·빈 출력 감지(status=ERROR) + pipeline_audit.yml `|| true` 제거
4. B-3: fetch_consensus workflow_dispatch 수동 재수집
5. B-1/B-2: watchlist stop/target/shares_held를 portfolio·exit_levels와 동기화(스크립트 신설 권장) — 보유 판정은 portfolio.positions를 정본으로 통일
6. D-1/D-2: 1800의 1.0→1.5×ATR 정정, 1500 §4 모순 해소

**8/14 전**
7. A-3: fetch_fundamentals REPORT_ORDER 역순 수정
8. A-6: 카톡 토큰 경보 재설계(최초 refresh 관측일 기준) + `::add-mask::` 적용
9. A-4: rule_attribution의 exit_tracking 쓰기를 setdefault로(또는 보유 종목 제외)

**구조 개선 (다음 policy review 사이클)**
10. C-1 목록 중 최소 게이트 3종 코드화: closing_auction ts 검증, 신규 진입 R/R 하한, earnings_blackout
11. B-8: policy.json·lessons.md 압축 방안(핫패스 분리), target_estimate의 report_section_md 분리 파일화
12. B-7: 주간 아카이브 실패를 7일 창 밖에서도 잡도록 감사 로직 수정 + W24~W27 소급 생성
13. C-2: check_state_schema 값 검증(null 금지)·전 라인 스캔, reconcile trade_count 비교 추가
14. D-5/D-6: README·file_references 일괄 갱신
