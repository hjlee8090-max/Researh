# 2026-09-06 — 주간 자기감사 (self-audit, 기계 생성)

> `scripts/self_audit.py` 산출 — 2026-07-06 수동 감사 항목의 정기 재측정. 수동 편집 금지.
> sunday_policy_review 는 이 리포트를 의무 인용하고, ⚠️ 항목마다 조치/보류 사유를 남긴다.

## 한눈에 보기

| 항목 | 상태 |
|---|---|
| A. 원장 정합성 | ✅ 일치 |
| B. 계좌 성과 | 왕복 24건 · 승률 37.5% · PF 0.48 · 순실현 -349,040원 |
| C. vs KOSPI (2026-05-20~) | 계좌 -7.326% vs KOSPI -7.24% → **격차 -0.09%p** |
| D. 스톱 휩쏘 | 손실 스톱 9건 중 t+5 채점 9건 · 휩쏘 7건 (77.8%) · 일실 합계 +273,209원 |
| E. 게이트 위반 | 총 0건 (provenance 0 · timing 0 · chase 0 · shock 0 · card 0) |
| F. 패치 vs 검증 | policy v2.36 (직전 감사 v2.36) · 신규 왕복 0건 |
| G. 배치 | 주식 8.5% (tier bull, 목표 [65, 80]) · heat 잔여 339090원 |
| H. 오버레이 백테스트 | 판정 있음(아래) |

## ⚠️ 이번 주 조치 필요 (findings — 처분 의무)

> 각 항목의 처분은 `state/self_audit_findings.json` 의 `disposition` 에 기입한다 (`{"action": "patch|defer|observe", "note": "...", "date": "..."}`). 무처분 2주 이상은 주간 워크플로 FAIL. patch 처분 후 재발은 자동 재상정.

| id | 항목 | 경과 | 처분 상태 |
|---|---|---|---|
| `whipsaw-high` | 스톱 휩쏘율 77.8% — 노이즈 저점 매도 반복 | 9주째 | defer — 정책 동결(Stage 0, state/policy_freeze.json) 중 — §1-8 재심 결과 brea |
| `deployment-below-band` | 주식비중 8.5% < 목표 하한 65% — 만성 미배치 | 9주째 | observe — 재확인(09-06) — 08-30 진단(게이트 3종 정당 작동, 국면 의존) 이후 배치가 8.5%로 오히려  |
| `lessons-balance` | lessons.md 581,374B > 예산 60,000B — 이관 처리량 부족 | 4주째 🔴overdue | **무처분** (패치 처분 후에도 재발 — 보완 효과 없음, 재상정) |

## H. 청산 오버레이 백테스트 판정 (요약 인용)

- 판정: 혼재 — 4개 설정·구간 중 3개에서 오버레이가 가치를 파괴했다(구간·설정 의존). [권장 Top10·월간리밸 (backtest_strategy 검증 설정) · full] 오버레이 B−A -253.5%p(하드스톱 -37.3 / 트레일링 -216.2), MDD 개선 +1.2%p, 전량청산 87건 중 휩쏘 59건 / [권장 Top10·월간리밸 (backtest_strategy 검증 설정) · recent_2026] 오버레이 B−A -39.9%p(하드스톱 -2.8 / 트레일링 -37.1), MDD 개선 +8.3%p, 전량청산 28건 중 휩쏘 21건 / [라이브 Top6·21일리밸 (policy momentum_strategy 설정) · full] 오버레이 B−A -167.6%p(하드스톱 -48.5 / 트레일링 -119.1), MDD 개선 -4.6%p, 전량청산 72건 중 휩쏘 50건 / [라이브 Top6·21일리밸 (policy momentum_strategy 설정) · recent_2026] 오버레이 B−A +9.3%p(하드스톱 -6.5 / 트레일링 +15.8), MDD 개선 +9.9%p, 전량청산 22건 중 휩쏘 16건

## 참고
- 판단 카드(사람이 읽는 매매 논리): `state/trade_cards.md`
- 룰별 손익 채점: `state/rule_attribution.json` / 원장: `state/trade_log.jsonl`
- 이 감사의 원본(수동): `reports/2026-07-06-self-reinforcement-audit.md`
