#!/usr/bin/env python3
"""
ungm_scraper.py — Qualis Tender Hunter  (UN Global Marketplace Tanzania tenders)
==================================================================================

Fetches active procurement notices from the UN Global Marketplace (ungm.org)
for Tanzania, scores them against the Qualis keyword profile, and writes
results to qualis_ungm_tenders.json (same schema as nest_scraper.py output).

Source:  https://www.ungm.org/Public/Notice
Method:  POST /Public/Notice/Search  (public, no auth needed)
Country: Tanzania = ID "2507"

Run:
    python ungm_scraper.py
    python ungm_scraper.py --debug
    python ungm_scraper.py --min-score 0     # show all Tanzania tenders
    python ungm_scraper.py --output FILE.json
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from keywords import STRONG_INCLUDE, SOFT_INCLUDE, HARD_EXCLUDE, PRIORITY_BUYERS

# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
UNGM_SEARCH  = "https://www.ungm.org/Public/Notice/Search"
UNGM_DETAIL  = "https://www.ungm.org/Public/Notice/{}"
DEFAULT_OUT  = os.path.join(SCRIPT_DIR, "qualis_ungm_tenders.json")
PAGE_SIZE    = 15        # UNGM caps at 15 regardless of PageSize param
TANZANIA_ID  = "2507"
MIN_SCORE    = 4
SOURCE_TAG   = "UNGM"

USER_AGENT   = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# FETCHING
# ─────────────────────────────────────────────────────────────────────────────
def fetch_page(page_index: int) -> str:
    """POST to UNGM search and return the raw HTML fragment."""
    body = json.dumps({
        "PageIndex": page_index,
        "PageSize": PAGE_SIZE,
        "Title": "",
        "Description": "",
        "Reference": "",
        "PublishedFrom": "",
        "PublishedTo": "",
        "DeadlineFrom": "",
        "DeadlineTo": "",
        "Countries": [TANZANIA_ID],
        "Agencies": [],
        "UNSPSCs": [],
        "NoticeTypes": [],
        "SortField": "Deadline",
        "SortAscending": True,
        "isPicker": False,
        "IsSustainable": False,
        "IsActive": True,
        "NoticeDisplayType": None,
        "NoticeSearchTotalLabelId": "noticeSearchTotal",
        "TypeOfCompetitions": [],
    }).encode("utf-8")

    req = urllib.request.Request(
        UNGM_SEARCH,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Referer": "https://www.ungm.org/Public/Notice",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        log(f"HTTP {e.code} on page {page_index}: {e.read().decode()[:200]}")
        return ""
    except Exception as ex:
        log(f"Fetch error page {page_index}: {ex}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# PARSING (no BeautifulSoup dependency — pure regex + stdlib)
# ─────────────────────────────────────────────────────────────────────────────
def parse_rows(html: str) -> list:
    """
    Extract notice rows from the UNGM HTML fragment.
    Each row: <div ... data-noticeid="NNNNN" class="...tableRow...dataRow...">
    Fields extracted: noticeId, title, deadline, published, org, type, reference
    """
    rows = []
    seen_ids = set()

    # Find all dataRow divs with a noticeid attribute
    row_pattern = re.compile(
        r'data-noticeid="(\d+)"[^>]*class="[^"]*tableRow[^"]*dataRow[^"]*"',
        re.IGNORECASE,
    )
    # Split the HTML into per-row chunks using the noticeid markers
    positions = [(m.start(), m.group(1)) for m in row_pattern.finditer(html)]

    for i, (start, notice_id) in enumerate(positions):
        if notice_id in seen_ids:
            continue   # skip duplicate desktop/mobile row
        seen_ids.add(notice_id)

        # Grab the chunk for this row (up to the next row start or 8000 chars)
        end = positions[i + 1][0] if i + 1 < len(positions) else start + 8000
        chunk = html[start:end]

        rows.append({
            "notice_id": notice_id,
            "title":     _extract_title(chunk),
            "deadline":  _extract_deadline(chunk),
            "published": _extract_published(chunk),
            "org":       _extract_org(chunk),
            "ref":       _extract_ref(chunk),
            "url":       UNGM_DETAIL.format(notice_id),
            "source":    SOURCE_TAG,
        })

    return rows


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _extract_title(chunk: str) -> str:
    # First try: full title from <a title="..."> attribute inside resultTitle cell
    # (UNGM truncates visible text but keeps full title in the attribute)
    cell_m = re.search(r'class="[^"]*resultTitle[^"]*"[^>]*>(.*?)</(?:td|div)>', chunk, re.DOTALL)
    if cell_m:
        cell_html = cell_m.group(1)
        # Try title attribute on anchor first
        attr_m = re.search(r'<a\b[^>]*\btitle="([^"]+)"', cell_html, re.DOTALL)
        if attr_m:
            return attr_m.group(1).strip()
        # Fall back to inner text
        return _strip_tags(cell_html).strip()
    return ""


def _extract_deadline(chunk: str) -> str:
    """Return ISO-8601 deadline string (UTC), or '' if unparseable."""
    m = re.search(r'class="[^"]*deadline[^"]*"[^>]*>(.*?)</(?:td|div)>', chunk, re.DOTALL)
    if not m:
        return ""
    raw = _strip_tags(m.group(1)).strip()
    # Format: "02-Jul-2026 23:00 (GMT 0.00)" or "02-Jul-2026 (GMT -4.00)"
    date_m = re.search(
        r"(\d{2}-[A-Za-z]{3}-\d{4})\s*(?:(\d{2}:\d{2}))?\s*\(GMT\s*([-+]?\d+(?:\.\d+)?)\)",
        raw,
    )
    if not date_m:
        return raw
    try:
        date_str  = date_m.group(1)
        time_str  = date_m.group(2) or "00:00"
        offset_h  = float(date_m.group(3))
        dt_naive  = datetime.strptime(f"{date_str} {time_str}", "%d-%b-%Y %H:%M")
        # Shift to UTC
        offset_sec = int(offset_h * 3600)
        dt_utc = dt_naive.replace(tzinfo=timezone.utc)
        # adjust: if GMT+3, subtract 3h to get UTC; GMT offset means "local = UTC + offset"
        from datetime import timedelta
        dt_utc = dt_utc - timedelta(seconds=offset_sec)
        return dt_utc.isoformat()
    except Exception:
        return raw


def _extract_published(chunk: str) -> str:
    # Published date is the 4th tableCell — grab all tableCell contents and pick index 3
    cells = re.findall(
        r'class="[^"]*tableCell[^"]*"[^>]*>(.*?)</(?:td|div)>',
        chunk, re.DOTALL,
    )
    if len(cells) >= 4:
        return _strip_tags(cells[3]).strip()
    return ""


def _extract_org(chunk: str) -> str:
    m = re.search(r'class="[^"]*resultAgency[^"]*"[^>]*>(.*?)</(?:td|div)>', chunk, re.DOTALL)
    return _strip_tags(m.group(1)).strip() if m else ""


def _extract_ref(chunk: str) -> str:
    # Reference: 7th tableCell (index 6)
    cells = re.findall(
        r'class="[^"]*tableCell[^"]*"[^>]*>(.*?)</(?:td|div)>',
        chunk, re.DOTALL,
    )
    if len(cells) >= 7:
        return _strip_tags(cells[6]).strip()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# SCORING  (mirrors nest_scraper.py logic exactly)
# ─────────────────────────────────────────────────────────────────────────────
def score_tender(title: str) -> dict:
    text = title.lower()

    # Hard exclude
    for kw in HARD_EXCLUDE:
        if kw.lower() in text:
            return {"score": 0, "matched": [], "excluded_by": kw}

    matched = []
    score   = 0

    for kw in STRONG_INCLUDE:
        if kw.lower() in text:
            matched.append(kw)
            score += 10

    for kw in SOFT_INCLUDE:
        if kw.lower() in text:
            matched.append(kw)
            score += 3

    return {"score": score, "matched": matched, "excluded_by": None}


def is_priority(org: str) -> bool:
    org_l = org.lower()
    return any(pb.lower() in org_l for pb in PRIORITY_BUYERS)


def days_until(iso_dl: str) -> int:
    if not iso_dl:
        return 9999
    try:
        dt = datetime.fromisoformat(iso_dl)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (dt - datetime.now(timezone.utc)).days)
    except Exception:
        return 9999


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Qualis UNGM Scraper")
    ap.add_argument("--debug",     action="store_true")
    ap.add_argument("--min-score", type=int, default=MIN_SCORE)
    ap.add_argument("--output",    default=DEFAULT_OUT)
    args = ap.parse_args()

    log("─── Qualis UNGM Scraper ─────────────────────────────────────────")
    log(f"Source  : UN Global Marketplace (Tanzania notices)")
    log(f"Min score: {args.min_score}")
    log(f"Output  : {args.output}")
    log("─────────────────────────────────────────────────────────────────")

    all_rows   = []
    page_index = 0

    while True:
        log(f"Fetching page {page_index} …")
        html = fetch_page(page_index)
        if not html:
            log("Empty response — stopping.")
            break

        rows = parse_rows(html)
        log(f"  → {len(rows)} unique notices on this page")

        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < PAGE_SIZE:
            break   # last page
        page_index += 1

    log(f"Total Tanzania notices fetched: {len(all_rows)}")

    # Score and filter
    matches = []
    for row in all_rows:
        result = score_tender(row["title"])

        if args.debug:
            log(
                f"  [{result['score']:3d}] {row['title'][:70]}"
                + (f"  ← excluded: {result['excluded_by']}" if result["excluded_by"] else "")
            )

        if result["score"] >= args.min_score:
            d = days_until(row["deadline"])
            matches.append({
                # Short-name schema (same as nest_scraper output)
                "t":          row["title"],
                "s":          result["score"],
                "k":          result["matched"],
                "dl":         row["deadline"],
                "days_left":  d,
                "buyer":      row["org"],
                "u":          row["url"],
                "ref":        row["ref"],
                "source":     SOURCE_TAG,
                "p":          is_priority(row["org"]),
                "value_tier": "STANDARD",   # UNGM doesn't publish contract values publicly
                "value_est":  "",
                "published":  row["published"],
            })

    matches.sort(key=lambda x: -x["s"])

    log(f"Qualis matches (score ≥ {args.min_score}): {len(matches)}")
    log(f"Did not match: {len(all_rows) - len(matches)}")

    out = {
        "source":         SOURCE_TAG,
        "fetched_at":     datetime.now(timezone.utc).isoformat(),
        "total_fetched":  len(all_rows),
        "total_matched":  len(matches),
        "live":           matches,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    log(f"Written → {args.output}")
    log("Done.")


if __name__ == "__main__":
    main()
