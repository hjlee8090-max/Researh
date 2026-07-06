# 인시던트 — 2026-07-06 09시 슬롯 알림·Pages 배포 레이스

## 증상
- 7/6 09시 리포트가 **정상 생성·main 반영**(커밋 `065f715`, 09:25 KST 생성)됐으나:
  1. GitHub Pages 리포트 목록에 7/6-09 카드 링크가 **누락**
  2. 09시 카카오 알림이 **미발송**(사용자 체감: "09시 리포트가 안 돌았다")

## 근본 원인 — 하나의 뿌리
`build_and_notify.yml` 최근 실행(run `28760279567`, workflow_dispatch, 00:29Z)이
**09시 리포트 커밋보다 앞선 커밋 `88d6f2b`(00:14Z 스냅샷)에서 체크아웃되어** 돌았다.

```
27200c4  data(notify) 배송원장        ← 이후 main HEAD
065f715  chore(09:00) 09시 리포트       ← 09 리포트 추가(00:28:56Z)
88d6f2b  data(prices) 00:14 스냅샷      ← ★ 마지막 Pages 빌드가 돈 커밋(09 없음)
```

- `build_html.py` 는 체크아웃 커밋의 `reports/*.md` 로 인덱스를 매번 재생성 → `88d6f2b`
  체크아웃엔 7/6-09 파일이 없어 목록에서 누락.
- `send_kakao.py` 의 `find_slot_report("09")` 도 같은 낡은 체크아웃에서 직전 영업일
  파일(`2026-07-03-09.md`)을 집어 `is_dated_today` 실패 → `stale_report` 스킵
  (원장: `{"event":"skip","slot":"09","reason":"stale_report"}`). 원장 전체 첫 발생.

auto_merge 병합은 `GITHUB_TOKEN` push 라 재귀 방지 규칙상 build_and_notify 를
재트리거하지 않아, 병합 이후 Pages 가 09:29 상태로 동결됐다.

## 복구
현재 main HEAD 는 7/6-09 리포트를 포함하므로, build_and_notify 를 현재 main 기준
1회 재실행하면 목록 재빌드(09 복구) + 09 카톡 재발송이 동시에 해소된다. 본 노트를
담은 `chore(09:00)` 커밋이 auto_merge → build_and_notify dispatch 경로를 다시 태운다.

## 후속 관찰 포인트
- dispatch 의 `--ref main` 이 방금 push 한 SHA 보다 뒤처진 커밋으로 해소되는 레이스가
  재발하는지(현재 1회) — 반복되면 auto_merge 에 "origin/main 이 push SHA 를 포함할
  때까지 확인 후 dispatch" 하드닝을 검토.
