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
    - Strips unit/apt/suite/# suffixes
    - Standardizes street type suffixes (AVENUE → AVE, etc.)
    - Collapses whitespace
    """
    addr = address.upper().strip()
    # Remove unit/apt/suite designators and everything after them
    addr = re.sub(r"\s*(APT|UNIT|STE|SUITE|#)\s*\S*", "", addr)
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


def is_address_match(
    parcel_address: str,
    record_address: str,
    threshold: float = 0.85,
) -> bool:
    """Check if a record's address matches the parcel address.

    Uses token-set similarity (Jaccard-like) on normalized addresses.
    """
    a = set(normalize_address(parcel_address).split())
    b = set(normalize_address(record_address).split())
    if not a or not b:
        return False
    intersection = a & b
    return len(intersection) / max(len(a), len(b)) >= threshold
