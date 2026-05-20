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
| 00:00 | 글로벌 야간 점검 (미국장 개장 직후·유럽장 후반·환율·원자재)<br>→ 보유 종목별 야간 영향 매핑·한국 개장 갭 예측 | reports/(자정 섹션 생성), watchlist.json 코멘트 |
| 09:00 | 자정 예측 검증 + 미국장 마감(05:00)까지 추가 흐름 + 한국 개장 인사이트 | reports/(09시 섹션 append), watchlist.json, trade_log.jsonl |
| 12:00 | 장중 점검 (모멘텀/이슈/단계 경보) | reports/(12시 섹션 append), watchlist.json |
| 15:00 | 마감 점검 (15:30 정마감 직전), 종가 임박치로 1차 검증 | reports/(15시 섹션 append), watchlist.json |
| 18:00 | 종가 확정 → 목표가 오차 판정 → lessons.md 갱신<br>포트폴리오 평가·체결, 종합 리포트 작성, 익일 종목 교체 결정 | reports/(18시 종합 섹션 append), portfolio.json, lessons.md, watchlist.json |

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
| 00:00 | _(미등록 — https://claude.ai/code/routines 에서 `prompts/0000_global.md` 를 실행하도록 매일 00:00 KST trigger 추가 필요)_ |
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

## 모바일 노티 셋업 (HTML 리포트 + 카카오톡)

09/12/15/18시 routine 마다 단계적으로:
1. 각 routine 이 `reports/YYYY-MM-DD.md` 의 **자기 시간대 섹션** 을 누적 작성 (09시 신규 생성, 12/15/18은 append)
2. GitHub Actions가 `reports/*.md` → HTML 변환 → GitHub Pages 배포
3. 카카오 '나에게 보내기' API 로 **해당 시간대 섹션의 '한눈에 보기'** 요약 + Pages 링크 전송
4. 폰 카톡에서 링크 탭 → 같은 페이지에 09→12→15→18 흐름이 누적되어 있어 "왜 이 결정을 했는지" 추적 가능

### 리포트 누적 구조 (파이프라인)
```
🌙 00:00 글로벌 야간 점검    ← 00시 routine 작성 (그날 파일 신규 생성, 미국장·유럽장·환율·매크로 → 한국 영향 매핑)
🌅 09:00 개장 점검          ← 09시 routine 추가 (자정 예측 검증 + 미국장 마감까지 흐름 + 한국 개장 인사이트)
🕛 12:00 장중 점검          ← 12시 routine 추가 (09시 검증·반박·강화, 단계 경보)
🔔 15:00 마감 임박 점검      ← 15시 routine 추가 (익일 액션 후보)
📊 18:00 종합·확정 리포트    ← 18시 routine 추가 (종가·오차·자기보완 학습 + 다음날 자정 routine 이 흡수할 메모)
```
각 routine 은 **이전 시간대 섹션을 절대 수정하지 않고** 자기 섹션만 append → 의사결정 히스토리 보존 → 18시 종합에서 흐름 검증 → 다음날 00시 routine 이 다시 이어받음 (순환 파이프라인).

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
