"""US Census Bureau API client.

Fetches demographic data from Decennial Census (2000–2020) and American
Community Survey 5-year estimates (2009–2023) at the census-tract level.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

# The Census API encodes "not available" as large negative annotation values:
# -666666666 (estimate not computed) is the most common, but ACS also returns
# -999999999, -888888888, -555555555, and -222222222. Anything at or below
# this threshold is an annotation, never real data.
_NOT_AVAILABLE_THRESHOLD = -111111111

# ── Variable mappings per decade ──────────────────────────────────────────────

# Decennial Census variable names differ across decades.
_DECENNIAL_CONFIGS: dict[int, dict[str, Any]] = {
    2020: {
        "dataset": "dec/dhc",
        "vars": {
            "P1_001N": "total_population",
            "H1_001N": "total_housing_units",
        },
    },
    2010: {
        "dataset": "dec/sf1",
        "vars": {
            "P001001": "total_population",
            "H001001": "total_housing_units",
        },
    },
    2000: {
        "dataset": "dec/sf1",
        # 2000/dec/sf1 addresses a tract by its basic code plus a *real*
        # suffix: four characters when the tract has no suffix, six when it
        # does.  2010 and 2020 pad every code to six, which is the form a
        # parcel's stored FIPS carries, so the six-character form 204s on
        # every no-suffix tract — 80 of 186 parcels in the fleet, across 27
        # states.  Verified against the dataset's own tract inventory: 3,088
        # tracts over 8 counties in 8 states, no six-character code ending in
        # `00` and no collision between the two widths, so dropping a trailing
        # `00` re-encodes the same tract rather than substituting its parent.
        # docs/audits/2026-08-census-decennial/REPORT.md §1.4.
        "trim_empty_tract_suffix": True,
        "vars": {
            "P001001": "total_population",
            "H001001": "total_housing_units",
        },
    },
    # 1990 is deliberately absent.  There is no 1990 decennial dataset on
    # api.census.gov at all: data.json lists 1,798 datasets, `dec/*` appears
    # at vintages 2000, 2010 and 2020 only, and all 36 datasets at vintage
    # 1990 are CPS, CBP, PEP and SIPP.  `1990/dec/sf1` has always been a 404,
    # which the ledger recorded as `absent`/`api_no_data` on every parcel
    # until that collapse was closed (see `_request` below).
    #
    # 1990 tract-level decennial data does exist — as a download, not a call:
    # NHGIS (nhgis.org) redistributes STF1/STF3 at tract level, and
    # www2.census.gov/census_1990/ carries the raw STF files.  Either is an
    # ingest, so 1990 comes back with the census tabular ingest pass (the
    # Scheduled entry in docs/audits/2026-08-second-audit/STATUS.md), not by
    # adding a config here.
}

# ACS 5-year variable names (consistent across all available years).
_ACS5_VARIABLES: dict[str, str] = {
    "B01003_001E": "total_population",
    "B19013_001E": "median_household_income",
    "B25077_001E": "median_home_value",
    "B25035_001E": "median_year_built",
    "B25001_001E": "total_housing_units",
    "B25002_003E": "vacant_housing_units",
    "B25003_001E": "occupied_housing_units",
    "B25003_002E": "owner_occupied_units",
    "B25003_003E": "renter_occupied_units",
    "B01002_001E": "median_age",
    "B25064_001E": "median_gross_rent",
}

# Years to fetch for each dataset.
DECENNIAL_YEARS = [2000, 2010, 2020]
ACS5_YEARS = [2009, 2012, 2015, 2018, 2021, 2023]

# Census geocoder vintage each (dataset, year) is published on.
#
# A parcel's stored tract is resolved at the current vintage, so asking for it
# in a year published on older geography silently costs that year.  Two
# independent things move underneath a tract FIPS, and a year is only safe if
# the vintage is named for both:
#
#   - the tract itself, redrawn every decade (a tract created in the 2020
#     redistricting does not exist in 2010 data);
#   - its county-equivalent parent.  Connecticut replaced its eight counties
#     with nine planning regions "for purposes of collecting, tabulating, and
#     disseminating statistical data in 2022"
#     (www2.census.gov/geo/pdfs/reference/ct_county_equiv_change.pdf), so
#     Orange CT is 09009157100 through ACS 2021 and 09170157100 from ACS 2022
#     — the same tract 1571, a different parent.  ACS 5-year 2022+ is the only
#     family that uses the planning-region codes; every decennial vintage,
#     2020 included, still answers under the county codes.
#
# So every year the geocoder can serve names its vintage, rather than only the
# years that happened to be failing when the map was written.  Years absent
# from the map fall back to the stored tract: decennial 2000 is 2000 geography,
# which no vintage serves — Census2010_Current is the geocoder's oldest.  That
# costs 2000 only where the stored county-equivalent is not the one the 2000
# vintage answers under, which today is Connecticut alone
# (docs/audits/2026-08-census-decennial/REPORT.md §1.5).
#
# ACS 2009 is 2000 tract geography too, and is mapped to Census2010_Current
# regardless: it is the nearest vintage that exists, it carries the county-era
# parent that 2009 is published under, and where the tract itself was
# redistricted in 2010 the answer is the same 204 the stored tract already
# gets — never worse, sometimes a recovered year.
_GEOGRAPHY_VINTAGES: dict[tuple[str, int], str] = {
    ("acs5", 2009): "Census2010_Current",
    ("acs5", 2012): "Census2010_Current",
    ("acs5", 2015): "Census2010_Current",
    ("acs5", 2018): "Census2010_Current",
    ("acs5", 2021): "ACS2021_Current",
    ("acs5", 2023): "ACS2023_Current",
    ("decennial", 2010): "Census2010_Current",
    ("decennial", 2020): "Census2020_Current",
}


def geography_vintage(dataset: str, year: int) -> str | None:
    """Return the geocoder vintage for a census year, or None for the current one."""
    return _GEOGRAPHY_VINTAGES.get((dataset, year))


class CensusApiError(Exception):
    """Raised when the Census API returns an unexpected error."""


class CensusMissingKeyError(CensusApiError):
    """Raised when the Census API rejects a request due to a missing or invalid key."""


class CensusHttpStatusError(CensusApiError):
    """Raised when the Census API answers with a non-200, non-204 status.

    "The endpoint errored" and "the tract has no data" are different states,
    and this class is the difference.  ``_request`` used to map 404 to
    ``None`` alongside 204, which became ``{}`` and then an
    ``absent``/``api_no_data`` ledger row — so ``1990/dec/sf1``, a URL that
    has never resolved, spent every sweep recorded as data absence on every
    parcel.  The status and the dataset path travel with the error so the
    ledger can write ``failed``/``http_404`` and say which URL.
    """

    def __init__(self, status_code: int, path: str) -> None:
        super().__init__(f"Census API returned {status_code} for {path}")
        self.status_code = status_code
        self.path = path


class CensusUnknownVariableError(CensusApiError):
    """Raised when a requested variable does not exist in the queried vintage.

    Variable availability differs across years, and the API rejects the whole
    request — not just the offending field — with a 400.  Callers retry
    without the variable rather than losing the entire year.
    """

    def __init__(self, variable: str) -> None:
        super().__init__(f"Unknown Census variable: {variable}")
        self.variable = variable


# Body of a 400 looks like: error: unknown variable 'B25001_001E'
_UNKNOWN_VARIABLE_RE = re.compile(r"unknown variable '([^']+)'", re.IGNORECASE)


class CensusFetcher:
    """Async client for the US Census Bureau API."""

    BASE_URL = "https://api.census.gov/data"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        if not api_key:
            raise CensusMissingKeyError(
                "Census API key is required. Get a free key at "
                "https://api.census.gov/data/key_signup.html "
                "and set CENSUS_API_KEY in your .env file."
            )
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch_acs5(
        self,
        year: int,
        state_fips: str,
        county_fips: str,
        tract_code: str,
    ) -> dict[str, Any]:
        """Fetch ACS 5-year estimates for a tract.

        Returns a dict with normalized field names (e.g. "total_population").
        """
        resp = await self._request_dropping_unknown(
            f"{self.BASE_URL}/{year}/acs/acs5",
            variables=list(_ACS5_VARIABLES.keys()),
            state_fips=state_fips,
            county_fips=county_fips,
            tract_code=tract_code,
        )
        if resp is None:
            return {}

        raw = _parse_response(resp)
        return _normalize(raw, _ACS5_VARIABLES)

    async def fetch_decennial(
        self,
        year: int,
        state_fips: str,
        county_fips: str,
        tract_code: str,
    ) -> dict[str, Any]:
        """Fetch decennial census data for a tract.

        Returns a dict with normalized field names (e.g. "total_population").
        """
        config = _DECENNIAL_CONFIGS.get(year)
        if not config:
            logger.warning("No decennial config for year %d", year)
            return {}

        resp = await self._request_dropping_unknown(
            f"{self.BASE_URL}/{year}/{config['dataset']}",
            variables=list(config["vars"].keys()),
            state_fips=state_fips,
            county_fips=county_fips,
            tract_code=_tract_for_dataset(tract_code, config),
        )
        if resp is None:
            return {}

        raw = _parse_response(resp)
        return _normalize(raw, config["vars"])

    async def _request_dropping_unknown(
        self,
        url: str,
        *,
        variables: list[str],
        state_fips: str,
        county_fips: str,
        tract_code: str,
    ) -> list[list[str]] | None:
        """Request variables, dropping any the vintage doesn't recognize.

        The API rejects the entire request when one variable is unavailable
        for that year, so retry without it instead of losing every field.
        """
        remaining = list(variables)
        while remaining:
            try:
                return await self._request(
                    url,
                    variables=remaining,
                    state_fips=state_fips,
                    county_fips=county_fips,
                    tract_code=tract_code,
                )
            except CensusUnknownVariableError as exc:
                if exc.variable not in remaining:
                    # Can't attribute the rejection to anything we asked for —
                    # retrying the same list would loop forever.
                    raise
                remaining.remove(exc.variable)
                logger.warning(
                    "Census variable unavailable for vintage; retrying without it",
                    extra={"url": url, "variable": exc.variable, "remaining": len(remaining)},
                )
        return None

    async def _request(
        self,
        url: str,
        *,
        variables: list[str],
        state_fips: str,
        county_fips: str,
        tract_code: str,
    ) -> list[list[str]] | None:
        """Make a Census API request. Returns None on a 204 (tract not found).

        A 4xx/5xx raises ``CensusHttpStatusError``: an endpoint that errors is
        not a tract that has no data, and collapsing the two is what made a
        dead 1990 URL read as absence on every parcel.
        """
        params: dict[str, str] = {
            "get": ",".join(variables),
            "for": f"tract:{tract_code}",
            "in": f"state:{state_fips} county:{county_fips}",
        }
        if self.api_key:
            params["key"] = self.api_key

        try:
            resp = await self.client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.error("Census API request failed", extra={"url": url}, exc_info=exc)
            raise CensusApiError(f"HTTP error: {exc}") from exc

        if resp.status_code == 302:
            location = resp.headers.get("location", "")
            if "missing_key" in location or resp.headers.get("x-datawebapi-keyerror"):
                raise CensusMissingKeyError(
                    "Census API key is missing or invalid. Get a free key at "
                    "https://api.census.gov/data/key_signup.html "
                    "and set CENSUS_API_KEY in your .env file."
                )

        if resp.status_code == 204:
            logger.info(
                "Census API: no data for tract",
                extra={"url": url, "status": resp.status_code},
            )
            return None

        if resp.status_code == 400:
            match = _UNKNOWN_VARIABLE_RE.search(resp.text)
            if match:
                raise CensusUnknownVariableError(match.group(1))

        if resp.status_code != 200:
            logger.error(
                "Census API error",
                extra={"url": url, "status": resp.status_code, "body": resp.text[:500]},
            )
            raise CensusHttpStatusError(resp.status_code, _dataset_path(url))

        # The Census API sometimes returns its HTML error page with a 200.
        try:
            return cast(list[list[str]], resp.json())
        except json.JSONDecodeError as exc:
            logger.error(
                "Census API returned non-JSON body",
                extra={"url": url, "body": resp.text[:200]},
            )
            raise CensusApiError(f"Census API returned invalid JSON: {exc}") from exc


def _tract_for_dataset(tract_code: str, config: dict[str, Any]) -> str:
    """Re-encode a stored six-character tract for the dataset asking for it.

    Only ``2000/dec/sf1`` needs this, and only for a tract whose two-digit
    suffix is empty — see the comment on that config entry.  A tract with a
    real suffix is left alone: trimming one would ask about a different,
    coarser geography and quietly label it with the parcel's tract.
    """
    if not config.get("trim_empty_tract_suffix"):
        return tract_code
    if len(tract_code) != 6 or not tract_code.endswith("00"):
        return tract_code
    return tract_code[:4]


def _dataset_path(url: str) -> str:
    """The dataset part of a Census API URL, for an error message.

    Never the query string: the API key lives there.
    """
    return url.removeprefix(CensusFetcher.BASE_URL) or url


def parse_tract_fips(tract_fips: str) -> tuple[str, str, str]:
    """Split a full FIPS code into (state, county, tract) components.

    A tract FIPS is structured as: {state_fips:2}{county_fips:3}{tract_code:6}
    Example: "08031006202" → ("08", "031", "006202")
    """
    if len(tract_fips) != 11:
        raise ValueError(f"Expected 11-character tract FIPS, got {len(tract_fips)}: {tract_fips!r}")
    return tract_fips[:2], tract_fips[2:5], tract_fips[5:]


def _parse_response(data: list[list[str]]) -> dict[str, int | float | None]:
    """Convert Census API's header+rows format to a dict.

    First row is headers, second row is values. Geography fields are excluded.
    """
    if len(data) < 2:
        return {}

    headers = data[0]
    values = data[1]
    geo_fields = {"state", "county", "tract"}

    return {h: _to_number(v) for h, v in zip(headers, values, strict=False) if h not in geo_fields}


def _normalize(
    raw: dict[str, int | float | None],
    var_map: dict[str, str],
) -> dict[str, int | float | None]:
    """Map Census API variable names to our normalized field names."""
    return {var_map[k]: v for k, v in raw.items() if k in var_map}


def _to_number(val: str | None) -> int | float | None:
    """Parse a Census API string value to a number.

    The API returns numbers as strings; large negative annotation values
    mean "not available" and are mapped to None.
    """
    if val is None or val == "":
        return None
    try:
        n = int(val)
        return None if n <= _NOT_AVAILABLE_THRESHOLD else n
    except ValueError:
        try:
            f = float(val)
            return None if f <= _NOT_AVAILABLE_THRESHOLD else f
        except ValueError:
            return None
