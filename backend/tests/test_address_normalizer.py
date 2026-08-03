"""Tests for address normalization and fuzzy matching.

Every county in the pipeline spells addresses differently, and this module
is the only thing reconciling them. The formats below are the real ones:
Census geocoder output, NYC DOB permits, NYC sales, Denver ArcGIS, DC
DCGIS, San Jose CKAN, Adams County ArcGIS.

The true-negative table matters as much as the true-positive one — a
matcher that accepts everything is worse than one that rejects too much,
because wrong records get attributed to a building silently.
"""

from __future__ import annotations

import pytest

from app.services.address_normalizer import (
    extract_search_terms,
    is_address_match,
    normalize_address,
)

# ── normalize_address ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Census geocoder output — the parcel side of every comparison
        ("245 E 17TH ST", "245 E 17 ST"),
        ("1600 PENNSYLVANIA AVE NW", "1600 PENNSYLVANIA AVE NW"),
        # NYC DOB permits: directionals spelled out, ordinal suffixes dropped
        ("245 EAST 17 STREET", "245 E 17 ST"),
        ("350 WEST 42 STREET", "350 W 42 ST"),
        # NYC sales: ordinals kept, suffix spelled out
        ("245 EAST 17TH STREET", "245 E 17 ST"),
        # Denver ArcGIS
        ("1437 N BANNOCK ST", "1437 N BANNOCK ST"),
        ("8340 NORTHFIELD BLVD", "8340 NORTHFIELD BLVD"),
        # DC — quadrant preserved, AVENUE folded
        ("100 MARYLAND AVENUE NE", "100 MARYLAND AVE NE"),
        # San Jose CKAN
        ("200 E SANTA CLARA ST", "200 E SANTA CLARA ST"),
        # Adams County
        ("12345 FOX RUN CIRCLE", "12345 FOX RUN CIR"),
        # Compound directionals
        ("500 SOUTHWEST TEMPLE ST", "500 SW TEMPLE ST"),
        ("500 NORTHEAST 1ST AVE", "500 NE 1 AVE"),
        # Ordinals of every suffix form
        ("1 1ST ST", "1 1 ST"),
        ("2 2ND AVE", "2 2 AVE"),
        ("3 3RD PL", "3 3 PL"),
        ("4 4TH BLVD", "4 4 BLVD"),
        # Whole-token substitution only — these must survive intact
        ("100 EASTON ST", "100 EASTON ST"),
        ("100 WESTMINSTER AVE", "100 WESTMINSTER AVE"),
        ("100 STERLING DR", "100 STERLING DR"),
        ("100 WEBSTER AVE", "100 WEBSTER AVE"),
        # A street literally named for a direction still folds — both sides
        # get the same treatment, so they still meet
        ("100 SOUTH ST", "100 S ST"),
        # Units and punctuation
        ("245 E 17th St, Apt 4B", "245 E 17 ST"),
        ("245 E 17th St #4B", "245 E 17 ST"),
        ("245 E 17th St, Suite 200", "245 E 17 ST"),
        ("245 E 17th St Unit 3", "245 E 17 ST"),
        # Periods dropped, not spaced — "N.W." must stay one token
        ("1600 Pennsylvania Ave., N.W.", "1600 PENNSYLVANIA AVE NW"),
        ("123 ST. MARY ST", "123 ST MARY ST"),
        # No street number
        ("SOUTH LEMAY AVENUE", "S LEMAY AVE"),
        # Degenerate input
        ("", ""),
        ("   ", ""),
        (",,,", ""),
        ("#5", ""),
        # Unicode and unusual characters pass through rather than exploding
        ("123 CAFÉ ST", "123 CAFÉ ST"),
        ("123 O'BRIEN ST", "123 O'BRIEN ST"),
        ("12-34 45TH ST", "12-34 45 ST"),
    ],
)
def test_normalize_address(raw: str, expected: str) -> None:
    assert normalize_address(raw) == expected


# ── is_address_match — true positives ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("parcel", "record", "why"),
    [
        (
            "245 E 17TH ST, NEW YORK, NY, 10003",
            "245 EAST 17 STREET",
            "NYC DOB spells out the directional and drops the ordinal",
        ),
        (
            "245 E 17TH ST, NEW YORK, NY, 10003",
            "245 EAST 17TH STREET",
            "NYC sales spells out the directional only",
        ),
        (
            "350 W 42ND ST, NEW YORK, NY, 10036",
            "350 WEST 42 STREET",
            "same building, both variations at once",
        ),
        (
            "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
            "1600 PENNSYLVANIA AVENUE NW",
            "DC sales spells out the suffix",
        ),
        (
            "100 MARYLAND AVE NE, WASHINGTON, DC, 20002",
            "100 MARYLAND AVENUE NE",
            "DC quadrant preserved on both sides",
        ),
        (
            "1437 BANNOCK ST, DENVER, CO, 80202",
            "1437 N BANNOCK ST",
            "county record carries a directional the geocoder dropped",
        ),
        (
            "200 E SANTA CLARA ST, SAN JOSE, CA, 95113",
            "200 EAST SANTA CLARA STREET",
            "San Jose spells everything out",
        ),
        (
            "12345 FOX RUN CIR, BRIGHTON, CO, 80601",
            "12345 FOX RUN CIRCLE",
            "Adams County spells out the suffix",
        ),
        (
            "245 E 17TH ST, NEW YORK, NY, 10003",
            "245 E 17TH ST APT 4B",
            "unit designators are stripped before comparison",
        ),
        (
            "500 NE 1ST AVE, MIAMI, FL, 33132",
            "500 NORTHEAST 1 AVENUE",
            "compound directional plus ordinal",
        ),
        (
            "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
            "1600 Pennsylvania Ave. N.W.",
            "punctuated quadrant stays a single token",
        ),
    ],
)
def test_is_address_match_true_positives(parcel: str, record: str, why: str) -> None:
    assert is_address_match(parcel, record), why


# ── is_address_match — true negatives ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("parcel", "record", "why"),
    [
        (
            "100 N MAIN ST",
            "100 S MAIN ST",
            "opposite directionals are different streets",
        ),
        (
            "100 NORTH MAIN ST",
            "100 S MAIN ST",
            "spelling out the directional must not hide the mismatch",
        ),
        (
            "100 E 17TH ST",
            "100 WEST 17 STREET",
            "normalization must not collapse E into W",
        ),
        (
            "100 MAIN ST",
            "1000 MAIN ST",
            "near-miss street number",
        ),
        (
            "100 MAIN ST",
            "100 MAIN AVE",
            "same name, different street type",
        ),
        (
            "245 E 17TH ST",
            "245 E 18TH ST",
            "adjacent numbered street",
        ),
        (
            "100 MAIN ST",
            "100 OAK ST",
            "unrelated street name",
        ),
        (
            "100 EASTON ST",
            "100 E ON ST",
            "substring substitution would have made these equal",
        ),
        (
            "245 E 17TH ST",
            "",
            "empty record address",
        ),
        (
            "",
            "245 E 17TH ST",
            "empty parcel address",
        ),
        (
            "245 E 17TH ST",
            "MAIN ST",
            "record with no street number",
        ),
        (
            "245",
            "245",
            "street number alone carries no street identity",
        ),
    ],
)
def test_is_address_match_true_negatives(parcel: str, record: str, why: str) -> None:
    assert not is_address_match(parcel, record), why


def test_directional_variants_score_above_genuine_mismatch() -> None:
    """The threshold only works because the two are no longer tied.

    Before normalization, "E 17TH ST" vs "EAST 17 STREET" (a spelling
    variant) and "N MAIN ST" vs "S MAIN ST" (different streets) both
    scored 0.67. Nothing placed between them could separate the two.
    """
    variant = ("245 E 17TH ST", "245 EAST 17 STREET")
    mismatch = ("100 N MAIN ST", "100 S MAIN ST")

    # A threshold of 1.0 still accepts the variant; anything at or below
    # 0.67 starts accepting the mismatch. The default 0.7 sits in the gap.
    assert is_address_match(*variant, threshold=1.0)
    assert not is_address_match(*mismatch, threshold=0.7)
    assert is_address_match(*mismatch, threshold=0.66)


# ── extract_search_terms ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1600 Pennsylvania Ave NW", ("1600", "PENNSYLVANIA")),
        # Directional prefix skipped so the LIKE query targets the name
        ("1437 N Bannock St", ("1437", "BANNOCK")),
        ("245 EAST 17 STREET", ("245", "17")),
        # Ordinal dropped here too — NYC DOB stores "17", so a "17TH"
        # search term would return nothing to match against
        ("245 E 17TH ST", ("245", "17")),
        ("", ("", "")),
        ("245", ("245", "")),
    ],
)
def test_extract_search_terms(raw: str, expected: tuple[str, str]) -> None:
    assert extract_search_terms(raw) == expected
