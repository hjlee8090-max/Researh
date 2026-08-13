# policy.json 근거·유래 장부 (policy_rationale.md)

> v2.33 D (docs/plan_removal_exclusion.md §5-D) — policy 본문에는 룰·파라미터·ref 만 남기고,
> 유래·사고 사례·설계 배경 산문은 여기 전문 보존한다(핫패스 배제 — 학습 재료 삭제 없음 원칙).
> check_lessons_applied.py 의 haystack 에 포함되므로 '미반영' 오탐이 생기지 않는다.
> **이관 시 원문 그대로 append — 수정 금지.** 신규 policy 룰의 유래 서술도 처음부터 여기 적는다.

## §price_data_quality.web_verify_guard.index_snapshot_confirmation.purpose

v2.23 — KOSPI 지수(regime.last_close) 스냅샷이 지연(as_of≠오늘)인 상태에서 실제로는 지수가 크게 움직였는데(±3% 초과) 09/12/15시가 이를 '스냅샷 지연·미확정'으로 자동 기각하고 보유 종목 breadth(개별주 혼조)만으로 방향을 판정해 '지수 잔잔' 오도 서사를 낸 것을 막는다. (2026-07-16 사고: 한은 기준금리 인상發 KOSPI -6.37% 크래시를 09/12/15시가 방어주 혼조 보합만 보고 '미확정'으로 처리 — 방어주 divergence 로 breadth 가 잔잔해도 지수 방향의 반증이 아니다. 18시·웹 2출처 교차로 뒤늦게 정정.) ⚠️ 2026-07-31 12시 반대 방향 재발(2건째): as_of=오늘·stale 아님인데 지수 값만 12%p 지연(5,643.73 vs 실측 6,300선) — '날짜' 트리거가 발동하지 않았고 같은 스냅샷의 삼성전자 +19.1%·SK하이닉스 +22.2% 와의 모순도 대조되지 않았다. v2.31 이 트리거를 '지수 vs 대형주 내부 정합성(5%p 초과 괴리)'로 확장.

## §risk.max_single_trade_risk_pct_of_equity_by_tier.purpose

v2.7 — 평면 단일거래 상한 2% 가 손절폭(ATR2배 14~18% 또는 -10% 플로어)과 곱해져 종목당 포지션을 ~98만원(=equity×2%÷10%)에 묶어, strong_bull 목표비중(80~95%)에 수학적으로 닿지 못하게 했다(2주+ 운용: strong_bull 인데 현금 100%·누적 -1.8%, 최근 거래에서 종목당 100만원을 넘긴 적이 없음). portfolio_heat_budget_by_tier 와 대칭으로 tier별 단일거래 상한을 둬 강세장에선 종목당 비중을 키우고(strong_bull 3.5%×equity÷손절10%≈종목당 ~30%) 약세장에선 조인다. compute_allocation.py 가 raw_tier 로 이 표를 조회해 per_trade_risk_pct·per_trade_risk_basis·single_trade_risk_ceiling_krw 를 산출하며, tier 가 unknown 이거나 표에 없으면 max_single_trade_risk_pct_of_equity(2.0)로 폴백한다.

## §position_sizing.single_trade_risk_cap.structural_note

max_position_weight_pct(35%) × 손절폭(예: red −10%) = equity 의 3.5% 로 단일거래 상한(2.0%)·heat 예산(6.0%)과 충돌할 수 있다. 이때 리스크 상한이 비중을 끌어내리는 것이 의도된 동작이다. 강세장 완전배치를 원하면 (i)손절폭 타이트화 (ii)max_positions 상향 (iii)두 상한 상향 중 정책 결정으로 택한다. (2026-06-01 사용자 결정: 단일거래 1.5→2.0% 상향 + 합산 heat 6.0% 예산 도입 — 종목 수 기반 배치를 허용하되 누적 리스크를 통제.) (2026-06-08 사용자 결정·v2.7: (iii) 두 상한을 tier별로 차등 — strong_bull 단일거래 3.5%·heat 9% 로 종목당 비중을 ~30%까지 키워 목표비중 도달, 약세 tier 로 갈수록 조임. 손절폭은 그대로 두고 max_single_trade_risk_pct_of_equity_by_tier·portfolio_heat_budget_by_tier 로 푼다.)

## §risk.portfolio_heat_budget_by_tier.purpose

v2.5 — 히트 예산을 시장 레짐 tier 에 따라 차등한다. flat 6% 는 단일거래 2%·손절 ~10% 조합에서 종목당 비중 ~20% × 3종목 = ≈60% 에서 막혀 strong_bull 목표비중(80~95%)에 닿지 못했다(강세장 미배치). 강세 tier 일수록 예산을 키워 breadth(종목 수)로 목표비중을 채우게 한다. compute_allocation.py 가 snapshot.regime.tier(raw_tier)로 이 표를 조회하며, tier 가 unknown 이거나 표에 없으면 portfolio_heat_budget_pct_of_equity(6.0) 로 폴백한다. target_equity_pct 밴드(market_regime.dynamic_sizing)와 짝이 되도록 설계: strong_bull 9.0% ÷ 종목당 2% = 4.5종목 × ~20% ≈ 90%(밴드 중앙).

## §risk.breakeven_ratchet.purpose

v2.20 — 본전 래칫 스톱(그림자 관측 전용). 트레일링 활성화(목표진행 70%) 전 구간에서 손절선이 진입가-2×ATR 에 고정된 채 주가만 오르면 open_risk 가 부풀어 히트 예산을 잠근다(7/2 실측: LIG넥스원 1종목=예산 42%, deploy 권고 137만원 vs 히트 잔여 0원). 이익이 ATR 단위로 진행되면 스톱을 본전 이상으로만 올려(래칫 — 하향 없음) 예산을 재활용하고 좌측 꼬리를 자른다. 실증: 6/23 보호손절 +25,369원. 반대 위험: 본전 노이즈 체결(5/28 KB금융 give-back 교훈) — ATR 게이트·종가 판정으로 완충하고 그림자 채점으로 net 실익 입증 후에만 라이브 전환. 전문: reports/2026-07-02-position-management-research.md P1.

## §price_data_quality.web_verify_guard.source_date_verification.purpose

v2.6 — 웹 교차확인(live_verify)이 '오늘'이 아닌 묵은 날짜의 기사를 현재 시세로 도용하는 것을 막는다. (2026-06-08: 6/8 09시 routine 이 stale 6/5 스냅샷을 두고 웹검색이 돌려준 실제 2026-06-01자 MBC 기사(imnews.imbc.com/.../6826849_37004.html, KOSPI 종가 8,788.38·삼성전자 급등·젠슨황 방한)를 '6/8 시세'로 오인 도용 → 삼성전자 ORANGE→GREEN 허구 해소·리포트/lessons/portfolio 동반 오염. web_verify_guard 의 '스냅샷보다 최신' 조건(outlier_rule (b))을 LLM 이 '6/8 장중'으로 거짓 자기인증했고, 출처 게재일이 실제로 6/1 임을 강제 확인하는 절차가 없었다.)

## §dynamic_reprice.purpose

2달 운용 관찰(2026-08-05 사용자 검토 요청): 목표 매수/매도 금액이 주간 계획·직전 리포트의 절대가격 앵커로 고정되고 시장이 움직여도 틀을 유지하려는 경직성 보완. 실측 — 신한지주 목표 103,000 이 목표 진행률 215%(최고 종가 109,200)에도 고정, 추정 기준선 118,700 대비 -13% 방치. 기존 장치의 사각: rr_breach_forced_action(v2.26)은 R/R '하락'만, holding_estimate_review(v2.24)는 기대수익 '음수 전환'만 발동 — 목표 '초과 소진'과 매수 밴드의 시세 이탈은 무신호였다.

## §sector_rotation_reentry.sensitivity_by_tier.purpose

v2.10 — 시장 상황(레짐 tier)에 따라 바닥 재진입 민감도를 자동 조정한다. 강세장은 섹터 로테이션이 강하고 침체 섹터가 강하게 반등하므로 일찍(aggressive) 잡고, 약세장은 떨어지는 칼날·가짜 바닥이 많으므로 충분히 확인(conservative)한 뒤만 잡는다. screen_universe.py 가 snapshot.regime.tier 로 조회하며(sensitivity_mode=auto), tier 가 unknown 이거나 mode 가 고정값(aggressive/medium/conservative)이면 sensitivity 폴백.

## §position_sizing.max_positions_note

v2.20 — momentum_strategy.config.top_n(6)과 동기 유지. 5 로 남아 있던 동안 바스켓 만석(6종목) 시 compute_allocation 의 vacant_slots = max(0, 5−6) = 0 이 영구화돼 09시 §2-C deploy 경로가 사문화됐다(2026-06-30 top_n 10→6 축소 때 미동기화 — reports/2026-07-02-position-management-research.md 병목 B). top_n 변경 시 이 값을 함께 조정한다.

## §market_hours.purpose

v2.3 — 장중 시간(세션) 정책. 직전까지 영업일(요일/공휴일)만 판정하고 '시각'은 보지 않아, 18시 routine 이 종가 도달 손절을 routine 실행 시각(18:00)으로 체결 기록하는 등 한국장 거래 시간(정규장 09:00~15:30) 밖의 체결이 trade_log 에 남았다(2026-06-01 SELL_ORANGE_STOP ts=18:00). 정규장에서만 실시간 체결을 허용하고, 마감 후 routine 은 종가 기준 청산만 하도록 명문화한다.

## §reward_risk_management.regime_adaptive_rr.purpose

v2.0 — 추세추종 전략과 고정 R/R 게이트의 충돌 해소. 강세 tier 에서는 모멘텀 종목이 이미 상승해 목표가까지 reward 가 줄고 -10% 손절까지 risk 는 남아 R/R 이 구조적으로 1.2 밑으로 떨어진다(예: 삼성전자 5/29 R/R=0.63 으로 진입 봉쇄). tier 별 하한을 차등 적용하고, 목표가는 dynamic_exit_model.target_price_rule 로 저항선·모멘텀 반영해 상향(reward 확보)한다.

## §reward_risk_management.entry_rr_projection_requirement.purpose

진입 시 R/R 이 tier 하한 턱걸이(하한~하한+0.2)인 종목은 목표 진행률이 오르면 R/R 이 필연적으로 하락한다 — 2026-08-07 하나금융지주 실측(이틀 연속 손절 상향에도 하한 미복원, 원인은 진입 시점 손절폭이 목표까지 거리 대비 처음부터 넓었던 것). 사후 재조정이 아니라 진입 시점에 이 궤적을 예상해 두면 rr_breach_forced_action 발동을 '기습'이 아니라 '예정된 이벤트'로 다룰 수 있다.

## §risk.index_shock_stop_deferral.purpose

v2.22(2026-07-06 감사 처방④) — 실현 손실 청산 6건 전부가 지수 급락일(-3.25%/-5.4%/-8.4%/-9.99% 등)에 격발됐고 6건 전부 청산 후 15거래일 내 +8~16% 회복(개별 thesis 훼손 0건). 종목 스톱이 지수 일중 변동에 격발되는 휩쏘를 '이틀 연속 종가 이탈' 요구로 완충한다. 반대 위험(진짜 폭락 방치)은 ATR 관통 예외 + red 하드 플로어(-20%)가 방어.

## §proactive_inference.band_width_rule.purpose

예측 밴드 폭이 시장 국면과 무관하게 평시 ±5% 대로 고정돼, 실현변동성이 폭발한 구간에서 구조적으로 좁아지던 문제를 막는다. 2026-07-30 18시(5,300~5,880)·07-31 09시(5,420~5,850) 두 예측이 같은 원인으로 연속 상단 12% 초과 miss 했고, 같은 날 15시(6,380~6,720)는 적중했다 — 차이는 예측력이 아니라 그 시점에 변동성이 이미 보였는지였다.

## §entry_filters.post_surge_cooldown.purpose

v2.5 codify — lessons.md 2026-05-28 HD조선 교훈 ①(수주·호재 발표 직후 급등한 종목은 1~2일 소화 기간 후 진입, 급등 당일·다음날 진입 시 차익실현 노출 위험). HD조선 5/27 LNG 5조2511억 수주 급등 직후(09:10) 진입 → 5/28~6/1 매물 소화·섹터 소외로 orange 청산(-43,098). 급등 직후 진입의 차익실현 노출을 게이트한다.

## §entry_filters.overnight_gap_prediction_buffer.purpose

codify(2026-06-07 policy-review) — lessons.md 2026-05-22 루틴 오차(KOSPI 역대 최대 급등 다음날 갭다운 예측 -1~-2.5% vs 실제 -4.21%, 2%p 과소 추정). 표준 버퍼(±1%)로 추정해 차익실현 규모를 과소 평가한 갭을 gate 한다. prompts/0000_global.md §2-1 자정 갭다운 예측 단계에 적용.

## §price_data_quality.pre_trade_gate.purpose

v2.2 — 2026-06-01 레이스(스케줄 fetch_prices 가 routine 의 0-1 git pull 직후 도착 → routine 이 60시간 묵은 5/29 스냅샷으로 삼성전자 신규매수를 체결, 신선본은 09:13·10:37 에 별도 커밋) 재발 방지. 매수·매도를 trade_log/portfolio 에 기록(booking)하기 직전 스냅샷을 재동기화·재검증한다.

## §price_data_quality.data_freshness.purpose

v2.1 — 스냅샷의 '수집 시각(as_of) vs routine 실행 시각' 차이(age, 분)를 추적·차등 적용한다. 직전까지 stale 키(=직접 수집 실패)만 봤고 데이터 노화(age)는 무시해, GitHub Actions 가 routine 1시간 전 성공 수집한 가격을 갓 나온 high 데이터처럼 매매에 썼다('stale 키 없음 ≠ 신선함'). (외부 dispatch 트리거 전환 후) 외부 스케줄러가 routine 5분 전 dispatch 로 수집하므로 age 는 보통 fresh(~5분)지만, 외부 트리거 지연·실패 시 백업 cron(약 1시간 전) 수집본으로 age 가 커질 수 있어 age 를 명시·게이트한다. compute_allocation.py 가 snapshot_age_min 과 freshness 등급을 state/allocation.json 에 기록하고, 각 routine 0-B 가 이를 읽어 적용한다.

## §reward_risk_management.holding_estimate_review.purpose

v2.24 — 매수측 estimate_gate(기대수익<0 신규진입 차단, v2.12)의 보유측 대응물. 신규 진입은 음수 추정을 차단하면서 보유 종목은 기대수익이 음수로 전환·지속돼도 아무 룰이 발동하지 않던 매수/매도 비대칭을 닫는다(2026-07-20 실측: 한미반도체 추정 기대수익 -5.3%(B) 인데 운용 목표가는 현재가 +50% 위 고정·무반응, 트레일링 활성화 진행률도 부풀려진 정적 목표가 기준이라 보호 전환이 구조적으로 지연). A/B 등급 추정의 기대수익이 임계 미만인 기록이 target_estimate_log.jsonl 에서 consecutive_reports 회 연속이면 compute_exit_levels 가 exit_levels.json 의 tickers.<t>.estimate.review_required=true 로 표면화한다.

## §price_data_quality.web_verify_guard.purpose

v2.4 — 웹 교차확인(live_verify)이 묵은 값/개장 고가를 '현재가'로 잘못 채택하고 그 위에 없는 촉매를 지어내 결론을 뒤집는 것을 막는다. (2026-06-02 현대차: 스냅샷 710,000(12:40, naver+yahoo 2출처 high, today_high=772,000)을 두고 웹 754,000(개장 스파이크, today_high 근처)을 '현재가'로 채택 → '+4.29% 급등·관세 완화 기대감 추정' 허구 서사 → 비중 상한 초과·thesis 약화·진입 불가 결론. 실제 종가는 729,000(-2.80%)로 정반대. 스냅샷이 이미 today_ohlc=시가770,000/고가772,000/저가697,000/현재710,000 을 갖고 있었는데 무시됐다.)

## §entry_filters.relative_strength.purpose

v2.5 — 섹터 로테이션/상대강도 축. 개별 종목의 절대 모멘텀(ret60)만 보면 '오르는 장'에서 후행 섹터(예: 반도체 주도장의 조선·금융)도 양(+)이라 채택돼 지수를 못 따라간다(2주 운용: 조선 3회·금융 3회 연속 손실, KOSPI +8.8% 인데 -1.77%). KOSPI 대비 '초과수익(excess return)'을 점수화해 지금 자금이 쏠리는 주도 섹터에 가중한다. benchmark=KOSPI 60일 수익률(market_snapshot.regime.ret_60d_pct, fetch_market_data 가 ^KS11 로 산출). 지수 데이터가 없으면(unknown) 0.5 중립 폴백으로 왜곡하지 않는다.

## §price_data_quality.source_provenance_gate.purpose

v2.6 — web_verify_guard.source_date_verification(프롬프트 의존)를 우회해 묵은 날짜의 기사가 '오늘 시세'로 trade_log 에 기록되는 것을 CI 에서 하드 차단하는 마지막 안전장치(trade_provenance_gate·trade_timing_gate 와 동일 패턴). 프롬프트가 무시돼도 묵은 출처 도용이 main 에 도달하지 못하게 한다. (2026-06-08 사고: 6/1자 MBC 기사를 6/8 시세로 도용 — 당시 이 게이트가 있었으면 recycled_value_gate 가 'KOSPI 8788=6/1 종가 재활용'으로 차단했다.)

## §price_data_quality.trade_provenance_gate.purpose

v2.2 — pre_trade_gate(프롬프트 의존)를 우회해 묵은/미검증 가격으로 체결되는 것을 CI 에서 하드 차단하는 마지막 안전장치. 모든 booking(BUY/SELL 계열) trade_log 항목은 price_source 를 기록해야 하며, scripts/check_trade_log_gate.py 가 위반 시 exit 1 → audit_pipeline(build_and_notify) 빌드 FAIL + auto_merge_routines 병합 차단을 일으킨다(프롬프트가 무시돼도 묵은 가격 체결이 main 에 도달하지 못함).
