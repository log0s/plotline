"""US Census Bureau API client.

Fetches demographic data from Decennial Census (1990–2020) and American
Community Survey 5-year estimates (2009–2023) at the census-tract level.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Sentinel value the Census API uses for "data not available"
_NOT_AVAILABLE = -666666666

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
        "vars": {
            "P001001": "total_population",
            "H001001": "total_housing_units",
        },
    },
    1990: {
        "dataset": "dec/sf1",
        "vars": {
            "P0010001": "total_population",
            "H0010001": "total_housing_units",
        },
    },
}

# ACS 5-year variable names (consistent across all available years).
_ACS5_VARIABLES: dict[str, str] = {
    "B01003_001E": "total_population",
    "B19013_001E": "median_household_income",
    "B25077_001E": "median_home_value",
    "B25035_001E": "median_year_built",
    "B25003_001E": "occupied_housing_units",
    "B25003_002E": "owner_occupied_units",
    "B25003_003E": "renter_occupied_units",
    "B01002_001E": "median_age",
    "B25064_001E": "median_gross_rent",
}

# Years to fetch for each dataset.
DECENNIAL_YEARS = [1990, 2000, 2010, 2020]
ACS5_YEARS = [2009, 2012, 2015, 2018, 2021, 2023]


class CensusApiError(Exception):
    """Raised when the Census API returns an unexpected error."""


class CensusFetcher:
    """Async client for the US Census Bureau API."""

    BASE_URL = "https://api.census.gov/data"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
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
        variables = list(_ACS5_VARIABLES.keys())
        url = f"{self.BASE_URL}/{year}/acs/acs5"

        resp = await self._request(
            url,
            variables=variables,
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
            logger.warning(f"No decennial config for year {year}")
            return {}

        url = f"{self.BASE_URL}/{year}/{config['dataset']}"
        variables = list(config["vars"].keys())

        resp = await self._request(
            url,
            variables=variables,
            state_fips=state_fips,
            county_fips=county_fips,
            tract_code=tract_code,
        )
        if resp is None:
            return {}

        raw = _parse_response(resp)
        return _normalize(raw, config["vars"])

    async def _request(
        self,
        url: str,
        *,
        variables: list[str],
        state_fips: str,
        county_fips: str,
        tract_code: str,
    ) -> list[list[str]] | None:
        """Make a Census API request. Returns None on 204/404 (tract not found)."""
        params = {
            "get": ",".join(variables),
            "for": f"tract:{tract_code}",
            "in": f"state:{state_fips} county:{county_fips}",
            "key": self.api_key,
        }

        try:
            resp = await self.client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.error(f"Census API request failed: {exc}", extra={"url": url})
            raise CensusApiError(f"HTTP error: {exc}") from exc

        if resp.status_code in (204, 404):
            logger.info(
                f"Census API: no data for tract",
                extra={"url": url, "status": resp.status_code},
            )
            return None

        if resp.status_code != 200:
            logger.error(
                f"Census API error",
                extra={"url": url, "status": resp.status_code, "body": resp.text[:500]},
            )
            raise CensusApiError(
                f"Census API returned {resp.status_code}: {resp.text[:200]}"
            )

        return resp.json()


def parse_tract_fips(tract_fips: str) -> tuple[str, str, str]:
    """Split a full FIPS code into (state, county, tract) components.

    A tract FIPS is structured as: {state_fips:2}{county_fips:3}{tract_code:6}
    Example: "08031006202" → ("08", "031", "006202")
    """
    if len(tract_fips) != 11:
        raise ValueError(
            f"Expected 11-character tract FIPS, got {len(tract_fips)}: {tract_fips!r}"
        )
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

    return {
        h: _to_number(v)
        for h, v in zip(headers, values)
        if h not in geo_fields
    }


def _normalize(
    raw: dict[str, int | float | None],
    var_map: dict[str, str],
) -> dict[str, int | float | None]:
    """Map Census API variable names to our normalized field names."""
    return {
        var_map[k]: v
        for k, v in raw.items()
        if k in var_map
    }


def _to_number(val: str | None) -> int | float | None:
    """Parse a Census API string value to a number.

    The API returns numbers as strings. -666666666 means "not available".
    """
    if val is None or val == "":
        return None
    try:
        n = int(val)
        return None if n == _NOT_AVAILABLE else n
    except ValueError:
        try:
            f = float(val)
            return None if f == float(_NOT_AVAILABLE) else f
        except ValueError:
            return None
