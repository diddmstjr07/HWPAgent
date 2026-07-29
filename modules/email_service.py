"""서비스 알림 이메일 발송 유틸리티."""
from email.message import EmailMessage
from email.utils import formataddr
import html
import os
import smtplib
import ssl


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def email_delivery_configured() -> bool:
    return bool(
        os.getenv('SMTP_HOST')
        and os.getenv('SMTP_USERNAME')
        and os.getenv('SMTP_PASSWORD')
        and (os.getenv('SMTP_FROM_EMAIL') or os.getenv('SMTP_USERNAME'))
    )


def build_student_number_update_message(
    *,
    recipient_email: str,
    recipient_name: str,
    academic_year: int,
    current_grade: int,
    update_url: str,
) -> EmailMessage:
    """학번 갱신 요청 이메일을 생성합니다."""
    sender_email = os.getenv('SMTP_FROM_EMAIL') or os.getenv('SMTP_USERNAME') or ''
    sender_name = os.getenv('SMTP_FROM_NAME', 'DOC Agent')
    safe_name = html.escape(recipient_name or '학생')
    safe_url = html.escape(update_url, quote=True)

    message = EmailMessage()
    message['Subject'] = f'[{academic_year}학년도] {current_grade}학년 학번을 업데이트해 주세요'
    message['From'] = formataddr((sender_name, sender_email))
    message['To'] = recipient_email
    message.set_content(
        f"{recipient_name or '학생'}님, 새 학년이 시작되었습니다.\n\n"
        f"현재 {current_grade}학년으로 자동 반영되었습니다. "
        "반과 번호가 바뀌었을 수 있으니 아래 링크에서 새 학번 4자리를 입력해 주세요.\n\n"
        f"{update_url}\n\n"
        f"학번 형식 예시: {current_grade}412 = {current_grade}학년 4반 12번\n"
    )
    message.add_alternative(
        f'''<!doctype html>
<html lang="ko">
  <body style="margin:0;background:#f6f7f9;font-family:Arial,'Noto Sans KR',sans-serif;color:#172033;">
    <div style="max-width:560px;margin:0 auto;padding:32px 18px;">
      <div style="background:#fff;border:1px solid #e3e7ee;border-radius:16px;padding:28px;">
        <p style="margin:0 0 8px;color:#6b778c;font-size:13px;">DOC Agent · {academic_year}학년도</p>
        <h1 style="margin:0 0 18px;font-size:22px;line-height:1.35;">새 학번을 알려주세요</h1>
        <p style="margin:0 0 12px;font-size:15px;line-height:1.7;">{safe_name}님, 현재 학년이 <strong>{current_grade}학년</strong>으로 자동 반영되었습니다.</p>
        <p style="margin:0 0 22px;font-size:15px;line-height:1.7;">반과 번호가 바뀌었을 수 있으니 새 학번 4자리를 입력해 주세요. 예: <strong>{current_grade}412 = {current_grade}학년 4반 12번</strong></p>
        <a href="{safe_url}" style="display:inline-block;padding:12px 18px;background:#172033;color:#fff;text-decoration:none;border-radius:9px;font-weight:700;">학번 업데이트</a>
        <p style="margin:22px 0 0;color:#7c879a;font-size:12px;line-height:1.6;">본인이 요청하지 않은 메일이라면 이 메시지를 무시해 주세요.</p>
      </div>
    </div>
  </body>
</html>''',
        subtype='html',
    )
    return message


def send_email(message: EmailMessage) -> None:
    """SMTP 환경변수 설정을 사용해 이메일을 전송합니다."""
    if not email_delivery_configured():
        raise RuntimeError('SMTP 환경변수가 설정되지 않았습니다.')

    host = os.environ['SMTP_HOST']
    port = int(os.getenv('SMTP_PORT', '465' if _env_flag('SMTP_USE_SSL') else '587'))
    username = os.environ['SMTP_USERNAME']
    password = os.environ['SMTP_PASSWORD']
    context = ssl.create_default_context()

    if _env_flag('SMTP_USE_SSL'):
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as client:
            client.login(username, password)
            client.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=20) as client:
        client.ehlo()
        if _env_flag('SMTP_USE_TLS', True):
            client.starttls(context=context)
            client.ehlo()
        client.login(username, password)
        client.send_message(message)
