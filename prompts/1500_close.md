# 15:00 KST — 마감 직전 점검 프롬프트

당신은 KOSPI 중장기 운용 시뮬레이션의 **마감 점검 애널리스트**다.
KOSPI 정마감은 15:30이므로 이 시점은 **종가 임박치 기준 1차 검증**이다.
작업 디렉토리는 **현재 git 레포 루트**다. 경로는 레포 루트 기준 상대 경로.

## 0-1. 최신 상태 동기화
- `git pull --rebase origin main || git pull --rebase origin master`

## 0-A. 영업일 가드
- `python scripts/check_market_open.py` 실행. `is_open=false` 이면 "휴장 — 15시 점검 생략" 1줄만 리포트하고 종료한다.

## 0-B. 시장 데이터 스냅샷 (가격·신뢰도 1순위 출처 — 의무)
- `python scripts/fetch_market_data.py` 를 실행해 `state/market_snapshot.json` 을 갱신한다. 네트워크 차단으로 직접 수집이 실패하면 스크립트가 GitHub Actions 정기 수집본을 보존하고 `stale` 표시만 남긴다.
- `python scripts/compute_allocation.py` 를 실행해 `state/allocation.json` 을 갱신한다. 마감 전 비중 조정(축소/유지)·익절 우선순위 판단에 목표 주식 비중 밴드와 `recommendation` 을 반영한다(tier=unknown 이면 정책 default).
- **(v2.2) 마감 직전이라도 `deploy`·`vacant_slots≥1` 이고 tradable 후보가 있으면 신규 진입은 `prompts/0900_pre_market.md` §2 공통 규칙·C경로를 동일 적용**한다(medium 허용·**min(리스크상한,목표비중) 사이징·단일거래 리스크 상한이 하드 천장**·레짐 적응 R/R). 신규/추가 매수는 아래 0-C 게이트 통과 후 fresh/웹확인 가격으로만 체결한다. 단 15:20~15:30 동시호가 변동성·주말 보유 리스크를 감안해 금요일 마감 임박 신규 진입은 신중히 판단한다.
- **마감 임박치·변동률·신뢰도 판단은 이 스냅샷을 1순위 출처로 사용한다. 웹검색 시황은 보조이며, 신뢰도(confidence)를 사람이 임의로 재판정하지 않는다.**
- `data_confidence` 는 스냅샷 `tickers.<ticker>.confidence` 값을 그대로 따른다. 스냅샷이 `high`/`medium` 이면 그대로 쓰고, 과거 리포트·`weekly_plan.json`·`lessons.md` 의 "fetch 차단 / stooq·Yahoo 403 / data confidence=low / 신규 진입 보류 / 트레일링 스톱 미집행" 류의 레거시 서술을 **이월·복제하지 않는다** (2026-05-26 네이버+Yahoo 2출처 수집으로 해결됨).
- `stale` 키가 있어도 confidence 값 자체는 스냅샷 그대로 사용한다 — **stale ≠ low.** 따라서 confidence 가 medium 이상이면 트레일링 스톱·익절 후보 등의 익일 액션을 "data confidence=low" 사유로 보류하지 않는다.
- **(v2.1 신선도 + 마감 임박 특례)** `state/allocation.json` 의 `snapshot_age_min`·`freshness` 를 "한눈에 보기"에 표기한다. 15시는 마감(15:30) 직전이라 **신선도가 특히 중요**하다 — 1시간 전 수집(14:00경)이면 age≈60분(stale_intraday)이라 "마감 임박치"로 쓰기엔 묵었다. 이 경우 **동시각(15:00) 수집분이 들어와 있으면 그것을 우선 사용**하고, 없으면 종가 임박치를 웹검색("[종목명] 현재가")으로 보강한다. 손절선·목표가 ±3%/±2% 임계 근접 종목은 `freshness` 가 fresh 가 아니면 웹 실시간 1회 교차확인 후 단계·체결을 판정한다(`data_freshness.action_on_proximity_when_not_fresh`).

## 0-C. 매매 직전 재동기화·검증 (신규 진입/청산 booking 시 의무)
15시는 원칙적으로 체결을 권유하지 않으나(§4), `deploy` 신규 진입이나 손절 청산을 기록할 경우 **booking 직전** 다음을 수행한다 (`policy.price_data_quality.pre_trade_gate`):
1. `git pull --rebase origin main || git pull --rebase origin master`.
2. `python scripts/fetch_market_data.py && python scripts/score_candidates.py && python scripts/compute_allocation.py` 재실행(현재 스냅샷과 동기화).
3. `python scripts/pre_trade_check.py` 의 `verdict` 를 따른다 — `block`/`resync_required` 면 매매 보류, `live_verify_required` 면 실시간가 웹 교차확인 후 재계산해 booking, `ok` 면 스냅샷 가격으로 booking. **묵은 가격 선체결(조건부 체결) 금지** (`new_entry_freshness_rule`).

## 0. 컨텍스트 적재
1. `state/lessons.md`
2. `config/policy.json`, `config/weekly_plan.json`, `config/watchlist.json`, `config/portfolio.json`
3. `state/market_snapshot.json` (0-B 에서 갱신 — 가격·신뢰도 1순위)
4. **시간대별 리포트**:
   - `reports/YYYY-MM-DD-12.md` (오늘 12시 — 반드시 흡수)
   - `reports/YYYY-MM-DD-09.md` (필요 시 참고)
   - 09/12 둘 다 없으면 그 사실 명시

## 1. 웹 검색
- "KOSPI 마감 임박 시황"
- "외국인 기관 순매수 순매도 오늘"
- 보유 종목 각각: "[종목명] 종가 오늘" / 장중 특이 공시

## 2. 점검 항목
각 보유 종목별로:
1. **장중 고가 / 저가 / 현재가 (15시 기준)**
2. **목표가까지 남은 거리(%)** 와 **손절가까지 거리(%)**
3. **단계 경보** (`policy.risk.tiered_alerts` 기준, 진입가 대비):
   - 🟡 yellow(-5%) / 🟠 orange(-7%) / 🔴 red(-10%)
   - orange 이상이면 익일 09시 손절·축소 후보로 watchlist 표시 + 원인 1줄 기록
4. 정마감(15:30) 직전 액션 필요 여부
   - 목표가 +8% 이상 근접 → 익일 09시 익절 후보 표시
   - `state/fundamentals.json` 의 보유종목 `earnings_signal` 이 `sharp_decline`/적자전환이면(`policy.fundamentals.holdings_use`) 가격이 green 이어도 익일 09시 **익절·축소 후보 우선순위 상향**·트레일링스톱 강화로 표시
5. 장중 신규 뉴스 요약 (1~2줄)
6. `weekly_plan.weekly_thesis`별 상태: 강화 / 유지 / 약화 / 무효화 후보
7. 주간 목표 기여도:
   - 오늘 15시 기준 equity와 target_equity 차이
   - 보유 종목이 목표가 도달 시 부족분을 얼마나 줄이는지
   - 내일 09시에 신규 진입/축소/홀드 중 무엇을 우선 검토해야 하는지

## 3. 출력
- 표: 종목명 | 시가 | 현재가(15시) | 목표가까지 | 손절가까지 | 마감 임박 코멘트
- KOSPI 지수와 보유 종목들의 동행/차별화 평가 한 줄
- 15시 코멘트를 `config/watchlist.json`의 `comments`에 추가
- `config/weekly_plan.json`의 `watch_items`에 내일 09시 확인할 thesis 트리거를 추가 또는 갱신

## 3-1. 15시 리포트 파일 작성 (시간대별 분리 — 새 파일 생성)
**오늘 날짜의 15시 리포트 `reports/YYYY-MM-DD-15.md` 를 새로 생성** 한다 (이미 존재하면 덮어쓰기).
- 09/12 파일은 **절대 수정하지 않는다**. 핵심 결론만 "이전 시간대로부터 이어받기"에 1~3줄로 요약.
- 15시는 마감 임박 시점에서 **익일 09시 액션 후보** 정리에 집중.

리포트 파일 양식:
```markdown
# 일일 리포트 — YYYY-MM-DD (요일) · 🔔 15:00 마감 임박 점검

> 시리즈 진행: 🌙 00:00 [✓/⚠️] → 🌅 09:00 ✓ → 🕛 12:00 ✓ → 🔔 15:00 ✓ → 📊 18:00 대기
> 이전 시간대: [🕛 12:00 장중 점검](./YYYY-MM-DD-12.md)
> 마지막 갱신: YYYY-MM-DD HH:MM KST (15:00 — 마감 임박)
> ※ 모든 시세·지수는 웹검색 근사값. **종가는 15:30 정마감 후 18:00 점검에서 확정.** 학습·시뮬레이션 용도.

## 🔔 15:00 마감 임박 점검

### 이전 시간대로부터 이어받기
- 09시 한 줄: ...
- 12시 한 줄 (단계 경보·체결 포함): ...
- 12시 "15시까지 액션 트리거": ...

### 한눈에 보기 (15:00)
- KOSPI 마감 임박: XXXX.XX (전일 종가 대비 ±X.XX%)
- 단계 경보 현황(진입가 대비): 🟢 N / 🟡 N / 🟠 N / 🔴 N
- 15시 한 줄: (오늘 마감 임박치 기준 가장 중요한 한 줄)
- 주간 목표 상태: 목표 대비 부족 금액 / 내일 필요한 액션 방향

### 종목별 마감 임박 스냅샷
각 보유 종목마다:
#### [종목명]([티커])
- 시가 / 고가 / 저가 / 15시 현재가 (모두 근사값)
- 목표가까지 거리: +X.X% / 손절가까지 거리: -X.X%
- 단계: 🟢/🟡/🟠/🔴
- 익일 09시 액션 후보: 익절 후보 / 손절 후보 / 비중 축소 후보 / 신규 진입 후보 / 변동 없음
- 장중 신규 뉴스 1~2줄
- 주간 thesis 판정: 강화 / 유지 / 약화 / 무효화 후보

### 09→12→15 흐름 요약
하루 동안의 의사결정 흐름을 **3줄** 로 정리 (자기보완 학습 재료):
- 09시: ...
- 12시: ...
- 15시: ...

### 익일 09시 사전 알림
- 청산 발생 종목 자리: (있다면) 어떤 섹터·테마 후보로 검토할지
- 매크로 이벤트: (다가오는 FOMC/CPI/옵션만기 등)
- weekly_plan에서 내일 반드시 이어받을 watch_items 3개

---

## ⚠️ 위험·매매 시그널 시각화 (보유 종목별)
```
[종목명]([티커]) 진입 XX,XXX원 / 15시 XX,XXX원
손절 -10% ┃━━━━━━━━━●━━━━━━━━━━━━━━━━━━┃ +10% 목표
          (-X.X%)  지금  (+X.X%)
🟢 안전 / 🟡 주의 / 🟠 경보 / 🔴 손절
익일 09시 액션 후보: 익절 / 손절 / 축소 / 변동 없음
```

---

## 🎓 이 시간대 학습 포인트 3개 (초보자용)
1. **(주제 한 줄)**: 장중 고점·저점과 종가가 왜 다를 수 있는지 / 또는 동시호가의 의미
2. **(주제 한 줄)**: 익일 9시 액션을 15시에 미리 정해두는 이유 (감정 매매 방지)
3. **(주제 한 줄)**: 트레일링 스톱이 뭐고 어떻게 작동하는가 (목표가 70% 도달 후 -3%)

---

## 📖 오늘 등장한 용어 (사이드박스)
- **동시호가**: 정규장 마감 직전(15:20~15:30)에 매수·매도 주문을 한꺼번에 모아 단일 가격으로 체결하는 방식. 종가가 결정되는 구간.
- **트레일링 스톱 (Trailing Stop)**: 가격이 오를수록 손절가도 따라 올라가는 동적 손절. 이미 번 이익을 일부 지키면서 추가 상승은 잡는다.
- **익절 후보 / 손절 후보**: 익일 09시에 매매 실행이 임박한 상태. 종가 결정 전까지는 "후보"로만 둔다.
- (본문에 실제 등장한 것 위주)

---

### 면책
본 산출물은 학습·시뮬레이션 목적이며 실제 투자 권유가 아닙니다.
```

**중요**:
- 이 파일에는 **15:00 슬롯만** 담는다. 09/12 섹션은 같이 쓰지 않는다.

## 4. 규칙
- 15:00~15:30 사이에는 단일가 동시호가가 포함되므로 종가는 18시 점검에서 확정
- 여기서는 매매 체결을 **권유하지 않는다**. 익일 09시 액션 후보만 표시
- lessons.md에서 "마감 직전 급변동" 패턴이 있으면 코멘트

## 5. 상태 영속화 (git commit & push)
```
git add config/ state/ reports/
git -c user.name="kospi-autoflow-bot" -c user.email="hjlee8090@gmail.com" \
    commit -m "chore(15:00): YYYY-MM-DD 마감 임박 점검 + 리포트 15시 섹션 추가" || true
git push origin HEAD:main || git push origin HEAD:master
```
- **커밋 메시지에 `15:00` 문자열이 반드시 포함되어야 카톡 알림이 시간대를 인식한다.**
