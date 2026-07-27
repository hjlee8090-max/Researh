# policy.json 산문 이관 (policy_notes)

`config/policy.json` 의 `purpose` 산문 중 300B 초과분을 여기로 옮겼다. 본문에는 첫 문장과 `purpose_ref` 앵커만 남는다 — 핫패스 콘텍스트 예산(context_budget) 때문이다. 규칙의 근거·재발 방지 기록이므로 삭제가 아니라 이관이며, `check_lessons_applied` 의 교훈 반영 대조 haystack 에 이 파일이 포함된다.

## momentum-strategy-discovery-gate

경로: `policy.momentum_strategy.discovery_gate.purpose`

엔진 신호 일원화(기획 A관문). momentum_signal(절대모멘텀)이 매수를 결정하는데 screen_universe 는 상대강도(KOSPI대비)로 promote/rotate 를 판단해 '같은 종목을 momentum 은 사고 screen 은 회전아웃'하던 모순 제거. momentum_signal.full_ranking.score 를 단일 점수 권위로 삼고, 상대강도·테마·품질은 2차 랭킹/컨텍스트로 강등.

## risk-chase-entry-filter

경로: `policy.risk.chase_entry_filter.purpose`

v2.22(2026-07-06 감사 처방③) — 고ATR 종목을 단기 급등 직후 사는 패턴이 즉시 손실로 반복 전환(6/4 삼성전자 3거래일 +13.7% 후 진입→orange/red 양분 손절 -82,480원, 6/30 LS ELECTRIC 2거래일 +13% 후 진입→7/6 트레일 손실 청산, 한미반도체 진입 2일 뒤 -15%). 검증: scripts/pre_trade_check.py --tickers 가 booking 전 판정, scripts/check_trade_log_gate.py 가 사후 하드 차단.

## risk-index-shock-stop-deferral

경로: `policy.risk.index_shock_stop_deferral.purpose`

v2.22(2026-07-06 감사 처방④) — 실현 손실 청산 6건 전부가 지수 급락일(-3.25%/-5.4%/-8.4%/-9.99% 등)에 격발됐고 6건 전부 청산 후 15거래일 내 +8~16% 회복(개별 thesis 훼손 0건). 종목 스톱이 지수 일중 변동에 격발되는 휩쏘를 '이틀 연속 종가 이탈' 요구로 완충한다. 반대 위험(진짜 폭락 방치)은 ATR 관통 예외 + red 하드 플로어(-20%)가 방어.

## risk-breakeven-ratchet

경로: `policy.risk.breakeven_ratchet.purpose`

v2.20 — 본전 래칫 스톱(그림자 관측 전용). 트레일링 활성화(목표진행 70%) 전 구간에서 손절선이 진입가-2×ATR 에 고정된 채 주가만 오르면 open_risk 가 부풀어 히트 예산을 잠근다(7/2 실측: LIG넥스원 1종목=예산 42%, deploy 권고 137만원 vs 히트 잔여 0원). 이익이 ATR 단위로 진행되면 스톱을 본전 이상으로만 올려(래칫 — 하향 없음) 예산을 재활용하고 좌측 꼬리를 자른다. 실증: 6/23 보호손절 +25,369원. 반대 위험: 본전 노이즈 체결(5/28 KB금융 give-back 교훈) — ATR 게이트·종가 판정으로 완충하고 그림자 채점으로 net 실익 입증 후에만 라이브 전환. 전문: reports/2026-07-02-position-management-research.md P1.

## risk-portfolio-heat-budget-by-tier

경로: `policy.risk.portfolio_heat_budget_by_tier.purpose`

v2.5 — 히트 예산을 시장 레짐 tier 에 따라 차등한다. flat 6% 는 단일거래 2%·손절 ~10% 조합에서 종목당 비중 ~20% × 3종목 = ≈60% 에서 막혀 strong_bull 목표비중(80~95%)에 닿지 못했다(강세장 미배치). 강세 tier 일수록 예산을 키워 breadth(종목 수)로 목표비중을 채우게 한다. compute_allocation.py 가 snapshot.regime.tier(raw_tier)로 이 표를 조회하며, tier 가 unknown 이거나 표에 없으면 portfolio_heat_budget_pct_of_equity(6.0) 로 폴백한다. target_equity_pct 밴드(market_regime.dynamic_sizing)와 짝이 되도록 설계: strong_bull 9.0% ÷ 종목당 2% = 4.5종목 × ~20% ≈ 90%(밴드 중앙).

## risk-max-single-trade-risk-pct-of-equity-by-tier

경로: `policy.risk.max_single_trade_risk_pct_of_equity_by_tier.purpose`

v2.7 — 평면 단일거래 상한 2% 가 손절폭(ATR2배 14~18% 또는 -10% 플로어)과 곱해져 종목당 포지션을 ~98만원(=equity×2%÷10%)에 묶어, strong_bull 목표비중(80~95%)에 수학적으로 닿지 못하게 했다(2주+ 운용: strong_bull 인데 현금 100%·누적 -1.8%, 최근 거래에서 종목당 100만원을 넘긴 적이 없음). portfolio_heat_budget_by_tier 와 대칭으로 tier별 단일거래 상한을 둬 강세장에선 종목당 비중을 키우고(strong_bull 3.5%×equity÷손절10%≈종목당 ~30%) 약세장에선 조인다. compute_allocation.py 가 raw_tier 로 이 표를 조회해 per_trade_risk_pct·per_trade_risk_basis·single_trade_risk_ceiling_krw 를 산출하며, tier 가 unknown 이거나 표에 없으면 max_single_trade_risk_pct_of_equity(2.0)로 폴백한다.

## risk-portfolio-heat

경로: `policy.risk.portfolio_heat.purpose`

v2.2 — 단일거래 상한(2.0%)만으로는 여러 포지션의 리스크가 누적될 때 전체 책(book) 위험을 통제하지 못한다. 모든 보유 포지션의 미실현 손절위험(open risk) 합계를 equity 의 portfolio_heat_budget_pct_of_equity(6.0%) 이하로 제한한다. 신규 진입은 진입 후 합산 heat 가 예산을 넘지 않는 수량까지만 허용한다.

## risk-exit-classification

경로: `policy.risk.exit_classification.purpose`

v2.25 — rule_attribution 기준 청산 룰 7종(TRAILING_STOP·ORANGE/RED_STOP·GIVE_BACK·CHANDELIER·SHOCK_DEFERRAL·STOP)이 전부 가격 트리거였다. '논거가 깨져서 판다'와 '가격 규율로 판다'가 구분되지 않아, 논거 훼손 종목이 쇼크유예로 하루씩 밀리고 기회비용 청산은 아예 발생하지 않았다(기회비용오차 0건).

## market-regime-dynamic-sizing

경로: `policy.market_regime.dynamic_sizing.purpose`

지수의 성장세(200일선 위치+기울기, 60일선 위치)를 5단계 tier 로 점수화해 목표 주식 비중(=1-현금) 밴드를 동적으로 정한다. fetch_market_data.py 가 tier 를 산출해 snapshot.regime 에 기록하고, compute_allocation.py 가 현재 주식 비중과 비교해 배치/축소 권고(KRW)를 낸다.

## price-data-quality-web-verify-unavailable-fallback

경로: `policy.price_data_quality.web_verify_unavailable_fallback.purpose`

v2.17 — 조직 정책이 금융 호스트를 막아(이그레스 403) 세션 웹 교차확인 불가면 live_verify_required 영구 미충족으로 신규 매수만 봉쇄되던 비대칭 해소(2026-06-23~ '가격조회 다 실패'의 원인; 정기 수집 GitHub Actions 는 정상이라 스냅샷이 권위 가격). 배경·CLI·근본해결: docs/network_egress_allowlist.md.

## price-data-quality-decision-card-gate

경로: `policy.price_data_quality.decision_card_gate.purpose`

v2.22(2026-07-06 감사) — 매수·매도 판단을 사람이 읽고 공감/반박할 수 있게 만든다. 기존 reason 한 줄은 서사·수치가 섞여 검증 불가능했고(5/20 첫날 3종 매수는 무효화 조건 자체가 없었음), 판단의 질을 사후 채점하려면 구조화된 카드가 필요하다. scripts/render_trade_cards.py 가 이 카드를 state/trade_cards.md 로 렌더링해 사람이 매 거래를 검토한다.

## price-data-quality-pre-trade-gate

경로: `policy.price_data_quality.pre_trade_gate.purpose`

v2.2 — 2026-06-01 레이스(스케줄 fetch_prices 가 routine 의 0-1 git pull 직후 도착 → routine 이 60시간 묵은 5/29 스냅샷으로 삼성전자 신규매수를 체결, 신선본은 09:13·10:37 에 별도 커밋) 재발 방지. 매수·매도를 trade_log/portfolio 에 기록(booking)하기 직전 스냅샷을 재동기화·재검증한다.

## price-data-quality-trade-provenance-gate

경로: `policy.price_data_quality.trade_provenance_gate.purpose`

v2.2 — pre_trade_gate(프롬프트 의존)를 우회해 묵은/미검증 가격으로 체결되는 것을 CI 에서 하드 차단하는 마지막 안전장치. 모든 booking(BUY/SELL 계열) trade_log 항목은 price_source 를 기록해야 하며, scripts/check_trade_log_gate.py 가 위반 시 exit 1 → audit_pipeline(build_and_notify) 빌드 FAIL + auto_merge_routines 병합 차단을 일으킨다(프롬프트가 무시돼도 묵은 가격 체결이 main 에 도달하지 못함).

## price-data-quality-data-freshness

경로: `policy.price_data_quality.data_freshness.purpose`

v2.1 — 스냅샷의 '수집 시각(as_of) vs routine 실행 시각' 차이(age, 분)를 추적·차등 적용한다. 직전까지 stale 키(=직접 수집 실패)만 봤고 데이터 노화(age)는 무시해, GitHub Actions 가 routine 1시간 전 성공 수집한 가격을 갓 나온 high 데이터처럼 매매에 썼다('stale 키 없음 ≠ 신선함'). (외부 dispatch 트리거 전환 후) 외부 스케줄러가 routine 5분 전 dispatch 로 수집하므로 age 는 보통 fresh(~5분)지만, 외부 트리거 지연·실패 시 백업 cron(약 1시간 전) 수집본으로 age 가 커질 수 있어 age 를 명시·게이트한다. compute_allocation.py 가 snapshot_age_min 과 freshness 등급을 state/allocation.json 에 기록하고, 각 routine 0-B 가 이를 읽어 적용한다.

## price-data-quality-web-verify-guard

경로: `policy.price_data_quality.web_verify_guard.purpose`

v2.4 — 웹 교차확인(live_verify)이 묵은 값/개장 고가를 '현재가'로 잘못 채택하고 그 위에 없는 촉매를 지어내 결론을 뒤집는 것을 막는다. (2026-06-02 현대차: 스냅샷 710,000(12:40, naver+yahoo 2출처 high, today_high=772,000)을 두고 웹 754,000(개장 스파이크, today_high 근처)을 '현재가'로 채택 → '+4.29% 급등·관세 완화 기대감 추정' 허구 서사 → 비중 상한 초과·thesis 약화·진입 불가 결론. 실제 종가는 729,000(-2.80%)로 정반대. 스냅샷이 이미 today_ohlc=시가770,000/고가772,000/저가697,000/현재710,000 을 갖고 있었는데 무시됐다.)

## price-data-quality-web-verify-guard-source-date-verification

경로: `policy.price_data_quality.web_verify_guard.source_date_verification.purpose`

v2.6 — 웹 교차확인(live_verify)이 '오늘'이 아닌 묵은 날짜의 기사를 현재 시세로 도용하는 것을 막는다. (2026-06-08: 6/8 09시 routine 이 stale 6/5 스냅샷을 두고 웹검색이 돌려준 실제 2026-06-01자 MBC 기사(imnews.imbc.com/.../6826849_37004.html, KOSPI 종가 8,788.38·삼성전자 급등·젠슨황 방한)를 '6/8 시세'로 오인 도용 → 삼성전자 ORANGE→GREEN 허구 해소·리포트/lessons/portfolio 동반 오염. web_verify_guard 의 '스냅샷보다 최신' 조건(outlier_rule (b))을 LLM 이 '6/8 장중'으로 거짓 자기인증했고, 출처 게재일이 실제로 6/1 임을 강제 확인하는 절차가 없었다.)

## price-data-quality-web-verify-guard-index-snapshot-confirmation

경로: `policy.price_data_quality.web_verify_guard.index_snapshot_confirmation.purpose`

v2.23 — KOSPI 지수(regime.last_close) 스냅샷이 지연(as_of≠오늘)인 상태에서 실제로는 지수가 크게 움직였는데(±3% 초과) 09/12/15시가 이를 '스냅샷 지연·미확정'으로 자동 기각하고 보유 종목 breadth(개별주 혼조)만으로 방향을 판정해 '지수 잔잔' 오도 서사를 낸 것을 막는다. (2026-07-16 사고: 한은 기준금리 인상發 KOSPI -6.37% 크래시를 09/12/15시가 방어주 혼조 보합만 보고 '미확정'으로 처리 — 방어주 divergence 로 breadth 가 잔잔해도 지수 방향의 반증이 아니다. 18시·웹 2출처 교차로 뒤늦게 정정.)

## price-data-quality-source-provenance-gate

경로: `policy.price_data_quality.source_provenance_gate.purpose`

v2.6 — web_verify_guard.source_date_verification(프롬프트 의존)를 우회해 묵은 날짜의 기사가 '오늘 시세'로 trade_log 에 기록되는 것을 CI 에서 하드 차단하는 마지막 안전장치(trade_provenance_gate·trade_timing_gate 와 동일 패턴). 프롬프트가 무시돼도 묵은 출처 도용이 main 에 도달하지 못하게 한다. (2026-06-08 사고: 6/1자 MBC 기사를 6/8 시세로 도용 — 당시 이 게이트가 있었으면 recycled_value_gate 가 'KOSPI 8788=6/1 종가 재활용'으로 차단했다.)

## market-hours

경로: `policy.market_hours.purpose`

v2.3 — 장중 시간(세션) 정책. 직전까지 영업일(요일/공휴일)만 판정하고 '시각'은 보지 않아, 18시 routine 이 종가 도달 손절을 routine 실행 시각(18:00)으로 체결 기록하는 등 한국장 거래 시간(정규장 09:00~15:30) 밖의 체결이 trade_log 에 남았다(2026-06-01 SELL_ORANGE_STOP ts=18:00). 정규장에서만 실시간 체결을 허용하고, 마감 후 routine 은 종가 기준 청산만 하도록 명문화한다.

## reward-risk-management-regime-adaptive-rr

경로: `policy.reward_risk_management.regime_adaptive_rr.purpose`

v2.0 — 추세추종 전략과 고정 R/R 게이트의 충돌 해소. 강세 tier 에서는 모멘텀 종목이 이미 상승해 목표가까지 reward 가 줄고 -10% 손절까지 risk 는 남아 R/R 이 구조적으로 1.2 밑으로 떨어진다(예: 삼성전자 5/29 R/R=0.63 으로 진입 봉쇄). tier 별 하한을 차등 적용하고, 목표가는 dynamic_exit_model.target_price_rule 로 저항선·모멘텀 반영해 상향(reward 확보)한다.

## reward-risk-management-holding-estimate-review

경로: `policy.reward_risk_management.holding_estimate_review.purpose`

v2.24 — 매수측 estimate_gate(기대수익<0 신규진입 차단, v2.12)의 보유측 대응물. 신규 진입은 음수 추정을 차단하면서 보유 종목은 기대수익이 음수로 전환·지속돼도 아무 룰이 발동하지 않던 매수/매도 비대칭을 닫는다(2026-07-20 실측: 한미반도체 추정 기대수익 -5.3%(B) 인데 운용 목표가는 현재가 +50% 위 고정·무반응, 트레일링 활성화 진행률도 부풀려진 정적 목표가 기준이라 보호 전환이 구조적으로 지연). A/B 등급 추정의 기대수익이 임계 미만인 기록이 target_estimate_log.jsonl 에서 consecutive_reports 회 연속이면 compute_exit_levels 가 exit_levels.json 의 tickers.<t>.estimate.review_required=true 로 표면화한다.

## entry-filters-earnings-blackout-gate

경로: `policy.entry_filters.earnings_blackout_gate.purpose`

v2.23 — fundamentals.earnings_blackout(실적 D-1~당일 신규 진입 보류)이 프롬프트 전용 규칙이라 어느 스크립트도 검사하지 않던 구멍을 CI 로 폐쇄. check_trade_log_gate.find_earnings_blackout_violations 가 catalysts.json 의 earnings 계열 이벤트(generated=법정기한 추정 포함)와 BUY ts 를 대조해 D-1~당일 진입을 main 도달 전 차단한다.

## entry-filters-block-if-cumulative-return-below-pct-by-tier

경로: `policy.entry_filters.block_if_cumulative_return_below_pct_by_tier.purpose`

v2.7 — 평면 -7% 5일 급락필터가 광범위 조정(Broadcom shock·KOSPI 주간 -7%)에서 전 후보를 동시 차단해 strong_bull deploy 신호와 충돌하던 모순 해소. tier별로 강세장 눌림목은 더 넓게(리더가 닿게), 약세장은 더 좁게(자본보존) 임계를 둔다. fetch_market_data.py 가 레짐 tier 로 이 표를 조회하며(없으면 block_if_cumulative_return_below_pct -7.0 폴백), trend_lookback_days(5) 기준 5거래일 누적 수익률이 임계 미만이면 진입 차단. score_candidates.trend_score(momentum 서브점수)는 -7% 밴드를 그대로 둬 깊은 눌림목이 점수상 약간 불리하게 남는다(보수).

## entry-filters-relative-strength-leader-widening

경로: `policy.entry_filters.relative_strength_leader_widening.purpose`

v2.7 — KOSPI 대비 60일 초과수익(excess = stock.ret_60d_pct − KOSPI.ret_60d_pct)이 excess_min_pct(+10%p) 이상인 주도주는 tier 임계를 extra_pct(-7%p)만큼 더 넓혀(예 strong_bull -13→-20%) '리더의 깊은 눌림목'만 통과시킨다. 후행주(RS 하위)는 넓히지 않아 계속 차단된다. 최종 임계는 entry_filter_hard_floor_pct(-22%) 아래로는 내려가지 않는다(진짜 자유낙하 차단). 예: 2026-06-08 SK하이닉스(excess +68.8%p·후보 점수 1위)가 5일 -17%로 평면 -7% 필터에 막히던 것을 이 예외가 strong_bull -20% 로 통과시키고, 반면 HD조선·한화에어로(RS 하위)는 -13% 유지로 계속 차단된다.

## entry-filters-relative-strength-leader-widening-dynamic-excess-min

경로: `policy.entry_filters.relative_strength_leader_widening.dynamic_excess_min.purpose`

강세장(KOSPI 자체가 주도)에서 거의 모든 종목의 KOSPI 대비 초과수익이 음(-)이 되어 promote 가 영구 0이 되는 문제 해소. 종목별 '기업가치(실적)+최근 호재뉴스' 품질로 음수 초과수익 허용폭을 동적 산출 — 좋은 회사+촉매면 KOSPI 에 다소 뒤져도 추적 승격 허용, 무뉴스·부실은 +base 엄격 유지.

## entry-filters-relative-strength

경로: `policy.entry_filters.relative_strength.purpose`

v2.5 — 섹터 로테이션/상대강도 축. 개별 종목의 절대 모멘텀(ret60)만 보면 '오르는 장'에서 후행 섹터(예: 반도체 주도장의 조선·금융)도 양(+)이라 채택돼 지수를 못 따라간다(2주 운용: 조선 3회·금융 3회 연속 손실, KOSPI +8.8% 인데 -1.77%). KOSPI 대비 '초과수익(excess return)'을 점수화해 지금 자금이 쏠리는 주도 섹터에 가중한다. benchmark=KOSPI 60일 수익률(market_snapshot.regime.ret_60d_pct, fetch_market_data 가 ^KS11 로 산출). 지수 데이터가 없으면(unknown) 0.5 중립 폴백으로 왜곡하지 않는다.

## entry-filters-post-surge-cooldown

경로: `policy.entry_filters.post_surge_cooldown.purpose`

v2.5 codify — lessons.md 2026-05-28 HD조선 교훈 ①(수주·호재 발표 직후 급등한 종목은 1~2일 소화 기간 후 진입, 급등 당일·다음날 진입 시 차익실현 노출 위험). HD조선 5/27 LNG 5조2511억 수주 급등 직후(09:10) 진입 → 5/28~6/1 매물 소화·섹터 소외로 orange 청산(-43,098). 급등 직후 진입의 차익실현 노출을 게이트한다.

## entry-filters-reentry-discipline

경로: `policy.entry_filters.reentry_discipline.purpose`

v2.11 — 동일 종목 재진입 추격 차단. 2026-06-04 삼성전자 재진입(직전 익절 청산가 354,290 대비 +2.0% 위·52주 신고점 97.6% 위치)이 -82,480원 — 익절 후 더 비싸게 다시 사는 buy-high 루프를 게이트한다. 반대로 2026-06-09 저점 복원 진입(직전 손절가 대비 -5.2%)은 유효했다 — 아래 면제 조항이 이를 허용한다. 직전 청산 기록은 state/trade_log.jsonl 의 해당 종목 최근 SELL 계열 항목으로 확인한다.

## entry-filters-estimate-gate

경로: `policy.entry_filters.estimate_gate.purpose`

v2.12 — 목표주가 추정 레이어(state/target_estimate.json)의 기대수익이 음(-)인 종목은 신규 진입 차단. 점수 게이트(추세·신뢰도) 통과해도 밸류·뉴스·섹터 집중도 종합 추정이 하락을 가리키면 한 번 더 거르는 안전핀. 근거: 백테스트(reports/2026-06-10-target-model-backtest.md·2026-06-11-sector-global-research.md) 60일 방향 corr 0.4~0.5·후행주 적중률 70.4%. 등급 C(현재가 폴백)·추정 누락·max_age_hours 초과 stale 은 게이트를 만들지 않는다(결측이 차단 룰이 되는 래칫 방지). '추정 +X% 이상 매수' 공격 트리거는 미채택 — estimate_scorecard 표본 누적 후 sunday_policy_review 에서 임계 재검토.

## entry-filters-intraday-breach-contingency

경로: `policy.entry_filters.intraday_breach_contingency.purpose`

v2.5 codify — lessons.md 2026-05-28·05-29 HD조선 교훈 ③(장중 orange/red 이탈을 하루 4회 routine 사이에 실시간 감지 못해 종가 후에야 확인 — 407K·405K 장중 이탈 미대응). 정기 수집 스냅샷이 있어도 장중 임계 이탈 대응이 늦는 갭의 '비상 대응 절차'를 명문화한다.

## entry-filters-overnight-gap-prediction-buffer

경로: `policy.entry_filters.overnight_gap_prediction_buffer.purpose`

codify(2026-06-07 policy-review) — lessons.md 2026-05-22 루틴 오차(KOSPI 역대 최대 급등 다음날 갭다운 예측 -1~-2.5% vs 실제 -4.21%, 2%p 과소 추정). 표준 버퍼(±1%)로 추정해 차익실현 규모를 과소 평가한 갭을 gate 한다. prompts/0000_global.md §2-1 자정 갭다운 예측 단계에 적용.

## sector-rotation-reentry

경로: `policy.sector_rotation_reentry.purpose`

v2.8 — 범용 섹터 로테이션 재진입 엔진. 침체 섹터(특히 avoid_sectors)를 '바닥 가격 반등(5일)'이 아니라 '호재(촉매) + 시장 몰입(자금이 실제로 도는 증거)' 두 개가 같이 올 때 풀어 재진입한다. 조선 전용이 아니라 config(universe.json sector/theme + watchlist.avoid_sectors)로 정의된 모든 섹터에 동일 적용한다. 핵심 원리: 스토리(호재)만으론 부족(조선은 LNG 슈퍼사이클 스토리를 내내 갖고도 3회 손실 — 스토리≠자금). 호재=방아쇠, 몰입증거=안전핀(헤드라인이 진짜 자금을 끌었는지 검증).

## sector-rotation-reentry-sensitivity-by-tier

경로: `policy.sector_rotation_reentry.sensitivity_by_tier.purpose`

v2.10 — 시장 상황(레짐 tier)에 따라 바닥 재진입 민감도를 자동 조정한다. 강세장은 섹터 로테이션이 강하고 침체 섹터가 강하게 반등하므로 일찍(aggressive) 잡고, 약세장은 떨어지는 칼날·가짜 바닥이 많으므로 충분히 확인(conservative)한 뒤만 잡는다. screen_universe.py 가 snapshot.regime.tier 로 조회하며(sensitivity_mode=auto), tier 가 unknown 이거나 mode 가 고정값(aggressive/medium/conservative)이면 sensitivity 폴백.

## lessons-rule-sunset

경로: `policy.lessons_rule_sunset.purpose`

v2.11 — 손실 직후 즉석 신설되는 제한 룰(예: 'Broadcom D-1~D+2 반도체 15% 캡'이 바로 다음날 6/9 회복 진입을 12%로 캡)이 일몰 없이 누적돼 미배치를 악화시키는 래칫 차단. 2026-05-20~06-09 평균 주식비중 20.2%(strong_bull 목표 80~95%)의 한 원인.

## thesis-card-gate

경로: `policy.thesis.card_gate.purpose`

v2.25 — thesis 스키마는 v2.x 부터 정의돼 있었으나 보유 3종(079550·042700·055550) 전부 thesis 객체가 비어 있었다(2026-07-26 audit WARN). 논거 층이 비면 청산 판정이 가격 규칙 하나로 축소된다. 카드 필수 필드를 게이트로 세워 '논거 없는 보유'를 표면화한다.

## valuation-anchor

경로: `policy.valuation_anchor.purpose`

v2.11 — PER/PBR 밴드 기반 '냉정한 목표가 상한'과 진입 과열 가드. 모멘텀·ATR 목표가가 기업가치에서 과도하게 이탈하는 것을 캡한다(2026-05-20~06-09 목표 도달 0/6 — 목표가 인플레가 원인 중 하나). 밸류에이션은 후행·저속 신호이므로 진입 타이밍 신호로 쓰지 않는다 — 상한(ceiling)·과열 경고(overheat)·확신 틸트로만 사용. 사이클 업종(반도체·조선·자동차·전지·중공업)은 PER 함정(피크 실적=최저 PER) 때문에 preferred_metric=PBR.

## context-budget

경로: `policy.context_budget.purpose`

핫패스(매 routine 의무 적재) 파일의 무한 누적 → 콘텍스트 오버 → 규칙 누락·판단 열화 방지. 매매 룰 래칫 감시(blocked_day_rate)와 동형의 크기 래칫 안전장치. 근거: docs/plan_context_compaction.md (2026-06-12 진단 — 의무 적재 ~500KB, watchlist 1,945줄로 Read 캡 임박).

