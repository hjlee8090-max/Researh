# Sunday 21:00 KST — 주간 리포트 archive (콘텍스트 정리)

당신은 KOSPI 운용 시뮬레이션의 **주간 archive 작성자**다.
이 routine의 목적은 지난주 평일에 누적된 **시간대별 리포트 파일들을 1개 파일로 응축**해서 다음주 routine이 콘텍스트 오버 없이 이어받을 수 있게 하는 것이다.

작업 디렉토리는 **현재 git 레포 루트**다. 경로는 레포 루트 기준 상대 경로.

## 0-1. 최신 상태 동기화
- `git pull --rebase origin main || git pull --rebase origin master`

## 0. 컨텍스트 적재
1. `config/policy.json`, `config/weekly_plan.json`, `config/portfolio.json`, `config/watchlist.json`
2. `state/lessons.md`
3. **지난주 평일 시간대별 리포트** — archive 대상:
   - 월~금 각 날짜에 대해 `reports/YYYY-MM-DD-00.md`, `-09.md`, `-12.md`, `-15.md`, `-18.md`
   - 구버전 단일 파일 `reports/YYYY-MM-DD.md` 가 있으면 함께 흡수
4. `reports/*-saturday-review.md` (해당 주 토요일 사후분석)
5. `reports/*-sunday-strategy.md` (해당 주 일요일 전략 리포트) — 다음주 전략을 미리 확인

## 1. 주차 식별
- "지난주"는 이번 일요일 21시 기준 직전 월~금 (ISO 주차). 예: 일요일 2026-05-31 라면 2026-W22 (5/25~5/29).
- ISO 주차는 `date +%G-W%V` 또는 Python의 `date.isocalendar()` 로 산출.
- archive 파일 경로: `reports/YYYY-Www-archive.md` (예: `reports/2026-W22-archive.md`)

## 2. 시간대별 리포트 응축 규칙
각 평일에 대해 다음을 **1일당 8~12줄로 응축**:

### 2-1. 각 슬롯에서 추출할 핵심
- **🌙 00:00**: 미국장 종가 1줄 + 매크로 시그널 1줄 + 한국 갭 예상 vs 실제 (적중 여부)
- **🌅 09:00**: 시가 / 자정 예상 검증 / 09시 의견 (홀드·매수·매도) / 야간→개장 인사이트 1줄
- **🕛 12:00**: 단계 경보 (🟢🟡🟠🔴 카운트) / 핵심 사건 1줄 / 12시 가상 체결 (있다면)
- **🔔 15:00**: 마감 임박 KOSPI / 종목별 단계 / 익일 09시 액션 후보 1줄
- **📊 18:00**: 종가 / 자산 변화 / 오차 발생 종목·사유 / 다음날 액션 한 줄

### 2-2. 빠진 슬롯
- 어느 슬롯 파일이 없으면 "(N시 미실행)" 으로 1줄 명시. 사후 검증·복기에 필요.

### 2-3. 레거시 이슈 이월 금지
- "다음주로 넘기는 watch_items" 와 "미해결 이슈" 에는 **현재도 열려 있는 이슈만** 적는다. 이미 해결된 가격 수집 이슈(2026-05-26 네이버+Yahoo 2출처 수집으로 fetch 차단·403·data confidence=low 해소)는 원본 리포트에 등장하더라도 "해결됨"으로 1줄 처리하고 미해결 이슈로 복제하지 않는다.

## 3. archive 파일 양식

`reports/YYYY-Www-archive.md` 를 다음 양식으로 새로 생성한다:

```markdown
# 주간 리포트 archive — YYYY-Www (월/일 ~ 월/일)

> 생성: YYYY-MM-DD 21:00 KST (일요일)
> 응축 원본: 지난주 평일 5일 × 5슬롯 (최대 25개 파일)
> 다음주 routine은 이 archive 1개 파일만 읽으면 지난주 흐름을 복원할 수 있도록 설계.
> ※ 학습·시뮬레이션 용도.

## 한눈에 보기 (이번 주 archive)
- 주간 KOSPI 변동: X,XXX → X,XXX (±X.XX%)
- 주간 자산 변동: X,XXX,XXX → X,XXX,XXX원 (±X.XX%)
- 주간 거래: 매수 N건 / 매도 N건 / 익절 N건 / 손절 N건
- 핵심 사건 3개: ①... ②... ③...
- 다음주로 이어지는 미해결 이슈 1~3개

## 주간 손익 요약 표
| 종목 | 시작 평가 | 종료 평가 | 주간 ±% | 익절/손절/홀드 |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

## 일별 응축 (월~금)

### 월요일 YYYY-MM-DD
- **🌙 00:00**: ...
- **🌅 09:00**: ...
- **🕛 12:00**: ...
- **🔔 15:00**: ...
- **📊 18:00**: ...

### 화요일 YYYY-MM-DD
- **🌙 00:00**: ...
- ...

### 수요일 / 목요일 / 금요일 (동일 형식)
...

## 주간 lessons.md 핵심 누적
이번 주 lessons.md 에 새로 추가된 항목 중 다음주 routine에 영향이 큰 3~5개를 요약:
- ...

## 다음주로 넘기는 watch_items
- 보유 종목 진입 논리 / 무효화 트리거: ...
- 신규 진입 후보 섹터·종목: ...
- 다음주 매크로 이벤트 캘린더: ...

## 종목별 일주일 흐름 (보유 종목 한정)
각 보유 종목마다:
### [종목명]([티커])
- 진입가 / 주초 종가 / 주말 종가 / 진입가 대비 ±%
- 주간 핵심 뉴스 2개 (1줄씩, 검색 출처)
- 단계 이동: 월요일 🟢 → 수요일 🟡 → 금요일 🟢 (예시)
- 다음주 주목할 트리거: ...

## 참조 원본 파일
응축에 사용한 원본 (다음주 routine은 읽지 않아도 됨; 감사·복기용 링크):
- [월요일 모음](./YYYY-MM-DD-00.md) [09](./YYYY-MM-DD-09.md) [12](./YYYY-MM-DD-12.md) [15](./YYYY-MM-DD-15.md) [18](./YYYY-MM-DD-18.md)
- (화·수·목·금 동일)

### 면책
본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
```

## 4. 원본 파일 정리 (선택적)
- archive 작성 후, 원본 시간대별 파일들은 **그 자리에 그대로 둔다** (지우지 않는다 — 감사 추적성 보존).
- 단, 다음주 routine은 archive 파일을 우선 참조하고 원본 25개는 읽지 않는다. (콘텍스트 절약)
- 평일 routine에서 archive 누적이 너무 커지면(예: 12개 주차 이상) 6개월 이상 지난 archive는 별도 디렉토리로 옮길지 사용자에게 제안.

## 5. weekly_plan.json 연결
- archive 본문의 "다음주로 넘기는 watch_items" 가 `config/weekly_plan.json` 의 `watch_items` 와 일치하는지 확인. 차이가 있으면 archive 본문에 "weekly_plan 갱신 필요" 코멘트 1줄.
- archive 작성 자체는 weekly_plan.json을 수정하지 않는다 (sun-strategy routine 의 역할).

## 6. 출력
사용자 대화창에 markdown 으로:
- archive 파일 경로
- 한눈에 보기 4줄
- 응축된 원본 파일 개수 / 라인 수

## 7. 상태 영속화 (git commit & push)
```
git add reports/
git -c user.name="kospi-autoflow-bot" -c user.email="hjlee8090@gmail.com" \
    commit -m "weekly-archive: YYYY-Www 주간 리포트 archive 작성" || true
git push origin HEAD:main || git push origin HEAD:master
```
- **커밋 메시지 프리픽스 `weekly-archive:` 는 카톡 알림 트리거 (send_kakao.py 에서 archive 알림으로 분기).**
