# GitHub 중심 모바일 운영 파이프라인

이 저장소의 운영 원칙은 **GitHub가 중앙 실행·저장·발송 허브**가 되는 것이다.
로컬 Windows 작업 스케줄러는 보조 수단이며, 모바일 확인은 GitHub Pages와 Kakao 알림을 기준으로 한다.

## 실행 주체

| 구분 | 실행 위치 | 산출물 | 모바일 발송 |
|---|---|---|---|
| 00:30 글로벌 점검 | Claude cloud routine 또는 Codex worktree | `reports/YYYY-MM-DD.md` 00시 섹션 | `chore(00:00):` 커밋 후 Kakao |
| 09:00 개장 점검 | Claude cloud routine 또는 Codex worktree | 09시 섹션, `portfolio.json`, `watchlist.json` | `chore(09:00):` 커밋 후 Kakao |
| 12:00 장중 점검 | Claude cloud routine 또는 Codex worktree | 12시 섹션, 체결/경보 | `chore(12:00):` 커밋 후 Kakao |
| 15:00 마감 임박 | Claude cloud routine 또는 Codex worktree | 15시 섹션, 익일 후보 | `chore(15:00):` 커밋 후 Kakao |
| 18:00 일일 확정 | Claude cloud routine 또는 Codex worktree | 18시 확정 리포트, `weekly_plan.json` 갱신 | `report:` 커밋 후 Kakao |
| 19:30 평일 감사 | GitHub Actions | `reports/YYYY-MM-DD-audit.md` | 감사 workflow가 직접 Pages 배포 + Kakao |
| 토요일 사후분석 | Codex worktree 또는 Claude cloud routine | `reports/YYYY-MM-DD-saturday-review.md` | `sat-review:` 커밋 후 Kakao |
| 일요일 다음주 전략 | Codex worktree 또는 Claude cloud routine | `reports/YYYY-MM-DD-sunday-strategy.md`, `weekly_plan.json` | `sun-strategy:` 커밋 후 Kakao |

## 커밋 프리픽스와 알림

GitHub Actions의 `build_and_notify.yml`은 아래 커밋 프리픽스를 감지해 HTML 빌드와 Kakao 발송을 수행한다.

- `chore(00:00):` 글로벌 야간 점검
- `chore(09:00):` 개장 점검
- `chore(12:00):` 장중 점검
- `chore(15:00):` 마감 임박 점검
- `report:` 일일 확정 리포트
- `audit:` 파이프라인 감사 리포트. 평일 감사 workflow는 GitHub 토큰 push가 다른 workflow를 깨우지 않는 경우를 피하기 위해 직접 Pages 배포와 Kakao 발송까지 수행한다.
- `sat-review:` 토요일 사후분석 리포트
- `sun-strategy:` 일요일 다음주 전략 리포트
- `weekly:` 기존 주말 통합 리포트 호환

## 주말 역할 분리

토요일은 **지난주를 복기**한다.

- 가격·수급·공시 검증
- 체결과 손익 복기
- 루틴 연결성 평가
- `lessons.md`, `policy.json`, 프롬프트 반영 후보 도출

일요일은 **다음주를 설계**한다.

- 주말 뉴스와 다음주 경제 일정 분석
- 다음주 `weekly_thesis` 작성
- 주간 목표·리스크 예산 재설계
- 월요일 09시 액션 플랜 작성

## 모바일 확인 흐름

1. 루틴 또는 감사가 리포트를 생성한다.
2. 변경사항을 커밋하고 GitHub에 push한다.
3. GitHub Actions가 HTML을 빌드해 GitHub Pages에 배포한다.
4. Kakao "나에게 보내기"로 해당 리포트 링크가 발송된다.
5. 모바일에서는 Kakao 링크 또는 GitHub Pages에서 리포트를 확인한다.

## 운영 원칙

- 실제 주문은 자동화하지 않는다.
- 모든 가격은 출처와 시각, 신뢰도 등급을 남긴다.
- 신규 진입은 `weekly_plan.json`의 thesis와 연결되어야 한다.
- 손절/익절은 고정 가격이 아니라 주간 목표와 리스크 예산을 함께 반영한다.
- PC가 꺼져 있어도 돌아야 하는 핵심 루틴은 local이 아니라 GitHub/cloud/worktree 기준으로 둔다.
