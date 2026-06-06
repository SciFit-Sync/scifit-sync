"""이메일 발송 서비스 (Gmail SMTP + aiosmtplib).

환경 변수:
    SMTP_USER      - 발신 Gmail 주소 (예: yourapp@gmail.com)
    SMTP_PASSWORD  - Gmail 앱 비밀번호 16자리
    ENV            - development 이면 실제 발송 대신 로그만 출력

발급 방법:
    1. Google 계정 → 보안 → 2단계 인증 활성화
    2. 보안 → 앱 비밀번호 → "메일 / 기타" → 16자리 복사 후 SMTP_PASSWORD에 입력
"""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def send_otp_email(to_email: str, otp_code: str) -> None:
    """OTP 인증번호를 이메일로 발송한다.

    개발 환경(ENV=development) 또는 SMTP_USER 미설정 시 로그만 출력하고 건너뜀.
    """
    settings = get_settings()

    # 개발 환경 또는 SMTP 미설정 → 로그로만 출력
    if settings.ENV == "development" or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.info("[DEV] OTP email skipped (no SMTP config). email=%s", to_email)
        return

    subject = "[SciFit-Sync] 이메일 인증번호"
    html_body = _build_otp_html(otp_code)
    text_body = f"SciFit-Sync 인증번호: {otp_code}\n\n이 코드는 10분간 유효합니다."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info("OTP email sent to %s", to_email)
    except Exception as exc:
        # 발송 실패해도 회원가입 자체는 막지 않음 — 재발송 API 따로 있음
        logger.error("Failed to send OTP email to %s: %s", to_email, exc)
        raise


def _build_otp_html(otp_code: str) -> str:
    """OTP 인증 이메일 HTML 템플릿."""
    digits = "".join(
        f'<span style="display:inline-block;width:44px;height:52px;line-height:52px;'
        f"text-align:center;font-size:28px;font-weight:700;border:2px solid #000;"
        f'border-radius:8px;margin:0 4px;color:#000;">{d}</span>'
        for d in otp_code
    )
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'Apple SD Gothic Neo',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,.08);">
        <tr><td align="center" style="padding-bottom:24px;">
          <span style="font-size:22px;font-weight:800;color:#000;">SciFit-Sync</span>
        </td></tr>
        <tr><td align="center" style="padding-bottom:8px;">
          <p style="margin:0;font-size:18px;font-weight:700;color:#000;">이메일 인증번호</p>
        </td></tr>
        <tr><td align="center" style="padding-bottom:20px;">
          <p style="margin:0;font-size:14px;color:#666;line-height:1.6;">
            아래 6자리 인증번호를 앱에 입력해주세요.<br>
            이 코드는 <strong>10분간</strong> 유효합니다.
          </p>
        </td></tr>
        <tr><td align="center" style="padding:24px 0;">
          {digits}
        </td></tr>
        <tr><td align="center" style="padding-top:24px;border-top:1px solid #eee;">
          <p style="margin:0;font-size:12px;color:#999;">
            본인이 요청하지 않았다면 이 메일을 무시해주세요.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
