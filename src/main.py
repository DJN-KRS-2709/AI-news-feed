"""CLI entry points.

Usage:
    python -m src.main digest              # fetch + rank + render + send
    python -m src.main digest --dry-run    # write HTML to out/, don't send
    python -m src.main feedback-sync       # poll IMAP, append feedback
    python -m src.main fetch-only          # just print fetched titles (debug)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .fetch import dedupe, fetch_all
from .feedback import sync_feedback
from .render import render_html, render_plaintext
from .score import rank_items
from .send import send_email
from .state import load_seen, save_seen

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
OUT_DIR = Path(__file__).resolve().parent.parent / "out"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def _require_env(*keys: str) -> bool:
    """Return True if all keys are present and non-empty. Otherwise log a
    friendly skip message and return False — the caller should exit 0 so the
    workflow stays green until the user wires up the secrets."""
    missing = [k for k in keys if not os.environ.get(k, "").strip()]
    if not missing:
        return True
    logging.warning(
        "skipping: required env vars not configured yet: %s. "
        "Add them as GitHub repo secrets and re-run.",
        ", ".join(missing),
    )
    return False


def cmd_digest(args: argparse.Namespace) -> int:
    dry_run = args.dry_run or os.environ.get("DIGEST_DRY_RUN", "").lower() == "true"

    # We need the LLM key always, and the SMTP creds whenever we're sending.
    required = ["ANTHROPIC_API_KEY"]
    if not dry_run:
        required += ["HOSTINGER_USER", "HOSTINGER_PASS"]
    if not _require_env(*required):
        return 0

    config = _load_config()
    max_items = int(os.environ.get("MAX_ITEMS", "6"))

    seen = load_seen()
    raw = fetch_all(config)
    fresh = dedupe(raw, seen)
    logging.info("fetched=%d after_dedupe=%d", len(raw), len(fresh))

    if not fresh:
        logging.warning("no fresh items; nothing to send")
        return 0

    picks, editor_note = rank_items(fresh, max_items=max_items)
    if not picks:
        logging.warning("model returned no picks; aborting")
        return 0

    feedback_to = os.environ.get("FEEDBACK_TO") \
        or os.environ.get("DIGEST_TO") \
        or os.environ["HOSTINGER_USER"]
    subject, html = render_html(picks, total_candidates=len(fresh),
                                feedback_to=feedback_to, editor_note=editor_note)
    plaintext = render_plaintext(picks, feedback_to=feedback_to,
                                 editor_note=editor_note)

    if dry_run:
        OUT_DIR.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        html_path = OUT_DIR / f"digest-{stamp}.html"
        txt_path = OUT_DIR / f"digest-{stamp}.txt"
        html_path.write_text(html)
        txt_path.write_text(plaintext)
        print(f"\nDRY RUN — wrote {html_path}\n")
        print(plaintext)
        return 0

    to_addr = os.environ.get("DIGEST_TO") or os.environ["HOSTINGER_USER"]
    send_email(to_addr=to_addr, subject=subject, html=html, plaintext=plaintext)

    # Mark sent items as seen so they don't repeat.
    save_seen(list(seen) + [r.item.id for r in picks])
    return 0


def cmd_feedback_sync(args: argparse.Namespace) -> int:
    if not _require_env("HOSTINGER_USER", "HOSTINGER_PASS"):
        return 0
    n = sync_feedback()
    print(f"ingested {n} new feedback entries")
    return 0


def cmd_fetch_only(args: argparse.Namespace) -> int:
    config = _load_config()
    items = fetch_all(config)
    fresh = dedupe(items, load_seen())
    print(f"\nfetched {len(items)} ({len(fresh)} after dedupe)\n")
    by_source: dict[str, list] = {}
    for it in fresh:
        by_source.setdefault(it.source, []).append(it)
    for source, lst in sorted(by_source.items()):
        print(f"--- {source} ({len(lst)}) ---")
        for it in lst[:8]:
            score = f"[{it.score}]" if it.score else ""
            print(f"  {score:>6}  {it.title[:90]}")
        print()
    return 0


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="ai-news-feed")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_digest = sub.add_parser("digest", help="build + send (or dry-run) the daily digest")
    p_digest.add_argument("--dry-run", action="store_true",
                          help="write HTML to out/ instead of sending")
    p_digest.set_defaults(func=cmd_digest)

    p_fb = sub.add_parser("feedback-sync", help="ingest feedback emails via IMAP")
    p_fb.set_defaults(func=cmd_feedback_sync)

    p_fetch = sub.add_parser("fetch-only", help="debug: print fetched items, no LLM/send")
    p_fetch.set_defaults(func=cmd_fetch_only)

    args = parser.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
