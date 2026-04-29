"""IMAP feedback ingest.

Polls the Hostinger mailbox for unread messages whose subject starts with
`[ainews-feedback]`, parses the structured subject + optional body note, and
appends each as a JSON record to data/taste-feedback.jsonl.

After processing, messages are marked read and moved to a "AI-Feedback-Processed"
folder (created on the fly) so we never double-count them.

Subject format produced by render.py:
    [ainews-feedback] up | <item-id> | <truncated title>

Optional body lines:
    Vote: up
    Item: <id>
    Title: <full title>

    <free-text note>
"""
from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from datetime import datetime, timezone
from email.header import decode_header

from .state import append_feedback

log = logging.getLogger(__name__)

PROCESSED_FOLDER = "AI-Feedback-Processed"

SUBJECT_RE = re.compile(
    r"^\s*\[ainews-feedback\]\s+(?P<vote>up|down)\s*\|\s*(?P<id>[a-f0-9]{6,16})\s*\|\s*(?P<title>.*)$",
    re.IGNORECASE,
)


def _decode_subject(raw: str) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(charset or "utf-8", errors="replace"))
            except Exception:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out).strip()


def _extract_text_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _extract_note(body: str) -> str:
    """Pull the user's free-text note from the body, ignoring our prefilled lines."""
    if not body:
        return ""
    lines = body.splitlines()
    note_lines: list[str] = []
    in_note = False
    for line in lines:
        if not in_note:
            if "Optional note" in line:
                in_note = True
            continue
        # Skip leading blank lines
        if not note_lines and not line.strip():
            continue
        note_lines.append(line.rstrip())
    note = "\n".join(note_lines).strip()
    # Trim any signature-like trailing junk (>200 chars is excessive for a note)
    return note[:1000]


def _ensure_folder(imap: imaplib.IMAP4_SSL, folder: str) -> None:
    try:
        typ, _ = imap.create(folder)
        if typ == "OK":
            log.info("created IMAP folder %s", folder)
    except Exception:
        pass  # folder probably exists


def sync_feedback() -> int:
    """Returns the number of new feedback entries appended."""
    user = os.environ["HOSTINGER_USER"]
    password = os.environ["HOSTINGER_PASS"]
    host = os.environ.get("HOSTINGER_IMAP_HOST", "imap.hostinger.com")
    port = int(os.environ.get("HOSTINGER_IMAP_PORT", "993"))

    log.info("connecting to IMAP %s:%d as %s", host, port, user)
    imap = imaplib.IMAP4_SSL(host, port)
    try:
        imap.login(user, password)
        _ensure_folder(imap, PROCESSED_FOLDER)
        imap.select("INBOX")

        # Search for unread messages with our subject prefix.
        typ, data = imap.search(None, '(UNSEEN SUBJECT "[ainews-feedback]")')
        if typ != "OK":
            log.warning("IMAP search failed: %s", typ)
            return 0

        ids = data[0].split() if data and data[0] else []
        log.info("found %d new feedback messages", len(ids))

        entries: list[dict] = []
        processed_ids: list[bytes] = []

        for msg_id in ids:
            typ, msg_data = imap.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_subject(msg.get("Subject", ""))

            m = SUBJECT_RE.match(subject)
            if not m:
                log.info("skipping (subject doesn't match): %s", subject)
                continue

            vote = m.group("vote").lower()
            item_id = m.group("id").lower()
            title = m.group("title").strip()
            body = _extract_text_body(msg)
            note = _extract_note(body)

            entry = {
                "vote": vote,
                "item_id": item_id,
                "title": title,
                "note": note,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
            entries.append(entry)
            processed_ids.append(msg_id)

        if entries:
            n = append_feedback(entries)
            log.info("appended %d feedback entries", n)

            # Mark + move so we don't reprocess. If COPY fails, leave as-is
            # but at least mark seen — the search filter will skip them next time.
            for msg_id in processed_ids:
                try:
                    imap.copy(msg_id, PROCESSED_FOLDER)
                    imap.store(msg_id, "+FLAGS", "(\\Deleted \\Seen)")
                except Exception as e:
                    log.warning("could not move msg %s: %s", msg_id, e)
                    imap.store(msg_id, "+FLAGS", "(\\Seen)")
            imap.expunge()

        return len(entries)
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()
