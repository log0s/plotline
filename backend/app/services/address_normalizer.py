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

# Two-letter directional abbreviations
DIRECTIONALS = {"NORTH", "SOUTH", "EAST", "WEST", "N", "S", "E", "W", "NE", "NW", "SE", "SW"}


def normalize_address(address: str) -> str:
    """Normalize an address for fuzzy matching against county records.

    - Uppercases
    - Strips punctuation that would otherwise stick to tokens ("AVE," vs "AVE")
    - Strips unit/apt/suite/# suffixes
    - Standardizes street type suffixes (AVENUE → AVE, etc.)
    - Collapses whitespace
    """
    addr = address.upper().strip()
    addr = addr.replace(",", " ").replace(".", " ")
    # Remove unit/apt/suite designators and everything after them. The
    # designator must be a standalone token — without the \b this regex
    # eats street names like WEBSTER, STERLING, or CAPTAIN from the inside.
    addr = re.sub(r"\s+(?:APT|UNIT|STE|SUITE)\b\s*\S*|\s*#\s*\S*", "", addr)
    # Standardize suffixes
    for long, short in SUFFIX_MAP.items():
        addr = re.sub(rf"\b{long}\b", short, addr)
    # Remove extra whitespace
    addr = re.sub(r"\s+", " ", addr).strip()
    return addr


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
    so a short form ("100 MAIN ST") matches a longer one ("100 N MAIN ST")
    but "100 N MAIN ST" vs "100 S MAIN ST" (0.67) stays below the threshold.
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
