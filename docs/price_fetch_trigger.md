# 시세 수집 정시 트리거 (외부 스케줄러 → workflow_dispatch)

## 왜 필요한가
`fetch_prices.yml`(시세 수집)을 GitHub `schedule`(cron)로만 돌리면 **30~50분+ 지연·누락**이 잦다
(GitHub 공식: 예약 워크플로는 best-effort이고 high load·매시 정각에 지연. 관측: UTC 03:00→03:32 등).
그 지연을 흡수하려고 routine 1시간 전부터 미리 받다 보니, routine 시점 스냅샷 나이(age)가 상시
40~60분이라 한 번도 `fresh(≤20분)`에 못 들어가고 **매번 웹 교차확인(live_verify)** 이 필요했다.

수집 자체는 빠르다(`fetch_market_data.py` 스레드풀 병렬화 후 ~1초). 문제는 **"언제 시작되느냐"**.
→ `schedule` 대신 **외부 스케줄러가 정시에 `workflow_dispatch`를 호출**하면 큐 지연 없이 수 초 내
시작되어, routine 5분 전에 받으면 스냅샷 age가 ~5분(=fresh)이 되고 웹 교차확인이 사라진다.

## 동작 구조
- **1순위(주 트리거)**: 외부 스케줄러(cron-job.org 등)가 routine 5분 전에 GitHub API로
  `workflow_dispatch` 호출 → 수집 job은 그대로 GitHub Actions 러너에서 실행(네이버/야후 접근 검증됨).
  - **단, 09시(개장 점검)만 예외**: "routine 5분 전 = 08:55"는 개장(09:00) 전이라 당일 시세가
    아직 없어 전일 종가만 담긴다(`today_ohlc=null`). 그래서 09시 슬롯은 **개장 직후 09:07** 에도
    한 번 더 호출해 시초가 반영 스냅샷을 받는다(12·15·18시는 11:55·14:55·17:55 수집이 장중이라 무관).
- **백업(안전망)**: `fetch_prices.yml`의 `schedule` cron. 외부 트리거가 멈췄을 때만 의미가 있으며,
  지연돼도 routine 전에는 들어오도록 일찍 잡아둔 보루다. 아침은 2겹 — **08:05**(개장 전, 전일 종가)
  + **09:05**(개장 직후, 시초가) — 이고, 오후는 11:05·14:05·17:05 1겹씩이다.
- **실패 시 graceful degrade**: 외부·백업 모두 실패해도 직전 스냅샷이 보존되고
  `policy.data_freshness` 게이트가 age를 인지·보정(신규 진입은 웹 교차확인)하므로 매매 안전성은 유지.

## 설정 (cron-job.org, 코드 0줄)

### 1) GitHub 토큰 발급 (계정 설정)
- https://github.com/settings/personal-access-tokens/new (Fine-grained token)
- Resource owner: `hjlee8090-max` / Repository access: **Only select repositories → Researh**
- Permissions → Repository permissions → **Actions: Read and write** (Metadata: Read-only 자동 포함)
- Generate 후 토큰(`github_pat_...`) 복사 — **1회만 표시**

### 2) cron-job.org에 알람 5개 등록 (평일)
```
URL:   https://api.github.com/repos/hjlee8090-max/Researh/actions/workflows/fetch_prices.yml/dispatches
방식:   POST
헤더:   Accept: application/vnd.github+json
       Authorization: Bearer <발급한_토큰>
       X-GitHub-Api-Version: 2022-11-28
본문:   {"ref":"main"}
시간(Asia/Seoul, 월~금): 08:55 / 09:07 / 11:55 / 14:55 / 17:55
```

- **09:07(개장 직후)는 시초가 확보용**이다. 08:55(개장 전)는 전일 종가만 담기므로 09시 리포트가
  당일 시가를 받으려면 이 호출이 필요하다(08:55는 개장 전 프라이밍용으로 유지 — 둘 다 둔다).
- **09시 routine 시작은 09:10~09:12로** 맞춘다. 09:07 호출이 스냅샷을 커밋하는 데 ~1~2분 걸리므로,
  routine이 그 전에 `git pull`하면 다시 08:55(전일 종가)를 읽어 효과가 없다.
- 새 잡도 **타임존 `Asia/Seoul`** 과 **`Authorization` 헤더(기존과 동일 토큰)** 가 들어갔는지 확인한다.

## 보안 주의
- 토큰은 **cron-job.org의 Authorization 헤더에만** 넣는다. 채팅·커밋·코드·레포 Secrets에 남기지 않는다.
- 실수로 노출되면 즉시 폐기(https://github.com/settings/personal-access-tokens) 후 재발급.
- 권한은 이 레포의 Actions로 한정 — 코드 푸시나 타 레포 접근은 불가.

## 기대 효과
- routine 시점 스냅샷 `freshness=fresh` → `live_verify_required` 자동 해제(코드 변경 불필요, age 기반 자동).
- 시세 수집 타이밍이 리포트 시각에 거의 밀착.
- **09시 개장 점검이 매일 당일 시가 스냅샷으로 들어온다**(기존 "출처 차단(403)·미확인"으로 전일
  종가 carry하던 구멍 해소 — 12·15·18시와 동일한 "장중 2출처 일치" 수준).
