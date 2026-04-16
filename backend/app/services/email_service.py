"""Email service — send verification codes via SMTP (QQ/163 mail)."""
from __future__ import annotations

import asyncio
import secrets
import smtplib
import ssl
import string
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import redis.asyncio as aioredis

from app.config import get_settings


def _generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


async def send_verification_code(redis: aioredis.Redis, email: str) -> dict:
    """Generate a 6-digit code, store in Redis, send via SMTP."""
    settings = get_settings()

    if not settings.smtp_host or not settings.smtp_user:
        return {"ok": False, "error": "邮件服务未配置"}

    # Rate limit: 1 code per email per 60 seconds
    rate_key = f"email_rate:{email}"
    if await redis.exists(rate_key):
        return {"ok": False, "error": "发送太频繁，请60秒后重试"}

    code = _generate_code()
    ttl = settings.email_code_expire_minutes * 60

    # Store code in Redis
    code_key = f"email_code:{email}"
    await redis.setex(code_key, ttl, code)
    await redis.setex(rate_key, 60, "1")  # 60s rate limit

    # Send email in thread pool to avoid blocking the event loop
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send_smtp, settings, email, code)
    except Exception as e:
        return {"ok": False, "error": f"邮件发送失败: {str(e)[:100]}"}

    return {"ok": True, "expire_minutes": settings.email_code_expire_minutes}


async def verify_code(redis: aioredis.Redis, email: str, code: str) -> bool:
    """Check if the code matches what's stored in Redis."""
    code_key = f"email_code:{email}"
    stored = await redis.get(code_key)
    if not stored:
        return False
    stored_str = stored.decode() if isinstance(stored, bytes) else stored
    if stored_str != code.strip():
        return False
    # Code is valid — delete it so it can't be reused
    await redis.delete(code_key)
    return True


def _send_smtp(settings, to_email: str, code: str) -> None:
    """Send verification email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    msg["To"] = to_email
    msg["Subject"] = f"【ProfitLens】注册验证码: {code}"

    html = f"""
    <div style="max-width:480px;margin:0 auto;font-family:-apple-system,sans-serif;">
      <div style="background:#409eff;color:#fff;padding:20px 30px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">ProfitLens ERP</h2>
      </div>
      <div style="background:#fff;padding:30px;border:1px solid #e4e7ed;border-top:none;border-radius:0 0 8px 8px;">
        <p>您好，您的注册验证码是：</p>
        <div style="text-align:center;margin:24px 0;">
          <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#409eff;
                       background:#f0f7ff;padding:12px 32px;border-radius:8px;display:inline-block;">
            {code}
          </span>
        </div>
        <p style="color:#909399;font-size:13px;">
          验证码 {settings.email_code_expire_minutes} 分钟内有效，请勿泄露给他人。<br>
          如非本人操作，请忽略此邮件。
        </p>
      </div>
    </div>
    """

    msg.attach(MIMEText(html, "html", "utf-8"))

    if settings.smtp_use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=10) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, to_email, msg.as_string())
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, to_email, msg.as_string())
