#!/usr/bin/env python3
"""
nest_scraper.py — Qualis Tender Hunter v2  (NeST live biddable tenders)
========================================================================

Fetches currently-published tenders from NeST (Tanzania) via its public
GraphQL API and runs Qualis keyword matching on them.

v2 improvements (Session 6 performance audit):
  - AUTO-PAGINATION: first fetch detects total records, re-fetches if needed
    => never miss tenders due to page-size cap (was missing 63/day)
  - SCORE THRESHOLD: matches below MIN_SCORE are silently discarded
    => eliminates furniture/lab-equipment false positives from dashboard
  - FRAMEWORK BONUS: Framework Contracts get +5 (repeat high-value business)
  - TITLE CLEANING: strips stray newlines / leading whitespace from NeST titles
  - RICHER OUTPUT: deadline_days_left, value_tier, eligibility_local_only

Run:
    python nest_scraper.py
    python nest_scraper.py --debug         # show why tenders were excluded
    python nest_scraper.py --min-score 0   # show all matches including noise
    python nest_scraper.py --output FILE.json
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from keywords import STRONG_INCLUDE, SOFT_INCLUDE, HARD_EXCLUDE, PRIORITY_BUYERS

# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
GRAPHQL_URL  = "https://nest.go.tz/gateway/nest-app/graphql"
DEFAULT_OUT  = os.path.join(SCRIPT_DIR, "qualis_live_tenders.json")
MIN_SCORE    = 4          # discard matches below this score
FRAMEWORK_BONUS = 5       # framework contracts = repeat high-value business

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
    "Accept":       "application/json, text/plain, */*",
    "Referer":      "https://nest.go.tz/tenders/published-tenders",
    "User-Agent":   "QualisTenderHunter/2.0 (+Qualis Engineering Limited; info@qualiseng.com)",
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────────────────────────────────────
def fetch_tenders(page_size: int = 300) -> dict:
    """POST to NeST GraphQL and return parsed JSON."""
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
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(GRAPHQL_URL, data=body, headers=HEADERS, method="POST")
    log(f"POST {GRAPHQL_URL}  (pageSize={page_size})")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_all_tenders() -> tuple:
    """
    Auto-adaptive fetch: get page 1, check total, re-fetch with exact count if needed.
    Returns (rows, total_published).
    """
    resp = fetch_tenders(page_size=300)
    if resp.get("errors"):
        log(f"GraphQL errors: {resp['errors']}")
        sys.exit(2)

    items = (resp.get("data") or {}).get("items") or {}
    rows  = items.get("rows", [])
    total = items.get("totalRecords", 0)

    log(f"First fetch: got {len(rows)} of {total} published tenders")

    if total > len(rows):
        exact = total + 50          # buffer for tenders published mid-run
        log(f"Re-fetching with pageSize={exact} to capture all {total} tenders...")
        resp2  = fetch_tenders(page_size=exact)
        items2 = (resp2.get("data") or {}).get("items") or {}
        rows   = items2.get("rows", [])
        log(f"Second fetch: got {len(rows)} rows (target was {total})")

    return rows, total


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY BUYER
# ─────────────────────────────────────────────────────────────────────────────
def match_priority_buyer(buyer: str):
    """Return the matching priority pattern (lowercase) or None."""
    if not buyer:
        return None
    buyer_l = buyer.lower()
    for p in PRIORITY_BUYERS:
        if p and p in buyer_l:
            return p
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────────────────────────────────────
def score_tender(row: dict) -> dict:
    """
    Score one NeST tender row.

    Rules (in order):
      1. HARD_EXCLUDE wins absolutely - score=0, match=False
      2. STRONG keywords: +10 each
      3. SOFT keywords:   +2 each
      4. Framework Contract: +FRAMEWORK_BONUS
      5. match=True only if final score >= MIN_SCORE
    """
    title   = (row.get("descriptionOfTheProcurement") or "").strip().replace("\n", " ")
    sub_cat = row.get("entitySubCategoryName") or ""
    cat     = row.get("procurementCategoryName") or ""
    etype   = row.get("entityType") or ""
    haystack = " ".join([title, sub_cat, cat]).lower()

    # 1. Hard exclusion
    excluded_by = None
    for ex in HARD_EXCLUDE:
        if ex in haystack:
            excluded_by = ex
            break

    matched_kws = []
    score = 0

    if not excluded_by:
        for kw in STRONG_INCLUDE:
            if kw in haystack:
                score += 10
                matched_kws.append(kw)
        for kw in SOFT_INCLUDE:
            if kw in haystack:
                score += 2
                matched_kws.append(kw)

        # Framework contract bonus (repeat high-value business)
        if "FRAMEWORK" in etype.upper():
            score += FRAMEWORK_BONUS

    strong_hits = [k for k in matched_kws if k in STRONG_INCLUDE]
    soft_hits   = [k for k in matched_kws if k in SOFT_INCLUDE]

    if strong_hits:
        reason = "Strong: " + ", ".join(strong_hits[:3])
    elif soft_hits:
        reason = "Soft: " + ", ".join(soft_hits[:3])
    elif excluded_by:
        reason = f"Excluded: {excluded_by}"
    else:
        reason = "No match"

    return {
        "score":            score,
        "match":            score >= MIN_SCORE and not excluded_by,
        "matched_keywords": matched_kws,
        "reason":           reason,
        "excluded_by":      excluded_by,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def parse_deadline(d: str):
    if not d:
        return None
    try:
        dt = datetime.fromisoformat(d)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def days_left(deadline_dt):
    if deadline_dt is None:
        return None
    delta = deadline_dt - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds() / 86400))


def value_tier(score: int, etype: str) -> str:
    """Rough commercial value tier for sorting / display."""
    is_fw = "FRAMEWORK" in (etype or "").upper()
    if is_fw or score >= 30:
        return "HIGH"
    if score >= 15:
        return "MEDIUM"
    return "STANDARD"


def is_local_only(eligible: str) -> bool:
    """True if tender is restricted to local companies (no foreign competition)."""
    if not eligible:
        return False
    return "COMPANY_FOREIGN" not in eligible and "MANUFACTURER_FOREIGN" not in eligible


def clean_title(t: str) -> str:
    return (t or "").strip().replace("\n", " ").replace("  ", " ")


def summarize_row(row: dict, scoring: dict) -> dict:
    deadline_dt    = parse_deadline(row.get("submissionOrOpeningDate"))
    buyer          = row.get("procuringEntityName") or ""
    priority_match = match_priority_buyer(buyer)
    etype          = row.get("entityType") or ""
    eligible       = row.get("eligibleTypes") or ""
    score          = scoring["score"]

    return {
        "id":               row.get("entityId"),
        "entity_uuid":      row.get("entityUuid"),
        "ref":              row.get("referenceNumber"),
        "t":                clean_title(row.get("descriptionOfTheProcurement")),
        "buyer":            buyer,
        "buyer_uuid":       row.get("procuringEntityUuid"),
        "p":                priority_match is not None,
        "pm":               priority_match or "",
        "type":             etype,
        "cat":              row.get("procurementCategoryName"),
        "subcat":           row.get("entitySubCategoryName"),
        "fy":               row.get("financialYearCode"),
        "inv":              row.get("invitationDate"),
        "dl":               row.get("submissionOrOpeningDate"),
        "dl_days":          days_left(deadline_dt),
        "lots":             row.get("lotCount") or 1,
        "addendum":         row.get("hasAddendum") or False,
        "local_only":       is_local_only(eligible),
        "value_tier":       value_tier(score, etype),
        "s":                score,
        "r":                scoring["reason"],
        "k":                scoring["matched_keywords"],
        "u":                f"https://nest.go.tz/tenders/published-tender/{row.get('entityUuid')}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def run(output: str, debug: bool, min_score: int):
    rows, total_published = fetch_all_tenders()

    matches       = []
    excluded_samp = []
    no_match_samp = []
    below_thresh  = []

    for row in rows:
        sc = score_tender(row)
        if sc["match"]:
            matches.append(summarize_row(row, sc))
        elif debug:
            s = summarize_row(row, sc)
            if sc["excluded_by"] and len(excluded_samp) < 10:
                excluded_samp.append(s)
            elif sc["score"] > 0 and sc["score"] < min_score and len(below_thresh) < 10:
                below_thresh.append((s, sc["score"]))
            elif not sc["excluded_by"] and sc["score"] == 0 and len(no_match_samp) < 10:
                no_match_samp.append(s)

    # Sort: priority -> score (desc) -> deadline (asc)
    matches.sort(key=lambda m: (
        0 if m.get("p") else 1,
        -m["s"],
        m["dl"] or "9999",
    ))

    priority_count = sum(1 for m in matches if m.get("p"))
    high_value     = sum(1 for m in matches if m.get("value_tier") == "HIGH")

    # Build output JSON — dashboard expects both "live" and "matches" keys
    meta = {
        "built_at":             datetime.now(timezone.utc).isoformat(),
        "live_source":          "NeST published-tenders (live)",
        "live_generated_at":    datetime.now(timezone.utc).isoformat(),
        "live_total_pub":       total_published,
        "live_fetched":         len(rows),
        "live_match_count":     len(matches),
        "live_priority":        priority_count,
        "live_high_value":      high_value,
        "min_score_threshold":  min_score,
        "ocds_year":            "-",
        "ocds_total":           0,
        "ocds_relevant":        0,
        "ocds_match_count":     0,
        "ocds_generated_at":    None,
        "kw_top":               [],
    }

    out = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "source":          "NeST published-tenders (live)",
        "graphql_url":     GRAPHQL_URL,
        "total_published": total_published,
        "fetched":         len(rows),
        "match_count":     len(matches),
        "priority_count":  priority_count,
        "min_score":       min_score,
        "matches":         matches,   # legacy key (send_alert.py)
        "live":            matches,   # dashboard key
        "ocds":            [],
        "meta":            meta,
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # Console report
    sep = "=" * 78
    print()
    print(sep)
    print("  QUALIS LIVE-TENDER HUNTER v2 - NeST published-tenders")
    print(sep)
    print(f"  Total published on NeST :  {total_published:,}")
    print(f"  Fetched this run        :  {len(rows):,}")
    print(f"  Score threshold         :  >= {min_score}")
    print(f"  MATCHED Qualis profile  :  {len(matches):,}")
    print(f"  Priority buyer hits     :  {priority_count:,}")
    print(f"  High-value tenders      :  {high_value:,}  (Framework or score>=30)")
    if rows:
        print(f"  Match rate (of fetched) :  {100 * len(matches) / len(rows):.1f}%")
    print(sep)

    if not matches:
        print("  No Qualis matches above threshold. Use --min-score 0 to see all.")
    else:
        print()
        print("  TOP MATCHES:")
        print()
        for i, m in enumerate(matches, 1):
            star   = "*" if m.get("p") else " "
            tier   = f"[{m['value_tier']}]" if m["value_tier"] != "STANDARD" else ""
            dl_str = f"{m['dl_days']} days left" if m.get("dl_days") is not None else "deadline TBD"
            print(f"  [{i:>2}]{star} Score {m['s']:>3}  {tier:<8} {m['type']:<14} {(m['t'] or '')[:80]}")
            buyer_str = (m["buyer"] or "-")[:80]
            if m.get("p"):
                buyer_str += f"  [PRIORITY: '{m['pm']}']"
            print(f"       Buyer:    {buyer_str}")
            print(f"       Deadline: {m['dl']}  ({dl_str})")
            print(f"       Ref:      {m['ref']}")
            print(f"       Keywords: {', '.join(m['k'][:4])}")
            print(f"       URL:      {m['u']}")
            print()

    if debug:
        if below_thresh:
            print(sep)
            print(f"  DEBUG: {len(below_thresh)} matches BELOW score threshold ({min_score})")
            for s, sc in below_thresh:
                print(f"  LOW  score={sc}  {(s['t'] or '')[:80]}")
                print(f"       {s['r']}")
                print()
        if excluded_samp:
            print(sep)
            print(f"  DEBUG: {len(excluded_samp)} sample EXCLUDED tenders")
            for s in excluded_samp:
                print(f"  X    {(s['t'] or '')[:80]}")
                print(f"       {s['r']}")
                print()
        if no_match_samp:
            print(sep)
            print(f"  DEBUG: {len(no_match_samp)} samples with NO keyword match")
            for s in no_match_samp:
                print(f"  -    {(s['t'] or '')[:80]}")
                print(f"       cat={s['cat']}, sub={s['subcat']}")
                print()

    print(f"\n  Saved -> {output}")
    print()


def main():
    p = argparse.ArgumentParser(description="Qualis Live Tender Hunter v2 (NeST GraphQL)")
    p.add_argument("--output",    default=DEFAULT_OUT)
    p.add_argument("--min-score", type=int, default=MIN_SCORE,
                   help=f"Minimum score to include in output (default: {MIN_SCORE})")
    p.add_argument("--debug",     action="store_true",
                   help="Print excluded / below-threshold / no-match samples")
    args = p.parse_args()

    try:
        run(args.output, args.debug, args.min_score)
    except urllib.error.HTTPError as e:
        log(f"ERROR: HTTP {e.code} - {e.reason}")
        sys.exit(1)
    except urllib.error.URLError as e:
        log(f"ERROR: network - {e.reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
