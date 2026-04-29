"""LLM-based ranking + summarization.

Ranks the day's items against the taste profile and accumulated feedback,
then returns the top N with a personalised "why this matters" line each.

Uses Claude with structured JSON output. The model is told *what* the reader
cares about, *what* they've upvoted/downvoted recently, and is asked to think
about it before producing JSON.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from typing import Optional

from anthropic import Anthropic

from .models import Item, RankedItem
from .state import load_feedback, load_taste_profile

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_CANDIDATES = 60          # cap before sending to the model
MAX_OUTPUT_TOKENS = 4000


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n - 1] + "…"


def _summarize_feedback(feedback: list[dict]) -> str:
    """Distill recent feedback into a short prompt-friendly snippet."""
    if not feedback:
        return "(no prior feedback yet)"

    ups = [f for f in feedback if f.get("vote") == "up"]
    downs = [f for f in feedback if f.get("vote") == "down"]

    def top_sources(items, k=5):
        c = Counter(i.get("source", "") for i in items if i.get("source"))
        return [s for s, _ in c.most_common(k)]

    def recent_titles(items, k=8):
        return [i.get("title", "") for i in items[-k:] if i.get("title")]

    lines = []
    lines.append(f"Total upvotes: {len(ups)}, downvotes: {len(downs)}.")
    if ups:
        lines.append("Recent UPVOTED titles (more like these):")
        for t in recent_titles(ups):
            lines.append(f"  + {t}")
        if top_sources(ups):
            lines.append(f"Sources he upvotes most: {', '.join(top_sources(ups))}")
    if downs:
        lines.append("Recent DOWNVOTED titles (less like these):")
        for t in recent_titles(downs):
            lines.append(f"  - {t}")
        if top_sources(downs):
            lines.append(f"Sources he downvotes most: {', '.join(top_sources(downs))}")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the editor of a daily AI news digest tailored for one
specific reader: Dejan Krstic. Your job is to pick the 6 most valuable items
from a candidate pool, ranked by how much they help him in his actual work.

Be ruthless. Quality over quantity. If only 3 items deserve to be there, return
3. Never pad. Never include items just to fill a slot.

Diversity matters: don't pick 6 items from the same source if other strong
items exist. Prefer items that meaningfully differ in angle (tooling vs craft
vs strategy vs research).

You will output STRICT JSON only — no prose, no markdown, no code fences.
Schema:

{
  "picks": [
    {
      "id": "<string, the item id provided>",
      "relevance": <integer 0-100>,
      "angle": "<one of: tooling, craft, strategy, research, community, other>",
      "why": "<1-2 sentences, max 240 chars, written TO Dejan, second person, explain WHY this matters for his work>"
    }
  ],
  "editor_note": "<optional 1-sentence note if today's pool is weak or unusual; empty string otherwise>"
}
"""


def _build_user_prompt(items: list[Item], max_items: int,
                       taste_profile: str, feedback_summary: str) -> str:
    candidates = []
    for i, it in enumerate(items):
        candidates.append({
            "id": it.id,
            "title": it.title,
            "source": it.source,
            "url": it.url,
            "score": it.score,
            "summary": _truncate(it.summary, 350),
        })

    return f"""# Reader profile

{taste_profile}

# Recent feedback (use this to refine taste)

{feedback_summary}

# Today's candidate pool ({len(items)} items)

```json
{json.dumps(candidates, ensure_ascii=False, indent=2)}
```

# Task

Pick the top {max_items} items (or fewer if the pool is weak) for Dejan's
digest today. Rank by how much they help him *do his work* — building,
teaching, coaching, prototyping, leading.

Return JSON only, matching the schema in the system prompt.
"""


def _parse_picks(raw: str) -> tuple[list[dict], str]:
    """Extract picks + editor_note from the model's JSON output."""
    # The model is asked to return strict JSON. Be defensive anyway.
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        # Try to find the outermost {...}
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            raise
        data = json.loads(m.group(0))
    return data.get("picks", []), data.get("editor_note", "")


def rank_items(items: list[Item], max_items: int = 6,
               model: Optional[str] = None) -> tuple[list[RankedItem], str]:
    """Returns (ranked_picks, editor_note)."""
    if not items:
        return [], "No fresh items in any feed today."

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    # Cap candidate pool size — biggest signal is title + source, so prefer
    # items with explicit scores at the top.
    items_sorted = sorted(items,
                          key=lambda x: (x.score or 0, x.published or 0),
                          reverse=True)
    pool = items_sorted[:MAX_CANDIDATES]
    by_id = {it.id: it for it in pool}

    client = Anthropic(api_key=api_key)
    model_name = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    user_prompt = _build_user_prompt(
        pool, max_items,
        taste_profile=load_taste_profile(),
        feedback_summary=_summarize_feedback(load_feedback()),
    )

    log.info("ranking %d candidates with %s", len(pool), model_name)
    resp = client.messages.create(
        model=model_name,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = "".join(block.text for block in resp.content
                  if getattr(block, "type", "") == "text")

    picks, editor_note = _parse_picks(raw)

    ranked: list[RankedItem] = []
    for p in picks[:max_items]:
        item = by_id.get(p.get("id"))
        if not item:
            log.warning("model returned unknown item id %s", p.get("id"))
            continue
        ranked.append(RankedItem(
            item=item,
            relevance=int(p.get("relevance", 0)),
            why=str(p.get("why", "")).strip(),
            angle=str(p.get("angle", "")).strip(),
        ))

    log.info("ranked %d items (editor_note: %r)", len(ranked), editor_note)
    return ranked, editor_note
