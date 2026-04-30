"""SMTP send via any standard SMTP provider.

Uses MAIL_USER / MAIL_PASS / MAIL_SMTP_HOST / MAIL_SMTP_PORT env vars.
Defaults to Gmail (smtp.gmail.com:465). For Gmail you need a 16-char
App Password (not your Google account password) — see README.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

log = logging.getLogger(__name__)


def send_email(to_addr: str, subject: str, html: str, plaintext: str,
               from_name: str | None = None) -> None:
    user = os.environ["MAIL_USER"]
    password = os.environ["MAIL_PASS"]
    host = os.environ.get("MAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("MAIL_SMTP_PORT", "465"))
    sender_name = from_name or os.environ.get("DIGEST_FROM_NAME", "AI News Feed")

    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, user))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=user.split("@")[-1])
    msg.set_content(plaintext)
    msg.add_alternative(html, subtype="html")

    log.info("sending mail to %s via %s:%d", to_addr, host, port)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
    log.info("sent")
