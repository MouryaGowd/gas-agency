"""Email sending. Real SMTP when SMTP_HOST is set, otherwise emails are written to
data/outbox/*.eml and recorded as 'logged' so the whole flow can be tested offline."""
import re
import smtplib
import time
from email.message import EmailMessage

from . import config


def send_email(to: str, subject: str, html: str, text: str) -> tuple[str, str]:
    """Returns (status, detail). status is 'sent', 'logged' or 'failed'."""
    real_to = to
    if config.TEST_EMAIL_REDIRECT:
        to = config.TEST_EMAIL_REDIRECT
        subject = f"[to: {real_to}] {subject}"

    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    # Demo/synthetic addresses must never reach a real mail server.
    fake_domain = to.lower().rsplit("@", 1)[-1] in ("example.com", "example.org", "test", "local")
    if not config.SMTP_HOST or fake_domain:
        config.OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", real_to.lower()).strip("-")
        path = config.OUTBOX_DIR / f"{int(time.time() * 1000)}-{slug}.eml"
        path.write_bytes(bytes(msg))
        return "logged", f"SMTP not configured; saved {path.name}"

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
        return "sent", f"delivered to {to}"
    except Exception as exc:  # noqa: BLE001 - report any SMTP failure to the admin UI
        return "failed", f"{type(exc).__name__}: {exc}"
