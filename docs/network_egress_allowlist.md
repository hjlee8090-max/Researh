# 세션 네트워크 이그레스 allowlist (가격조회 403 근본 해결)

## 증상
오늘자 리포트가 "가격조회 다 실패 / 실시간 가격 확인 통로가 막혀(403) 신규 매수 보류"로
반복 기록된다(2026-06-23~). 정작 `state/market_snapshot.json` 은 오늘자·네이버=야후 2출처
일치·신뢰도 high 로 **정상**이다.

## 원인 (둘을 구분)
가격조회에는 두 경로가 있고, **막히는 건 경로 2뿐**이다.

1. **정기 스냅샷 수집 — 정상.** `fetch_prices.yml` → `scripts/fetch_market_data.py` 는
   GitHub Actions 러너(개방된 인터넷)에서 돈다. 네이버 siseJson·Yahoo v8 chart 에 정상 접근해
   `market_snapshot.json` 을 만든다.
2. **세션의 라이브 검증(live_verify) — 차단.** Claude Code 세션(리모트 실행 환경)의 모든
   아웃바운드 HTTPS 는 **정책 집행 이그레스 프록시**를 거친다. 조직 네트워크 정책이 금융
   호스트를 allowlist 에 넣지 않으면 프록시가 CONNECT 터널을 **403(policy denial)** 로 거부한다.

확인 방법(세션 안에서):
```
curl -sS "$HTTPS_PROXY/__agentproxy/status"   # recentRelayFailures 에 connect_rejected/403 + host 가 찍힌다
curl -o /dev/null -w "%{http_code}\n" --max-time 12 \
  "https://query1.finance.yahoo.com/v8/finance/chart/%5EKS11?range=1d&interval=1d"
# → CONNECT tunnel failed, response 403  (네이버/야후가 거부한 게 아니라 프록시가 거부)
```
프록시 README: `/root/.ccr/README.md` — "403/407 은 조직 egress 정책 차단. 우회 금지, 보고하라."

## 근본 해결 (A 트랙 — 환경 설정)
세션이 다시 실시간 검증을 하려면 **환경의 네트워크 정책**에서 금융 호스트를 허용해야 한다.
이는 코드가 아니라 Claude Code on the web **환경 생성 시 고른 네트워크 정책**의 설정이다.

허용해야 할 호스트:
| 용도 | 호스트 |
|---|---|
| 네이버 금융 일별 시세 | `api.finance.naver.com`, `finance.naver.com` |
| Yahoo Finance 차트/지수 | `query1.finance.yahoo.com`, `query2.finance.yahoo.com` |
| KRX EOD 백스톱(pykrx) | `data.krx.go.kr` |

설정 위치·방법은 환경 네트워크 정책에 따라 다르다 — 더 허용적인 정책으로 전환하거나
커스텀 allowlist 에 위 호스트를 추가한다. 문서: https://code.claude.com/docs/en/claude-code-on-the-web

> 참고: GitHub Actions 정기 수집은 별도 러너라 이 정책과 무관하게 계속 동작한다. A 트랙은
> 오직 **세션 안에서의 라이브 재검증**을 복구하기 위한 것이다.

## 안전망 (B 트랙 — 코드/정책)
A 를 못 바꾸는 동안에도 교착되지 않도록, 정기 스냅샷(오늘자·≥2출처 일치·high)을 권위
가격으로 인정한다 — `policy.price_data_quality.web_verify_unavailable_fallback`.
`scripts/pre_trade_check.py` 가 세션 이그레스가 막혔는지(`--egress auto` 자동 프로브) +
스냅샷이 권위 가격인지를 함께 판정해, 둘 다면 `live_verify_required` 를 `ok`(snapshot_fresh
booking)로 전환한다. 단일출처·medium·전일자·임계 근접 청산은 폴백에서 제외(기존 보수 동작 유지).
하드 CI 게이트(`check_trade_log_gate.py`)는 `snapshot_fresh` 를 허용하므로 손상되지 않는다.
