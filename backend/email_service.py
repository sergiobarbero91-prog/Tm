"""
Email service — thin wrapper around smtplib for Gmail SMTP.

Config via env vars (see backend/.env):
    SMTP_HOST      — smtp.gmail.com
    SMTP_PORT      — 587 (STARTTLS)
    SMTP_USERNAME  — the Gmail address that sends the mail
    SMTP_PASSWORD  — a Gmail "app password" (not the account password)
    SMTP_FROM      — display "From" address (defaults to SMTP_USERNAME)

When any of the first four are missing the sender switches to DEV MODE:
it does not touch the network, only logs the email body so the developer
can copy/paste the link during local testing.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from shared import logger


def _cfg() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "user": os.environ.get("SMTP_USERNAME", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "from_addr": os.environ.get("SMTP_FROM", "").strip() or os.environ.get("SMTP_USERNAME", "").strip(),
    }


def is_dev_mode() -> bool:
    c = _cfg()
    return not (c["host"] and c["user"] and c["password"] and c["from_addr"])


def send_email(to: str, subject: str, text_body: str, html_body: Optional[str] = None) -> bool:
    """Send one email. Returns True on success, False otherwise.

    In DEV MODE (missing SMTP creds) the payload is logged instead so that
    developers can still exercise the flow end-to-end without configuring
    Gmail.
    """
    if is_dev_mode():
        logger.warning(
            "[email/DEV] SMTP not configured — logging email instead of sending it.\n"
            f"  TO: {to}\n  SUBJECT: {subject}\n  BODY:\n{text_body}"
        )
        return True

    c = _cfg()
    msg = EmailMessage()
    msg["From"] = c["from_addr"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()

    # Forzar IPv4 SIN romper la validacion SSL (que necesita el hostname).
    # Parcheamos getaddrinfo solo durante esta llamada para descartar IPv6,
    # asi el hostname sigue viajando en la conexion (SNI + cert verify).
    import socket as _sock
    _original_getaddrinfo = _sock.getaddrinfo

    def _getaddrinfo_ipv4(host, port, *args, **kwargs):
        return _original_getaddrinfo(host, port, _sock.AF_INET, _sock.SOCK_STREAM)

    _sock.getaddrinfo = _getaddrinfo_ipv4
    try:
        # Puerto 465 = SSL implicito; 587 = STARTTLS
        if c["port"] == 465:
            with smtplib.SMTP_SSL(c["host"], c["port"], context=context, timeout=15) as server:
                server.login(c["user"], c["password"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(c["host"], c["port"], timeout=15) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(c["user"], c["password"])
                server.send_message(msg)
        logger.info(f"[email] Sent '{subject}' to {to}")
        return True
    except Exception as exc:  # pragma: no cover — network/SMTP failure paths
        logger.exception(f"[email] Send failed to={to}: {exc}")
        return False
    finally:
        _sock.getaddrinfo = _original_getaddrinfo
