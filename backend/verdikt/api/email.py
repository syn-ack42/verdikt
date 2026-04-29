"""SMTP email sending helper. Config is read from site_settings table (DB), falling back to env vars."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_SETTING_KEYS = ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "smtp_use_tls")


def get_smtp_config(session: Session) -> dict:
    """Return SMTP configuration dict, merging DB settings over env-var fallbacks."""
    from verdikt.api.deps import get_config
    from verdikt.storage.auth_orm import SiteSettingsRow

    config = get_config()
    db: dict[str, Optional[str]] = {}
    for key in _SETTING_KEYS:
        row = session.get(SiteSettingsRow, key)
        db[key] = row.value if row else None

    return {
        "host": db.get("smtp_host") or getattr(config, "smtp_host", None),
        "port": int(db.get("smtp_port") or getattr(config, "smtp_port", 587) or 587),
        "user": db.get("smtp_user") or getattr(config, "smtp_user", None),
        "password": db.get("smtp_password") or getattr(config, "smtp_password", None),
        "from": db.get("smtp_from") or getattr(config, "smtp_from", None),
        "use_tls": (db.get("smtp_use_tls") or "true").lower() == "true",
    }


def is_smtp_configured(session: Session) -> bool:
    cfg = get_smtp_config(session)
    return bool(cfg.get("host") and cfg.get("from"))


def send_email(session: Session, to: str, subject: str, body_html: str, body_text: str) -> bool:
    """Send an email. Returns True on success, False if SMTP is not configured or sending fails."""
    cfg = get_smtp_config(session)
    if not cfg.get("host") or not cfg.get("from"):
        log.warning("SMTP not configured — skipping email to %s (subject: %s)", to, subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)
            server.ehlo()
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=10)
        if cfg.get("user") and cfg.get("password"):
            server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from"], [to], msg.as_string())
        server.quit()
        log.info("Email sent to %s (subject: %s)", to, subject)
        return True
    except Exception as exc:
        log.error("Failed to send email to %s: %s", to, exc)
        return False
