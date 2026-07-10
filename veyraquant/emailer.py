import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from .config import SmtpConfig


logger = logging.getLogger(__name__)

SEND_TIMEOUT_SECONDS = 30
SEND_MAX_ATTEMPTS = 3
SEND_RETRY_BACKOFF_SECONDS = 2.0


def _recipients(to_email: str) -> list[str]:
    return [addr.strip() for addr in to_email.split(",") if addr.strip()]


def build_message(config: SmtpConfig, subject: str, body: str, html_body: str | None = None) -> MIMEMultipart:
    """Assemble a multipart/alternative message (plain first, HTML last)."""
    msg = MIMEMultipart("alternative")
    msg["From"] = config.from_email
    msg["To"] = config.to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="veyraquant")
    # RFC 2046: in multipart/alternative, list parts from least to most
    # preferred, so the plain-text fallback comes before the HTML view.
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_email(config: SmtpConfig, subject: str, body: str, html_body: str | None = None) -> None:
    if not all([config.user, config.password, config.from_email, config.to_email]):
        raise RuntimeError("Missing SMTP_USER/SMTP_APP_PASSWORD/FROM_EMAIL/TO_EMAIL")

    msg = build_message(config, subject, body, html_body)
    recipients = _recipients(config.to_email)

    last_error: Exception | None = None
    for attempt in range(1, SEND_MAX_ATTEMPTS + 1):
        try:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=SEND_TIMEOUT_SECONDS) as server:
                server.login(config.user, config.password)
                server.send_message(msg, to_addrs=recipients)
            if attempt > 1:
                logger.info("Email sent on attempt %d/%d.", attempt, SEND_MAX_ATTEMPTS)
            return
        except (smtplib.SMTPException, OSError) as exc:
            last_error = exc
            logger.warning(
                "Email send attempt %d/%d failed: %s", attempt, SEND_MAX_ATTEMPTS, exc
            )
            if attempt < SEND_MAX_ATTEMPTS:
                time.sleep(SEND_RETRY_BACKOFF_SECONDS * attempt)

    raise RuntimeError(f"Email send failed after {SEND_MAX_ATTEMPTS} attempts") from last_error
