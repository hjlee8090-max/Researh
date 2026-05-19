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
  policy.json         정책 파라미터 (목표/손절/비중)
  portfolio.json      현금·보유종목·평가금액
  watchlist.json      현재 추천 3종목 + 진입가·목표가·손절가·코멘트
state/
  lessons.md          자기보완 학습 노트 (오차 사유 누적)
  trade_log.jsonl     모든 의사결정 이력 (라인당 1 JSON)
reports/
  YYYY-MM-DD.md       초보자 친화 일일 리포트
prompts/
  0900_pre_market.md  개장 점검 프롬프트
  1200_midday.md      장중 점검
  1500_close.md       마감 점검
  1800_report.md      목표가 검증 + 학습 + 일일 리포트
```

## 스케줄 (Asia/Seoul, 평일)
| 시각 | 내용 | 산출물 갱신 |
|------|------|------------|
| 09:00 | 개장 후 뉴스 스캔 → 종목별 매수/매도/홀드 + 단기 액션 | watchlist.json, trade_log.jsonl |
| 12:00 | 장중 점검 (모멘텀/이슈) | watchlist.json 코멘트 |
| 15:00 | 마감 점검 (15:30 정마감 직전), 종가 임박치로 1차 검증 | watchlist.json 코멘트 |
| 18:00 | 종가 확정 → 목표가 오차 판정 → lessons.md 갱신<br>포트폴리오 평가·체결, 일일 리포트 작성, 익일 종목 교체 결정 | reports/, portfolio.json, lessons.md, watchlist.json |

## 자기보완 루프
1. 18시 프롬프트가 watchlist의 **각 종목 실제 종가 vs 목표가** 비교
2. ±5% 이내면 OK, 초과면 사유 분류
   - `매크로` (환율/금리/지수)
   - `섹터` (업종 이슈)
   - `개별` (실적/공시/뉴스)
   - `가정오류` (애널리스트 가정 자체가 틀림)
3. `state/lessons.md`에 누적
4. **모든 추천·점검 프롬프트는 동작 직전 lessons.md를 먼저 읽고 동일 실수를 피한다**

## 실행 방법
GitHub 레포 `hjlee8090-max/Researh`에 호스팅됨. 어디서든 동일 상태를 이어받아 동작.

### A. 원격 routine (PC 꺼져있어도 자동 실행) — 기본 모드
- 평일 09:00 / 12:00 / 15:00 / 18:00 KST에 Anthropic 클라우드에서 자동 발화
- 각 routine은 이 레포를 git clone → 해당 시각 prompt 파일 읽기 → 실행 → git commit/push
- 등록·관리: https://claude.ai/code/routines

| 시각 | Routine ID |
|---|---|
| 09:00 | `trig_01SMcVbAS1L2tUrhKAWbHUk7` |
| 12:00 | `trig_01Fx8FfsxXqCsugnW3XjZM6M` |
| 15:00 | `trig_01U8ZvyhgVRkYTDeP9BjttjQ` |
| 18:00 | `trig_01TD41NpsamHcveUeokYcyyM` |

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
