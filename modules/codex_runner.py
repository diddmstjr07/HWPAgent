"""Codex Runner 클라이언트.

사용자의 ChatGPT 계정을 기기 코드(device code)로 연결하고, 그 계정 토큰으로
Codex 모델을 호출합니다. 실제 `codex` CLI는 별도 Node 서비스(Codex Runner)가 감싸고
있으며, 여기서는 HTTP로만 통신합니다. services/hwp-node 를 부르는
v2_hwp_proxy.py 와 같은 사이드카 프록시 구조입니다.

필요 환경변수:
    CODEX_RUNNER_URL            Runner 주소 (예: https://xxx.up.railway.app)
    CODEX_RUNNER_SHARED_SECRET  Runner 공유 시크릿 (32자 이상)
    ACCOUNT_IDENTITY_SECRET     ChatGPT 계정 식별자 HMAC 키 (32자 이상)
"""
import hashlib
import hmac
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = float(os.getenv('CODEX_RUNNER_HTTP_TIMEOUT_MS', '210000')) / 1000

# Runner가 돌려주는 연결 상태
STATUS_CONNECTED = 'connected'
STATUS_DISCONNECTED = 'disconnected'
STATUS_PENDING = 'pending'
STATUS_ERROR = 'error'
STATUS_UNAVAILABLE = 'unavailable'


class CodexRunnerError(Exception):
    """Runner 호출 실패. status_code는 클라이언트에 그대로 내려줄 HTTP 상태입니다.

    kind는 화면이 다르게 보여줘야 하는 실패의 종류다(예: usage_limit).
    """

    def __init__(self, message: str, status_code: int = 503, kind: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.kind = kind


def _config() -> Optional[Dict[str, str]]:
    raw_url = (os.getenv('CODEX_RUNNER_URL') or '').strip()
    secret = os.getenv('CODEX_RUNNER_SHARED_SECRET') or ''
    identity_secret = os.getenv('ACCOUNT_IDENTITY_SECRET') or ''
    if not raw_url or len(secret) < 32 or len(identity_secret) < 32:
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme not in ('http', 'https'):
        raise CodexRunnerError('CODEX_RUNNER_URL은 HTTP(S) 주소여야 합니다.', 500)
    return {
        'url': raw_url.rstrip('/'),
        'secret': secret,
        'identity_secret': identity_secret,
    }


def is_configured() -> bool:
    """Runner 설정이 갖춰졌는지 확인합니다."""
    try:
        return _config() is not None
    except CodexRunnerError:
        return False


def runner_session_id(instance_id: str) -> str:
    """브라우저 설치 단위로 Runner 세션을 격리하는 식별자.

    instance_id를 그대로 넘기지 않고 HMAC을 거쳐, 쿠키 값을 아는 것만으로는
    Runner 세션을 직접 지목할 수 없게 합니다.
    """
    settings = _config()
    if not settings:
        raise CodexRunnerError('AI Runner가 아직 설정되지 않았습니다.', 503)
    return hmac.new(
        settings['secret'].encode('utf-8'),
        f'browser-auth:{instance_id}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def hash_account_identity(email: str) -> Optional[str]:
    """ChatGPT 계정 이메일을 HMAC으로 치환합니다. 원문 이메일은 저장하지 않습니다."""
    settings = _config()
    if not settings or not email:
        return None
    normalized = email.strip().lower()
    return hmac.new(
        settings['identity_secret'].encode('utf-8'),
        f'chatgpt-account:{normalized}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


USAGE_LIMIT_KIND = 'usage_limit'
_USAGE_LIMIT_HINTS = ('usage limit', 'rate limit', 'quota')

# 러너는 로그인 하나당 한 번에 한 턴만 돌린다. 앞의 턴이 아직 안 끝났다는 뜻이라
# 고장이 아니라 기다리면 되는 상태다. 서버 오류로 뭉뚱그리면 학생이 원인을 알 수 없다.
BUSY_KIND = 'runner_busy'
_BUSY_HINT = 'another turn is already running'


def _usage_limit_message(raw: str) -> str:
    """사용량 초과는 '언제 풀리는지'가 핵심이라 그 부분만 살려서 전한다."""
    match = re.search(r'try again at\s+([^().]+)', raw, re.IGNORECASE)
    when = match.group(1).strip().rstrip(',') if match else ''
    if when:
        return f'ChatGPT 사용량을 모두 썼어요. {when} 이후에 다시 시도할 수 있어요.'
    return 'ChatGPT 사용량을 모두 썼어요. 한도가 초기화된 뒤 다시 시도해 주세요.'


def _public_error(status: int, raw: Optional[str]) -> tuple:
    """Runner 내부 정보(경로·스택)가 사용자에게 새지 않도록 메시지를 정제합니다.

    (사용자 문구, 종류)를 돌려줍니다. 사용량 초과는 러너가 500으로 주기도 해서
    상태 코드보다 본문을 먼저 본다 — 아니면 '요청을 완료하지 못했습니다'로 뭉개진다.
    """
    message = (raw or '').strip()
    lowered = message.lower()
    if status == 429 or any(hint in lowered for hint in _USAGE_LIMIT_HINTS):
        return _usage_limit_message(message), USAGE_LIMIT_KIND
    if _BUSY_HINT in lowered:
        return ('앞의 요청을 아직 처리하고 있어요. 잠시 뒤에 다시 시도해 주세요.', BUSY_KIND)
    if status == 401 or status >= 500:
        return 'Codex Runner에서 요청을 완료하지 못했습니다.', None
    if status == 409 and 'not connected' in lowered:
        return '먼저 ChatGPT 계정을 연결해 주세요.', None
    if not message or len(message) > 240:
        return 'Codex Runner 요청을 처리하지 못했습니다.', None
    if any(token in lowered for token in ('stderr', 'stack', '/data/sessions', 'codex_home')):
        return 'Codex Runner 요청을 처리하지 못했습니다.', None
    return message, None


def _runner_fetch(instance_id: str, pathname: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = _config()
    if not settings:
        raise CodexRunnerError('AI Runner가 아직 설정되지 않았습니다.', 503)

    payload = dict(body or {})
    payload['sessionId'] = runner_session_id(instance_id)
    try:
        response = requests.post(
            f"{settings['url']}{pathname}",
            json=payload,
            headers={
                'Authorization': f"Bearer {settings['secret']}",
                'Content-Type': 'application/json',
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        logger.warning('[CODEX] timeout %s (%.0fs)', pathname, REQUEST_TIMEOUT_SECONDS)
        raise CodexRunnerError('AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.', 504)
    except requests.RequestException as exc:
        logger.warning('[CODEX] connect failed %s: %s', pathname, exc)
        raise CodexRunnerError('Codex Runner에 연결할 수 없습니다.', 503)

    try:
        result = response.json()
    except ValueError:
        result = {}
    if not isinstance(result, dict):
        result = {}

    if not response.ok:
        # 사용자에게 가는 문구는 뭉뚱그리므로, 원인을 찾으려면 서버 로그에 남겨야 한다.
        logger.warning('[CODEX] %s -> HTTP %s: %s',
                       pathname, response.status_code,
                       str(result.get('error') or response.text or '')[:500])
        public, kind = _public_error(response.status_code, result.get('error') or response.text)
        # 사용량 초과는 러너가 500으로 주더라도 429로 정정해 내려보낸다.
        if kind == USAGE_LIMIT_KIND:
            status = 429
        elif kind == BUSY_KIND:
            # 고장이 아니라 겹친 것이다. 잠시 뒤 같은 요청을 다시 보내면 된다.
            status = 409
        else:
            # Runner의 401은 우리 쪽 시크릿 문제이므로 사용자에게는 502로 알린다.
            status = 502 if response.status_code == 401 else (
                503 if response.status_code >= 500 else response.status_code
            )
        raise CodexRunnerError(public, status, kind)
    return result


def get_status(instance_id: str) -> Dict[str, Any]:
    """현재 Runner 세션의 ChatGPT 연결 상태를 조회합니다."""
    raw = _runner_fetch(instance_id, '/v1/session/status')
    status = raw.get('status')
    if status not in (STATUS_CONNECTED, STATUS_DISCONNECTED, STATUS_PENDING, STATUS_ERROR):
        raise CodexRunnerError('Codex Runner가 알 수 없는 상태를 반환했습니다.', 502)

    account_email = raw.get('accountEmail')
    account_hash = (
        hash_account_identity(account_email)
        if status == STATUS_CONNECTED and isinstance(account_email, str)
        else None
    )
    return {
        'status': status,
        'account_hash': account_hash,
        # 계정 프로비저닝 전용. 브라우저 응답에 절대 싣지 않는다(_connection_payload 참고).
        'account_email': account_email if isinstance(account_email, str) else None,
        'plan_type': raw.get('planType'),
        'rate_limit': raw.get('rateLimit'),
        'error': (
            'ChatGPT 로그인을 완료하지 못했습니다. 새 코드를 발급해 다시 시도해 주세요.'
            if status == STATUS_ERROR else None
        ),
    }


def start_device_login(instance_id: str) -> Dict[str, str]:
    """기기 코드 로그인을 시작하고 인증 URL과 사용자 코드를 반환합니다."""
    raw = _runner_fetch(instance_id, '/v1/session/login/device')
    login_id = raw.get('loginId')
    verification_url = raw.get('verificationUrl')
    user_code = raw.get('userCode')
    if not login_id or not verification_url or not user_code:
        raise CodexRunnerError('Codex가 로그인 코드를 발급하지 못했습니다.', 502)
    return {
        'login_id': login_id,
        'verification_url': verification_url,
        'user_code': user_code,
    }


def logout(instance_id: str) -> None:
    """Runner 세션의 ChatGPT 로그인을 해제합니다."""
    _runner_fetch(instance_id, '/v1/session/logout')


def list_models(instance_id: str) -> List[Dict[str, Any]]:
    """연결된 계정에서 쓸 수 있는 Codex 모델 목록을 반환합니다."""
    raw = _runner_fetch(instance_id, '/v1/session/models')
    models = raw.get('models')
    if not isinstance(models, list):
        return []
    return [
        {
            'id': model.get('id'),
            'display_name': model.get('displayName'),
            'is_default': bool(model.get('isDefault')),
        }
        for model in models
        if isinstance(model, dict) and model.get('id')
    ]


def choose_model(models: List[Dict[str, Any]], preferred: Optional[str] = None) -> Optional[str]:
    """선호 모델이 사용 가능하면 그것을, 아니면 기본 모델을 고릅니다."""
    ids = [model['id'] for model in models]
    if preferred and preferred in ids:
        return preferred
    for model in models:
        if model.get('is_default'):
            return model['id']
    return ids[0] if ids else None


def run(
    instance_id: str,
    prompt: str,
    output_schema: Dict[str, Any],
    model: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Codex에 한 턴을 실행시키고 구조화된 결과를 받습니다."""
    if not model:
        model = choose_model(list_models(instance_id))
    if not model:
        raise CodexRunnerError('현재 계정에서 사용할 수 있는 Codex 모델을 찾지 못했습니다.', 409)

    raw = _runner_fetch(instance_id, '/v1/session/run', {
        'model': model,
        'threadId': thread_id,
        'prompt': prompt,
        'outputSchema': output_schema,
    })
    if not raw.get('text') or not raw.get('threadId'):
        raise CodexRunnerError('Codex가 응답을 완성하지 못했습니다.', 502)
    return {
        'thread_id': raw['threadId'],
        'text': raw['text'],
        'model': raw.get('model') or model,
    }
