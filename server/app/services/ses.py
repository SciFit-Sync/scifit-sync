import asyncio
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_OTP_SUBJECT = "[SciFit-Sync] 이메일 인증 코드"

_OTP_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<body style="font-family: sans-serif; background:#f7f7f7; padding:40px 0;">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:8px;padding:32px;">
    <h2 style="margin-top:0;">SciFit-Sync 이메일 인증</h2>
    <p>아래 인증 코드를 앱에 입력해주세요.</p>
    <div style="font-size:36px;font-weight:bold;letter-spacing:8px;
                text-align:center;padding:24px;background:#f0f0f0;border-radius:6px;">
      {otp_code}
    </div>
    <p style="color:#888;font-size:13px;margin-top:24px;">
      이 코드는 <strong>10분</strong> 후 만료됩니다.<br>
      본인이 요청하지 않은 경우 무시하세요.
    </p>
  </div>
</body>
</html>
"""

_OTP_TEXT = "SciFit-Sync 인증 코드: {otp_code} (10분 후 만료)"


def _build_ses_client():
    settings = get_settings()
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("ses", **kwargs)


def _send_otp_sync(to_email: str, otp_code: str) -> None:
    settings = get_settings()
    client = _build_ses_client()
    client.send_email(
        Source=settings.SES_FROM_EMAIL,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": _OTP_SUBJECT, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": _OTP_TEXT.format(otp_code=otp_code), "Charset": "UTF-8"},
                "Html": {"Data": _OTP_HTML.format(otp_code=otp_code), "Charset": "UTF-8"},
            },
        },
    )


async def send_otp_email(to_email: str, otp_code: str) -> None:
    """AWS SES로 OTP 이메일 발송. SES_FROM_EMAIL 미설정 시 로그로 대체."""
    settings = get_settings()

    if not settings.SES_FROM_EMAIL:
        logger.info("[개발] OTP for %s: %s (SES_FROM_EMAIL 미설정)", to_email, otp_code)
        return

    try:
        await asyncio.to_thread(_send_otp_sync, to_email, otp_code)
        logger.info("OTP 이메일 발송 완료: %s", to_email)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        logger.error("SES ClientError (%s) → %s: %s", code, to_email, e)
        raise
    except BotoCoreError as e:
        logger.error("SES BotoCoreError → %s: %s", to_email, e)
        raise
