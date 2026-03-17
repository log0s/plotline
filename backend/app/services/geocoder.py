"""US Census Geocoder client.

Calls the Census Bureau's one-line address geocoding API and parses
the result into a structured dataclass.

API docs: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# The benchmark ID for the most current TIGER/Line data
_BENCHMARK = "2020"


class GeocoderError(Exception):
    """Base exception for geocoder errors."""


class GeocoderUnavailableError(GeocoderError):
    """Raised when the Census Geocoder API cannot be reached."""


class AddressNotFoundError(GeocoderError):
    """Raised when the Census Geocoder returns no match for an address."""


@dataclass(frozen=True)
class GeocodeResult:
    """Structured result from a successful geocoding request."""

    normalized_address: str
    latitude: float
    longitude: float
    census_tract_id: str | None
    county: str | None
    state_fips: str | None


async def geocode_address(address: str, settings: Settings) -> GeocodeResult:
    """Geocode a US address using the Census Bureau Geocoder API.

    Args:
        address: Free-form US address string.
        settings: Application settings (provides URL, timeout, optional API key).

    Returns:
        GeocodeResult with coordinates and census metadata.

    Raises:
        GeocoderUnavailableError: Network error or non-2xx response from the API.
        AddressNotFoundError: Address could not be matched.
    """
    params: dict[str, str] = {
        "address": address,
        "benchmark": _BENCHMARK,
        "format": "json",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key

    logger.info("Calling Census Geocoder", extra={"address": address})

    try:
        async with httpx.AsyncClient(timeout=settings.census_geocoder_timeout) as client:
            response = await client.get(settings.census_geocoder_url, params=params)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise GeocoderUnavailableError(
            f"Census Geocoder timed out after {settings.census_geocoder_timeout}s"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise GeocoderUnavailableError(
            f"Census Geocoder returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise GeocoderUnavailableError(
            f"Network error contacting Census Geocoder: {exc}"
        ) from exc

    data = response.json()
    address_matches = (
        data.get("result", {}).get("addressMatches", [])
    )

    if not address_matches:
        raise AddressNotFoundError(
            f"No geocoding match found for address: {address!r}"
        )

    # Use the first (best) match
    match = address_matches[0]
    coords = match["coordinates"]
    geographies = match.get("geographies", {})

    # Extract census tract info if available (requires vintage/layers params —
    # not requested in Phase 1 benchmark-only call, so may be absent)
    census_tract_id: str | None = None
    county: str | None = None
    state_fips: str | None = None

    census_tracts = geographies.get("Census Tracts", [])
    if census_tracts:
        tract = census_tracts[0]
        state_fips = tract.get("STATE")
        county_fips = tract.get("COUNTY")
        tract_fips = tract.get("TRACT")
        if state_fips and county_fips and tract_fips:
            census_tract_id = f"{state_fips}{county_fips}{tract_fips}"
        county = tract.get("BASENAME")

    logger.info(
        "Census Geocoder match found",
        extra={
            "normalized_address": match.get("matchedAddress"),
            "lat": coords["y"],
            "lng": coords["x"],
        },
    )

    return GeocodeResult(
        normalized_address=match.get("matchedAddress", address),
        latitude=float(coords["y"]),
        longitude=float(coords["x"]),
        census_tract_id=census_tract_id,
        county=county,
        state_fips=state_fips,
    )
