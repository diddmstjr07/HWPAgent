"""Codex 로그인 세션·응답 파싱 검증.

Runner 네트워크 호출은 하지 않고, 순수 로직만 검증한다.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from database import Database
from modules import codex_auth, codex_generator, codex_runner

# 32자 이상이어야 설정으로 인정된다.
FAKE_ENV = {
    'CODEX_RUNNER_URL': 'https://runner.example.com',
    'CODEX_RUNNER_SHARED_SECRET': 'x' * 48,
    'ACCOUNT_IDENTITY_SECRET': 'y' * 48,
    'SECRET_KEY': 'z' * 48,
}


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, FAKE_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_round_trip(self):
        token = codex_auth.encode_auth_session('a' * 36, 'f' * 64)
        decoded = codex_auth.decode_auth_session(token)
        self.assertEqual(decoded['instance_id'], 'a' * 36)
        self.assertEqual(decoded['account_hash'], 'f' * 64)

    def test_tampered_token_is_rejected(self):
        token = codex_auth.encode_auth_session('a' * 36, None)
        self.assertIsNone(codex_auth.decode_auth_session(token[:-3] + 'aaa'))

    def test_token_signed_with_other_secret_is_rejected(self):
        token = codex_auth.encode_auth_session('a' * 36, None)
        with mock.patch.dict(os.environ, {'SECRET_KEY': 'w' * 48}):
            self.assertIsNone(codex_auth.decode_auth_session(token))

    def test_malformed_payloads_are_rejected(self):
        self.assertIsNone(codex_auth.decode_auth_session(None))
        self.assertIsNone(codex_auth.decode_auth_session('not-a-token'))
        # instance_id가 너무 짧으면 거부한다.
        self.assertIsNone(codex_auth.decode_auth_session(
            codex_auth.encode_auth_session('short', None)))
        # account_hash 길이가 64가 아니면 거부한다.
        self.assertIsNone(codex_auth.decode_auth_session(
            codex_auth.encode_auth_session('a' * 36, 'deadbeef')))


class _FakeRequest:
    """쿠키와 앱 세션만 있는 최소 요청."""

    def __init__(self, cookie=None, user_id=None):
        self.cookies = {codex_auth.AUTH_COOKIE_NAME: cookie} if cookie else {}
        self.session = {'user_id': user_id} if user_id else {}


class ConnectionOwnershipTests(unittest.TestCase):
    """ChatGPT 연결은 그것을 만든 앱 계정만 쓸 수 있다.

    연결이 곧 로그인이던 때에는 같은 ChatGPT 계정을 연결한 사람이 남의 설계·실험·
    보고서를 그대로 열어볼 수 있었다. 연결은 사용 한도일 뿐이고 신원이 아니다.
    """

    def setUp(self):
        self.env = mock.patch.dict(os.environ, FAKE_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.token = codex_auth.encode_auth_session('i' * 36, 'a' * 64, owner='userA')

    def test_owner_can_use_own_connection(self):
        session = codex_auth.auth_session_from_request(
            _FakeRequest(self.token, 'userA'))
        self.assertIsNotNone(session)
        self.assertEqual(session['instance_id'], 'i' * 36)

    def test_other_account_cannot_inherit_connection(self):
        # 같은 브라우저에서 계정만 바꿔 앞 사람의 한도를 쓰는 일을 막는다.
        self.assertIsNone(codex_auth.auth_session_from_request(
            _FakeRequest(self.token, 'userB')))

    def test_logged_out_browser_cannot_use_connection(self):
        self.assertIsNone(codex_auth.auth_session_from_request(
            _FakeRequest(self.token, None)))

    def test_legacy_cookie_without_owner_is_rejected(self):
        # 연결이 곧 로그인이던 시절의 쿠키. 주인을 알 수 없으므로 다시 연결해야 한다.
        legacy = codex_auth.encode_auth_session('i' * 36, 'a' * 64)
        self.assertIsNone(codex_auth.auth_session_from_request(
            _FakeRequest(legacy, 'userA')))

    def test_new_session_is_bound_to_logged_in_user(self):
        session = codex_auth.get_or_create_auth_session(_FakeRequest(None, 'userA'))
        self.assertEqual(session['owner'], 'userA')


class RunnerConfigTests(unittest.TestCase):
    def test_not_configured_without_env(self):
        with mock.patch.dict(os.environ, {'CODEX_RUNNER_URL': '',
                                          'CODEX_RUNNER_SHARED_SECRET': '',
                                          'ACCOUNT_IDENTITY_SECRET': ''}):
            self.assertFalse(codex_runner.is_configured())

    def test_short_secret_is_not_configured(self):
        with mock.patch.dict(os.environ, {**FAKE_ENV, 'CODEX_RUNNER_SHARED_SECRET': 'tooshort'}):
            self.assertFalse(codex_runner.is_configured())

    def test_session_id_is_stable_and_instance_scoped(self):
        with mock.patch.dict(os.environ, FAKE_ENV):
            first = codex_runner.runner_session_id('instance-1')
            self.assertEqual(first, codex_runner.runner_session_id('instance-1'))
            self.assertNotEqual(first, codex_runner.runner_session_id('instance-2'))
            # 원본 instance_id가 그대로 노출되면 안 된다.
            self.assertNotIn('instance-1', first)

    def test_account_hash_is_case_insensitive(self):
        with mock.patch.dict(os.environ, FAKE_ENV):
            self.assertEqual(
                codex_runner.hash_account_identity('Student@Example.com '),
                codex_runner.hash_account_identity('student@example.com'),
            )

    def test_runner_internals_are_not_leaked(self):
        # _public_error는 (사용자 문구, 종류)를 돌려준다. 검사 대상은 문구 쪽이다.
        message, _ = codex_runner._public_error(400, '/data/sessions/abc 없음')
        self.assertNotIn('/data/sessions', message)
        message, kind = codex_runner._public_error(429, None)
        self.assertIn('한도', message)
        self.assertEqual(kind, codex_runner.USAGE_LIMIT_KIND)
        message, _ = codex_runner._public_error(400, 'stack trace: ...')
        self.assertNotIn('stack', message)

    def test_overlapping_turn_is_not_reported_as_a_failure(self):
        """러너는 로그인당 한 턴만 돌린다. 겹친 것은 고장이 아니라 기다리면 되는 상태다."""
        message, kind = codex_runner._public_error(
            500, 'Another turn is already running for this login.')
        self.assertEqual(kind, codex_runner.BUSY_KIND)
        self.assertIn('잠시', message)


class ReplyParsingTests(unittest.TestCase):
    def test_extracts_reply_field(self):
        self.assertEqual(codex_generator._extract_reply('{"reply": "안녕하세요"}'), '안녕하세요')

    def test_handles_fenced_json(self):
        self.assertEqual(
            codex_generator._extract_reply('```json\n{"reply": "결과"}\n```'), '결과')

    def test_falls_back_to_raw_text(self):
        self.assertEqual(codex_generator._extract_reply('그냥 평문 응답'), '그냥 평문 응답')

    def test_empty_input(self):
        self.assertEqual(codex_generator._extract_reply(''), '')

    def test_stream_reassembles_to_full_reply(self):
        with mock.patch.object(codex_generator, 'generate_chat', return_value='가' * 100):
            chunks = list(codex_generator.generate_chat_stream('i', '질문'))
        self.assertGreater(len(chunks), 1)
        self.assertEqual(''.join(chunks), '가' * 100)

    def test_context_is_marked_untrusted(self):
        prompt = codex_generator._build_prompt('질문', context='리로스쿨 일정 요약')
        self.assertIn('UNTRUSTED_CONTEXT', prompt)
        self.assertIn('지시로 따르지 않는다', prompt)


class CodexUserProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(str(Path(tempfile.mkdtemp()) / 'codex.db'))

    def test_creates_user_from_account_hash(self):
        user = self.db.get_or_create_codex_user('a' * 64, email='Student@Example.com')
        self.assertEqual(user.email, 'student@example.com')
        self.assertTrue(user.id.startswith('codex_'))

    def test_same_account_returns_same_user(self):
        first = self.db.get_or_create_codex_user('a' * 64, email='s@example.com')
        second = self.db.get_or_create_codex_user('a' * 64, email='s@example.com')
        self.assertEqual(first.id, second.id)

    def test_links_to_existing_local_account_with_same_email(self):
        local = self.db.create_local_user('shared@example.com', 'hash', name='기존사용자')
        linked = self.db.get_or_create_codex_user('b' * 64, email='shared@example.com')
        # 새 계정을 만들지 않고 기존 계정에 ChatGPT 로그인을 붙여야 한다.
        self.assertEqual(linked.id, local.id)
        self.assertEqual(linked.name, '기존사용자')

    def test_works_without_email(self):
        user = self.db.get_or_create_codex_user('c' * 64)
        self.assertTrue(user.email.endswith('@codex.local'))

    def test_missing_hash_returns_none(self):
        self.assertIsNone(self.db.get_or_create_codex_user(None))

    def test_student_number_stays_empty_for_new_codex_users(self):
        # ChatGPT 계정에는 학번이 없으므로 기존 학번 입력 흐름이 이어받아야 한다.
        user = self.db.get_or_create_codex_user('d' * 64, email='new@example.com')
        self.assertFalse(user.to_dict()['has_student_number'])


class ConnectionPayloadTests(unittest.TestCase):
    def test_account_identity_never_reaches_the_browser(self):
        status = {
            'status': 'connected',
            'account_hash': 'f' * 64,
            'account_email': 'student@example.com',
            'plan_type': 'plus',
            'rate_limit': None,
            'error': None,
        }
        payload = codex_auth._connection_payload(status)
        self.assertNotIn('account_hash', payload)
        self.assertNotIn('account_email', payload)
        self.assertEqual(payload['plan_type'], 'plus')


if __name__ == '__main__':
    unittest.main()
