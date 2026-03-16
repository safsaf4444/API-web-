from __future__ import annotations

import logging
import os

logger = logging.getLogger("uvicorn")


def _send_resend(to: str, subject: str, html_body: str) -> bool:
    from backend.core.config import settings

    # Get the API key directly from the environment
    api_key = os.getenv("RESEND_API_KEY", "")
    
    # Use the verified domain from your config (e.g., verify@serenresearch.com)
    mail_from = settings.mail_from 

    if not api_key:
        logger.warning("⚠️ RESEND_API_KEY not set — skipping email send")
        return False

    try:
        import resend
        resend.api_key = api_key
        
        # Trigger the email send
        response = resend.Emails.send({
            "from": mail_from,
            "to": to,
            "subject": subject,
            "html": html_body,
        })
        
        logger.info(f"✅ Email sent successfully to {to}: {subject}")
        return True
        
    except Exception as e:
        logger.error(f"💥 Resend email failed to {to}. Error: {str(e)}")
        return False


def send_verification_email(to_email: str, username: str, token: str) -> bool:
    from backend.core.config import settings
    
    verify_url = f"{settings.frontend_url}/login.html?token={token}&mode=verify"
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
            Hi {username}, click below to verify your email and activate your Seren account.
        </p>
        <a href="{verify_url}"
           style="display: inline-block; background: #1e3a5f; color: white; padding: 12px 28px;
                  text-decoration: none; border-radius: 4px; font-weight: 500; margin-bottom: 24px;">
            Verify Email
        </a>
        <p style="color: #718096; font-size: 13px; margin-top: 24px;">
            This link expires in 24 hours. If you didn't create a Seren account, ignore this email.
        </p>
    </body>
    </html>
    """
    return _send_resend(to_email, subject, html)


def send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    from backend.core.config import settings
    
    reset_url = f"{settings.frontend_url}/login.html?token={token}&mode=reset"
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
            If you didn't request this, ignore this email.
        </p>
    </body>
    </html>
    """
    return _send_resend(to_email, subject, html)