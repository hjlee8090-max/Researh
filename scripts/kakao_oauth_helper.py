#!/usr/bin/env python3
"""카카오 OAuth 1회 셋업 헬퍼.

사용 절차:
  1. https://developers.kakao.com 에서 앱 생성 (또는 기존 앱 선택)
  2. [앱 설정 > 플랫폼 > Web] 에 https://example.com 추가
  3. [제품 설정 > 카카오 로그인] 활성화
     - Redirect URI: https://example.com 추가
  4. [제품 설정 > 카카오 로그인 > 동의항목] 에서
     '카카오톡 메시지 전송 (talk_message)' 사용 설정
  5. [앱 키] 에서 REST API 키 복사
  6. 이 스크립트 실행:
        export KAKAO_REST_API_KEY=발급받은_REST_API_키
        python scripts/kakao_oauth_helper.py
  7. 출력된 URL을 브라우저로 열고 카카오 동의
  8. 동의 후 example.com 으로 리디렉트됨 (Not Found 페이지여도 OK).
     주소창의 ?code=XXXXX 값만 복사해 입력
  9. 출력된 refresh_token 을 GitHub 레포 Secrets 에 등록:
        Settings > Secrets and variables > Actions > New repository secret
        - Name : KAKAO_REFRESH_TOKEN
        - Value: 출력된 refresh_token
        그리고 REST API 키도:
        - Name : KAKAO_REST_API_KEY
        - Value: 발급받은 REST API 키
"""
import json
import os
import sys
import urllib.parse
import urllib.request


def main():
    rest_key = os.environ.get("KAKAO_REST_API_KEY")
    if not rest_key:
        sys.exit("환경변수 KAKAO_REST_API_KEY 를 먼저 export 하세요.\n"
                 "예) export KAKAO_REST_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

    redirect_uri = os.environ.get("KAKAO_REDIRECT_URI", "https://example.com")

    auth_url = (
        "https://kauth.kakao.com/oauth/authorize?"
        + urllib.parse.urlencode({
            "client_id": rest_key,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "talk_message",
        })
    )

    print("=" * 72)
    print("1) 아래 URL을 브라우저로 열고 카카오 로그인/동의를 진행하세요:\n")
    print(auth_url)
    print()
    print("2) 동의 후 리디렉트된 페이지의 주소창에서 ?code=XXXXX 값만 복사하세요.")
    print("   (Not Found 페이지여도 정상입니다 — URL의 code 파라미터만 필요)")
    print("=" * 72)

    code = input("\ncode: ").strip()
    if not code:
        sys.exit("code 가 비어있습니다.")

    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": rest_key,
        "redirect_uri": redirect_uri,
        "code": code,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://kauth.kakao.com/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        sys.exit(f"토큰 교환 실패: {e}")

    if "refresh_token" not in res:
        sys.exit(f"refresh_token 미발급 응답: {res}")

    print()
    print("=" * 72)
    print("✅ 토큰 발급 성공!")
    print()
    print("GitHub 레포 Settings > Secrets and variables > Actions 에 등록:")
    print()
    print(f"  KAKAO_REST_API_KEY  = {rest_key}")
    print(f"  KAKAO_REFRESH_TOKEN = {res['refresh_token']}")
    print()
    print(f"  (access_token 은 자동 갱신되므로 등록 불필요)")
    print(f"  (refresh_token 은 60일 유효. 만료 임박시 send_kakao.py 가 신규 토큰을 로그에 출력)")
    print("=" * 72)


if __name__ == "__main__":
    main()
