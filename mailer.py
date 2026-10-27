"""
Medicare SMTP Email Delivery Service
Handles secure, authenticated dispatch of short-lived verification codes.
Reads credentials strictly from environment variables.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def get_smtp_config():
    """Retrieve SMTP configuration from environment variables."""
    return {
        "server": os.environ.get("SMTP_SERVER", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", 587)),
        "username": os.environ.get("SMTP_USERNAME", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"),
        "sender": os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get("SMTP_SENDER") or "no-reply@medicare.io",
        "dev_mode": os.environ.get("SMTP_DEV_MODE", "false").lower() in ("true", "1", "yes")
    }


def send_verification_email(recipient_email, code, purpose_label, recipient_name="Medical Professional"):
    """
    Send a secure short-lived verification code to the registered email address.
    Returns (success: bool, message: str).
    """
    cfg = get_smtp_config()

    # Friendly purpose text
    if "doctor" in purpose_label.lower():
        role_label = "Doctor Portal Authentication"
    elif "authority" in purpose_label.lower():
        role_label = "Authority Portal Authentication"
    else:
        role_label = "Secure Access Verification"

    subject = f"Medicare Security: Your {role_label} Code is {code}"

    # Plain text version
    text_content = f"""Hello {recipient_name},

Your one-time access verification code for the Medicare {role_label} is:

{code}

This code is valid for 10 minutes and can only be used once.
If you did not attempt to sign in to the Medicare Portal, please notify the system administrator immediately.

Best regards,
Medicare Application Security Team
"""

    # HTML formatted email
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f6fbfb; margin: 0; padding: 20px; }}
  .email-container {{ max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #ddecfa; padding: 32px 28px; box-shadow: 0 4px 14px rgba(0,0,0,0.04); }}
  .header {{ text-align: center; border-bottom: 1px solid #eef4f9; padding-bottom: 20px; margin-bottom: 24px; }}
  .logo {{ font-size: 24px; font-weight: bold; color: #155985; text-decoration: none; }}
  .badge {{ display: inline-block; background: #eaf6ff; color: #155985; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 12px; margin-top: 8px; text-transform: uppercase; }}
  .content {{ color: #2c445a; font-size: 15px; line-height: 1.6; }}
  .code-box {{ background: #f0f7fd; border: 2px dashed #9bc9eb; border-radius: 12px; text-align: center; padding: 20px; margin: 24px 0; }}
  .code {{ font-family: 'Courier New', monospace; font-size: 34px; font-weight: bold; letter-spacing: 6px; color: #0f4c75; }}
  .timer-notice {{ color: #7f95a8; font-size: 13px; margin-top: 8px; }}
  .security-alert {{ background: #fff8e6; border-left: 4px solid #f59e0b; padding: 12px 14px; font-size: 13px; color: #7c4a03; border-radius: 0 8px 8px 0; margin-top: 20px; }}
  .footer {{ text-align: center; color: #8fa4b5; font-size: 12px; margin-top: 28px; border-top: 1px solid #eef4f9; padding-top: 16px; }}
</style>
</head>
<body>
  <div class="email-container">
    <div class="header">
      <div class="logo">🏥 Medicare Healthcare</div>
      <div class="badge">{role_label}</div>
    </div>
    <div class="content">
      <p>Hello <strong>{recipient_name}</strong>,</p>
      <p>A sign-in attempt was initiated for your registered account. Please use the system-generated access verification code below to complete your authentication:</p>
      
      <div class="code-box">
        <div class="code">{code}</div>
        <div class="timer-notice">⏱ Valid for 10 minutes • Single-use only</div>
      </div>

      <div class="security-alert">
        <strong>🔒 Security Notice:</strong> Medicare personnel will never ask for this code. Do not share it with anyone.
      </div>
    </div>
    <div class="footer">
      This is an automated security transmission. Responses to this email are not monitored.
    </div>
  </div>
</body>
</html>"""

    # Check if in testing or development mode with missing credentials
    if not cfg["server"] or not cfg["username"] or not cfg["password"]:
        if cfg["dev_mode"] or os.environ.get("TESTING") == "true" or os.environ.get("FLASK_ENV") != "production":
            return True, "Code generated (mock delivery for testing/dev mode)."
        
        return False, "SMTP email service is not configured. Please configure SMTP_SERVER, SMTP_USERNAME, and SMTP_PASSWORD in Render environment variables."

    # Dispatch via SMTP
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = recipient_email

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        if cfg["port"] == 465:
            server = smtplib.SMTP_SSL(cfg["server"], cfg["port"], timeout=10)
        else:
            server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=10)
            if cfg["use_tls"]:
                server.starttls()

        server.login(cfg["username"], cfg["password"])
        server.sendmail(cfg["sender"], [recipient_email], msg.as_string())
        server.quit()
        return True, "Verification code sent to registered email address."
    except Exception as e:
        print(f"[!] SMTP Error delivering code to {recipient_email}: {type(e).__name__}: {e}")
        return False, f"Failed to send email: {type(e).__name__}. Please verify SMTP credentials."
