"""Render the digest as an HTML email + plaintext fallback.

Each item gets two mailto: buttons. Clicking one opens the user's mail client
with a prefilled subject like:

    [ainews-feedback] up | <item-id> | <truncated title>

The IMAP feedback ingest later parses those subjects.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from jinja2 import Environment, BaseLoader, select_autoescape

from .models import RankedItem

TZ = ZoneInfo("Europe/Belgrade")

ANGLE_COLOURS = {
    "tooling":   "#0ea5e9",
    "craft":     "#a855f7",
    "strategy":  "#f59e0b",
    "research":  "#10b981",
    "community": "#ef4444",
    "other":     "#64748b",
}


def _feedback_mailto(to_addr: str, vote: str, item_id: str, title: str) -> str:
    short_title = title if len(title) <= 80 else title[:77] + "…"
    subject = f"[ainews-feedback] {vote} | {item_id} | {short_title}"
    body = (
        f"Vote: {vote}\n"
        f"Item: {item_id}\n"
        f"Title: {title}\n\n"
        "Optional note (gets fed back into the taste profile):\n\n"
    )
    return f"mailto:{to_addr}?subject={quote(subject)}&body={quote(body)}"


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background:#f7f7f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#111;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f7f5;">
    <tr><td align="center">
      <table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#fff;margin:24px 0;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06);">

        <tr><td style="padding:28px 32px 8px 32px;">
          <div style="font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;font-weight:600;">AI News Feed · {{ date_str }}</div>
          <h1 style="margin:6px 0 0 0;font-size:22px;line-height:1.3;font-weight:700;letter-spacing:-0.01em;">Today's six</h1>
          {% if editor_note %}
          <p style="margin:12px 0 0 0;font-size:14px;color:#475569;font-style:italic;">{{ editor_note }}</p>
          {% endif %}
        </td></tr>

        {% for r in picks %}
        <tr><td style="padding:18px 32px 0 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e2e8f0;padding-top:18px;">
            <tr>
              <td style="vertical-align:top;">
                <div style="font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:{{ angle_colour(r.angle) }};font-weight:700;margin-bottom:6px;">
                  {{ r.angle or "item" }} · {{ r.item.source }}{% if r.relevance %} · {{ r.relevance }}/100{% endif %}
                </div>
                <div style="font-size:17px;line-height:1.35;font-weight:600;margin:0 0 8px 0;">
                  <a href="{{ r.item.url }}" style="color:#0f172a;text-decoration:none;">{{ loop.index }}. {{ r.item.title }}</a>
                </div>
                <div style="font-size:14px;line-height:1.55;color:#334155;margin:0 0 12px 0;">
                  {{ r.why }}
                </div>
                <div style="margin-top:10px;">
                  <a href="{{ r.item.url }}" style="display:inline-block;font-size:13px;color:#2563eb;text-decoration:none;font-weight:500;margin-right:14px;">Read →</a>
                  <a href="{{ feedback(feedback_to, 'up', r.item.id, r.item.title) }}" style="display:inline-block;font-size:13px;color:#15803d;text-decoration:none;font-weight:500;margin-right:14px;border:1px solid #d1fae5;background:#f0fdf4;padding:5px 10px;border-radius:6px;">Up · more like this</a>
                  <a href="{{ feedback(feedback_to, 'down', r.item.id, r.item.title) }}" style="display:inline-block;font-size:13px;color:#b91c1c;text-decoration:none;font-weight:500;border:1px solid #fee2e2;background:#fef2f2;padding:5px 10px;border-radius:6px;">Down · less like this</a>
                </div>
              </td>
            </tr>
          </table>
        </td></tr>
        {% endfor %}

        <tr><td style="padding:24px 32px 28px 32px;">
          <div style="border-top:1px solid #e2e8f0;padding-top:16px;font-size:12px;color:#64748b;line-height:1.5;">
            Tap Up / Down on any item — your mail client will open with a prefilled subject. Just hit send. Feedback gets folded into tomorrow's taste profile automatically.
            <br><br>
            Sources scanned: Reddit, Hacker News, Substack, lab + tooling blogs, arXiv. Total candidates today: {{ total_candidates }}.
          </div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _build_env() -> Environment:
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape(["html"]))
    env.globals["feedback"] = _feedback_mailto
    env.globals["angle_colour"] = lambda a: ANGLE_COLOURS.get(a, ANGLE_COLOURS["other"])
    return env


def render_html(picks: list[RankedItem], total_candidates: int,
                feedback_to: str, editor_note: str = "") -> tuple[str, str]:
    """Returns (subject, html_body)."""
    now = datetime.now(TZ)
    date_str = now.strftime("%a %b %d, %Y")
    if picks:
        subject = f"AI digest · {now.strftime('%a %b %d')} · {picks[0].item.title[:60]}"
    else:
        subject = f"AI digest · {now.strftime('%a %b %d')} · quiet day"

    env = _build_env()
    template = env.from_string(HTML_TEMPLATE)
    html = template.render(
        picks=picks,
        date_str=date_str,
        subject=subject,
        feedback_to=feedback_to,
        editor_note=editor_note,
        total_candidates=total_candidates,
    )
    return subject, html


def render_plaintext(picks: list[RankedItem], feedback_to: str,
                     editor_note: str = "") -> str:
    """Plaintext fallback for clients that don't render HTML."""
    lines = ["AI News Feed — today's six", ""]
    if editor_note:
        lines += [editor_note, ""]
    for i, r in enumerate(picks, 1):
        lines += [
            f"{i}. {r.item.title}",
            f"   {r.item.source}  ·  {r.angle or 'item'}  ·  {r.relevance}/100",
            f"   {r.why}",
            f"   Read:  {r.item.url}",
            f"   👍 Up:    {_feedback_mailto(feedback_to, 'up', r.item.id, r.item.title)}",
            f"   👎 Down:  {_feedback_mailto(feedback_to, 'down', r.item.id, r.item.title)}",
            "",
        ]
    return "\n".join(lines)
