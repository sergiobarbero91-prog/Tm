"""
Email service — Emergent Managed Email proxy.

The VPS blocks all outbound SMTP ports so we send transactional email via
Emergent's HTTPS proxy (port 443, always open). Nothing here talks smtplib.

Config via env vars:
    EMERGENT_EMAIL_KEY   — per-app key provisioned by the platform
    EMAIL_FROM_NAME      — brand name shown as sender (e.g. "As del Volante")
    EMAIL_REPLY_TO       — optional Reply-To inbox owned by the app owner

If the key or brand name are missing the sender switches to DEV MODE and only
logs the email so a developer can copy the link locally.
"""
from __future__ import annotations

import ipaddress
import os
import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

import httpx

from shared import logger


EMAIL_BASE_URL = "https://integrations.emergentagent.com"


def _cfg() -> dict:
    return {
        "key": os.environ.get("EMERGENT_EMAIL_KEY", "").strip(),
        "from_name": os.environ.get("EMAIL_FROM_NAME", "").strip(),
        "reply_to": os.environ.get("EMAIL_REPLY_TO", "").strip() or None,
    }


def is_dev_mode() -> bool:
    c = _cfg()
    return not (c["key"] and c["from_name"])


# ─────────────────────────── Guardrail gate ───────────────────────────
# Structural defense-in-depth for G2 + G3 (see playbook). Never weaken.
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = (
    "reply with your password",
    "reply with the code",
    "send your password",
    "cvv",
    "send us your password",
    "enter your password below",
    "confirm your card number",
    "your full card number",
    "seed phrase",
    "recovery phrase",
    "verify your card",
    "social security number",
    "confirm your bank details",
)
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: set = set()
        self.urls: list = []
        self.anchors: list = []
        self._href: Optional[str] = None
        self._text: list = []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


# ─────────────────────────── Public API ───────────────────────────────
async def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> bool:
    """Send one email via the Emergent proxy. Returns True on success.

    Backwards-compatible signature with the previous smtplib implementation:
    callers pass a plain-text fallback and (optionally) HTML. If HTML is not
    provided we wrap the text in a minimal template so the proxy always
    receives HTML (the API requires it).
    """
    if is_dev_mode():
        logger.warning(
            "[email/DEV] EMERGENT_EMAIL_KEY / EMAIL_FROM_NAME missing — logging "
            "email instead of sending it.\n"
            f"  TO: {to}\n  SUBJECT: {subject}\n  BODY:\n{text_body}"
        )
        return True

    c = _cfg()
    html = html_body or (
        "<div style=\"font-family:Arial,sans-serif;padding:16px;color:#0F172A\">"
        + "".join(f"<p>{line}</p>" for line in text_body.splitlines() if line.strip())
        + "</div>"
    )
    try:
        _assert_safe_email(subject, html)
    except ValueError as ve:
        logger.error(f"[email] Guardrail blocked send to={to}: {ve}")
        return False

    payload = {
        "to": [to],
        "subject": subject,
        "html": html,
        "from_name": c["from_name"],
    }
    if c["reply_to"]:
        payload["contact_email"] = c["reply_to"]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": c["key"]},
                json=payload,
            )
        resp.raise_for_status()
        email_id = resp.json().get("id") if resp.content else None
        logger.info(f"[email] Sent '{subject}' to {to} (id={email_id})")
        return True
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[email] Proxy returned {e.response.status_code} for {to}: {e.response.text}"
        )
        return False
    except Exception as exc:
        logger.exception(f"[email] Send failed to={to}: {exc}")
        return False
