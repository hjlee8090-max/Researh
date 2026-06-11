# KOSPI 자기보완형 주식 오토플로우

500만원 가상 포트폴리오로 KOSPI 대형주 3종목을 중장기 운용하는 시뮬레이션 파이프라인.
매일 4번(09/12/15/18시) 자동으로 뉴스를 조사하고 의사결정을 갱신하며,
18시에 목표가 오차를 분석해 다음날 추천에 반영하는 **자기보완 루프**를 갖는다.

> 본 산출물은 학습·시뮬레이션 용도이며 실제 투자 권유가 아니다.

## 정책
- **종목군**: KOSPI 대형주(시총 상위) 중심
- **운용 기간**: 중장기 (스윙 ~ 수 주)
- **목표 수익**: 종목당 +10%
- **손절선**: 종목당 -10%
- **섹터**: 제한 없음
- **포트폴리오**: 500만원, 종목당 최대 30%, 현금 최소 10%
- **거래비용**: 슬리피지 0.2% + 거래세 0.18% (시뮬레이션)

## 디렉토리
```
config/
  policy.json              정책 파라미터 (목표/손절/비중)
  portfolio.json           현금·보유종목·평가금액
  watchlist.json           현재 추천 3종목 + 진입가·목표가·손절가·코멘트
  weekly_plan.json         이번 주 thesis·watch_items·invalidation_triggers
  candidates.json          신규 진입 후보 목록 (fetch_market_data가 5거래일 추세 자동 수집 대상)
  universe.json            (v2.7) 신규 진입 후보의 모집단 — screen_universe.py가 상대강도+테마로 랭킹·승격/회전아웃 제안
  market_calendar.json     KRX 휴장일 + 장중 세션(정규장 09:00~15:30·동시호가) — 0-A 영업일·세션 가드
  catalysts.json           종목별 다가오는 촉매(실적발표·배당·매크로) 캘린더 — generated_events(법정기한 추정)+manual_events(웹검색 확정). D-day 경보·신규 진입 보류 (catalyst-calendar)
  news_impact.json         뉴스 유형별 주가 가산점 테이블(+manual_news 기록) — estimate_target_price.py 의 뉴스/촉매 프리미엄 입력
  news_keywords.json       뉴스 자동 분류 키워드 레지스트리(12개 유형과 1:1, 종목 별칭 포함) — fetch_news.py 입력. 키워드 보강=분류 보강
  news_history.json        백테스트용 라벨드 뉴스 타임라인(레포 운용 기록 추출) — backtest_target_model.py 입력
state/
  lessons.md               자기보완 학습 노트 (오차 사유 누적)
  trade_log.jsonl          모든 의사결정 이력 (라인당 1 JSON)
  audit_log.jsonl          파이프라인 자동 점검 이력
  market_snapshot.json     (gitignored) 매 routine마다 fetch_market_data.py가 생성하는 다중출처 가격·5일추세 스냅샷
reports/
  YYYY-MM-DD-00.md         🌙 자정 글로벌 야간 리포트
  YYYY-MM-DD-09.md         🌅 개장 점검 리포트
  YYYY-MM-DD-12.md         🕛 장중 점검 리포트
  YYYY-MM-DD-15.md         🔔 마감 임박 점검 리포트
  YYYY-MM-DD-18.md         📊 18시 종합·확정 리포트
  YYYY-MM-DD-audit.md      파이프라인 자동 감사 리포트 (평일 19:30)
  YYYY-MM-DD-saturday-review.md  토요일 사후분석
  YYYY-MM-DD-sunday-strategy.md  일요일 전략
  YYYY-Www-archive.md      일요일 21시 — 지난주 평일 25개 파일을 1개로 응축
prompts/
  0000_global.md           자정 글로벌 야간 점검
  0900_pre_market.md       09시 개장 점검
  1200_midday.md           12시 장중 점검
  1500_close.md            15시 마감 임박
  1800_report.md           18시 종합·확정 + 자기보완 루프
  saturday_review.md       토요일 사후분석
  sunday_strategy.md       일요일 다음주 전략
  sunday_policy_review.md  일요일 20시 정책·프롬프트 패치 리뷰 (lessons → policy 반영 점검)
  sunday_archive.md        일요일 21시 주간 archive (콘텍스트 정리)
  weekend_report.md        주말 노트
docs/
  file_references.md       파일 참조 구조 점검표 (어느 prompt/script가 어느 파일을 읽는지)
  github_mobile_pipeline.md
  weekend_dryrun_checklist.md  주말 routine 첫 실행 점검표
scripts/
  fetch_market_data.py     네이버 + Yahoo Finance 다중출처 가격 수집 + 5거래일 추세 자동 산출
  fetch_catalysts.py       종목별 다가오는 촉매 추정 (정기보고서 법정기한 + DART list.json 보정) → config/catalysts.json
  fetch_consensus.py       증권사 컨센서스 수집 (FnGuide — 목표주가·투자의견·추정치) → state/consensus.json (Phase 2 earnings-preview 입력)
prompts/
  earnings_preview.md      Phase 2 — 실적 발표 전 beat/inline/miss 시나리오 + 발표 후 자기채점 (이벤트 기반, 0900·1800 호출)
  check_market_open.py     KRX 영업일/휴장일 판정 (exit 0=영업, 10=주말, 11=공휴일)
  check_market_session.py  KRX 장중 세션·체결모드 판정 (live/closing_price/none) — 18시 종가청산만, 마감후 신규진입 금지
  score_candidates.py      후보 종목 자동 점수화 (추세·신뢰도·thesis·악재) → 09시 routine 진입 후보 랭킹
  estimate_target_price.py 목표주가 추정 v1.1 — 밸류 밴드·컨센·테마(호라이즌할인·추세게이트)·뉴스/촉매(시간감쇠·기반영차감)·섹터 활발성 결합 → state/target_estimate.json
  fetch_news.py            종목 뉴스 자동 수집(Google News RSS 국문·영문+네이버 종목뉴스)·키워드 분류 → state/news_feed.json (fetch_news.yml 평일 07:30/17:40 KST)
  score_target_estimates.py 추정 vs 실현 주간 채점 + 뉴스 키워드 보강 점검 → state/estimate_scorecard.json (sunday_policy_review 0-C)
  fetch_history.py         백테스트용 장기 일봉(~2.5년) 수집 → state/price_history.json (fetch_history.yml 수동/push 트리거)
  backtest_target_model.py 목표주가 추정식 백테스트 — 충격-감쇠·이벤트 스터디·워크포워드 검증, v1.0 vs v1.1 비교 → state/backtest_target_model.json
  screen_universe.py       (v2.7/2.8) 모집단(universe.json) 상대강도+테마 랭킹 → 승격/회전아웃 제안 + 섹터별 몰입(sector_rotation·avoid_reentry) → state/universe_screen.json
  reconcile_portfolio.py   trade_log ↔ portfolio.json cash·positions·realized_pnl 정합성 검증
  build_lessons_index.py   lessons.md 분류·룰 자동 인덱싱 → sunday_policy_review 1차 입력
  audit_pipeline.py        파이프라인 무결성 점검 (의존성 0)
  write_audit_report.py    audit 결과 + 자동 수정 → 사람 친화 리포트
  build_html.py            reports/*.md → _site/*.html (GitHub Pages)
  send_kakao.py            카카오 '나에게 보내기' 알림
  kakao_oauth_helper.py    1회 refresh_token 발급
```

## 스케줄 (Asia/Seoul)
**평일** — 시간대별 분리 파일 5개 생성 (한 파일 = 한 슬롯)

| 시각 | 내용 | 생성 파일 |
|------|------|------------|
| 00:00 | 글로벌 야간 점검 (미국장·유럽장·환율·원자재) → 보유 종목 야간 영향 매핑·한국 개장 갭 예측 | `reports/YYYY-MM-DD-00.md` |
| 09:00 | 자정 예측 검증 + 미국장 마감(05:00)까지 흐름 + 한국 개장 인사이트 | `reports/YYYY-MM-DD-09.md` |
| 12:00 | 장중 점검 (단계 경보·함정 패턴 cross-check) | `reports/YYYY-MM-DD-12.md` |
| 15:00 | 마감 임박 점검, 종가 임박치로 1차 검증, 익일 09시 액션 후보 정리 | `reports/YYYY-MM-DD-15.md` |
| 18:00 | (마감 후) 종가 확정 → 목표가 오차 판정 → lessons.md 갱신, 포트폴리오 평가, **종가 청산만**(ts=15:30·closing_auction, 신규진입은 09시 이연), 종합 리포트 | `reports/YYYY-MM-DD-18.md` |

**주말**

| 시각 | 내용 | 생성 파일 |
|------|------|------------|
| 토 18:00 | 지난주 사후분석 | `reports/YYYY-MM-DD-saturday-review.md` |
| 일 18:00 | 다음주 전략·weekly_plan 갱신 | `reports/YYYY-MM-DD-sunday-strategy.md` |
| **일 21:00** | **지난주 평일 25개 시간대별 파일 → 1개 archive 응축** (콘텍스트 절약) | `reports/YYYY-Www-archive.md` |

> 각 시간대 파일은 **자기 슬롯만 담는다**. 이전 시간대 결론은 "이전 시간대로부터 이어받기" 박스에 1~3줄로만 요약. 이전 파일은 **절대 수정하지 않음** (히스토리·자기보완 학습 재료 보존).

## 자기보완 루프
1. 18시 프롬프트가 watchlist의 **각 종목 실제 종가 vs 목표가** 비교
2. ±5% 이내면 OK, 초과면 사유 분류
   - `매크로` (환율/금리/지수)
   - `섹터` (업종 이슈)
   - `개별` (실적/공시/뉴스)
   - `가정오류` (애널리스트 가정 자체가 틀림)
3. `state/lessons.md`에 누적
4. **모든 추천·점검 프롬프트는 동작 직전 lessons.md를 먼저 읽고 동일 실수를 피한다**

## 목표주가 추정 레이어 (estimate_target_price.py, v1.1)
파이프라인의 흩어진 신호를 하나의 식으로 결합해 **12개월 내 도달 가능한 대략적 목표가(원)** 를 산출한다:

```
추정목표가 = 기준가 × (1 + 추세게이트×(테마P + 양뉴스P) + 음뉴스P + 섹터P + 모멘텀틸트) → 천장 캡
```

v1.1은 삼성전자·현대차 2.5년(592거래일) 백테스트로 보정됐다
(`reports/2026-06-10-target-model-backtest.md`): ①추세 게이트 — 테마·호재는 자금이 따라오는
주도주(KOSPI 대비 60일 초과수익 ≥+10%p)에서만 전액 반영(후행주 0.3배, 60일 적중률 25.9%→70.4%)
②뉴스 기반영분 차감 — 뉴스가 이미 움직인 초과수익을 가산점에서 빼 이중계상 차단
③모멘텀 틸트 재보정 — 초과수익 [10,30) 구간 최고·극단(≥30) 둔화 + 52주고점 근접 가점.

v1.2는 뉴스 입력을 자동화했다: `fetch_news.py`(평일 07:30/17:40 KST)가 Google News RSS와
네이버 종목뉴스를 수집해 `config/news_keywords.json`의 유형별 키워드로 분류 →
`state/news_feed.json`. 자동 분류 항목은 confidence factor(0.6) 할인으로 가산점에 반영되고,
검증을 거친 manual_news 가 항상 우선한다. **유형 미매칭 기사도 unclassified 로 보존**되므로
라우틴이 검토해 manual_news 로 승격하거나 키워드를 보강한다(재현율 우선 — 놓친 뉴스는
sunday_policy_review 에서 키워드 레지스트리에 반영).

v1.3은 해외뉴스와 연속 섹터값을 더했다(`reports/2026-06-11-sector-global-research.md`):
①해외뉴스 — 영어 쿼리 8종(채널·대상 종목 태깅) 수집·분류 후 **채널 전이계수**(오버나이트 β
실증: 동종 0.45·고객 0.35·매크로 0)로 할인해 가산. 교차섹터 전이 없음(β≈0)이 실증돼 쿼리별
affects_tickers 매핑이 강제된다. ②**섹터값** — 섹터 거래대금 점유율(자금 집중도 0.7) +
상대모멘텀(0.3)의 연속값으로, 섹터 프리미엄 = 최대 8% × (0.5×몰입 사다리 + 0.5×섹터값) 블렌드
(60일 예측력 사다리 단독 대비 +40%, 조선 0.521·AI메모리 0.451).

v1.4는 자기보완 루프에 편입됐다: 추정 스냅샷이 `state/target_estimate_log.jsonl` 에 매 실행
적재되고, `score_target_estimates.py` 가 추정 vs 실현(5/20/60거래일)을 채점해
`state/estimate_scorecard.json` 을 만든다. sunday_policy_review(일 20시)가 0-C 단계에서
실행해 §1-5 로 점검한다 — 적중률 악화 시 추정식 패치 후보 상정(단 파라미터 변경은 백테스트
재실행 근거 필수), unclassified/오분류 검토 → manual_news 승격·키워드 보강 의무.
- **기준가**: PER/PBR 5년 밴드 중앙값 적정가(valuation.json) + 컨센서스 목표가(consensus.json) 평균. 결측 시 현재가 폴백(등급 하향)
- **테마P** (≤20%): Σ(테마 strength × 종목 노출) × 호라이즌 할인 — "3~5년 메가트렌드"는 12개월 목표가에 1/3만 반영
- **뉴스P** (±12%): `config/news_impact.json` 유형별 가산점 — 과거 뉴스는 90일 시간감쇠, 다가오는 촉매(catalysts.json)는 발생확률×D-day 근접가중×방향(DART earnings_signal)으로 할인
- **섹터P** (≤8%): 섹터 몰입 신호(universe_screen.json)로 "활발성이 언제 올지"를 4단계(현재 활발/1~2개월/2~4개월/촉매 대기)로 추정해 차등 반영
- **천장 캡**: policy.valuation_anchor 동일 — min(추정치, 컨센×1.15, 밸류에이션 천장)

출력 `state/target_estimate.json` 은 fetch_prices 워크플로마다 갱신되며, watchlist 의 target_price 를 자동으로 덮어쓰지 않는다(routine 의 dynamic_exit_model 목표가 산정 참고 레이어). 신뢰등급 A/B/C 는 가용 데이터 레이어 수(밸류 밴드·컨센·시세·테마·섹터·실적신호) 기준 — 밸류 밴드·컨센이 시드되기 전에는 B/C 수준의 거친 추정이다.

## 실행 방법
GitHub 레포 `hjlee8090-max/Researh`에 호스팅됨. 어디서든 동일 상태를 이어받아 동작.

### A. 원격 routine (PC 꺼져있어도 자동 실행) — 기본 모드
- 평일 09:00 / 12:00 / 15:00 / 18:00 KST에 Anthropic 클라우드에서 자동 발화
- 각 routine은 이 레포를 git clone → 해당 시각 prompt 파일 읽기 → 실행 → git commit/push
- 등록·관리: https://claude.ai/code/routines

| 시각 | Routine ID |
|---|---|
| 00:00 | 등록됨 (매일 00:00 KST — `prompts/0000_global.md`) |
| 09:00 | `trig_01SMcVbAS1L2tUrhKAWbHUk7` |
| 12:00 | `trig_01Fx8FfsxXqCsugnW3XjZM6M` |
| 15:00 | `trig_01U8ZvyhgVRkYTDeP9BjttjQ` |
| 18:00 | `trig_01TD41NpsamHcveUeokYcyyM` |
| 토 18:00 | 등록됨 (2026-06-10 — `prompts/saturday_review.md`, rule_attribution 의무 인용) |
| 일 18:00 | 등록됨 (2026-06-10 — `prompts/sunday_strategy.md`, valuation.json 주간 시드 포함) |
| 일 20:00 | 등록됨 (2026-06-10 — `prompts/sunday_policy_review.md`, lessons → policy 패치 리뷰 + 룰 손익 채점·일몰 심사) |
| 일 21:00 | 등록됨 (매주 일요일 21:00 KST — `prompts/sunday_archive.md`) |

> **routine 산출물의 main 자동 반영**: 원격 routine 이 격리 환경에서 세션 브랜치에만 push 하고 main 에 머지되지 않는 경우를 대비해 `.github/workflows/auto_merge_routines.yml` 가 동작한다. routine 커밋 프리픽스(`chore(` / `report:` / `audit:` / `sat-review:` / `sun-strategy:` / `policy-review:` / `weekly:` / `weekly-archive:`)이고 봇 작성자인 브랜치 push 를, routine 커밋을 `origin/main` 위에 rebase 한 뒤 fast-forward 로 main 에 머지한다(헤드 커밋 메시지 보존 → 카톡 알림 정상 발화). 충돌 시에는 머지하지 않고 브랜치를 남겨 수동 검토를 유도한다. routine 프롬프트 §commit 의 `git push origin HEAD:main` 이 환경 제약으로 세션 브랜치에 떨어져도 이 워크플로가 닫아준다.

### B. 로컬 Claude Code (선택)
PC에서 직접 돌리고 싶을 때:
```
git pull --rebase
prompts/0900_pre_market.md 실행 (또는 1200/1500/1800)
```
프롬프트 내부에 git pull/push 절차가 포함되어 있어 원격과 동일한 상태 일관성을 보장한다.

### C. 로컬 Windows 작업스케줄러 (옵션)
PC가 항상 켜져있고 빠른 응답을 원할 때 추가 등록 가능:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1
```
원격 routine이 이미 PC 오프에도 동작하므로 **필수 아님**. 중복 실행되어도 git rebase로 충돌 없이 흡수된다.

## 첫 가동
- 구조 세팅 + GitHub 푸시 완료. **다음 09:00 KST 원격 routine 발화 시 종목 3개 첫 추천**.
- 추천 직후 가상 매수 체결 기록 → 18시부터 정상 자기보완 루프.

## 모바일 노티 셋업 (HTML 리포트 + 카카오톡)

각 routine 은 **자기 시간대 전용 리포트 파일을 새로 생성** 한다 (이전 파일 수정 금지):
1. 00/09/12/15/18 routine → `reports/YYYY-MM-DD-{00,09,12,15,18}.md` 각각 1개
2. GitHub Actions가 `reports/*.md` → HTML 변환 → GitHub Pages 배포
3. 카카오 '나에게 보내기' API 로 **해당 시간대 파일의 '한눈에 보기'** 요약 + Pages 링크 전송 (그 슬롯 HTML 페이지로 바로 이동)
4. 인덱스 페이지(`/index.html`)에서 날짜별로 5개 슬롯이 한 카드로 묶여 있어 "왜 이 결정을 했는지" 추적 가능
5. 일요일 21시 archive routine 이 지난주 평일 25개 파일을 1개 `reports/YYYY-Www-archive.md` 로 응축 → 다음주 routine 콘텍스트 절약

### 시간대별 리포트 파이프라인 (분리 파일)
```
🌙 00:00 글로벌 야간 점검    → reports/YYYY-MM-DD-00.md
🌅 09:00 개장 점검          → reports/YYYY-MM-DD-09.md  (이전: -00.md를 "이어받기" 박스에서 요약)
🕛 12:00 장중 점검          → reports/YYYY-MM-DD-12.md  (이전: -09.md 요약)
🔔 15:00 마감 임박 점검      → reports/YYYY-MM-DD-15.md  (이전: -12.md 요약)
📊 18:00 종합·확정 리포트    → reports/YYYY-MM-DD-18.md  (이전 4개를 모두 종합·검증)
🗂️ 일 21:00 주간 archive    → reports/YYYY-Www-archive.md  (지난주 평일 25개 → 1개로 응축)
```

각 시간대 파일은 다음 공통 섹션을 포함한다 (초보자 친화):
- **이전 시간대로부터 이어받기**: 1~3줄로 이전 슬롯 결론 요약 → 단일 파일만 봐도 흐름 추적 가능
- **⚠️ 위험·매매 시그널 시각화**: 진입가·현재가·목표가·손절가를 1줄 게이지로 표시
- **🎓 이 시간대 학습 포인트 3개**: 초보자가 챙길 핵심 학습
- **📖 오늘 등장한 용어 사이드박스**: HBM·NIM·DXY·VIX 등 본문에 나온 용어 풀이

이전 시간대 파일은 **절대 수정하지 않는다** (히스토리·자기보완 학습 재료 보존).

### 1회 셋업

**A. GitHub Pages 활성화** (1회)
- Settings → Pages → Source: **GitHub Actions** 선택

**B. Kakao Developers 앱 등록** (1회)
- https://developers.kakao.com 에서 앱 생성
- [앱 설정 > 플랫폼 > Web] 에 `https://example.com` 추가
- [제품 설정 > 카카오 로그인] 활성화, Redirect URI `https://example.com`
- [동의항목] '카카오톡 메시지 전송 (talk_message)' 사용 설정
- REST API 키 복사

**C. Refresh Token 발급** (1회, 로컬에서)
```bash
export KAKAO_REST_API_KEY=발급받은_키
python scripts/kakao_oauth_helper.py
# 출력된 URL 브라우저로 열고 동의 → ?code=XXX 복사 → 입력
# 출력된 refresh_token 복사
```

**D. GitHub Secrets 등록** (1회)
- Settings → Secrets and variables → Actions → New repository secret
- `KAKAO_REST_API_KEY` = REST API 키
- `KAKAO_REFRESH_TOKEN` = 발급받은 refresh_token

### 동작
- 00시 commit (`chore(00:00 ...)`) — 🌙 글로벌 야간 섹션 요약을 카톡 발송 (자정에 자고 있어도 아침에 확인 가능)
- 09/12/15시 commit (`chore(09:00 ...)` / `chore(12:00 ...)` / `chore(15:00 ...)`) — 해당 시간대 섹션 요약을 카톡 발송
- 18시 commit (`report:`) — 📊 18시 종합 섹션의 '한눈에 보기' 요약을 카톡 발송
- `refresh_token`은 60일 유효. 만료 임박 시 send_kakao.py 로그에 신규 토큰이 출력됨 → Secret 업데이트
- 60일 지나 완전 만료되면 1회 셋업 C/D 단계 재실행
