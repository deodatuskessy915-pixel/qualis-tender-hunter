#!/usr/bin/env python3
"""
nest_scraper.py — Qualis Tender Hunter, Phase 2 (live biddable tenders)

Fetches currently-published tenders from NeST (Tanzania) via its public
GraphQL API and runs Qualis keyword matching on them. Outputs a JSON file
with everything needed for the dashboard (buyer + deadline + score).

Discovery (2026-05-31): the Angular app at nest.go.tz/tenders/published-tenders
calls a public GraphQL endpoint at
    https://nest.go.tz/gateway/nest-app/graphql
with the operation getPublishedEntityViewData. No auth required. This script
replays that same call with pageSize=200 so we get all currently open tenders
in one round-trip (~92 at last count, well under 200).

NOTE: This SUPERSEDES the original per-ocid scraping plan, which was killed
when we discovered NeST returns 404 for OCDS planning-stage ocids. See
the project memory and PROJECT-KNOWLEDGE.md Session 4 log for the path.

Run:
    python nest_scraper.py
    python nest_scraper.py --debug             # show why a tender was excluded
    python nest_scraper.py --output FILE.json  # custom output path

Output:
    qualis_live_tenders.json  (next to this script, in the workspace folder)
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from keywords import STRONG_INCLUDE, SOFT_INCLUDE, HARD_EXCLUDE, PRIORITY_BUYERS


def match_priority_buyer(buyer: str):
    """Return the matching priority-buyer pattern (or None) for a tender buyer.
    Matching is case-insensitive substring against PRIORITY_BUYERS."""
    if not buyer:
        return None
    buyer_l = buyer.lower()
    for p in PRIORITY_BUYERS:
        if p and p in buyer_l:
            return p
    return None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPHQL_URL = "https://nest.go.tz/gateway/nest-app/graphql"
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "qualis_live_tenders.json")

# Exact query captured from the live Angular app (verified 2026-05-31).
GRAPHQL_QUERY = """query getPublishedEntityViewData($input: DataRequestInputInput, $withMetaData: Boolean) {
  items: getPublishedEntityViewData(input: $input, withMetaData: $withMetaData) {
    totalPages
    totalRecords
    currentPage
    last
    first
    hasNext
    hasPrevious
    numberOfRecords
    recordsFilteredCount
    pageSize
    rows: data {
      descriptionOfTheProcurement
      entityId
      entityNumber
      entityStatus
      entitySubCategoryAcronym
      entitySubCategoryName
      entityType
      uuid: entityUuid
      entityUuid
      financialYearCode
      id
      invitationDate
      lotCount
      hasAddendum
      eligibleTypes
      procurementCategoryName
      procurementCategoryAcronym: entityCategoryAcronym
      procuringEntityLogoUuid
      procuringEntityName
      procuringEntityUuid
      submissionOrOpeningDate
      referenceNumber
    }
  }
}"""

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://nest.go.tz/tenders/published-tenders",
    "User-Agent": "QualisTenderHunter/1.0 (+Qualis Engineering Limited; info@qualiseng.com)",
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


def fetch_published_tenders(page_size: int = 200) -> dict:
    """Call NeST's GraphQL endpoint and return the parsed response."""
    payload = {
        "operationName": "getPublishedEntityViewData",
        "variables": {
            "input": {
                "page": 1,
                "pageSize": page_size,
                "fields": [
                    {"fieldName": "invitationDate", "isSortable": True, "orderDirection": "DESC"}
                ],
                "mustHaveFilters": [
                    {"fieldName": "entityStatus", "operation": "IN", "inValues": ["PUBLISHED"]}
                ],
            }
        },
        "query": GRAPHQL_QUERY,
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(GRAPHQL_URL, data=body_bytes, headers=HEADERS, method="POST")
    log(f"POST {GRAPHQL_URL}  (pageSize={page_size})")
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8", errors="replace"))


# --- Qualis scoring ----------------------------------------------------------
def score_tender_row(row: dict) -> dict:
    """Apply Qualis matching rules to one NeST published-tender row.
    Field names differ from the OCDS matcher, but the rules are the same:
    HARD_EXCLUDE wins absolute, otherwise STRONG=10 / SOFT=2 per match.
    """
    title = row.get("descriptionOfTheProcurement") or ""
    sub_cat = row.get("entitySubCategoryName") or ""
    cat = row.get("procurementCategoryName") or ""
    haystack = " ".join([title, sub_cat, cat]).lower()

    # Hard exclusions take precedence over any include hit
    excluded_by = None
    for ex in HARD_EXCLUDE:
        if ex in haystack:
            excluded_by = ex
            break

    matched_keywords = []
    score = 0
    if not excluded_by:
        for kw in STRONG_INCLUDE:
            if kw in haystack:
                score += 10
                matched_keywords.append(kw)
        for kw in SOFT_INCLUDE:
            if kw in haystack:
                score += 2
                matched_keywords.append(kw)

    strong_hits = [k for k in matched_keywords if k in STRONG_INCLUDE]
    soft_hits = [k for k in matched_keywords if k in SOFT_INCLUDE]
    if strong_hits:
        reason = "Strong: " + ", ".join(strong_hits[:3])
    elif soft_hits:
        reason = "Soft: " + ", ".join(soft_hits[:3])
    elif excluded_by:
        reason = f"Excluded: {excluded_by}"
    else:
        reason = "No match"

    return {
        "score": score,
        "match": score > 0 and not excluded_by,
        "matched_keywords": matched_keywords,
        "reason": reason,
        "excluded_by": excluded_by,
    }


def parse_deadline(d: str):
    if not d:
        return None
    try:
        # NeST gives 'YYYY-MM-DDTHH:MM' in Tanzania local time (UTC+3).
        # We don't apply the offset because comparison precision is in days.
        dt = datetime.fromisoformat(d)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def summarize_row(row: dict, scoring: dict) -> dict:
    deadline_dt = parse_deadline(row.get("submissionOrOpeningDate"))
    buyer = row.get("procuringEntityName")
    priority_match = match_priority_buyer(buyer or "")
    return {
        "entity_id": row.get("entityId"),
        "entity_uuid": row.get("entityUuid"),
        "reference_number": row.get("referenceNumber"),
        "entity_number": row.get("entityNumber"),
        "title": row.get("descriptionOfTheProcurement"),
        "buyer": buyer,
        "buyer_uuid": row.get("procuringEntityUuid"),
        "priority": priority_match is not None,
        "priority_match": priority_match,
        "entity_type": row.get("entityType"),                   # FRAMEWORK / TENDER
        "category": row.get("procurementCategoryName"),         # Goods / Works / Non Consultancy
        "category_acronym": row.get("procurementCategoryAcronym"),
        "sub_category": row.get("entitySubCategoryName"),
        "financial_year": row.get("financialYearCode"),
        "invitation_date": row.get("invitationDate"),
        "deadline": row.get("submissionOrOpeningDate"),
        "deadline_dt": deadline_dt.isoformat() if deadline_dt else None,
        "lot_count": row.get("lotCount"),
        "has_addendum": row.get("hasAddendum"),
        "eligible_types": row.get("eligibleTypes"),
        "score": scoring["score"],
        "reason": scoring["reason"],
        "matched_keywords": scoring["matched_keywords"],
        "nest_url": f"https://nest.go.tz/tenders/published-tender/{row.get('entityUuid')}",
    }


def run(output: str, debug: bool, page_size: int):
    response = fetch_published_tenders(page_size=page_size)

    if response.get("errors"):
        log(f"GraphQL errors: {response['errors']}")
        sys.exit(2)

    items = ((response.get("data") or {}).get("items") or {})
    rows = items.get("rows", [])
    total_records = items.get("totalRecords", 0)
    log(f"Got {len(rows)} of {total_records} published tenders")

    if total_records > len(rows):
        log(f"WARNING: pageSize ({page_size}) is smaller than total records ({total_records}). "
            f"Re-run with --page-size {total_records + 10}.")

    matches = []
    excluded_samples = []
    no_match_samples = []
    for row in rows:
        scoring = score_tender_row(row)
        if scoring["match"]:
            matches.append(summarize_row(row, scoring))
        elif debug:
            sample = summarize_row(row, scoring)
            if scoring["excluded_by"] and len(excluded_samples) < 10:
                excluded_samples.append(sample)
            elif not scoring["excluded_by"] and len(no_match_samples) < 10:
                no_match_samples.append(sample)

    # Sort: priority buyers first, then highest score, then earliest deadline.
    # Priority comes BEFORE score because a known-relationship buyer changes
    # the cost-of-bidding calculus — even a soft-score Qualis tender is worth
    # a look if it's a current client.
    matches.sort(key=lambda m: (
        0 if m.get("priority") else 1,
        -m["score"],
        m["deadline"] or "9999",
    ))

    priority_count = sum(1 for m in matches if m.get("priority"))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "NeST published-tenders (live)",
        "graphql_url": GRAPHQL_URL,
        "total_published": total_records,
        "fetched": len(rows),
        "match_count": len(matches),
        "priority_count": priority_count,
        "matches": matches,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # --- Report ---
    print()
    print("=" * 78)
    print("  QUALIS LIVE-TENDER HUNTER — NeST published-tenders")
    print("=" * 78)
    print(f"  Total published on NeST:       {total_records:,}")
    print(f"  Fetched in this run:           {len(rows):,}")
    print(f"  MATCHED QUALIS PROFILE:        {len(matches):,}")
    print(f"  ...of which PRIORITY BUYER:    {priority_count:,}")
    if rows:
        print(f"  Match rate:                    {100 * len(matches) / len(rows):.1f}%")
    print("=" * 78)
    print()

    if not matches:
        print("  No Qualis matches in the current published-tenders set.")
        print("  Use --debug to see why each tender was filtered.")
    else:
        print(f"  TOP MATCHES (best first):")
        print()
        for i, m in enumerate(matches, 1):
            star = "*" if m.get("priority") else " "
            print(f"  [{i:>2}]{star}Score {m['score']:>3}  {m['entity_type']:<10s} — {(m['title'] or '')[:90]}")
            buyer_str = (m['buyer'] or '-')[:80]
            if m.get("priority"):
                buyer_str = f"{buyer_str}  [PRIORITY: matched '{m['priority_match']}']"
            print(f"       Buyer:    {buyer_str}")
            print(f"       Deadline: {m['deadline']}")
            print(f"       Ref:      {m['reference_number']}")
            print(f"       Matched:  {', '.join(m['matched_keywords'][:4])}")
            print(f"       Page:     {m['nest_url']}")
            print()

    print(f"  Full results saved: {output}")

    if debug:
        if excluded_samples:
            print()
            print("=" * 78)
            print(f"  DEBUG: {len(excluded_samples)} samples of EXCLUDED tenders")
            print("=" * 78)
            for s in excluded_samples:
                print(f"  X  {(s['title'] or '')[:80]}")
                print(f"     {s['reason']}")
                print()
        if no_match_samples:
            print("=" * 78)
            print(f"  DEBUG: {len(no_match_samples)} samples with NO KEYWORD MATCH")
            print("=" * 78)
            for s in no_match_samples:
                print(f"  -  {(s['title'] or '')[:80]}")
                print(f"     cat={s['category']}, sub={s['sub_category']}")
                print()


def main():
    p = argparse.ArgumentParser(description="Qualis Live Tender Hunter (NeST GraphQL)")
    p.add_argument("--output", default=DEFAULT_OUTPUT,
                   help=f"Output JSON path (default: {DEFAULT_OUTPUT})")
    p.add_argument("--page-size", type=int, default=200,
                   help="GraphQL pageSize (default: 200 — enough for all currently-open NeST tenders)")
    p.add_argument("--debug", action="store_true",
                   help="Print samples of excluded / non-matching tenders too")
    args = p.parse_args()

    try:
        run(args.output, args.debug, args.page_size)
    except urllib.error.HTTPError as e:
        log(f"ERROR: HTTP {e.code} — {e.reason}")
        sys.exit(1)
    except urllib.error.URLError as e:
        log(f"ERROR: network — {e.reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
