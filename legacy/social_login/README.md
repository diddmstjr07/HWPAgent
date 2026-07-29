# 소셜 로그인 백업 (Google / Kakao / Naver)

ChatGPT(Codex) 로그인으로 교체하면서 로그인 화면에서 제거한 자산을 보관합니다.

## 보관 파일

| 파일 | 원래 위치 |
|---|---|
| `login_buttons.html` | `templates/login.html` 의 `.social-login` 블록 (구 325~336행) |
| `login_buttons.css` | `templates/login.html` 의 `.btn-social` / `.btn-google` / `.btn-kakao` / `.btn-naver` 규칙 (구 216~233행) |
| `login_buttons.js` | `data-social-auth` 링크에 `next` 파라미터를 붙이던 스크립트 (구 384~388행) |

세 파일 모두 Google·Kakao·Naver 브랜드 SVG 로고 원본을 그대로 담고 있습니다.

## 백엔드는 아직 살아 있습니다

프론트엔드 버튼만 제거했고 OAuth 엔드포인트는 [app.py](../../app.py)에 그대로 있습니다.

- `GET /api/auth/social/{provider}` — `social_login`
- `GET /api/auth/social/{provider}/callback` — `social_callback`

즉 지금은 **UI에서만 진입로가 사라진 상태**입니다. 라우트가 여전히 노출되어 있으므로,
완전히 제거하려면 위 두 핸들러와 `_build_oauth_redirect_uri`, 관련 환경변수
(`GOOGLE_CLIENT_ID`, `KAKAO_CLIENT_ID`, `NAVER_CLIENT_ID` 등)를 함께 정리해야 합니다.

## 되돌리는 방법

1. `login_buttons.css` 내용을 `templates/login.html` 의 `<style>` 안에 다시 붙인다.
2. `login_buttons.html` 을 `.divider` 아래에 다시 넣는다.
3. `login_buttons.js` 를 로그인 스크립트에 다시 넣는다.

백엔드는 손대지 않았으므로 위 3단계만으로 복구됩니다.
