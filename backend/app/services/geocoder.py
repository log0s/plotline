"""US Census Geocoder client.

Calls the Census Bureau's one-line address geocoding API and parses
the result into a structured dataclass.

API docs: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.redact import redact

logger = logging.getLogger(__name__)

# "Public_AR_Current" is the current-vintage benchmark — faster and more
# accurate than the frozen "2020" benchmark.
_BENCHMARK = "Public_AR_Current"

# Vintage must match benchmark to get census tract geographies.
_VINTAGE = "Current_Current"

# Maximum number of attempts before giving up.
_MAX_ATTEMPTS = 3

# Retry policy for `lookup_tract_at_vintage`, mirroring census.py's N2 policy
# (commit 8a86fad): a status worth asking again about is a 5xx, not a 4xx — a
# 404 is a settled "no such resource," not an outage. Deliberately narrower
# than `httpx.HTTPError`: an `InvalidURL` is our bug, not the upstream's.
_VINTAGE_RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})
_VINTAGE_RETRYABLE_TRANSPORT = (httpx.ReadTimeout, httpx.ConnectError)
_VINTAGE_RETRY_ATTEMPTS = 3

# Two full `census_geocoder_timeout` (20 s, config.py:60) attempts plus
# jittered backoff must fit before a third attempt starts: 2*20s +
# jittered(1.0) + jittered(2.0) <= 43.75s worst case. Scales census.py's own
# budget arithmetic (there: 2*30s+backoff <= ~64s < 65s budget) down to this
# client's shorter timeout. This lookup runs once per distinct vintage per
# parcel (cached in `_VintageTracts`, tasks/timeline.py) inside the same
# census task N2 already budgets for.
_VINTAGE_RETRY_BUDGET_S = 45.0

# Upward-only spread, so a fleet-wide sweep's parallel workers do not resume
# in lockstep after the same outage.
_VINTAGE_RETRY_JITTER_FRACTION = 0.25


def _vintage_jittered(delay: float) -> float:
    """``delay`` spread upward by up to ``_VINTAGE_RETRY_JITTER_FRACTION`` of itself."""
    return delay * (1.0 + random.random() * _VINTAGE_RETRY_JITTER_FRACTION)


def _vintage_retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse a Retry-After header (delta-seconds form) into seconds."""
    raw = resp.headers.get("retry-after")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


# Coordinates the autocomplete endpoint has handed out, keyed by the pair
# itself. POST /geocode may only fall back to client-supplied lat/lon when
# the pair is here: it is then a point *this backend* produced from a
# Photon result, not an arbitrary location (security audit SEC-2/SEC-5).
# The value is the suggestion's display name, which becomes the parcel's
# normalized_address on that path so attacker text never does. Longer than
# the 300 s autocomplete cache: a user can sit on a suggestion for a while
# before searching.
_SERVED_COORDS_TTL = 6 * 3600


def _served_coords_key(latitude: float, longitude: float) -> str:
    return f"served-coords:{latitude:.5f},{longitude:.5f}"


def remember_served_coordinates(redis: Any, suggestions: list[tuple[float, float, str]]) -> None:
    """Record (lat, lon, display_name) triples autocomplete is about to return."""
    if not suggestions:
        return
    pipe = redis.pipeline()
    for lat, lon, name in suggestions:
        pipe.set(_served_coords_key(lat, lon), name, ex=_SERVED_COORDS_TTL)
    pipe.execute()


def served_display_name(redis: Any, latitude: float, longitude: float) -> str | None:
    """The display name autocomplete served with this pair, or None if it never did.

    Raises on a Redis error: the caller treats that as "not served" (fails
    closed — the forward geocode path is unaffected).
    """
    value = redis.get(_served_coords_key(latitude, longitude))
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


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


def _describe(exc: httpx.HTTPError) -> str:
    """Status code or error class only — never ``str(exc)``, which httpx
    renders with the full request URL and therefore the ``key=`` parameter."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {redact(str(exc))}"


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
                    f"Network error contacting Census Geocoder: {_describe(exc)}"
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
                raise GeocoderUnavailableError(
                    f"Census reverse geocoder error: {_describe(exc)}"
                ) from exc

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


async def _vintage_get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, str]
) -> httpx.Response:
    """GET the vintage tract lookup, retrying transient failures within a budget.

    Z6: this call used to retry only `httpx.TimeoutException`, on a flat 1 s
    sleep — `ConnectError` and a 5xx raised on the first attempt with no retry
    at all, which is what let one `ConnectError` degrade a sweep parcel to its
    stored tract (STATUS.md Z6). Mirrors census.py's N2 policy (`8a86fad`):
    `ReadTimeout`, `ConnectError` and `{500, 502, 503, 504}` retry up to three
    times with jittered backoff honouring `Retry-After`; a 4xx (or any other
    `HTTPError`) is terminal on the first attempt — a settled answer, not an
    outage.
    """
    started = time.monotonic()
    delay = 1.0
    last_status: int | None = None
    last_response: httpx.Response | None = None
    last_transport: httpx.RequestError | None = None

    for attempt in range(_VINTAGE_RETRY_ATTEMPTS):
        retry_after: float | None = None
        try:
            response = await client.get(url, params=params)
        except _VINTAGE_RETRYABLE_TRANSPORT as exc:
            last_transport = exc
            last_status = None
        except httpx.RequestError as exc:
            raise GeocoderUnavailableError(f"Vintage tract lookup error: {_describe(exc)}") from exc
        else:
            if response.status_code not in _VINTAGE_RETRYABLE_STATUSES:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise GeocoderUnavailableError(
                        f"Vintage tract lookup error: {_describe(exc)}"
                    ) from exc
                return response
            last_status = response.status_code
            last_response = response
            last_transport = None
            retry_after = _vintage_retry_after_seconds(response)

        if attempt == _VINTAGE_RETRY_ATTEMPTS - 1:
            break

        wait = retry_after if retry_after is not None else delay
        spent = time.monotonic() - started
        if spent + wait > _VINTAGE_RETRY_BUDGET_S:
            logger.warning(
                "Vintage tract lookup retry exceeds the request budget, giving up",
                extra={
                    "vintage": params.get("vintage"),
                    "attempt": attempt + 1,
                    "wait_s": wait,
                    "spent_s": spent,
                },
            )
            break

        wait = min(_vintage_jittered(wait), _VINTAGE_RETRY_BUDGET_S - spent)
        logger.warning(
            "Vintage tract lookup failed; retrying",
            extra={
                "vintage": params.get("vintage"),
                "attempt": attempt + 1,
                "wait_s": wait,
                "status": last_status,
                "error": str(last_transport) if last_transport else None,
            },
        )
        await asyncio.sleep(wait)
        delay *= 2

    if last_transport is not None:
        raise GeocoderUnavailableError(
            f"Vintage tract lookup error: {_describe(last_transport)}"
        ) from last_transport

    assert last_status is not None and last_response is not None
    try:
        last_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise GeocoderUnavailableError(f"Vintage tract lookup error: {_describe(exc)}") from exc
    raise AssertionError("unreachable: raise_for_status must raise for a retryable status")


async def lookup_tract_at_vintage(
    latitude: float,
    longitude: float,
    vintage: str,
    settings: Settings,
) -> str | None:
    """Return the tract FIPS containing a point in a given geography vintage.

    Tract boundaries are redrawn every decade, so the tract a parcel sits in
    under the current (2020) geography may not exist in the geography an older
    ACS or decennial vintage was published on.  Resolving the point again at
    that vintage is the only reliable way to find the tract that does — FIPS
    arithmetic does not work, because a split does not preserve numbering
    (Denver 41.07 became 41.11, among others).

    Returns None when the vintage yields no tract for the point.

    Raises:
        GeocoderUnavailableError: Census API unreachable after retries, or a
            terminal (non-retryable) HTTP status. The caller (`_VintageTracts`
            in tasks/timeline.py) does *not* catch this and fall back to the
            stored tract — Z6: a wrong tract silently written as `ok` is worse
            than a `failed` row the ledger can retry.
    """
    url = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
    params: dict[str, str] = {
        "x": str(longitude),
        "y": str(latitude),
        "benchmark": _BENCHMARK,
        "vintage": vintage,
        "layers": "Census Tracts",
        "format": "json",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key

    logger.info(
        "Looking up tract at vintage",
        extra={"lat": latitude, "lon": longitude, "vintage": vintage},
    )

    async with httpx.AsyncClient(timeout=settings.census_geocoder_timeout) as client:
        response = await _vintage_get_with_retry(client, url, params)

    data = _parse_json(response, "Census reverse geocoder")

    try:
        geographies = (data.get("result") or {}).get("geographies") or {}
        census_tracts = geographies.get("Census Tracts", [])
        if not census_tracts:
            logger.info(
                "No tract for point in vintage",
                extra={"vintage": vintage},
            )
            return None

        tract = census_tracts[0]
        state_fips = tract.get("STATE")
        county_fips = tract.get("COUNTY")
        tract_fips = tract.get("TRACT")
    except _SHAPE_ERRORS as exc:
        raise _shape_error("Census reverse geocoder", exc) from exc

    if not (state_fips and county_fips and tract_fips):
        return None

    return f"{state_fips}{county_fips}{tract_fips}"
