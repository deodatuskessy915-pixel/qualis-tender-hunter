#!/usr/bin/env python3
"""
send_alert.py — Qualis Tender Hunter v3  (Daily Digest + Alert)
================================================================

Sends a DAILY DIGEST to Telegram every morning regardless of new matches.
Also highlights new matches when they appear.

Channels:
  TELEGRAM: Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in GitHub Secrets
  EMAIL:    Set RESEND_API_KEY in GitHub Secrets

Usage:
    python send_alert.py               # production — always sends digest
    python send_alert.py --dry-run     # print what would be sent, no network
    python send_alert.py --force       # treat all matches as new (test mode)
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
TENDERS_FILE  = os.path.join(SCRIPT_DIR, "qualis_live_tenders.json")
PREVIOUS_FILE = os.path.join(SCRIPT_DIR, "previous_matches.json")

RESEND_API_KEY    = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
ALERT_TO_EMAIL    = os.environ.get("ALERT_TO_EMAIL", "deodatuskessy915@gmail.com")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

RESEND_URL = "https://api.resend.com/emails"
MIN_ALERT_SCORE = 4


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def fmt_days(dl: str) -> str:
    if not dl:
        return "deadline TBD"
    try:
        dt = datetime.fromisoformat(dl)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = (dt - datetime.now(timezone.utc)).days
        if days < 0:   return "CLOSED"
        if days == 0:  return "CLOSES TODAY"
        if days == 1:  return "1 day left"
        return f"{days} days left"
    except Exception:
        return dl


def days_left(dl: str) -> int:
    if not dl:
        return 9999
    try:
        dt = datetime.fromisoformat(dl)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - datetime.now(timezone.utc)).days
    except Exception:
        return 9999


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_current_matches() -> tuple:
    """Returns (matches_above_threshold, total_tenders_fetched)."""
    if not os.path.exists(TENDERS_FILE):
        log(f"ERROR: {TENDERS_FILE} not found — run nest_scraper.py first")
        return [], 0
    with open(TENDERS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    all_tenders = data.get("live") or data.get("matches") or []
    total = (data.get("total_published") or data.get("fetched")
             or data.get("total_fetched") or len(all_tenders))
    matches = [m for m in all_tenders
               if (m.get("s") or m.get("score") or 0) >= MIN_ALERT_SCORE]
    return matches, int(total)


def load_previous_ids() -> set:
    if not os.path.exists(PREVIOUS_FILE):
        return set()
    with open(PREVIOUS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("match_ids", []))


def save_previous_ids(matches: list):
    ids = [m.get("entity_uuid") or m.get("id") or m.get("ref") for m in matches]
    ids = [i for i in ids if i]
    with open(PREVIOUS_FILE, "w", encoding="utf-8") as f:
        json.dump({"match_ids": ids,
                   "updated_at": datetime.now(timezone.utc).isoformat(),
                   "count": len(ids)}, f, indent=2)
    log(f"Saved {len(ids)} match IDs to previous_matches.json")


def find_new_matches(current: list, prev_ids: set) -> list:
    return [m for m in current
            if (m.get("entity_uuid") or m.get("id") or m.get("ref")) not in prev_ids]


# Field normalisation (v2 short names + v1 long names)
def m_title(m):    return (m.get("t") or m.get("title") or "Untitled").strip()
def m_buyer(m):    return m.get("buyer") or "Unknown buyer"
def m_dl(m):       return m.get("dl") or m.get("deadline") or ""
def m_score(m):    return m.get("s") or m.get("score") or 0
def m_url(m):      return m.get("u") or m.get("nest_url") or ""
def m_kws(m):      return m.get("k") or m.get("matched_keywords") or []
def m_priority(m): return bool(m.get("p") or m.get("priority"))
def m_tier(m):     return m.get("value_tier") or "STANDARD"
def m_value(m):    return m.get("value_est") or ""


# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM — Daily Digest
# ─────────────────────────────────────────────────────────────────────────────
def build_daily_digest(new_matches: list, all_matches: list,
                       total_tenders: int = 0) -> str:
    now_str = datetime.now().strftime("%d %b %Y, %H:%M") + " EAT"
    lines = []
    no_match = max(0, total_tenders - len(all_matches)) if total_tenders else 0

    # Header
    lines.append("🏗 <b>Qualis Daily Tender Report</b>")
    lines.append(f"📅 {now_str}")
    lines.append("")

    # Snapshot stats
    high_val  = sum(1 for m in all_matches if m_tier(m) == "HIGH")
    priority  = sum(1 for m in all_matches if m_priority(m))
    closing_3 = [m for m in all_matches if 0 <= days_left(m_dl(m)) <= 3]
    closing_7 = [m for m in all_matches if 0 <= days_left(m_dl(m)) <= 7]

    lines.append("📊 <b>Today's snapshot</b>")
    if total_tenders:
        lines.append(f"• Tenders scanned: <b>{total_tenders}</b>")
        lines.append(f"• ✅ Matched Qualis profile: <b>{len(all_matches)}</b>")
        lines.append(f"• ❌ Did not match: <b>{no_match}</b>")
    else:
        lines.append(f"• Active matches: <b>{len(all_matches)}</b>")
    lines.append(f"• 🔥 High-value: <b>{high_val}</b>")
    lines.append(f"• ⭐ Priority buyers: <b>{priority}</b>")
    lines.append(f"• ⚡ Closing ≤ 3 days: <b>{len(closing_3)}</b>")
    lines.append(f"• ⏳ Closing ≤ 7 days: <b>{len(closing_7)}</b>")
    if new_matches:
        lines.append(f"• 🆕 New since last run: <b>{len(new_matches)}</b>")
    lines.append("")

    # Urgent closings (always shown)
    if closing_3:
        lines.append("⚡ <b>URGENT — closing within 3 days</b>")
        for m in sorted(closing_3, key=lambda x: days_left(m_dl(x)))[:3]:
            d = days_left(m_dl(m))
            label = "TODAY" if d == 0 else f"{d}d left"
            lines.append(f"  [{label}] {m_title(m)[:80]}")
            lines.append(f"  🏢 {m_buyer(m)}  |  💰 {m_value(m) or 'est. TBD'}")
            lines.append(f"  🔗 <a href='{m_url(m)}'>View</a>")
        lines.append("")

    # New matches OR deadline rundown
    if new_matches:
        lines.append(
            f"🆕 <b>{len(new_matches)} NEW "
            f"match{'es' if len(new_matches) != 1 else ''} since last run</b>"
        )
        lines.append("")
        for i, m in enumerate(new_matches[:5], 1):
            star = "⭐ " if m_priority(m) else ""
            tier = "🔥 HIGH · " if m_tier(m) == "HIGH" else ""
            lines.append(f"<b>{i}. {star}{tier}Score {m_score(m)}</b>")
            lines.append(f"📋 {m_title(m)[:120]}")
            lines.append(f"🏢 {m_buyer(m)}")
            if m_value(m):
                lines.append(f"💰 {m_value(m)}")
            lines.append(f"⏰ {fmt_days(m_dl(m))}")
            kws = m_kws(m)
            if kws:
                lines.append(f"🔑 {', '.join(kws[:4])}")
            lines.append(f"🔗 <a href='{m_url(m)}'>View on NeST</a>")
            lines.append("")
        if len(new_matches) > 5:
            lines.append(f"…and {len(new_matches) - 5} more on the dashboard.")
            lines.append("")
    else:
        # No new — show deadline countdown
        lines.append("✅ <b>No new tenders since last run</b>")
        lines.append("")
        lines.append("📆 <b>Upcoming deadlines — active matches</b>")
        active = sorted(
            [m for m in all_matches if days_left(m_dl(m)) >= 0],
            key=lambda x: days_left(m_dl(x))
        )[:7]
        for m in active:
            d = days_left(m_dl(m))
            if d == 0:       label = "⚡ TODAY"
            elif d <= 3:     label = f"⚡ {d}d"
            elif d <= 7:     label = f"⏳ {d}d"
            else:            label = f"📅 {d}d"
            flags = " ".join(filter(None, [
                "🔥" if m_tier(m) == "HIGH" else "",
                "⭐" if m_priority(m) else ""
            ]))
            lines.append(
                f"{label} {flags} <b>Score {m_score(m)}</b> · {m_title(m)[:70]}"
            )
            lines.append(f"  🏢 {m_buyer(m)}")
        lines.append("")

    # Top matches by score
    top = sorted(all_matches, key=lambda x: -m_score(x))[:3]
    if top:
        lines.append("🏆 <b>Top matches right now</b>")
        for m in top:
            tier = "🔥 " if m_tier(m) == "HIGH" else ""
            star = "⭐ " if m_priority(m) else ""
            lines.append(f"{tier}{star}<b>Score {m_score(m)}</b> · {m_title(m)[:80]}")
            lines.append(f"  🏢 {m_buyer(m)}  ·  ⏰ {fmt_days(m_dl(m))}")
            if m_value(m):
                lines.append(f"  💰 {m_value(m)}")
            lines.append(f"  🔗 <a href='{m_url(m)}'>View</a>")
        lines.append("")

    lines.append(
        "📊 <a href='https://qualis-tender-hunter.netlify.app'>Open Full Dashboard</a>"
    )
    return "\n".join(lines)


def send_telegram(new_matches: list, all_matches: list,
                  total_tenders: int = 0, dry_run: bool = False) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram: not configured (add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to Secrets)")
        return False

    msg = build_daily_digest(new_matches, all_matches, total_tenders)

    if dry_run:
        log("── DRY RUN: Telegram ──")
        print(msg)
        return True

    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log(f"Telegram delivered to {TELEGRAM_CHAT_ID}")
                return True
            log(f"Telegram error: {result}")
            return False
    except urllib.error.HTTPError as e:
        log(f"Telegram HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
        return False
    except Exception as ex:
        log(f"Telegram exception: {ex}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL — Resend
# ─────────────────────────────────────────────────────────────────────────────
def build_email_html(new_matches: list, all_matches: list) -> str:
    today = datetime.now().strftime("%d %b %Y")
    rows = ""
    for m in new_matches:
        score     = m_score(m)
        score_col = "#22c55e" if score >= 20 else "#f59e0b" if score >= 10 else "#8a93ad"
        pri_badge = "&#11088; PRIORITY &middot; " if m_priority(m) else ""
        tier_badge = "&#128293; HIGH VALUE &middot; " if m_tier(m) == "HIGH" else ""
        kw_html = " ".join(
            f'<span style="background:#1c2035;color:#8a93ad;padding:2px 7px;'
            f'border-radius:4px;font-size:11px;">{k}</span>'
            for k in m_kws(m)[:5]
        )
        rows += f"""
        <tr style="border-bottom:1px solid #1c2035;">
          <td style="padding:16px;vertical-align:top;width:60px;text-align:center;">
            <span style="font-size:24px;font-weight:800;color:{score_col};">{score}</span><br>
            <span style="font-size:9px;color:#4d566e;text-transform:uppercase;">score</span>
          </td>
          <td style="padding:16px;vertical-align:top;">
            <div style="font-size:11px;color:#FFB800;font-weight:700;margin-bottom:4px;">
              {pri_badge}{tier_badge}{fmt_days(m_dl(m))}</div>
            <div style="font-size:14px;font-weight:600;color:#e8eaf2;margin-bottom:6px;">
              {m_title(m)}</div>
            <div style="font-size:12px;color:#8a93ad;margin-bottom:8px;">
              &#127962; {m_buyer(m)}</div>
            <div style="margin-bottom:10px;">{kw_html}</div>
            <a href="{m_url(m)}"
               style="display:inline-block;background:#FFB800;color:#000;padding:7px 16px;
                      border-radius:6px;font-size:12px;font-weight:700;text-decoration:none;">
              View on NeST &#8594;</a>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="utf-8"><title>Qualis Tender Report</title></head>
<body style="margin:0;padding:0;background:#0b0e17;font-family:-apple-system,sans-serif;color:#e8eaf2;">
<div style="max-width:640px;margin:0 auto;padding:28px 16px;">
  <div style="display:flex;align-items:center;gap:14px;margin-bottom:28px;">
    <div style="width:42px;height:42px;background:#FFB800;border-radius:10px;
                text-align:center;line-height:42px;font-size:20px;font-weight:900;
                color:#000;flex-shrink:0;">Q</div>
    <div>
      <div style="font-size:18px;font-weight:800;">Qualis
        <span style="color:#FFB800;">Daily Tender Report</span></div>
      <div style="font-size:11px;color:#4d566e;">{today} &middot; Tanzania Infrastructure Intelligence</div>
    </div>
  </div>
  <div style="background:#161926;border:1px solid rgba(255,184,0,.3);border-radius:10px;
              padding:16px 20px;margin-bottom:24px;">
    <span style="font-size:28px;font-weight:800;color:#FFB800;">{len(new_matches)}</span>
    <span style="font-size:14px;color:#e8eaf2;margin-left:8px;">
      new tender{'s' if len(new_matches)!=1 else ''} since last run</span>
    <div style="font-size:12px;color:#8a93ad;margin-top:4px;">
      {len(all_matches)} total live matches today</div>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0"
    style="background:#161926;border:1px solid rgba(255,255,255,.07);
           border-radius:10px;border-collapse:collapse;margin-bottom:24px;">
    {rows if rows else
     '<tr><td style="padding:20px;color:#8a93ad;text-align:center;">No new matches today — check dashboard for full list</td></tr>'}
  </table>
  <div style="text-align:center;margin-bottom:28px;">
    <a href="https://qualis-tender-hunter.netlify.app"
      style="display:inline-block;background:#FFB800;color:#000;padding:14px 32px;
             border-radius:8px;font-size:14px;font-weight:800;text-decoration:none;">
      Open Live Dashboard &#8594;</a>
  </div>
  <div style="text-align:center;font-size:11px;color:#4d566e;
              border-top:1px solid rgba(255,255,255,.05);padding-top:16px;">
    Qualis Engineering Limited &middot; CRB Class V &middot; TIN 157-968-718<br>
    Automated daily at 06:00 EAT
  </div>
</div></body></html>"""


def send_email(new_matches: list, all_matches: list, dry_run: bool = False) -> bool:
    if not RESEND_API_KEY:
        log("Email: RESEND_API_KEY not set — skipping")
        return False

    subject = (
        f"{len(new_matches)} new tender{'s' if len(new_matches)!=1 else ''} — Qualis Alert"
        if new_matches else
        f"Qualis Daily Report — {len(all_matches)} active matches"
    )
    html = build_email_html(new_matches, all_matches)

    if dry_run:
        log(f"── DRY RUN: Email to {ALERT_TO_EMAIL} — {subject}")
        return True

    payload = json.dumps({
        "from": RESEND_FROM_EMAIL,
        "to": [ALERT_TO_EMAIL],
        "subject": subject,
        "html": html,
    }).encode("utf-8")

    req = urllib.request.Request(
        RESEND_URL, data=payload,
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            log(f"Email sent to {ALERT_TO_EMAIL}  id={result.get('id')}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log(f"Email HTTP {e.code}: {body}")
        return False
    except Exception as ex:
        log(f"Email exception: {ex}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    log("─── Qualis Alert System v3 (Daily Digest) ───────────────────────")
    log(f"Telegram : {'configured' if TELEGRAM_BOT_TOKEN else 'NOT configured'}")
    log(f"Email    : {'configured' if RESEND_API_KEY else 'NOT configured'}")
    log("─────────────────────────────────────────────────────────────────")

    current, total_tenders = load_current_matches()
    prev_ids = load_previous_ids()
    no_match = max(0, total_tenders - len(current))

    log(f"Tenders scanned  : {total_tenders}")
    log(f"Matched profile  : {len(current)}")
    log(f"Did not match    : {no_match}")
    log(f"Previous run IDs : {len(prev_ids)}")

    new_matches = find_new_matches(current, prev_ids)
    log(f"New since last   : {len(new_matches)}")

    if args.force and not new_matches:
        log("--force: treating all as new")
        new_matches = current

    # Always send daily digest
    log("Sending daily digest...")
    tg_ok    = send_telegram(new_matches, current,
                             total_tenders=total_tenders, dry_run=args.dry_run)
    email_ok = send_email(new_matches, current, dry_run=args.dry_run)

    if not tg_ok and not email_ok and not args.dry_run:
        log("BOTH channels failed — check secrets.")
    else:
        sent_via = " + ".join(filter(None, [
            "Telegram" if tg_ok else "",
            "Email" if email_ok else "",
            "dry-run" if args.dry_run else "",
        ]))
        log(f"Delivered via: {sent_via}")

    if not args.dry_run:
        save_previous_ids(current)
    log("Done.")


if __name__ == "__main__":
    main()
