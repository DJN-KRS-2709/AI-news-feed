"""Source fetchers — Reddit, Hacker News, RSS, arXiv.

Each fetcher takes a config block + lookback window and returns a list of Item.
Failures in any one source are logged and swallowed so one flaky feed never
kills the digest.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import quote_plus

import feedparser
import requests
from dateutil import parser as dateparser

from .models import Item

log = logging.getLogger(__name__)

USER_AGENT = "ai-news-feed/0.1 (+https://github.com/DJN-KRS-2709/AI-news-feed)"
HTTP_TIMEOUT = 15


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _within_window(published: datetime | None, lookback_hours: int) -> bool:
    if not published:
        return True  # keep undated items, scorer will sort it out
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published >= _now_utc() - timedelta(hours=lookback_hours)


# --------------------------------------------------------------------------- #
# Reddit
# --------------------------------------------------------------------------- #

def fetch_reddit(config: dict, lookback_hours: int) -> list[Item]:
    if not config.get("enabled"):
        return []
    items: list[Item] = []
    min_score = config.get("min_score", 25)
    limit = config.get("limit_per_sub", 10)

    for sub in config.get("subreddits", []):
        url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit={limit}"
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT},
                             timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("reddit r/%s failed: %s", sub, e)
            continue

        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            if d.get("score", 0) < min_score:
                continue
            if d.get("over_18") or d.get("stickied"):
                continue

            published = datetime.fromtimestamp(d["created_utc"], tz=timezone.utc) \
                if d.get("created_utc") else None
            if not _within_window(published, lookback_hours):
                continue

            permalink = f"https://www.reddit.com{d.get('permalink', '')}"
            override = d.get("url_overridden_by_dest") or ""
            # When the post links to a Reddit-hosted image/video, the
            # discussion thread is far more valuable than the raw asset.
            is_media = any(host in override for host in
                           ("i.redd.it", "v.redd.it", "i.imgur.com"))
            link = permalink if (is_media or not override) else override
            items.append(Item(
                source=f"reddit:r/{sub}",
                title=d.get("title", "").strip(),
                url=link,
                published=published,
                author=d.get("author"),
                summary=(d.get("selftext") or "")[:600],
                score=d.get("score"),
                extras={
                    "comments": d.get("num_comments", 0),
                    "permalink": f"https://www.reddit.com{d.get('permalink', '')}",
                },
            ))

        time.sleep(0.5)  # be polite to reddit's free endpoint

    log.info("reddit: %d items", len(items))
    return items


# --------------------------------------------------------------------------- #
# Hacker News (via Algolia)
# --------------------------------------------------------------------------- #

def fetch_hackernews(config: dict, lookback_hours: int) -> list[Item]:
    if not config.get("enabled"):
        return []
    min_points = config.get("min_points", 50)
    keywords = config.get("keywords", [])

    cutoff_ts = int((_now_utc() - timedelta(hours=lookback_hours)).timestamp())
    url = (
        "https://hn.algolia.com/api/v1/search_by_date"
        f"?tags=story&numericFilters=points>={min_points},created_at_i>{cutoff_ts}"
        "&hitsPerPage=80"
    )
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT},
                         timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception as e:
        log.warning("hackernews failed: %s", e)
        return []

    items: list[Item] = []
    kw_re = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE) \
        if keywords else None

    for h in hits:
        title = (h.get("title") or "").strip()
        if not title:
            continue
        if kw_re and not kw_re.search(title + " " + (h.get("story_text") or "")):
            continue

        published = None
        if h.get("created_at"):
            try:
                published = dateparser.parse(h["created_at"])
            except Exception:
                pass

        link = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        items.append(Item(
            source="hackernews",
            title=title,
            url=link,
            published=published,
            author=h.get("author"),
            summary=(h.get("story_text") or "")[:600],
            score=h.get("points"),
            extras={
                "comments": h.get("num_comments", 0),
                "hn_url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            },
        ))

    log.info("hackernews: %d items", len(items))
    return items


# --------------------------------------------------------------------------- #
# RSS feeds (Substack newsletters + company blogs)
# --------------------------------------------------------------------------- #

def fetch_rss(config: dict, lookback_hours: int) -> list[Item]:
    if not config.get("enabled"):
        return []
    items: list[Item] = []

    for feed in config.get("feeds", []):
        name = feed.get("name", "rss")
        url = feed.get("url")
        if not url:
            continue
        try:
            parsed = feedparser.parse(url, agent=USER_AGENT)
        except Exception as e:
            log.warning("rss %s failed: %s", name, e)
            continue
        if parsed.bozo and not parsed.entries:
            log.warning("rss %s parse error: %s", name, parsed.bozo_exception)
            continue

        for entry in parsed.entries[:25]:
            published = None
            for attr in ("published", "updated", "created"):
                v = entry.get(attr)
                if v:
                    try:
                        published = dateparser.parse(v)
                        break
                    except Exception:
                        continue
            if not _within_window(published, lookback_hours):
                continue

            title = (entry.get("title") or "").strip()
            link = entry.get("link", "").strip()
            if not (title and link):
                continue

            summary = entry.get("summary", "") or entry.get("description", "")
            # strip HTML tags from RSS summaries
            summary = re.sub(r"<[^>]+>", " ", summary)
            summary = re.sub(r"\s+", " ", summary).strip()[:600]

            items.append(Item(
                source=f"rss:{name}",
                title=title,
                url=link,
                published=published,
                author=entry.get("author"),
                summary=summary,
            ))

    log.info("rss: %d items across %d feeds", len(items),
             len(config.get("feeds", [])))
    return items


# --------------------------------------------------------------------------- #
# arXiv — keyword-filtered, conservative
# --------------------------------------------------------------------------- #

def fetch_arxiv(config: dict, lookback_hours: int) -> list[Item]:
    if not config.get("enabled"):
        return []
    cats = config.get("categories", [])
    keywords = config.get("keywords", [])
    max_per_run = config.get("max_per_run", 3)
    if not cats:
        return []

    cat_query = "+OR+".join(f"cat:{c}" for c in cats)
    kw_query = "+AND+(" + "+OR+".join(f"all:%22{quote_plus(k)}%22"
                                       for k in keywords) + ")" if keywords else ""
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query={cat_query}{kw_query}"
        "&sortBy=submittedDate&sortOrder=descending&max_results=15"
    )

    try:
        parsed = feedparser.parse(url, agent=USER_AGENT)
    except Exception as e:
        log.warning("arxiv failed: %s", e)
        return []

    items: list[Item] = []
    for entry in parsed.entries[:max_per_run * 3]:
        published = None
        if entry.get("published"):
            try:
                published = dateparser.parse(entry["published"])
            except Exception:
                pass
        if not _within_window(published, lookback_hours * 2):  # papers move slower
            continue

        title = re.sub(r"\s+", " ", entry.get("title", "")).strip()
        link = entry.get("link", "").strip()
        summary = re.sub(r"\s+", " ",
                         entry.get("summary", "")).strip()[:600]
        if not (title and link):
            continue

        items.append(Item(
            source="arxiv",
            title=title,
            url=link,
            published=published,
            author=", ".join(a.get("name", "") for a in entry.get("authors", []))[:120],
            summary=summary,
        ))
        if len(items) >= max_per_run:
            break

    log.info("arxiv: %d items", len(items))
    return items


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def fetch_all(config: dict) -> list[Item]:
    """Fetch from every enabled source. Each source is independent."""
    lookback = int(config.get("lookback_hours", 36))
    out: list[Item] = []
    out.extend(fetch_reddit(config.get("reddit", {}), lookback))
    out.extend(fetch_hackernews(config.get("hackernews", {}), lookback))
    out.extend(fetch_rss(config.get("rss", {}), lookback))
    out.extend(fetch_arxiv(config.get("arxiv", {}), lookback))
    return out


def dedupe(items: Iterable[Item], seen_ids: set[str]) -> list[Item]:
    """Drop items we've sent before; collapse duplicates by canonical URL."""
    by_id: dict[str, Item] = {}
    for it in items:
        if it.id in seen_ids:
            continue
        existing = by_id.get(it.id)
        if existing is None:
            by_id[it.id] = it
            continue
        # prefer the higher-scored/more-detailed copy
        if (it.score or 0) > (existing.score or 0):
            by_id[it.id] = it
    return list(by_id.values())
