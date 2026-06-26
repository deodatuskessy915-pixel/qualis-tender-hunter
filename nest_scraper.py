#!/usr/bin/env python3
"""
nest_scraper.py — Qualis Tender Hunter v3  (NeST live biddable tenders)
========================================================================

v3 improvements (Phase 2):
  - ALL-CATEGORY FETCH: scrapes Works / Goods / Non Consultancy / Consultancy
    separately, then merges — eliminates the NeST 200-row server cap entirely.
    Now captures all 262+ published tenders every run (was missing ~62/day).
  - SMART VALUE ESTIMATION: NeST exposes no financial data in its public API,
    so we derive intelligent TZS brackets from category, entity type, buyer
    tier, and matched keywords.  Labels are clearly marked "(est)".
  - DEDUPLICATION: entity IDs deduplicated across category fetches.
  - All v2 features retained: keyword scoring, framework bonus, priority buyers,
    deadline days, local-only flag, debug mode.

Run:
    python nest_scraper.py
    python nest_scraper.py --debug
    python nest_scraper.py --min-score 0
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
MIN_SCORE    = 4
FRAMEWORK_BONUS = 5

# All procurement categories on NeST — fetched separately to bust 200-row cap
NEST_CATEGORIES = ["Works", "Goods", "Non Consultancy", "Consultancy"]

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
    "User-Agent":   "QualisTenderHunter/3.0 (+Qualis Engineering Limited; info@qualiseng.com)",
}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# FETCH  (category-filtered, paginated)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_category(category: str, page: int = 1, page_size: int = 200) -> dict:
    """POST to NeST GraphQL filtered by one procurement category."""
    payload = {
        "operationName": "getPublishedEntityViewData",
        "variables": {
            "input": {
                "page": page,
                "pageSize": page_size,
                "fields": [
                    {"fieldName": "invitationDate", "isSortable": True, "orderDirection": "DESC"}
                ],
                "mustHaveFilters": [
                    {"fieldName": "entityStatus",
                     "operation": "IN", "inValues": ["PUBLISHED"]},
                    {"fieldName": "procurementCategoryName",
                     "operation": "IN", "inValues": [category]},
                ],
            }
        },
        "query": GRAPHQL_QUERY,
    }
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(GRAPHQL_URL, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_all_tenders() -> tuple:
    """
    Fetch every category separately, paginate within each if > 200,
    then merge + deduplicate by entityId.
    Returns (unique_rows, total_published_count).
    """
    all_rows    = []
    seen_ids    = set()
    total_nest  = 0

    for cat in NEST_CATEGORIES:
        page      = 1
        cat_total = None

        while True:
            log(f"Fetching {cat!r}  page={page} ...")
            resp = fetch_category(cat, page=page, page_size=200)

            if resp.get("errors"):
                log(f"  GraphQL errors for {cat}: {resp['errors']}")
                break

            items    = (resp.get("data") or {}).get("items") or {}
            rows     = items.get("rows", [])
            total    = items.get("totalRecords", 0)

            if cat_total is None:
                cat_total = total
                total_nest += total
                log(f"  {cat}: {total} published tenders")

            for row in rows:
                eid = row.get("entityId")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    all_rows.append(row)

            fetched_so_far = (page - 1) * 200 + len(rows)
            if fetched_so_far >= cat_total or not rows:
                break
            page += 1

    log(f"Total fetched: {len(all_rows)} unique tenders across {len(NEST_CATEGORIES)} categories")
    return all_rows, total_nest


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY BUYER
# ─────────────────────────────────────────────────────────────────────────────
def match_priority_buyer(buyer: str):
    if not buyer:
        return None
    buyer_l = buyer.lower()
    for p in PRIORITY_BUYERS:
        if p and p in buyer_l:
            return p
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SMART VALUE ESTIMATION
# (NeST publishes no financial data — we derive TZS brackets from context)
# ─────────────────────────────────────────────────────────────────────────────
# High-value keyword patterns and their estimated brackets
VALUE_SIGNALS_HIGH = [
    "transmission line", "distribution network", "mini-grid", "power plant",
    "substation", "hydropower", "solar pv system", "solar power", "wind farm",
    "electrical installation works", "lv distribution", "mv distribution",
    "marine", "port", "airport", "highway", "bridge", "dam", "water supply system",
    "bulk supply", "turnkey",
]
VALUE_SIGNALS_MEDIUM = [
    "solar", "generator", "transformer", "switchgear", "ups system",
    "electrical installation", "borehole", "water treatment", "irrigation",
    "construction", "rehabilitation", "renovation", "upgrade",
    "supply and installation", "supply of", "erection",
]

# Buyer tier — proxy for contract size
LARGE_BUYERS = [
    "tanesco", "tanroads", "tpa", "tazara", "tpdc", "dawasco", "ruwasa",
    "rea ", "nhc", "nssf", "ppf", "nic", "ticts", "dar es salaam",
    "ministry", "minister", "national", "authority", "agency", "commission",
    "board", "corporation", "institute", "university", "hospital",
]


def estimate_value(row: dict, score: int, matched_kws: list) -> dict:
    """
    Returns value_est (display string) and value_tier (HIGH / MEDIUM / STANDARD).
    Brackets are estimates only — NeST does not expose actual contract values.
    """
    cat    = (row.get("procurementCategoryName") or "").lower()
    etype  = (row.get("entityType") or "").upper()
    buyer  = (row.get("procuringEntityName") or "").lower()
    title  = (row.get("descriptionOfTheProcurement") or "").lower()
    hay    = title + " " + buyer

    is_framework = "FRAMEWORK" in etype
    is_works     = "works" in cat
    is_goods     = "goods" in cat

    # Framework contracts are always long-term high value
    if is_framework:
        return {"value_est": "TZS 500M+ (est)", "value_tier": "HIGH",
                "value_basis": "framework contract"}

    # Check high-value signals
    for sig in VALUE_SIGNALS_HIGH:
        if sig in hay:
            bracket = "TZS 1B+ (est)" if is_works else "TZS 200M–1B (est)"
            return {"value_est": bracket, "value_tier": "HIGH",
                    "value_basis": f"signal: {sig}"}

    # Large buyer boosts estimate
    large_buyer = any(lb in buyer for lb in LARGE_BUYERS)

    # Medium signals
    for sig in VALUE_SIGNALS_MEDIUM:
        if sig in hay:
            if is_works and large_buyer:
                bracket = "TZS 200M–1B (est)"
                tier    = "HIGH"
            elif is_works:
                bracket = "TZS 50M–500M (est)"
                tier    = "MEDIUM"
            else:
                bracket = "TZS 20M–200M (est)"
                tier    = "MEDIUM"
            return {"value_est": bracket, "value_tier": tier,
                    "value_basis": f"signal: {sig}"}

    # Category defaults
    if is_works and large_buyer:
        return {"value_est": "TZS 50M–500M (est)", "value_tier": "MEDIUM",
                "value_basis": "Works + large buyer"}
    if is_works:
        return {"value_est": "TZS 20M–200M (est)", "value_tier": "MEDIUM",
                "value_basis": "Works"}
    if is_goods and large_buyer:
        return {"value_est": "TZS 20M–200M (est)", "value_tier": "MEDIUM",
                "value_basis": "Goods + large buyer"}
    if is_goods:
        return {"value_est": "TZS 5M–50M (est)", "value_tier": "STANDARD",
                "value_basis": "Goods"}

    return {"value_est": "TZS 5M–50M (est)", "value_tier": "STANDARD",
            "value_basis": cat or "unknown"}


# ─────────────────────────────────────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────────────────────────────────────
def score_tender(row: dict) -> dict:
    title    = (row.get("descriptionOfTheProcurement") or "").strip().replace("\n", " ")
    sub_cat  = row.get("entitySubCategoryName") or ""
    cat      = row.get("procurementCategoryName") or ""
    etype    = row.get("entityType") or ""
    haystack = " ".join([title, sub_cat, cat]).lower()

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


def days_left(deadline_dt) -> int | None:
    if deadline_dt is None:
        return None
    delta = deadline_dt - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds() / 86400))


def is_local_only(eligible: str) -> bool:
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
    val            = estimate_value(row, score, scoring["matched_keywords"])

    return {
        "id":          row.get("entityId"),
        "entity_uuid": row.get("entityUuid"),
        "ref":         row.get("referenceNumber"),
        "t":           clean_title(row.get("descriptionOfTheProcurement")),
        "buyer":       buyer,
        "buyer_uuid":  row.get("procuringEntityUuid"),
        "p":           priority_match is not None,
        "pm":          priority_match or "",
        "type":        etype,
        "cat":         row.get("procurementCategoryName"),
        "subcat":      row.get("entitySubCategoryName"),
        "fy":          row.get("financialYearCode"),
        "inv":         row.get("invitationDate"),
        "dl":          row.get("submissionOrOpeningDate"),
        "dl_days":     days_left(deadline_dt),
        "lots":        row.get("lotCount") or 1,
        "addendum":    row.get("hasAddendum") or False,
        "local_only":  is_local_only(eligible),
        "value_est":   val["value_est"],
        "value_tier":  val["value_tier"],
        "value_basis": val["value_basis"],
        "s":           score,
        "r":           scoring["reason"],
        "k":           scoring["matched_keywords"],
        "u":           f"https://nest.go.tz/tenders/published-tender/{row.get('entityUuid')}",
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

    matches.sort(key=lambda m: (
        0 if m.get("p") else 1,
        -m["s"],
        m["dl"] or "9999",
    ))

    priority_count = sum(1 for m in matches if m.get("p"))
    high_value     = sum(1 for m in matches if m.get("value_tier") == "HIGH")
    unique_fetched = len(rows)

    meta = {
        "built_at":             datetime.now(timezone.utc).isoformat(),
        "live_source":          "NeST published-tenders (live, all-category v3)",
        "live_generated_at":    datetime.now(timezone.utc).isoformat(),
        "live_total_pub":       total_published,
        "live_fetched":         unique_fetched,
        "live_match_count":     len(matches),
        "live_priority":        priority_count,
        "live_high_value":      high_value,
        "min_score_threshold":  min_score,
        "categories_scraped":   NEST_CATEGORIES,
        "value_note":           "TZS values are estimates — NeST does not publish contract values",
        "ocds_year":            "—",
        "ocds_total":           0,
        "ocds_relevant":        0,
        "ocds_match_count":     0,
        "ocds_generated_at":    None,
        "kw_top":               [],
    }

    out = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "source":          "NeST published-tenders (live, all-category v3)",
        "graphql_url":     GRAPHQL_URL,
        "total_published": total_published,
        "fetched":         unique_fetched,
        "match_count":     len(matches),
        "priority_count":  priority_count,
        "min_score":       min_score,
        "matches":         matches,
        "live":            matches,
        "ocds":            [],
        "meta":            meta,
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    separator = "═" * 78
    print()
    print(separator)
    print("  QUALIS LIVE-TENDER HUNTER v3 — NeST all-category fetch")
    print(separator)
    print(f"  Categories scraped      :  {', '.join(NEST_CATEGORIES)}")
    print(f"  Total published on NeST :  {total_published:,}")
    print(f"  Unique tenders fetched  :  {unique_fetched:,}  (cap eliminated)")
    print(f"  Score threshold         :  >= {min_score}")
    print(f"  MATCHED Qualis profile  :  {len(matches):,}")
    print(f"  -> Priority buyer hits  :  {priority_count:,}")
    print(f"  -> High-value tenders   :  {high_value:,}")
    if rows:
        print(f"  Match rate (of fetched) :  {100 * len(matches) / len(rows):.1f}%")
    print(separator)

    if not matches:
        print()
        print("  No Qualis matches above threshold.")
    else:
        print()
        print("  TOP MATCHES:")
        print()
        for i, m in enumerate(matches, 1):
            star  = "★" if m.get("p") else " "
            val   = m.get("value_est", "—")
            dl_str = f"{m['dl_days']} days left" if m.get("dl_days") is not None else "deadline TBD"
            print(f"  [{i:>2}]{star} Score {m['s']:>3}  {m['type']:<16}  {(m['t'] or '')[:70]}")
            buyer_str = (m["buyer"] or "—")[:70]
            if m.get("p"):
                buyer_str += f"  [PRIORITY: '{m['pm']}']"
            print(f"       Buyer:    {buyer_str}")
            print(f"       Value:    {val}  (basis: {m.get('value_basis', '—')})")
            print(f"       Deadline: {m['dl']}  ({dl_str})")
            print(f"       Ref:      {m['ref']}")
            print(f"       Keywords: {', '.join(m['k'][:4])}")
            print(f"       URL:      {m['u']}")
            print()

    if debug:
        if below_thresh:
            print(separator)
            print(f"  DEBUG: {len(below_thresh)} matches BELOW score threshold ({min_score})")
            for s, sc in below_thresh:
                print(f"  LOW  score={sc}  {(s['t'] or '')[:80]}")
                print(f"       {s['r']}")
        if excluded_samp:
            print(separator)
            print(f"  DEBUG: {len(excluded_samp)} sample EXCLUDED tenders")
            for s in excluded_samp:
                print(f"  X    {(s['t'] or '')[:80]}")
                print(f"       {s['r']}")
        if no_match_samp:
            print(separator)
            print(f"  DEBUG: {len(no_match_samp)} samples with NO keyword match")
            for s in no_match_samp:
                print(f"  -    {(s['t'] or '')[:80]}")

    print(f"\n  Saved -> {output}")
    print()


def main():
    p = argparse.ArgumentParser(description="Qualis Live Tender Hunter v3")
    p.add_argument("--output",    default=DEFAULT_OUT)
    p.add_argument("--min-score", type=int, default=MIN_SCORE)
    p.add_argument("--debug",     action="store_true")
    args = p.parse_args()
    try:
        run(args.output, args.debug, args.min_score)
    except urllib.error.HTTPError as e:
        log(f"ERROR: HTTP {e.code} — {e.reason}")
        sys.exit(1)
    except urllib.error.URLError as e:
        log(f"ERROR: network — {e.reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
