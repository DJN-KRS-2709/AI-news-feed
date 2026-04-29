"""One-shot helper: hand-crafted ranking for today's digest.

Used to send the very first digest before the GitHub Action with Claude API
takes over. Picks are made by the assistant in chat (acting as the editor)
and pasted in below; this script only handles fetch → match → render.

After this, the daily Action does the same job autonomously via Claude.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.fetch import dedupe, fetch_all
from src.models import RankedItem
from src.render import render_html, render_plaintext
from src.state import load_seen


# ----- TODAY'S EDITORIAL PASS (id, relevance, angle, why) ------------------ #
PICKS = [
    {
        "id": "93ae1efde053",
        "relevance": 95,
        "angle": "craft",
        "why": "Solo founder hit 10k users in 6 weeks with Claude + Lovable — and "
               "what he built is a marketplace for AI agent skills. This is your "
               "PM-OS thesis as a live case study, written by someone who isn't a "
               "developer. Worth reading start to finish for the SEO/content workflow alone.",
    },
    {
        "id": "b09ab8c2c692",
        "relevance": 92,
        "angle": "craft",
        "why": "Side-by-side comparison of 11 Claude Code workflow systems (BMAD, "
               "OpenSpec, etc.) showing the canonical pipeline of each. Exactly the "
               "kind of meta-pattern table you'd want as a slide in Module 3 — "
               "shows pipeline length is a personality trait (3 steps to 12).",
    },
    {
        "id": "c78be514dcc4",
        "relevance": 90,
        "angle": "craft",
        "why": "Augment's piece on AGENTS.md treats project-level agent context as "
               "the new system prompt. This is the Living PRD argument from the "
               "other direction: bad context actively poisons the model. Direct "
               "input for your 'Skills > Prompts' framing.",
    },
    {
        "id": "f0b26b3b147e",
        "relevance": 86,
        "angle": "strategy",
        "why": "Forbes contrarian piece on vibe coding — exactly the critique you "
               "need to engage with publicly as a Product School instructor. Whether "
               "you agree or not, you should know the language opponents will use "
               "in the next 6 months.",
    },
    {
        "id": "06e180420eab",
        "relevance": 84,
        "angle": "strategy",
        "why": "Legal essay on who owns Claude-generated code. Affects every "
               "student who graduates from your program and ships something real. "
               "Worth a section in Module 6 (Presentation) on what to disclose to "
               "stakeholders and customers.",
    },
    {
        "id": "96589f1d5549",
        "relevance": 78,
        "angle": "strategy",
        "why": "Anthropic just joined the Blender Development Fund as a corporate "
               "patron — alongside the new MCP connectors for Blender, Adobe, "
               "Splice, Sketchup. The strategic shape: MCP becoming the integration "
               "layer for creative tools, not just dev tools.",
    },
]
EDITOR_NOTE = ("First digest. Heavy on craft today (3 of 6) because the discourse "
               "is all about workflow patterns this week. Diversity will balance "
               "as feedback accumulates.")
# --------------------------------------------------------------------------- #


def main() -> int:
    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    items = fetch_all(config)
    fresh = dedupe(items, load_seen())
    by_id = {it.id: it for it in fresh}

    ranked: list[RankedItem] = []
    missing = []
    for p in PICKS:
        item = by_id.get(p["id"])
        if not item:
            missing.append(p["id"])
            continue
        ranked.append(RankedItem(
            item=item,
            relevance=p["relevance"],
            why=p["why"],
            angle=p["angle"],
        ))

    if missing:
        print(f"WARNING: {len(missing)} picks missing from today's pool: {missing}")
        print(f"         (this is normal if items have rolled off the lookback window)")
        print(f"         have {len(ranked)} valid picks, sending those")

    if not ranked:
        print("ERROR: no picks survived; aborting")
        return 1

    feedback_to = "dejan@dejan-krstic.com"
    subject, html = render_html(ranked, total_candidates=len(fresh),
                                feedback_to=feedback_to,
                                editor_note=EDITOR_NOTE)
    plaintext = render_plaintext(ranked, feedback_to=feedback_to,
                                 editor_note=EDITOR_NOTE)

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "today-digest.html").write_text(html)
    (out_dir / "today-digest.txt").write_text(plaintext)
    (out_dir / "today-digest.json").write_text(json.dumps({
        "subject": subject,
        "picks": [r.to_dict() for r in ranked],
        "editor_note": EDITOR_NOTE,
        "total_candidates": len(fresh),
    }, indent=2, ensure_ascii=False))

    print(f"\nSubject: {subject}")
    print(f"Picks:   {len(ranked)} of {len(PICKS)}")
    print(f"Pool:    {len(fresh)} candidates")
    print(f"Output:  out/today-digest.html (HTML), .txt (plaintext), .json (metadata)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
