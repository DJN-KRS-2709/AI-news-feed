# AI News Feed

A daily, taste-aware AI news digest for one specific reader (Dejan).

Each morning at **08:00 Europe/Belgrade**, a GitHub Action fetches fresh items
from Reddit, Hacker News, Substack, lab/tooling blogs, and arXiv; ranks them
against a personal taste profile + accumulated 👍/👎 history using Claude;
picks **at most six**, and emails them via Hostinger SMTP.

Each item has **Up / Down** buttons that open your mail client with a
prefilled subject. Just hit send. A second action polls the inbox via IMAP
every 6 hours, parses the votes, and folds them into tomorrow's ranking.

The taste profile lives in [`data/taste-profile.md`](data/taste-profile.md) — fully
human-editable. The feedback log lives in
[`data/taste-feedback.jsonl`](data/taste-feedback.jsonl) and grows over time.

---

## How it works

```
┌──────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────┐
│  Reddit      │    │             │    │  Claude     │    │          │
│  HN          │───►│  fetch.py   │───►│  score.py   │───►│  send    │
│  RSS / blogs │    │  + dedupe   │    │  ranks +    │    │  email   │
│  arXiv       │    │             │    │  summarises │    │  (SMTP)  │
└──────────────┘    └─────────────┘    └─────────────┘    └────┬─────┘
                                              ▲                │
                                              │                ▼
                                       ┌─────────────┐   ┌──────────┐
                                       │ taste-      │   │ inbox:   │
                                       │ profile.md  │   │ 👍/👎    │
                                       │ + feedback  │◄──│ replies  │
                                       │ jsonl       │   │ (IMAP)   │
                                       └─────────────┘   └──────────┘
```

---

## Setup (one-time, ~15 minutes)

### 1. Create the GitHub repo and push this code

The repo is already wired to `git@github.com:DJN-KRS-2709/AI-news-feed.git`.
First push:

```bash
git add -A
git commit -m "feat: initial scaffold of AI news feed"
git push -u origin main
```

### 2. Add GitHub secrets (sensitive)

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Name                | Value                                                |
| ------------------- | ---------------------------------------------------- |
| `ANTHROPIC_API_KEY` | Your Claude API key (`sk-ant-...`)                   |
| `HOSTINGER_USER`    | Mailbox address, e.g. `dejan@dejan-krstic.com`       |
| `HOSTINGER_PASS`    | Mailbox password (the one you use in webmail)        |

### 3. Add GitHub variables (non-sensitive)

Same screen, **Variables** tab:

| Name                 | Suggested value           | Required?               |
| -------------------- | ------------------------- | ----------------------- |
| `DIGEST_TO`          | `dejan@dejan-krstic.com`  | yes                     |
| `FEEDBACK_TO`        | `dejan@dejan-krstic.com`  | yes (where 👍/👎 go)    |
| `DIGEST_FROM_NAME`   | `AI News Feed`            | optional                |
| `MAX_ITEMS`          | `6`                       | optional (default 6)    |
| `HOSTINGER_SMTP_HOST`| `smtp.hostinger.com`      | optional (default fine) |
| `HOSTINGER_SMTP_PORT`| `465`                     | optional (default fine) |
| `HOSTINGER_IMAP_HOST`| `imap.hostinger.com`      | optional (default fine) |
| `HOSTINGER_IMAP_PORT`| `993`                     | optional (default fine) |

### 4. Trigger a dry run from the Actions tab

GitHub → **Actions → Daily AI digest → Run workflow** with `dry_run = true`.
This builds the digest without sending. Look at the uploaded `digest-dry-run`
artifact to inspect the HTML before going live.

### 5. Schedule kicks in automatically

After a successful dry run, the daily cron will fire at **06:00 UTC**
(08:00 Belgrade) and the feedback sync will run every 6 hours.

---

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then fill in real values
set -a; source .env; set +a

# Just see what the fetchers find — no LLM, no email:
python -m src.main fetch-only

# Build the digest, write HTML to ./out, don't send:
python -m src.main digest --dry-run

# Send for real (only do this when you're sure):
python -m src.main digest

# Pull any 👍/👎 replies from the mailbox:
python -m src.main feedback-sync
```

---

## How feedback works

Each item in the email has two buttons:

- **Up · more like this** → opens mail with subject `[ainews-feedback] up | <id> | <title>`
- **Down · less like this** → same with `down`

Tap → send → done. The `feedback-sync` workflow polls every 6 hours, parses
those subjects, appends to `data/taste-feedback.jsonl`, marks the messages
read, and moves them to a `AI-Feedback-Processed` folder in your mailbox.

Tomorrow's ranking prompt includes a summary of recent upvotes and downvotes,
so the editorial taste evolves continuously. You can also leave a free-text
note in the body — it gets folded into the feedback log.

---

## Tuning the editorial voice

Two files do the heavy lifting:

- **[`data/taste-profile.md`](data/taste-profile.md)** — your bio, beliefs, what you
  want, what you don't. Edit freely. This is the most powerful lever.
- **[`config.yaml`](config.yaml)** — sources, subreddits, RSS feeds, keyword filters,
  thresholds. Add or remove feeds whenever you find new signal.

After editing, push to `main`. Next morning's digest uses the new config.

---

## Files at a glance

```
AI-news-feed/
├── .github/workflows/
│   ├── daily-digest.yml         # 06:00 UTC daily; manual run + dry-run option
│   └── feedback-sync.yml        # every 6h; pulls 👍/👎 replies via IMAP
├── data/
│   ├── taste-profile.md         # YOUR taste — edit freely
│   ├── taste-feedback.jsonl     # accumulating votes (auto-managed)
│   └── seen-items.json          # dedupe state (auto-managed)
├── src/
│   ├── fetch.py                 # Reddit, HN, RSS, arXiv fetchers
│   ├── score.py                 # Claude-based ranker + summariser
│   ├── render.py                # HTML email + plaintext fallback
│   ├── send.py                  # SMTP send via Hostinger
│   ├── feedback.py              # IMAP feedback ingest
│   ├── state.py                 # seen-items + feedback persistence
│   ├── models.py                # Item + RankedItem dataclasses
│   └── main.py                  # CLI: digest / feedback-sync / fetch-only
├── config.yaml
├── requirements.txt
└── .env.example
```

---

## Cost estimate

- **Claude Sonnet** ranking ≈ 60 candidate items + system prompt + JSON output
  → roughly 6–10k tokens per day → **~$0.05–0.15/day** at current Sonnet pricing.
- **Hostinger SMTP/IMAP** — included in your existing mail plan.
- **GitHub Actions** — well within the free tier (~2 minutes/day).

Total: pocket change, even running for a year.

---

## Roadmap (when v1 has earned it)

- LinkedIn newsletter ingestion (forward-to-folder + IMAP parser)
- Twitter/X via curated lists + RSSHub fallback
- Weekly "best of the week" rollup with self-reflection on taste drift
- A tiny dashboard at `dejan-krstic.com/news` showing the running history
- Auto-tuning of `taste-profile.md` from accumulated feedback (LLM-summarised PRs)
