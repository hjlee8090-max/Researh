# Stage 2 준비 — 한국투자증권 모의투자 연결 전제 (2026-09-02 결정 기록)

> 코드 작업은 아직 하지 않는다. Stage 1 cutover 기준(`docs/plan_stage1.md` §3) 충족 후 착수. 이 문서는 결정과 사람이 미리 해 둘 일만 적는다.

## 결정 (Decision Log)
- D-6 실투입 자본 = 현재 파이프라인 평가금액. 보유 전량을 종가 현금화(`state/stage.json.capital.reset`, rule=capital_reset 의도)하고 그 현금이 사이징 상한.
- D-7 브로커 = 한국투자증권 Open API **모의투자(VTS)**. 실계좌 전환은 Stage 3 별도 결정.

## 확정 / 확인 필요
| 항목 | 상태 | 내용 |
|---|---|---|
| 사이징 상한 | 확정 | `stage.json.capital.reset.cash_after_reset_krw`. 모의투자 계좌의 브로커 기본 가상잔고는 상한이 아니다(브로커 잔고 ≠ 정책 자본) |
| 주문 입력 | 확정 | `state/order_intents.json` 만이 주문 원천. LLM 거부권은 유지(사유 필수) |
| API 자격 | 사람 작업 | KIS Developers 에서 모의투자 앱 등록 → APP KEY/SECRET, 모의투자 계좌번호(8-2). GitHub Secrets: `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ACCOUNT_PRODUCT`(기본 01), `KIS_MODE=vts` |
| 네트워크 | 확인 필요 | 모의투자 도메인(`openapivts.koreainvestment.com:29443`)에 GitHub Actions 러너에서 접속 가능한지 — 웹 세션 루틴은 이그레스 정책상 불가 가정. 주문 경로는 Actions 워크플로로 둔다 |
| 토큰 | 확인 필요 | 접근토큰 유효기간·발급 횟수 제한(모의투자도 1일 1회 권장으로 알려짐) — 캐시 전략 필요 |
| 호가·수량 | 확인 필요 | 모의투자에서 시장가/지정가·동시호가 주문 지원 범위. 의도의 `closing_auction` 청산을 어떤 주문유형으로 매핑할지 |
| 승인 채널(O-3) | 미결 | 카톡 나에게 보내기는 단방향. GitHub Issue 라벨 / Telegram 봇 / 승인 페이지 중 택1 — **Tier 2 신규매수 승인 경로가 없으면 Stage 2 착수 불가** |
| 대사 | 설계 예정 | 매일 브로커 잔고·체결 ↔ `portfolio.json`·`trade_log` 대조, 불일치 시 자동 정지(kill switch 파일) |

## 이번에 하지 않은 것
- 브로커 클라이언트·주문 스크립트·대사 스크립트 — cutover 심사 통과 후.
