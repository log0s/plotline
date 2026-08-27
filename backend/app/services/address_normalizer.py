"""Address normalization and fuzzy matching for county record lookups.

County property records use wildly inconsistent address formats.
This module provides utilities to normalize addresses for comparison
and to extract search terms for Socrata LIKE queries.
"""

from __future__ import annotations

import re

# Standard USPS suffix abbreviations
SUFFIX_MAP = {
    "AVENUE": "AVE",
    "AV": "AVE",
    "STREET": "ST",
    "BOULEVARD": "BLVD",
    "DRIVE": "DR",
    "ROAD": "RD",
    "LANE": "LN",
    "COURT": "CT",
    "PLACE": "PL",
    "CIRCLE": "CIR",
    "TERRACE": "TER",
    "PARKWAY": "PKWY",
    "WAY": "WAY",
    "TRAIL": "TRL",
    "HIGHWAY": "HWY",
    "EXPRESSWAY": "EXPY",
    "FREEWAY": "FWY",
    "ALLEY": "ALY",
    "CROSSING": "XING",
}

# Spelled-out directionals → their abbreviation. Counties disagree here:
# the Census geocoder emits "E 17TH ST" while NYC DOB emits "EAST 17 STREET".
DIRECTIONAL_MAP = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}

# Two-letter directional abbreviations, plus the spelled-out forms
DIRECTIONALS = set(DIRECTIONAL_MAP) | set(DIRECTIONAL_MAP.values())

# 17TH → 17, 1ST → 1. Numeric tokens only: a bare "ST" is a street suffix
# and "MAIN" isn't an ordinal, so anchoring on leading digits is the whole
# guard we need.
_ORDINAL_RE = re.compile(r"^(\d+)(?:ST|ND|RD|TH)$")


def normalize_address(address: str) -> str:
    """Normalize an address for fuzzy matching against county records.

    - Uppercases
    - Strips punctuation that would otherwise stick to tokens ("AVE," vs "AVE")
    - Strips unit/apt/suite/# suffixes
    - Standardizes street type suffixes (AVENUE → AVE, etc.)
    - Abbreviates directionals (EAST → E)
    - Drops ordinal suffixes from numbered streets (17TH → 17)
    - Collapses whitespace

    Substitutions apply to whole tokens only. Replacing substrings would
    turn "EASTON ST" into "E ON ST" and "1ST AVE" into "1 AVE" for the
    wrong reason.
    """
    addr = address.upper().strip()
    # Periods are dropped rather than spaced: "N.W." has to survive as one
    # token, or the quadrant splits into {N, W} and stops matching "NW".
    addr = addr.replace(",", " ").replace(".", "")
    # Remove unit/apt/suite designators and everything after them. The
    # designator must be a standalone token — without the \b this regex
    # eats street names like WEBSTER, STERLING, or CAPTAIN from the inside.
    addr = re.sub(r"\s+(?:APT|UNIT|STE|SUITE)\b\s*\S*|\s*#\s*\S*", "", addr)

    tokens: list[str] = []
    for raw in addr.split():
        token = SUFFIX_MAP.get(raw, raw)
        token = DIRECTIONAL_MAP.get(token, token)
        ordinal = _ORDINAL_RE.match(token)
        tokens.append(ordinal.group(1) if ordinal else token)
    return " ".join(tokens)


def extract_search_terms(address: str) -> tuple[str, str]:
    """Extract street number and first street name word for a LIKE query.

    Returns (street_number, street_name_start).
    Example: "1600 Pennsylvania Ave NW" → ("1600", "PENNSYLVANIA")
    """
    normalized = normalize_address(address)
    parts = normalized.split()
    if len(parts) < 2:
        return (parts[0] if parts else "", "")

    street_number = parts[0]
    # Skip directional prefix if present (e.g., "E 49TH AVE")
    idx = 1
    if parts[idx] in DIRECTIONALS and len(parts) > 2:
        idx = 2
    return street_number, parts[idx] if idx < len(parts) else parts[1]


def city_from_address(address: str) -> str | None:
    """The city component of a geocoded address, or None if there isn't one.

    The Census geocoder's ``matchedAddress`` — what ``parcels.normalized_address``
    holds — is comma-delimited street, city, state, ZIP:
    ``"12804 EMERSON ST, THORNTON, CO, 80241"``. There is no city column on
    ``parcels`` and no city field on ``GeocodeResult``, so this line is the
    only place the city exists, which is why the county adapters' coverage
    gate reads it from here.

    Uppercased and stripped, matching how the adapters spell their city sets.
    A raw user-typed address that was never geocoded may have no second
    component at all; None is the honest answer there, and ``covers()``
    treats it as "don't know, don't deny".

    Production carries more than one shape (read 2026-08-27): the strict
    Census form ``"12804 EMERSON ST, THORNTON, CO, 80241"``, a
    spelled-out one ``"12804 Emerson Street, Thornton, Colorado 80241"``,
    and city-level geocodes with no street line at all —
    ``"Cupertino, California 95014"``, where the second component is the
    *state*, not the city. A component containing digits is therefore
    rejected: a US city name has none, and returning "CALIFORNIA 95014" as a
    city would let an allowlist adapter deny an address on a reading it never
    actually made.
    """
    parts = [p.strip() for p in address.split(",")]
    if len(parts) < 2 or not parts[1]:
        return None
    city = parts[1].upper()
    if any(c.isdigit() for c in city):
        return None
    return city


def _street_line(address: str) -> str:
    """The street portion of an address — everything before the first comma.

    Geocoder addresses look like "245 PARK AVE, NEW YORK, NY, 10167" while
    county records carry only the street line; comparing full-vs-street can
    never score well, so both sides are reduced to the street line first.
    """
    return address.split(",", 1)[0]


def is_address_match(
    parcel_address: str,
    record_address: str,
    threshold: float = 0.7,
) -> bool:
    """Check if a record's address refers to the parcel's street address.

    The street number must match exactly. The remaining street-name tokens
    are compared with an overlap coefficient (intersection / smaller set),
    so a short form ("100 MAIN ST") matches a longer one ("100 N MAIN ST").

    Normalization is what makes the threshold meaningful. It folds the
    formatting counties disagree on — EAST/E, 17TH/17, STREET/ST — so a
    spelling variant of the same street scores 1.0, while a genuinely
    different street differs by a real token: "100 N MAIN ST" vs
    "100 S MAIN ST" scores 0.67 and is rejected. Before normalization both
    landed at 0.67 and the threshold could not tell them apart.

    The subset behavior is deliberate but blunt: a record that simply omits
    a directional ("1600 PENNSYLVANIA AVE") still matches one that has it
    ("1600 PENNSYLVANIA AVE NW"), because the shorter set is the
    denominator.
    """
    a_tokens = normalize_address(_street_line(parcel_address)).split()
    b_tokens = normalize_address(_street_line(record_address)).split()
    if len(a_tokens) < 2 or len(b_tokens) < 2:
        return False
    if a_tokens[0] != b_tokens[0]:
        return False
    a = set(a_tokens[1:])
    b = set(b_tokens[1:])
    return len(a & b) / min(len(a), len(b)) >= threshold
