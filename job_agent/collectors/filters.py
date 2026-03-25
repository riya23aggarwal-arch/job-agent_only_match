"""
Shared filtering logic for all collectors.

Two-level filter applied BEFORE scoring:
  Level 1 — Title BLOCKLIST: instantly reject non-engineering roles
  Level 2 — Title ALLOWLIST: only pass roles with engineering keywords

Location filter: USA-only — rejects all non-US and ambiguous global locations.
"""

# ── LEVEL 1 — Hard blocklist ───────────────────────────────────────────────

TITLE_BLOCKLIST = [
    # Management — not IC roles
    "engineering manager", "senior manager", "staff manager",
    ", manager",  # "Technical Lead & Manager", "Lead & Manager"
    "& manager",
    " manager,",

    "director", "vp ", "vice president", "head of", "chief ",
    "cto", "ceo", "coo", "cfo",
    # Business / non-technical
    "marketing", "sales", "account executive", "account manager",
    "business development", "partnerships", "revenue",
    "recruiter", "recruiting", "talent acquisition", "hr ", "human resources",
    "finance", "accounting", "accountant", "payroll", "controller",
    "legal", "counsel", "compliance", "paralegal",
    "operations manager", "office manager", "executive assistant",
    "customer success", "customer support", "support engineer",
    "customer solutions", "solutions engineer", "field engineer",
    "pre-sales engineer", "sales engineer", "technical sales",
    "fullstack", "full stack", "full-stack",
    "frontend", "front end", "front-end",
    "backend engineer",  # usually web/API, not systems
    "mobile engineer", "android", "ios ",

    "content writer", "copywriter", "technical writer",
    "designer", " ux ", " ui ", "ux designer", "ui designer",
    "graphic design", "visual design",
    "product manager", "product owner", "program manager",
    "project manager", "scrum master", "agile coach",
    # Consultant / non-engineering IC
    "consultant", "solutions architect", "pre-sales", "presales",
    "developer advocate", "developer relations", "devrel",
    "technical account manager",
    # Wrong tech stacks
    "ios developer", "android developer", "mobile developer",
    "react developer", "frontend developer", "front-end developer",
    "ruby developer", "rails developer", "php developer",
    "data scientist", "data analyst", "data engineer",
    "ml engineer", "ai engineer", "ai researcher",
    "machine learning", "analytics engineer",
    "blockchain", "web3", "solidity",
    "seo ", "growth hacker", "digital marketing", "social media",
]

# ── LEVEL 2 — Allowlist ────────────────────────────────────────────────────

TITLE_ALLOWLIST = [
    "software engineer", "systems engineer", "platform engineer",
    "infrastructure engineer", "network engineer", "kernel engineer",
    "firmware engineer", "embedded engineer", "hardware engineer",
    "linux engineer", "driver engineer", "bsp engineer",
    "sre", "site reliability", "devops engineer",
    "security engineer", "automation engineer", "test engineer",
    "qa engineer", "release engineer", "build engineer",
    "software developer", "systems developer",
    "staff engineer", "principal engineer", "senior engineer",
    "tech lead", "technical lead", "architect",
    "fpga", "asic", "silicon", "vlsi",
    "engineer",      # catch-all
    "developer",      # "Linux Kernel Developer", "Driver Developer"
    "programmer",     # "Systems Programmer"
]

# ── USA location filter ────────────────────────────────────────────────────

# Explicit US cities and signals — must match one of these to be accepted
USA_SIGNALS = [
    # Bay Area
    "san jose", "san francisco", "santa clara", "sunnyvale",
    "mountain view", "palo alto", "menlo park", "redwood city",
    "san mateo", "fremont", "oakland", "berkeley", "milpitas",
    "cupertino", "campbell", "los gatos", "saratoga",
    "bay area", "silicon valley",
    # Other major US tech cities
    "seattle", "bellevue", "kirkland", "redmond",
    "new york", "brooklyn", "manhattan",
    "austin", "dallas", "houston",
    "boston", "cambridge",
    "chicago",
    "denver", "boulder",
    "atlanta",
    "raleigh", "durham",
    "los angeles", "santa monica", "culver city",
    "san diego",
    "portland",
    "phoenix", "scottsdale",
    "detroit", "ann arbor",
    "pittsburgh",
    "minneapolis",
    "miami", "fort lauderdale",
    "washington dc", "washington, dc", "arlington", "bethesda",
    "salt lake city",
    "nashville",
    # State full names
    "california", "oregon", "washington state", "texas", "new york state",
    "massachusetts", "colorado", "georgia", "illinois", "virginia",
    # State abbreviations (with comma or space — avoids partial matches)
    ", ca", "(ca)", " ca,",
    ", wa", ", tx", ", ny", ", ma", ", co",
    ", ga", ", nc", ", il", ", oh", ", mi",
    ", or", ", az", ", fl", ", va", ", md",
    ", ut", ", tn", ", mn", ", pa",
    # Explicit US markers
    "united states", ", us", " us ", "usa", "u.s.", "u.s.a",
    # Remote — must say US or have no country
    "us remote", "remote us", "remote - us", "remote (us",
    "remote, us", "united states remote",
]

# Ambiguous global terms — these sound remote-friendly but include non-US
GLOBAL_BLOCKLIST = [
    "worldwide", "global", "anywhere in the world",
    "north america",   # includes Canada
    "americas",        # includes South America
    "international",
    "emea", "apac", "latam",
    "europe", "european",
]

# Explicit non-US countries
NON_USA_BLOCKLIST = [
    "portugal", "lisbon", "porto",
    "united kingdom", "london", "manchester", "edinburgh", "birmingham",
    "germany", "berlin", "munich", "frankfurt", "hamburg",
    "france", "paris", "lyon", "marseille",
    "netherlands", "amsterdam", "rotterdam",
    "ireland", "dublin",
    "canada", "toronto", "vancouver", "montreal", "ottawa",
    "india", "bangalore", "hyderabad", "pune", "chennai", "mumbai", "delhi",
    "singapore",
    "australia", "sydney", "melbourne", "brisbane",
    "israel", "tel aviv",
    "poland", "warsaw", "krakow",
    "spain", "madrid", "barcelona",
    "sweden", "stockholm",
    "switzerland", "zurich", "geneva",
    "japan", "tokyo",
    "china", "beijing", "shanghai",
    "brazil", "sao paulo",
    "mexico", "mexico city",
    "new zealand", "auckland",
    "denmark", "copenhagen",
    "norway", "oslo",
    "finland", "helsinki",
    "austria", "vienna",
    "belgium", "brussels",
    "czech republic", "prague",
    "hungary", "budapest",
    "romania", "bucharest",
    "ukraine", "kyiv",
    "turkey", "istanbul",
    "south africa", "cape town", "johannesburg",
    "kenya", "nairobi",
    "nigeria", "lagos",
]


def passes_title_filter(title: str) -> tuple[bool, str]:
    """Returns (passes, reason)."""
    t = title.lower().strip()

    for blocked in TITLE_BLOCKLIST:
        if blocked in t:
            return False, f"blocklist: '{blocked}'"

    for allowed in TITLE_ALLOWLIST:
        if allowed in t:
            return True, "ok"

    return False, "no engineering keyword in title"


def passes_location_filter(location: str) -> tuple[bool, str]:
    """
    USA-only filter. Returns (passes, reason).

    Logic:
      1. Empty / truly unknown → pass (can't tell)
      2. Explicit non-US country → block
      3. Ambiguous global terms (Worldwide, Global) → block
      4. Known US city/state signal → pass
      5. Plain "Remote" with no country → pass (assume US unless proven otherwise)
      6. Anything else unrecognised → block (safer default)
    """
    if not location:
        return True, "empty — pass"

    loc = location.lower().strip()

    # Empty / placeholder values
    if loc in ("unknown", "not specified", "tbd", "see job description", "flexible", "anywhere"):
        return True, "unknown — pass"

    # Multi-location Workday jobs ("2 Locations", "3 Locations") — pass through
    # The actual locations are revealed on the detail page; don't drop them here
    import re
    if re.match(r"^\d+\s+locations?$", loc):
        return True, "multi-location — pass through"

    # Hard block non-US countries
    for non_us in NON_USA_BLOCKLIST:
        if non_us in loc:
            return False, f"non-US: '{non_us}'"

    # Block ambiguous global terms
    for global_term in GLOBAL_BLOCKLIST:
        if global_term in loc:
            return False, f"global/ambiguous: '{global_term}'"

    # Accept known US signals
    for us in USA_SIGNALS:
        if us in loc:
            return True, f"US signal: '{us}'"

    # Plain "remote" with no other context → accept (assume US)
    if loc in ("remote", "remote.", "hybrid", "hybrid remote"):
        return True, "plain remote — pass"

    # Remote mentioned alongside no country → accept
    if "remote" in loc and not any(n in loc for n in NON_USA_BLOCKLIST):
        return True, "remote (no non-US country) — pass"

    # Unrecognised location — block (safer than letting garbage through)
    return False, f"unrecognised location: '{location}'"
