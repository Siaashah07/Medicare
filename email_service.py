import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

def get_smtp_config():
    """Retrieve SMTP configuration from environment variables with safe fallbacks."""
    host = os.environ.get("SMTP_HOST") or os.environ.get("MAIL_SERVER") or ""
    port_str = os.environ.get("SMTP_PORT") or os.environ.get("MAIL_PORT") or "587"
    try:
        port = int(port_str)
    except ValueError:
        port = 587
    user = os.environ.get("SMTP_USER") or os.environ.get("MAIL_USERNAME") or ""
    password = os.environ.get("SMTP_PASSWORD") or os.environ.get("MAIL_PASSWORD") or ""
    use_tls = os.environ.get("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")
    from_email = os.environ.get("SMTP_FROM_EMAIL") or os.environ.get("MAIL_DEFAULT_SENDER") or user or "noreply@medicare.io"

    return {
        "host": host.strip(),
        "port": port,
        "user": user.strip(),
        "password": password.strip(),
        "use_tls": use_tls,
        "from_email": from_email.strip()
    }

def is_smtp_configured():
    """Check if SMTP credentials are configured in the environment."""
    cfg = get_smtp_config()
    return bool(cfg["host"] and cfg["user"] and cfg["password"])

def send_access_code_email(recipient_email, recipient_name, access_code, purpose="Doctor Portal Login", expires_in_minutes=10):
    """
    Send a secure short-lived access or verification code to a registered user.
    Never exposes passwords or sensitive account data.
    Returns (success: bool, message: str).
    """
    if not recipient_email or "@" not in recipient_email:
        return False, "Invalid recipient email address."

    cfg = get_smtp_config()

    # Plaintext fallback body
    text_content = f"""Hello {recipient_name},

Your Medicare secure access code for {purpose} is:

    {access_code}

This code is valid for {expires_in_minutes} minutes and can only be used once.
If you did not request this code, please immediately notify your hospital security officer.

Best regards,
Medicare Healthcare Security Team
"""

    # Rich professional HTML template
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f8fb; margin: 0; padding: 20px; }}
  .email-container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.06); border: 1px solid #e2ecf4; }}
  .header {{ background: linear-gradient(135deg, #155985 0%, #0d3c5b 100%); padding: 30px 24px; text-align: center; color: white; }}
  .header h1 {{ margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px; }}
  .header p {{ margin: 6px 0 0; font-size: 13px; opacity: 0.9; text-transform: uppercase; letter-spacing: 1.5px; }}
  .content {{ padding: 32px 28px; color: #1e3a52; line-height: 1.6; font-size: 15px; }}
  .greeting {{ font-size: 17px; font-weight: 600; margin-bottom: 12px; color: #0f2d4a; }}
  .code-box {{ background: #f0f7fd; border: 2px dashed #155985; border-radius: 12px; padding: 22px; text-align: center; margin: 24px 0; }}
  .code-label {{ font-size: 12px; text-transform: uppercase; color: #5a738e; letter-spacing: 1px; font-weight: 600; margin-bottom: 8px; }}
  .code {{ font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #155985; font-family: 'Courier New', monospace; }}
  .expiration {{ font-size: 13px; color: #c62828; margin-top: 10px; font-weight: 600; }}
  .info-list {{ margin: 20px 0; padding-left: 20px; color: #50677d; font-size: 14px; }}
  .footer {{ background: #f8fafc; padding: 20px 28px; text-align: center; font-size: 12px; color: #8295a7; border-top: 1px solid #eef2f6; }}
</style>
</head>
<body>
  <div class="email-container">
    <div class="header">
      <h1>🏥 Medicare Security</h1>
      <p>Secure Identity Verification</p>
    </div>
    <div class="content">
      <div class="greeting">Hello {recipient_name},</div>
      <p>You have initiated a secure login request for the <strong>{purpose}</strong>. Please use the system-generated verification code below to complete your authentication:</p>
      
      <div class="code-box">
        <div class="code-label">One-Time Access Code</div>
        <div class="code">{access_code}</div>
        <div class="expiration">⏱️ Valid for {expires_in_minutes} minutes only (Single-Use)</div>
      </div>

      <p><strong>Security Guidelines:</strong></p>
      <ul class="info-list">
        <li>This code is confidential. Never share it with anyone, including hospital staff.</li>
        <li>Medicare staff will never ask for your password or verification code.</li>
        <li>If you did not initiate this request, someone may be attempting to access your account. Please notify the security team immediately.</li>
      </ul>
    </div>
    <div class="footer">
      This is an automated security transmission from Medicare Healthcare System.<br>
      © {datetime.now().year} Medicare Inc. All medical information protected by strict confidentiality policies.
    </div>
  </div>
</body>
</html>"""

    # If SMTP is not configured
    if not is_smtp_configured():
        env_status = "SMTP credentials (SMTP_HOST, SMTP_USER, SMTP_PASSWORD) are not configured."
        # Safe development simulation
        is_dev = os.environ.get("FLASK_ENV") == "development" or not os.environ.get("RENDER")
        if is_dev:
            print("\n" + "="*65)
            print("[MEDICARE EMAIL SERVICE - DEV SIMULATION]")
            print("Recipient:  %s (%s)" % (recipient_email, recipient_name))
            print("Purpose:    %s" % purpose)
            print("Access Code: [ %s ] (Expires in %d mins)" % (access_code, expires_in_minutes))
            print("Note:       %s" % env_status)
            print("="*65 + "\n")
            return True, "Verification code generated and sent (Simulated in Dev Mode)."
        else:
            print(f"[!] Email delivery failed: {env_status}")
            return False, "Email service is temporarily unavailable. Please contact the system administrator to configure SMTP settings."

    # Send real email via SMTP
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Medicare Security: Your {purpose} Access Code"
        msg["From"] = cfg["from_email"]
        msg["To"] = recipient_email

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)

        if cfg["user"] and cfg["password"]:
            server.login(cfg["user"], cfg["password"])

        server.sendmail(cfg["from_email"], [recipient_email], msg.as_string())
        server.quit()
        return True, "Verification code sent to registered email address."
    except Exception as e:
        print(f"[!] SMTP Error delivering to {recipient_email}: {e}")
        return False, "Failed to deliver verification email. Please check SMTP settings or try again."
