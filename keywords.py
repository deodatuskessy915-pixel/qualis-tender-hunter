"""
Qualis Tender Hunter — Keyword Configuration
=============================================

The matching philosophy:
- INCLUDE keywords trigger a match (any one is enough)
- EXCLUDE keywords kill a match (any one disqualifies)
- Some keywords get extra weight (strong signals like "solar pv" or "33kv")

This is intentionally generous. Better to show Deodatus 10 tenders and
let him say "skip 3 of these" than to miss real opportunities.
"""

# Strong signals — these almost certainly mean Qualis work
STRONG_INCLUDE = [
    # Electrical work
    "electrical install",
    "electrical work",
    "electrical system",
    "electrical maintenance",
    "electrical fittings",
    "electrical materials",
    "electrical contractor",
    # Solar
    "solar pv",
    "solar system",
    "solar streetlight",
    "solar street light",
    "solar installation",
    "photovoltaic",
    # Generators
    "generator supply",
    "generator install",
    "generator maintenance",
    "standby generator",
    "genset",
    # Power infrastructure
    "33kv",
    "11kv",
    "substation",
    "transformer install",
    "power line",
    "transmission line",
    "distribution line",
    # UPS
    "ups system",
    "uninterruptible power",
    "uninterrupted power",
    # Hose
    "hydraulic hose",
    "pneumatic hose",
    "hose repair",
    "hose assembly",
    # Building materials (Qualis line of business)
    "cement supply",
    "supply of cement",
    "steel supply",
    "supply of steel",
    "building materials",
    # Common procurement phrases that fit Qualis
    "supply install test commission",
    "supply, installation, testing and commissioning",
    "design supply install",
    "design, supply and installation",
]

# Looser signals — relevant if not paired with exclusions
SOFT_INCLUDE = [
    "electrical",
    "electric",
    "solar",
    "generator",
    "ups",
    "substation",
    "transformer",
    "lighting",
    "streetlight",
    "street light",
    "hose",
    "hydraulic",
    "pneumatic",
    "switchgear",
    "cabling",
    "wiring",
    "panel board",
    "distribution board",
    "supply and install",
    "design and build",
    "commissioning",
    "hvac",
    "air conditioning",
    "ict installation",
    "structured cabling",
]

# Hard exclusions — these kill a match even if include keyword present
HARD_EXCLUDE = [
    # Food & hospitality
    "catering service",
    "food supply",
    "outside catering",
    "accommodation service",
    "hotel service",
    "tea and coffee",
    # Pure services we don't do
    "legal service",
    "legal counsel",
    "legal advisor",
    "advocate service",
    "translation service",
    "translator",
    "interpretation service",
    # Stationery / printing
    "printing service",
    "stationery supply",
    "supply of stationery",
    "office supplies",
    "managed print",
    # Pure transport
    "car hire",
    "vehicle hire",
    "fleet supply",
    "rental of vehicle",
    "fuel supply",
    # Training/consulting (no install)
    "training service",
    "training program",
    "consultancy service",
    "consulting service",
    "advisory service",
    "feasibility study",
    "needs assessment",
    "baseline survey",
    # Healthcare/medical (unless electrical install)
    "medical supplies",
    "pharmaceutical",
    "medicine supply",
    # Security guard service (not electrical security)
    "security guard",
    "security service personnel",
    # Insurance/finance
    "insurance service",
    "audit service",
    "financial service",
    # Cleaning
    "cleaning service",
    "janitorial",
    "fumigation",
    # Land/lease (unless ground install)
    "lease of land",
    "lease of space",
    "lease of office",
]

# When in doubt, these procurement methods are NOT what we want
EXCLUDE_PROCUREMENT_METHODS = [
    # We don't bid on "Direct" awards (already chosen supplier)
    "direct procurement",
]

# Regions Qualis operates in (used for boost, not exclusion)
OPERATING_REGIONS = [
    "dar es salaam",
    "mwanza",
    "mbeya",
    "iringa",
    "tabora",
    "arusha",
    "dodoma",
    "bagamoyo",
    "mkuranga",
    "morogoro",  # confirmed via sample tender
    "kilimanjaro",
    "tanga",
    "mtwara",
    "ruvuma",
    "shinyanga",  # client already there
    "singida",
    "kagera",
    "geita",
    "njombe",
    "rukwa",
    "katavi",
    "manyara",
    "songwe",
    "simiyu",
    "kigoma",
    "mara",
    "pwani",
    "lindi",
]

# Priority buyers — Qualis-prioritised procuring entities.
# Matching is case-insensitive substring, so partial names work:
#   "bank of tanzania" matches "BANK OF TANZANIA" and "Bank of Tanzania Mwanza Branch".
#
# To add a new priority buyer: just append a new line. No code changes elsewhere.
# Keep entries lowercase for clarity (matching is case-insensitive either way).
PRIORITY_BUYERS = [
    # Bank of Tanzania (BOT) — existing Qualis client. User-flagged top priority.
    "bank of tanzania",
    "bot",

    # Existing Qualis clients per PROJECT-KNOWLEDGE.md (the more they trust us, the easier the win)
    "oryx energies",
    "backlite media",
    "marie stopes",
    "azan logistics",
    "starlite media",
    "knauf gypsum",
    "imed",
    "toyota tanzania",
    "karimjee",
    "shinyanga municipal council",
    "emirate aluminium",
    "emirates aluminium",            # spelling variant
    "fresh spring fellowship",
    "alliance one tobacco",
    "tbl mwanza",
    "tanzania breweries",            # TBL = Tanzania Breweries Limited
    "cater & cure",
    "cater and cure",                # spelling variant
    "karibu tanzania",
    "emirates glass",
    "kapa manufacturing",
    "kkt sido arusha",
    "sido",                                         # SIDO acronym (rare — NeST usually publishes the full name)
    "small industries development organisation",    # SIDO long form — this is what NeST actually shows
    "ghl farm park",
]

# To add a buyer here later, just paste a new line above this comment.
# Lowercase, substring match. No code changes needed elsewhere — re-run
# nest_scraper.py to re-classify the next time you scrape.
