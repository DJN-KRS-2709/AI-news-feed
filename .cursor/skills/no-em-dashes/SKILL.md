---
name: no-em-dashes
description: >-
  Ensures the em-dash character never appears in any user-facing text the agent
  writes: Slack messages, emails, chat replies, drafted copy, commit and PR text,
  docs, or anything the user will read or paste elsewhere. Auto-invoke whenever
  drafting or editing a message, reply, email, summary, or any content the user
  may send or publish.
---

# No em-dashes

The user never wants to see an em-dash (`—`) in anything the agent produces for
them. This applies to every surface, not just code or course content: Slack
messages, emails, chat replies, summaries, drafted copy, commit messages, PR
titles and bodies, and any text the user will copy out and send.

## The rule

Never emit the em-dash character `—` (U+2014). Also avoid its entity and escape
forms (`&mdash;`, `&#8212;`, `\u2014`) and an en-dash (`–`) used as a substitute
for one. Rewrite instead, choosing punctuation that fits the sentence:

| Where the em-dash was used | Use instead |
|---|---|
| Aside or parenthetical mid-sentence (`text — aside — text`) | commas, or split into two sentences, or parentheses |
| One-sided pause (`text — more text`) | comma, colon, or full stop |
| Label / title separator (`Module 1 — Title`) | colon (`Module 1: Title`) |
| List or bullet lead-in | colon |
| Numeric range (`10 — 20`) | en-dash or the word "to" (`10 to 20`) |

Prefer the option that reads most naturally. When in doubt, a comma or a full
stop is almost always right.

## Before returning anything

Scan the drafted text for `—` and remove every one before sending. This check is
mandatory for any message, reply, email, or copy the user will paste elsewhere,
and for commit and PR text.

## Notes

- This is about the agent's own output. It complements, and does not replace, the
  course-content em-dash cleanup handled by `scripts/strip_emdashes.py` and the
  `ps-course-authoring` skill.
- The only acceptable appearance of `—` is when literally quoting the user, or
  when the user explicitly asks to keep or discuss the character itself.
