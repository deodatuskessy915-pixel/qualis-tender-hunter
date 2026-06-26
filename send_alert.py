#!/usr/bin/env python3
"""
send_alert.py — Qualis Tender Hunter email alerts via Resend

Compares qualis_live_tenders.json (today's run) with previous_matches.json
(last run's IDs). If new matches are found, sends an HTML email via Resend.

No pip dependencies — uses stdlib urllib only.

Run:
    python send_alert.py          # uses RESEND_API_KEY env var
    python send_alert.py --dry-run  # prints what would be sent, no email

Required env var:
    RESEND_API_KEY   — from resend.com → API Keys
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CURRENT_FILE  = os.path.join(SCRIPT_DIR, "qualis_live_tenders.json")
PREVIOUS_FILE = os.path.join(SCRIPT_DIR, "previous_matches.json")

ALERT_TO      = "deodatuskessy915@gmail.com"
ALERT_FROM    = "Qualis Tender Hunter <onboarding@resend.dev>"
DASHBOARD_URL = "https://qualis-tender-hunter.netlify.app"
RESEND_URL    = "https://api.resend.com/emails"


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def days_until(dl):
    if not dl:
        return None
    try:
        dt = datetime.fromisoformat(dl)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (dt - datetime.now(timezone.utc)).days)
    except Exception:
        return None


def deadline_label(dl):
    d = days_until(dl)
    if d is None:
        return "TBD"
    if d == 0:
        return "🔴 Closes today"
    if d == 1:
        return "🔴 1 day left"
    if d <= 6:
        return f"🟡 {d} days left"
    return f"🟢 {d} days left"


def build_email_html(new_matches, total_matches, generated_at):
    date_str = generated_at[:10] if generated_at else datetime.utcnow().strftime("%Y-%m-%d")
    count    = len(new_matches)
    plural   = "es" if count != 1 else ""

    rows = ""
    for m in new_matches:
        pri_star = "⭐ " if m.get("priority") else ""
        title    = m.get("title") or "—"
        buyer    = m.get("buyer") or "—"
        dl_label = deadline_label(m.get("deadline"))
        score    = m.get("score", 0)
        url      = m.get("nest_url") or DASHBOARD_URL
        kws      = ", ".join((m.get("matched_keywords") or [])[:4]) or "—"
        pri_note = f'<br><span style="color:#FFB800;font-size:11px">★ Priority buyer</span>' if m.get("priority") else ""

        rows += f"""
        <tr>
          <td style="padding:12px 14px;border-bottom:1px solid #1c2035;vertical-align:top">
            <div style="font-weight:600;color:#e8eaf2;line-height:1.35">{pri_star}{title}</div>
            <div style="font-size:11px;color:#8a93ad;margin-top:3px">{kws}</div>
            {pri_note}
          </td>
          <td style="padding:12px 14px;border-bottom:1px solid #1c2035;color:#8a93ad;font-size:13px;vertical-align:top">{buyer}</td>
          <td style="padding:12px 14px;border-bottom:1px solid #1c2035;font-size:13px;vertical-align:top;white-space:nowrap">{dl_label}</td>
          <td style="padding:12px 14px;border-bottom:1px solid #1c2035;text-align:center;vertical-align:top">
            <span style="background:rgba(255,184,0,0.15);color:#FFB800;font-weight:700;padding:3px 10px;border-radius:6px">{score}</span>
          </td>
          <td style="padding:12px 14px;border-bottom:1px solid #1c2035;text-align:right;vertical-align:top;white-space:nowrap">
            <a href="{url}" style="color:#FFB800;font-weight:600;font-size:12px">View on NeST →</a>
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:20px;background:#0b0e17;font-family:Inter,-apple-system,sans-serif">
<div style="max-width:680px;margin:0 auto;background:#0b0e17;border:1px solid rgba(255,255,255,0.08);border-radius:12px;overflow:hidden">

  <!-- Header -->
  <div style="background:#FFB800;padding:20px 28px">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;color:rgba(0,0,0,0.5);text-transform:uppercase;margin-bottom:4px">Qualis Tender Hunter</div>
    <h1 style="margin:0;font-size:22px;font-weight:800;color:#000;letter-spacing:-0.02em">
      {count} New Match{plural} Today
    </h1>
    <p style="margin:6px 0 0;color:rgba(0,0,0,0.6);font-size:13px">{date_str} · {total_matches} total matches on NeST right now</p>
  </div>

  <!-- Table -->
  <div style="padding:0">
    <table width="100%" style="border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#10131f">
          <th style="padding:10px 14px;text-align:left;color:#4d566e;font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em">Title &amp; Keywords</th>
          <th style="padding:10px 14px;text-align:left;color:#4d566e;font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em">Buyer</th>
          <th style="padding:10px 14px;text-align:left;color:#4d566e;font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em">Deadline</th>
          <th style="padding:10px 14px;text-align:center;color:#4d566e;font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em">Score</th>
          <th style="padding:10px 14px;color:#4d566e;font-size:10.5px"></th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <!-- CTA -->
  <div style="padding:24px 28px;text-align:center;background:#10131f;border-top:1px solid #1c2035">
    <a href="{DASHBOARD_URL}"
       style="display:inline-block;background:#FFB800;color:#000;padding:13px 28px;border-radius:8px;font-weight:700;font-size:14px;text-decoration:none;letter-spacing:-0.01em">
      Open Full Dashboard →
    </a>
  </div>

  <!-- Footer -->
  <div style="padding:14px 28px;background:#0b0e17;border-top:1px solid rgba(255,255,255,0.05);font-size:11px;color:#4d566e;text-align:center">
    Qualis Engineering Limited · CRB Class V Electrical Contractor · TIN 157-968-718 · Dar es Salaam
  </div>

</div>
</body>
</html>"""
    return html


def send_resend(api_key, subject, html, dry_run=False):
    payload = json.dumps({
        "from":    ALERT_FROM,
        "to":      [ALERT_TO],
        "subject": subject,
        "html":    html,
    }).encode("utf-8")

    if dry_run:
        print(f"[DRY RUN] Would send to {ALERT_TO}")
        print(f"[DRY RUN] Subject: {subject}")
        print(f"[DRY RUN] HTML length: {len(html)} chars")
        return

    req = urllib.request.Request(
        RESEND_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            print(f"✅ Email sent — id: {result.get('id')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"❌ Resend error: HTTP {e.code} — {body}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print email without sending")
    args = parser.parse_args()

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key and not args.dry_run:
        print("RESEND_API_KEY not set — skipping alert (set it or use --dry-run)")
        sys.exit(0)

    # Load current and previous
    current  = load_json(CURRENT_FILE,  {"matches": [], "generated_at": None})
    previous = load_json(PREVIOUS_FILE, {"match_ids": []})

    current_matches = current.get("matches", [])
    previous_ids    = set(previous.get("match_ids", []))
    current_ids     = {m.get("entity_uuid") for m in current_matches if m.get("entity_uuid")}

    new_matches = [m for m in current_matches if m.get("entity_uuid") not in previous_ids]

    # Always update previous_matches.json with today's IDs
    with open(PREVIOUS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "match_ids":  sorted(current_ids),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count":      len(current_matches),
        }, f, indent=2)
    print(f"Updated {PREVIOUS_FILE} with {len(current_ids)} match IDs")

    if not new_matches:
        print(f"No new matches — {len(current_matches)} total (same as last run). No email sent.")
        return

    print(f"Found {len(new_matches)} new match(es) out of {len(current_matches)} total. Sending alert...")

    date_str = (current.get("generated_at") or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
    count    = len(new_matches)
    plural   = "es" if count != 1 else ""
    subject  = f"🎯 {count} New Qualis Tender Match{plural} — {date_str}"

    html = build_email_html(new_matches, len(current_matches), current.get("generated_at"))
    send_resend(api_key, subject, html, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
