"""Shared data structures."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Item:
    """A single piece of content from any source."""

    source: str          # "reddit", "hackernews", "rss:Latent Space", "arxiv"
    title: str
    url: str
    published: Optional[datetime] = None
    author: Optional[str] = None
    summary: str = ""    # raw excerpt from source (not LLM-generated)
    score: Optional[int] = None    # source-native score (upvotes / points)
    extras: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Stable ID derived from URL — used for dedupe and feedback links."""
        canonical = self.url.split("?")[0].rstrip("/").lower()
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.published:
            d["published"] = self.published.isoformat()
        d["id"] = self.id
        return d


@dataclass
class RankedItem:
    """An Item enriched by the LLM with score and personalised summary."""

    item: Item
    relevance: int       # 0–100 — how well it matches the taste profile
    why: str             # 1–2 sentence "why this matters for Dejan"
    angle: str = ""      # short tag like "tooling", "strategy", "craft"

    def to_dict(self) -> dict:
        return {
            "id": self.item.id,
            "title": self.item.title,
            "url": self.item.url,
            "source": self.item.source,
            "relevance": self.relevance,
            "why": self.why,
            "angle": self.angle,
        }
