from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.core.config import settings

logger = logging.getLogger("uvicorn")


def _send_smtp(to: str, subject: str, html_body: str) -> bool:
    """Send email via SMTP. Returns True on success, False on failure."""
    if not settings.mail_enabled:
        logger.info(f"[EMAIL DISABLED] Would send to {to}: {subject}")
        return True

    if not settings.mail_username or not settings.mail_password:
        logger.warning("Email not configured — skipping send. Set MAIL_USERNAME and MAIL_PASSWORD.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.mail_server, settings.mail_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.mail_username, settings.mail_password)
            server.sendmail(settings.mail_from, to, msg.as_string())
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email send failed to {to}: {e}")
        return False


def send_verification_email(to_email: str, username: str, token: str) -> bool:
    verify_url = f"{settings.frontend_url}/verify-email.html?token={token}"
    subject = "Verify your Seren account"
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 40px 20px; color: #1a1a2e;">
        <div style="margin-bottom: 32px;">
            <span style="font-size: 24px; font-weight: 700; color: #1e3a5f;">SEREN</span>
        </div>
        <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 16px;">Verify your email address</h2>
        <p style="color: #4a5568; line-height: 1.6; margin-bottom: 24px;">
            Hi {username}, click the button below to verify your email and activate your Seren account.
        </p>
        <a href="{verify_url}"
           style="display: inline-block; background: #1e3a5f; color: white; padding: 12px 28px;
                  text-decoration: none; border-radius: 4px; font-weight: 500; margin-bottom: 24px;">
            Verify Email
        </a>
        <p style="color: #718096; font-size: 13px; margin-top: 24px;">
            This link expires in 24 hours. If you didn't create a Seren account, ignore this email.
        </p>
        <p style="color: #718096; font-size: 12px; margin-top: 8px;">
            Or paste this URL: {verify_url}
        </p>
    </body>
    </html>
    """
    return _send_smtp(to_email, subject, html)


def send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    reset_url = f"{settings.frontend_url}/reset-password.html?token={token}"
    subject = "Reset your Seren password"
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 40px 20px; color: #1a1a2e;">
        <div style="margin-bottom: 32px;">
            <span style="font-size: 24px; font-weight: 700; color: #1e3a5f;">SEREN</span>
        </div>
        <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 16px;">Reset your password</h2>
        <p style="color: #4a5568; line-height: 1.6; margin-bottom: 24px;">
            Hi {username}, click below to set a new password. This link expires in 1 hour.
        </p>
        <a href="{reset_url}"
           style="display: inline-block; background: #1e3a5f; color: white; padding: 12px 28px;
                  text-decoration: none; border-radius: 4px; font-weight: 500; margin-bottom: 24px;">
            Reset Password
        </a>
        <p style="color: #718096; font-size: 13px; margin-top: 24px;">
            If you didn't request this, ignore this email. Your password won't change.
        </p>
        <p style="color: #718096; font-size: 12px; margin-top: 8px;">
            Or paste this URL: {reset_url}
        </p>
    </body>
    </html>
    """
    return _send_smtp(to_email, subject, html)