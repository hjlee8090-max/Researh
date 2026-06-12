# 계획서 — 콘텍스트 압축·파이프라인 연결 보강 (2026-06-12)

> 목적: routine 1회당 의무 적재량(~500KB)을 줄여 **콘텍스트 오버로 인한 규칙 누락·판단 열화를 방지**하고,
> 리포트·감사의 신호 품질을 높인다. 모든 변경은 "주식으로 돈 버는 자기보완 루프"를 기준으로 부합성을 점검했다.

## 0. 자기보완 루프 부합성 점검 결과

원칙: **학습 재료는 삭제하지 않고 이관(archive)** — 핫패스(매 routine이 읽는 파일)에서만 뺀다.
의사결정에 쓰이는 신호(카운터·미해결 교훈·열린 트리거·보유 종목 코멘트 최근분)는 그대로 둔다.

| 변경 | 부합 판정 | 코드 레벨 근거 |
|---|---|---|
| watchlist comments 정리 (보유 최근 12개, 이전분 archive) | ✅ | `send_kakao.py:327`는 `comments[-1]`만 사용. 학습은 lessons/trade_log/reports/rule_attribution이 담당. 전문은 `state/watchlist_archive.json` + git 보존 |
| 청산 종목 watchlist 제거 (전체 기록 archive 이관) | ✅ 조건부 | 재진입 규율(v2.11)은 **trade_log**의 직전 SELL을 봄(watchlist 아님). 조건: candidates.json **자동 추가 금지** — 정리 작업이 진입 경로를 다시 열면 매매 행동이 바뀐다. 재발굴은 universe.json(4종목 모두 등재 확인) → screen_universe 경로가 담당 |
| weekly_plan.watch_items 캡 15 + 만료분 archive | ✅ 루프 강화 | "내일 00/09시가 이어받을 트리거"라는 본래 신호가 7주치 날짜스탬프 노이즈(52개)에 묻히는 것 자체가 루프 저해. 원인은 append 오용 → 프롬프트에 "재작성(대체)" 명문화 |
| policy.changelog → docs/ 분리 (최근 5건만 유지) | ✅ 조건부 | 조건: `check_lessons_applied.py`의 haystack이 policy.json 원문 grep이므로 **분리 파일을 haystack에 추가** (미반영→오탐 방지) |
| portfolio.history → state/portfolio_history.jsonl (config엔 최근 10개) | ✅ | history의 프로그램적 reader 없음(전 스크립트 grep 확인). 주말 사후분석은 최근 10개(1주+)로 충분, 전체는 jsonl |
| lessons.md ✅codify 완료 항목 본문 응축 | ✅ 조건부 | codify된 룰은 이미 policy/prompts가 강제 — 본문 전문은 중복. 조건: `###` 헤딩·`- 분류:`·`**다음 적용 룰**:`·반복 마커 보존(build_lessons_index/check_lessons_applied 파서 계약), 누적 패턴 카운터 불변, 전문은 `state/lessons_archive.md` 이관, **편집 전후 두 스크립트 출력 diff 검증** |
| 보유 R/R 하한을 레짐 적응형으로 통일 | ✅ 수익 직결 | 고정 1.2는 strong_bull에서 승자 조기 청산 압력 = 6/10 구조 진단("조기청산 비용 41%")과 정면 모순. 진입과 동일한 `min_rr_by_tier` 적용 |
| trade_log 액션 whitelist 확장 | ✅ | 매일 같은 WARN 5건 = 경보 피로 → 진짜 경고 매몰. reconcile의 `BUY_`/`SELL_` prefix 분류와 정합화 |
| audit 콘텍스트 예산 감시 | ✅ | 매매 룰 래칫 감시(blocked_day_rate)와 동형의 "크기 래칫" 감시 — 이번 비대화의 재발 방지 장치 |
| 18시 리포트 KOSPI 벤치마크 행 | ✅ | "강세장 미참여(평균 비중 20.2% vs KOSPI +11.3%)" 교훈의 제도화 — 루프의 채점 기준 자체 개선 |
| stale 헤드라인 단정 금지 + 카톡 노출부 운영용어 금칙 | ✅ | 사람 감독자의 판단 오염 방지(미검증 +7.02% 단정 표기 류) |
| write_audit_report 빈 경고 버그 수정 | ✅ | 경고 디테일 소실 = 감사 가시성 훼손 |
| sunday_policy_review grep-first 적재 | ✅ | 이미 §1-1·§1-4가 grep 기반 — "prompts 전체 읽기" 지시만 정합화 |
| README·file_references 갱신 + 월요일 00시 미실행 표면화 | ✅ | 00시 등록은 레포 밖(claude.ai routines) — audit WARN으로 매주 표면화해 사용자 수정 유도 |

**판정: 전 항목 부합.** 단 4개 조건(위 표의 "조건부")을 구현에 포함해야 안전하다.

## 1. 진단 요약 (근거 수치)

- 평일 routine 의무 적재: config+state 447KB + 프롬프트 20~54KB + 당일 리포트 ~40KB ≈ **500KB+ (≈200K+ 토큰)**
- `watchlist.json` **1,945줄** — Read 도구 기본 캡(2,000줄) 임박. comments 무한 누적(삼성 51개), 청산 종목 4개 기록 영구 보존
- `weekly_plan.watch_items` **52개**(+3.1KB/일 최고속), `policy.changelog` 22건, `portfolio.history` 33건, `lessons.md` 42KB
- 월요일 00시 슬롯 3주 연속 미실행(5/25·6/1·6/8) — README "매일 등록"과 불일치
- audit 사람용 섹션 빈 경고 5건/일 (`write_audit_report.py:218-223` 디테일 미부착)
- R/R 임계 이중 기준: 09시 진입=레짐 적응(1.0~1.6) vs 18시 §2-2·audit=고정 1.2

## 2. 변경 목록

### A. 신규 스크립트 — `scripts/compact_state.py` (의존성 0)
주 1회(일 21시 sunday_archive routine §0)·수동 실행. **멱등**. `--dry-run` 지원.
1. **watchlist**: 보유 종목 comments 최근 12개 유지(이전분 → `state/watchlist_archive.json`).
   비보유 종목은 stock 객체 전체를 archive로 이관 + `candidates.json` 미등재 시 추가(thesis_id·rationale 승계).
2. **weekly_plan.watch_items**: 최신 15개 유지, 초과분 → `state/watch_items_archive.jsonl` (week_id 포함 1줄 1건).
3. **portfolio.history**: 전체를 `state/portfolio_history.jsonl`에 merge(날짜 dedup) 후 config엔 최근 10개 유지.
4. **policy.changelog**: 전체를 `docs/policy_changelog.md`에 누적 기록 후 policy엔 최근 5건 유지.

### B. 스크립트 수정
- `check_lessons_applied.py`: haystack에 `docs/policy_changelog.md` 추가 (조건 1).
- `write_audit_report.py`: `humanize_audit_line` — 매핑 텍스트가 `": "`로 끝나면 원문 디테일을 이어붙임(빈 경고 버그). 신규 audit 메시지 번역 추가.
- `audit_pipeline.py`:
  1. `ALLOWED_TRADE_ACTIONS` += `HOLIDAY_EVAL`·`MIDDAY_CHECK` + `BUY_`/`SELL_` prefix 허용(reconcile과 정합). 비매매 액션은 `ticker` 필수 해제.
  2. `audit_reward_risk`: `state/allocation.json`의 tier → `regime_adaptive_rr.min_rr_by_tier` 적용(없으면 기존 1.2 폴백).
  3. `audit_context_budget` 신규: watchlist >100KB 또는 >1,500줄 / policy >90KB / watch_items >20 / portfolio.history >20 / lessons.md >60KB → WARN. 프롬프트 35KB↑ INFO·60KB↑ WARN.
  4. 영업일인데 당일 `-00.md` 부재 → WARN "(00시 routine 등록/실행 확인 필요)" — 월요일 미실행 표면화.
  5. 당일 최신 슬롯 리포트의 `### 한눈에 보기` 블록에 운영 용어(`live_verify`·`web_verify`·`pre_trade`·`HTTP 403`·`stale`·`freshness`·`tier=`·`§` 등) 노출 시 WARN.

### C. 프롬프트 수정 (최소 diff — 콘텍스트 추가 부담 최소화)
- `1800_report.md`: §2-1 watch_items는 **append가 아니라 재작성**(열린 트리거만, ≤15, 만료분은 compact가 이관) / §2-2 임계를 "레짐 적응 하한(`min_rr_by_tier`, tier 미확정 1.2)"으로 통일 / 포트폴리오 표에 "같은 기간 KOSPI" 행 / 가독성 원칙에 stale 단정 표기 금지 1줄.
- `1500_close.md`: watch_items 갱신 규칙 1줄(재작성·캡).
- `0900_pre_market.md`·`1200_midday.md`: 가독성 원칙에 stale 단정 표기 금지 1줄.
- `sunday_archive.md`: §0에 `python scripts/compact_state.py` 실행 단계 추가(콘텍스트 정리 routine과 목적 일치), §7 git add 범위에 `config/ state/ docs/` 포함 (조건 4).
- `sunday_policy_review.md`: §0 적재를 "prompts 전체 읽기 → grep-first(인덱스·대조 산출물 우선, 필요한 섹션만 Read)"로 수정.
- `sunday_strategy.md`: weekly_plan.objective에 `kospi_week_start_close` 기록 1줄(벤치마크 주간 비교 기준).

### D. 일회성 데이터 정리 (이번 작업에서 실행)
- `compact_state.py` 실제 실행 → watchlist/weekly_plan/portfolio/policy 압축 + archive 파일 생성.
- `lessons.md` 응축: ✅codify 완료 항목 본문을 2~3줄(분류·다음 적용 룰·codify 참조)로 축약, 전문 → `state/lessons_archive.md` (조건 3 검증 동반).

### E. 문서
- `README.md`: 디렉토리 트리 중첩 오류 수정, "이어받기 박스" → "📝 오늘의 이야기" 서술 갱신, 월요일 00시 실측 미실행 기록(등록 확인 필요), 압축 정책·신규 파일 문단.
- `docs/file_references.md`: compact_state·archive 파일·changelog 분리 반영.

## 3. 검증 계획
1. 전 config/state JSON `json.load` 통과.
2. `build_lessons_index.py`·`check_lessons_applied.py` lessons 편집 전후 실행 — 카운터·hard/soft/manual 분류 동일 확인.
3. `reconcile_portfolio.py` exit 0 유지.
4. `audit_pipeline.py` 실행 — 기존 가짜 WARN(액션 5건) 소멸·신규 체크 동작 확인.
5. `compact_state.py` 2회 연속 실행 — 멱등성(2회차 변경 0).
6. `write_audit_report.py` 생성 리포트에서 경고 디테일 표기 확인.
7. `build_html.py` 정상 빌드.

## 4. 범위 외 (후속 제안)
- 프롬프트 본문 자체 감량(0900 54KB — v2.x 사고 이력 서술을 lessons 참조로 치환): 운영 프롬프트의 의미 수술이라 **별도 회차**에서 단독 진행 권장 (이번 audit INFO가 크기를 계속 감시).
- 월요일 00:00 트리거 등록: 레포 밖(claude.ai/code/routines) — 사용자 액션 필요.
