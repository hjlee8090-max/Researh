# 리포트 형식 계약 (Report Contract) — 단일 스펙

> 목적: 시간대별 리포트의 파서 의존 요소(고정 문자열·구조)를 **한 곳**에 정의한다.
> 이전에는 이 계약이 4곳(send_kakao.py·build_html.py·audit_pipeline.py·프롬프트의 "파서 고정 문자열" 절)에
> 흩어져 있어 한쪽만 바뀌면 "카톡이 안 오는" 형태로만 사후 발견됐다 (진단 I14·I15, plan Phase 1-4).
> 기계 검사: `scripts/check_report_contract.py` (audit 이 매 실행 당일분을 WARN 으로 흡수).

## 0. 계약 소비자 (이 문서와 동기화해야 하는 코드)

| 소비자 | 사용 요소 | 위치 |
|---|---|---|
| `scripts/send_kakao.py` | 슬롯 헤더(SLOT_META)·`### 한눈에 보기` 추출 | SLOT_META 상수 근처 주석 참조 |
| `scripts/build_html.py` | `오늘의 한줄평` og:description 추출 | `extract_oneline()` |
| `scripts/audit_pipeline.py` | 한눈에 보기 금칙어(GLANCE_BANNED_TOKENS)·면책 | `audit_reports()` |
| `scripts/check_report_contract.py` | 본 문서 전체의 기계 사본 | 상수 블록 |
| `prompts/*.md` "파서 고정 문자열" 절 | 슬롯 헤더·한줄평·한눈에 보기 | 각 슬롯 프롬프트 |
| `prompts/sunday_archive.md` §2-1 | 슬롯 헤더 기준 주간 응축 | 추출 규칙 |

**변경 절차**: 이 문서를 먼저 고치고 → 소비자 6곳을 같은 커밋에서 동기화하고 → `check_report_contract.py` 를
최근 3일 리포트에 소급 실행(`--days 3`)해 회귀를 확인한다.

## 1. 슬롯 헤더 (고정 문자열 — 1글자도 바꾸지 않는다)

```
00 → ## 🌙 00:00 글로벌 야간 점검
06 → ## 🌄 06:00 미국장 마감 확정
09 → ## 🌅 09:00 개장 점검
12 → ## 🕛 12:00 장중 점검
15 → ## 🔔 15:00 마감 임박 점검
18 → ## 📊 18:00 종합·확정 리포트
```

- 발화 시각이 밀려도(09:20 발화 등) 헤더의 명목 시각은 위 그대로 유지한다 (README 슬롯 관례).

## 2. 필수 구조 요소 (슬롯 리포트 공통)

1. **시리즈 진행 줄**: `> 시리즈 진행:` 로 시작하는 1줄. **6개 슬롯 전부**(🌙 🌄 🌅 🕛 🔔 📊)를
   `✓ / ⚠️(미실행) / 대기` 상태와 함께 표기한다. 일부 슬롯을 빼고 적으면 미발행이 은폐된다(진단 I14).
2. **`### 한눈에 보기`**: 카톡 요약의 추출 원천. 불릿은 `- **라벨**: 값` 형식 — send_kakao 가
   라벨(예: "오늘의 액션", "KOSPI", "촉매")로 요약 줄을 고른다.
3. **`오늘의 한줄평`**: `오늘의 한줄평: <문장>` 형태 1줄 (build_html 이 og:description 으로 사용).
4. **`### 면책`**: 학습·시뮬레이션 고지.

## 3. 금지 요소 (독자 화면 보호)

- **본문 전체**(고정밀 — check_report_contract 검사): 내부 섹션 참조 `§`, 정책/모델 버전 `vX.Y`,
  트리거 ID `po-YYYYMMDD…`.
- **한눈에 보기 한정**(광폭 — audit GLANCE_BANNED_TOKENS 검사): `live_verify`·`web_verify`·`pre_trade`·
  `resync`·`HTTP 403`·`freshness`·`snapshot_age`·`tier=`·`stale`·`mark-to-market`·`time_stop`·`§`.
- 정책 근거가 필요하면 사람 말로 풀고, 상세는 "내부 규칙 문서 참조" 각주로 처리한다.

## 4. 위험 게이지 (v1 — 현행 최소 계약, Phase 4-6 에서 단일 규약 확정 예정)

- 코드펜스 안 게이지 한 줄에 현재가 마커 `●` 는 **정확히 1개**.
- 손절까지의 거리는 `-X.X%`(하락 거리) 부호로 표기한다 — `손절가까지 +X%` 금지 (진단 I13 부호 반전 사고).

## 5. 빈 섹션 금지

- 헤딩 직후 본문 없이 같은·상위 레벨 헤딩이 이어지면 위반(이중 헤딩 — 07-02-09 사고).
- 섹션 제목을 바꿀 때는 구제목을 지우고 신제목만 남긴다(과도기 이중 표기 금지).

## 6. 검사기 사용법

```bash
python scripts/check_report_contract.py                 # 오늘(KST) 슬롯 리포트
python scripts/check_report_contract.py --days 3        # 최근 3일 소급
python scripts/check_report_contract.py --date 2026-07-02 --strict   # 특정일, 위반 시 exit 1
```

- audit_pipeline 이 매 실행 당일분을 자동 검사한다 (WARN — 빌드 차단 없음).
- 리포트 형식을 바꾸는 모든 변경(Phase 4 포함)은 이 검사기의 통과가 배포 전제다.
