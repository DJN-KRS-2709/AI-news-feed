"""Persistent state — seen items + accumulated taste feedback."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEEN_FILE = DATA_DIR / "seen-items.json"
FEEDBACK_FILE = DATA_DIR / "taste-feedback.jsonl"
TASTE_PROFILE = DATA_DIR / "taste-profile.md"

# Cap memory of seen items so the file doesn't grow forever.
SEEN_RETENTION = 5000


def load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()).get("ids", []))
    except Exception as e:
        log.warning("could not read seen-items.json: %s", e)
        return set()


def save_seen(ids: Iterable[str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    keep = list(ids)[-SEEN_RETENTION:]
    SEEN_FILE.write_text(json.dumps({
        "ids": keep,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def load_taste_profile() -> str:
    if not TASTE_PROFILE.exists():
        return ""
    return TASTE_PROFILE.read_text()


def load_feedback(limit: int = 200) -> list[dict]:
    """Return the most recent feedback entries (newest last)."""
    if not FEEDBACK_FILE.exists():
        return []
    out: list[dict] = []
    for line in FEEDBACK_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:]


def append_feedback(entries: list[dict]) -> int:
    if not entries:
        return 0
    DATA_DIR.mkdir(exist_ok=True)
    with FEEDBACK_FILE.open("a") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return len(entries)
