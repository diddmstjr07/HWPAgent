"""ChatGPT(Codex) 기기 코드 연결 라우터.

ChatGPT 연결은 **사용 한도(토큰)를 빌려오는 것일 뿐, 앱 로그인이 아닙니다.**

예전에는 연결이 곧 로그인이었습니다. ChatGPT 계정 해시로 앱 사용자를 찾아
세션에 심었기 때문에, 같은 ChatGPT 계정을 연결한 사람은 누구든 그 앱 계정의
설계·실험·보고서를 그대로 보게 됐습니다. 남의 데이터가 통째로 불려오는 길이었고,
그래서 끊어냈습니다. 앱 신원은 이메일/비밀번호 로그인만 정합니다.

흐름:
    0. 앱 로그인 (POST /api/auth/login) — 이게 있어야 연결할 수 있습니다.
    1. POST /api/auth/codex/connect  -> 기기 코드 발급 (verification_url + user_code)
    2. 사용자가 ChatGPT에서 코드 승인
    3. GET  /api/auth/codex/status   -> 프런트가 폴링, connected가 되면 연결 완료
    4. POST /api/auth/codex/logout   -> 연결 해제

브라우저에는 서명된 instance_id 쿠키만 내려갑니다. ChatGPT 계정 이메일은
HMAC(account_hash)으로만 다루며 원문을 저장하지 않습니다. 쿠키에는 연결을 만든
앱 사용자(owner)도 함께 서명해 둡니다 — 그러지 않으면 한 브라우저에서 로그아웃한
뒤 다른 계정으로 들어온 사람이 앞 사람의 토큰을 그대로 물려받습니다.
"""
import logging
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeSerializer

from modules import codex_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/auth/codex', tags=['Codex Auth'])

AUTH_COOKIE_NAME = 'doc_agent_codex_auth'
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
_SALT = 'codex-auth-session'


def _serializer() -> URLSafeSerializer:
    secret = os.getenv('SECRET_KEY') or 'dev-secret-key'
    return URLSafeSerializer(secret, salt=_SALT)


def encode_auth_session(instance_id: str, account_hash: Optional[str],
                        owner: Optional[str] = None) -> str:
    return _serializer().dumps({'instance_id': instance_id,
                                'account_hash': account_hash,
                                'owner': owner})


def decode_auth_session(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        payload = _serializer().loads(raw)
    except BadSignature:
        return None
    instance_id = payload.get('instance_id') if isinstance(payload, dict) else None
    if not isinstance(instance_id, str) or not (16 <= len(instance_id) <= 80):
        return None
    account_hash = payload.get('account_hash')
    if account_hash is not None and not (isinstance(account_hash, str) and len(account_hash) == 64):
        return None
    owner = payload.get('owner')
    if owner is not None and not (isinstance(owner, str) and 0 < len(owner) <= 80):
        return None
    return {'instance_id': instance_id, 'account_hash': account_hash, 'owner': owner}


def current_app_user_id(request: Request) -> Optional[str]:
    """지금 로그인한 앱 사용자. 여기서는 읽기만 합니다 — 절대 쓰지 않습니다.

    ChatGPT 연결이 앱 신원을 정하던 것이 문제였으므로, 이 모듈은 세션의
    user_id를 건드리지 않습니다.
    """
    return request.session.get('user_id') if hasattr(request, 'session') else None


def auth_session_from_request(request: Request) -> Optional[Dict[str, Any]]:
    """요청에 실린 Codex 연결 세션을 돌려줍니다(없으면 None).

    연결을 만든 사람과 지금 로그인한 사람이 다르면 없는 것으로 봅니다.
    같은 브라우저에서 계정만 바꿔 앞 사람의 ChatGPT 한도를 쓰는 일을 막습니다.

    owner가 없는 쿠키(연결이 곧 로그인이던 시절의 것)도 없는 것으로 봅니다.
    주인을 알 수 없는 연결은 누구에게 붙일지 정할 수 없습니다. 다시 연결하면 됩니다.
    """
    session = decode_auth_session(request.cookies.get(AUTH_COOKIE_NAME))
    if not session:
        return None
    if not session.get('owner') or session['owner'] != current_app_user_id(request):
        return None
    return session


def get_or_create_auth_session(request: Request) -> Dict[str, Any]:
    """세션이 없으면 새 instance_id를 발급합니다."""
    return auth_session_from_request(request) or {
        'instance_id': str(uuid.uuid4()),
        'account_hash': None,
        'owner': current_app_user_id(request),
    }


def _attach_cookie(response: JSONResponse, session: Dict[str, Any]) -> JSONResponse:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        encode_auth_session(session['instance_id'], session.get('account_hash'),
                            session.get('owner')),
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite='lax',
        secure=os.getenv('COOKIE_SECURE', '').strip().lower() in {'1', 'true', 'yes', 'on'},
        path='/',
    )
    return response


def _error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status_code)


def disconnect(request: Request, response: JSONResponse) -> JSONResponse:
    """ChatGPT 연결을 끊고 인증 쿠키를 지웁니다.

    앱 로그아웃도 반드시 여기를 거쳐야 합니다. 세션만 비우면 쿠키에
    instance_id가 그대로 남아, 다음 연결 시도에서 get_status가 곧바로
    connected를 돌려주고 이전 계정으로 되돌아갑니다(계정을 바꿀 수 없음).

    러너 쪽 해제가 실패해도 쿠키는 지웁니다. 그러면 다음 요청은 새
    instance_id를 발급받아 기기 코드 로그인부터 다시 시작합니다.
    """
    session = auth_session_from_request(request)
    if session and codex_runner.is_configured():
        try:
            codex_runner.logout(session['instance_id'])
        except codex_runner.CodexRunnerError as exc:
            logger.warning('[CODEX] logout failed: %s', exc.message)
    response.delete_cookie(AUTH_COOKIE_NAME, path='/')
    return response


def _connection_payload(status: Dict[str, Any]) -> Dict[str, Any]:
    """브라우저로 내보낼 연결 정보. account_hash/account_email은 의도적으로 제외한다."""
    return {
        'status': status['status'],
        'plan_type': status.get('plan_type'),
        'rate_limit': status.get('rate_limit'),
        'error': status.get('error'),
    }


def _app_user_payload(request: Request) -> Optional[Dict[str, Any]]:
    """지금 로그인한 앱 사용자를 프런트에 알려줍니다.

    예전에는 이 자리에서 ChatGPT 계정 해시로 앱 사용자를 찾아 로그인시켰습니다
    (_sign_in_with_codex). 그 때문에 같은 ChatGPT 계정을 연결한 사람이 남의 설계·
    실험·보고서를 그대로 열어볼 수 있었습니다. 지금은 이미 로그인한 사람이
    누구인지 되돌려 줄 뿐, 신원을 만들거나 바꾸지 않습니다.
    """
    user_id = current_app_user_id(request)
    if not user_id:
        return None

    from database import db  # 순환 import를 피하려고 호출 시점에 가져온다.

    user = db.get_user(user_id)
    return user.to_dict() if user else None


@router.get('/status')
def codex_status(request: Request):
    """현재 브라우저의 ChatGPT 연결 상태를 반환합니다."""
    if not codex_runner.is_configured():
        return {
            'configured': False,
            'connection': {'status': codex_runner.STATUS_UNAVAILABLE, 'plan_type': None,
                           'rate_limit': None, 'error': None},
            'models': [],
            'user': _app_user_payload(request),
        }

    session = auth_session_from_request(request)
    if not session:
        return {
            'configured': True,
            'connection': {'status': codex_runner.STATUS_DISCONNECTED, 'plan_type': None,
                           'rate_limit': None, 'error': None},
            'models': [],
            'user': _app_user_payload(request),
        }

    try:
        status = codex_runner.get_status(session['instance_id'])
    except codex_runner.CodexRunnerError as exc:
        return _error(exc.message, exc.status_code)

    models = []
    if status['status'] == codex_runner.STATUS_CONNECTED:
        try:
            models = codex_runner.list_models(session['instance_id'])
        except codex_runner.CodexRunnerError:
            models = []

    response = JSONResponse({
        'configured': True,
        'connection': _connection_payload(status),
        'models': models,
        'user': _app_user_payload(request),
    })
    if status['status'] == codex_runner.STATUS_CONNECTED and status['account_hash']:
        session['account_hash'] = status['account_hash']
        _attach_cookie(response, session)
    return response


@router.post('/connect')
def codex_connect(request: Request):
    """기기 코드 연결을 시작합니다. 이미 연결돼 있으면 login은 null입니다.

    앱에 로그인한 뒤에만 연결할 수 있습니다. 연결이 신원을 만들지 않으므로,
    로그인 없이 연결하면 토큰을 어느 계정에 묶어야 할지 정할 수 없습니다.
    """
    if not codex_runner.is_configured():
        return _error('ChatGPT 연결이 아직 설정되지 않았습니다.', 503)
    if not current_app_user_id(request):
        return _error('먼저 앱에 로그인해 주세요. ChatGPT 연결은 로그인 뒤에 합니다.', 401)

    session = get_or_create_auth_session(request)
    try:
        status = codex_runner.get_status(session['instance_id'])
        if status['status'] == codex_runner.STATUS_CONNECTED:
            if status['account_hash']:
                session['account_hash'] = status['account_hash']
            return _attach_cookie(JSONResponse({
                'connected': True,
                'login': None,
                'connection': _connection_payload(status),
                'user': _app_user_payload(request),
            }), session)

        login = codex_runner.start_device_login(session['instance_id'])
    except codex_runner.CodexRunnerError as exc:
        return _error(exc.message, exc.status_code)

    return _attach_cookie(JSONResponse({
        'connected': False,
        'login': login,
        'connection': {'status': codex_runner.STATUS_PENDING, 'plan_type': None,
                       'rate_limit': None, 'error': None},
    }), session)


@router.post('/logout')
def codex_logout(request: Request):
    """ChatGPT 연결을 해제하고 인증 쿠키를 지웁니다."""
    # ChatGPT 연결이 곧 로그인이므로 앱 세션도 함께 끊는다.
    if hasattr(request, 'session'):
        request.session.pop('user_id', None)

    return disconnect(request, JSONResponse({'success': True}))
