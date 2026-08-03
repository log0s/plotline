"""US Census Geocoder client.

Calls the Census Bureau's one-line address geocoding API and parses
the result into a structured dataclass.

API docs: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# "Public_AR_Current" is the current-vintage benchmark — faster and more
# accurate than the frozen "2020" benchmark.
_BENCHMARK = "Public_AR_Current"

# Vintage must match benchmark to get census tract geographies.
_VINTAGE = "Current_Current"

# Maximum number of attempts before giving up.
_MAX_ATTEMPTS = 3


class GeocoderError(Exception):
    """Base exception for geocoder errors."""


class GeocoderUnavailableError(GeocoderError):
    """Raised when the Census Geocoder API cannot be reached."""


class AddressNotFoundError(GeocoderError):
    """Raised when the Census Geocoder returns no match for an address."""


def _parse_json(response: httpx.Response, label: str) -> dict[str, Any]:
    """Decode a geocoder response body, treating a non-JSON body as an outage.

    The Census geocoder serves its HTML maintenance page with a 200, so a
    decode failure means the service is down rather than that the request was
    wrong. census.py guards the same upstream behavior the same way.
    """
    try:
        # json.JSONDecodeError subclasses ValueError, so a stdlib-json swap
        # inside httpx would still land here.
        data = response.json()
    except ValueError as exc:
        logger.error(
            "Census Geocoder returned non-JSON body",
            extra={"label": label, "body": response.text[:200]},
        )
        raise GeocoderUnavailableError(
            f"{label} returned invalid JSON: {response.text[:200]!r}"
        ) from exc

    if not isinstance(data, dict):
        logger.error(
            "Census Geocoder returned a non-object body",
            extra={"label": label, "body": response.text[:200]},
        )
        raise GeocoderUnavailableError(
            f"{label} returned {type(data).__name__}, expected an object"
        )
    return data


def _shape_error(label: str, exc: Exception) -> GeocoderUnavailableError:
    """Wrap an unexpected-payload-shape failure as an upstream outage."""
    logger.error(
        "Census Geocoder returned an unexpected payload shape",
        extra={"label": label, "error": str(exc)},
    )
    return GeocoderUnavailableError(f"{label} returned an unexpected payload shape: {exc}")


# Raised by dict/list traversal over a payload that decoded but isn't shaped
# the way the API documents.
_SHAPE_ERRORS = (KeyError, TypeError, IndexError, ValueError, AttributeError)


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
        GeocoderUnavailableError: Network error, non-2xx response, or a body
            that isn't the JSON object the API documents (the geocoder serves
            its HTML maintenance page with a 200).
        AddressNotFoundError: Address could not be matched.
    """
    params: dict[str, str] = {
        "address": address,
        "benchmark": _BENCHMARK,
        "vintage": _VINTAGE,
        "layers": "Census Tracts,Counties",
        "format": "json",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key

    last_exc: Exception | None = None

    async with httpx.AsyncClient(timeout=settings.census_geocoder_timeout) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            logger.info(
                "Calling Census Geocoder",
                extra={"address": address, "attempt": attempt},
            )
            try:
                response = await client.get(settings.census_geocoder_url, params=params)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Census Geocoder timeout",
                    extra={"attempt": attempt, "timeout": settings.census_geocoder_timeout},
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(1.0)
                continue
            except httpx.HTTPStatusError as exc:
                raise GeocoderUnavailableError(
                    f"Census Geocoder returned HTTP {exc.response.status_code}"
                ) from exc
            except httpx.RequestError as exc:
                raise GeocoderUnavailableError(
                    f"Network error contacting Census Geocoder: {exc}"
                ) from exc

            # Success — parse and return
            data = _parse_json(response, "Census Geocoder")

            try:
                address_matches = (data.get("result") or {}).get("addressMatches") or []
            except AttributeError as exc:
                raise _shape_error("Census Geocoder", exc) from exc

            if not address_matches:
                raise AddressNotFoundError(f"No geocoding match found for address: {address!r}")

            try:
                match = address_matches[0]
                coords = match["coordinates"]
                latitude = float(coords["y"])
                longitude = float(coords["x"])
                geographies = match.get("geographies") or {}

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

                # County name comes from the Counties geography, not the tract.
                # No fallback to the tract's NAME: that yields "Census Tract
                # 62.02", which is truthy, so parcels.py's only-if-empty
                # backfill never heals it and county adapter lookup fails for
                # that parcel forever. None is recoverable; garbage isn't.
                counties = geographies.get("Counties", [])
                if counties:
                    county = counties[0].get("BASENAME")

                normalized_address = match.get("matchedAddress", address)
            except _SHAPE_ERRORS as exc:
                raise _shape_error("Census Geocoder", exc) from exc

            logger.info(
                "Census Geocoder match found",
                extra={
                    "normalized_address": normalized_address,
                    "lat": latitude,
                    "lng": longitude,
                },
            )

            return GeocodeResult(
                normalized_address=normalized_address,
                latitude=latitude,
                longitude=longitude,
                census_tract_id=census_tract_id,
                county=county,
                state_fips=state_fips,
            )

        raise GeocoderUnavailableError(
            f"Census Geocoder timed out after {_MAX_ATTEMPTS} attempts "
            f"({settings.census_geocoder_timeout}s each)"
        ) from last_exc


async def reverse_geocode(
    latitude: float,
    longitude: float,
    address: str,
    settings: Settings,
) -> GeocodeResult:
    """Look up census geographies for known coordinates.

    Used when we already have lat/lon (e.g. from an autocomplete provider)
    and only need census tract / county metadata from the Census Bureau.

    Args:
        latitude: WGS-84 latitude.
        longitude: WGS-84 longitude.
        address: Display address to store (not sent to Census).
        settings: Application settings.

    Returns:
        GeocodeResult with the supplied coordinates plus census metadata.

    Raises:
        GeocoderUnavailableError: Census API unreachable after retries.
    """
    url = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
    params: dict[str, str] = {
        "x": str(longitude),
        "y": str(latitude),
        "benchmark": _BENCHMARK,
        "vintage": _VINTAGE,
        "layers": "Census Tracts,Counties",
        "format": "json",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key

    last_exc: Exception | None = None

    async with httpx.AsyncClient(timeout=settings.census_geocoder_timeout) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            logger.info(
                "Calling Census reverse geocoder",
                extra={"lat": latitude, "lon": longitude, "attempt": attempt},
            )
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Census reverse geocoder timeout",
                    extra={"attempt": attempt},
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(1.0)
                continue
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                raise GeocoderUnavailableError(f"Census reverse geocoder error: {exc}") from exc

            data = _parse_json(response, "Census reverse geocoder")

            census_tract_id: str | None = None
            county: str | None = None
            state_fips: str | None = None

            try:
                geographies = (data.get("result") or {}).get("geographies") or {}

                census_tracts = geographies.get("Census Tracts", [])
                if census_tracts:
                    tract = census_tracts[0]
                    state_fips = tract.get("STATE")
                    county_fips = tract.get("COUNTY")
                    tract_fips = tract.get("TRACT")
                    if state_fips and county_fips and tract_fips:
                        census_tract_id = f"{state_fips}{county_fips}{tract_fips}"

                # See geocode_address: no tract-NAME fallback, for the same
                # reason — an unhealable wrong county is worse than none.
                counties = geographies.get("Counties", [])
                if counties:
                    county = counties[0].get("BASENAME")
            except _SHAPE_ERRORS as exc:
                raise _shape_error("Census reverse geocoder", exc) from exc

            logger.info(
                "Census reverse geocode complete",
                extra={"census_tract": census_tract_id, "county": county},
            )

            return GeocodeResult(
                normalized_address=address,
                latitude=latitude,
                longitude=longitude,
                census_tract_id=census_tract_id,
                county=county,
                state_fips=state_fips,
            )

        raise GeocoderUnavailableError(
            f"Census reverse geocoder timed out after {_MAX_ATTEMPTS} attempts"
        ) from last_exc
