"""Credentials never reach a log line or a task row as text (security audit SEC-4)."""

from __future__ import annotations

import io
import logging

import httpx
import pytest

from app.config import Settings
from app.logging_config import configure_logging
from app.redact import redact
from app.services.geocoder import GeocoderUnavailableError, reverse_geocode

CENSUS_KEY = "c3n5u5k3y0123456789abcdef"
SAS_SIG = "Zm9vYmFyc2lnbmF0dXJl%2Fabc%3D"
DB_PASSWORD = "hunter2pass"
TITILER_TOKEN = "titilertok3n"


@pytest.mark.parametrize(
    "text",
    [
        f"Server error '500' for url 'https://geocoding.geo.census.gov/geocoder?address=1+Main&key={CENSUS_KEY}&format=json'",
        f"https://naipeuwest.blob.core.windows.net/naip/x.tif?st=2026-08-22T00%3A00Z&se=2026-08-22T01Z&sp=rl&sv=2024-05-04&sr=c&skoid=k&sig={SAS_SIG}",
        f"GDAL: /vsicurl/https://landsateuwest.blob.core.windows.net/x.TIF?se=2026&sig={SAS_SIG}: 403",
        f"http://titiler/cog/info?url=https%3A%2F%2Fx&access_token={TITILER_TOKEN}",
        f"postgresql://neondb_owner:{DB_PASSWORD}@ep-x.neon.tech/neondb?sslmode=require",
        f"rediss://default:{DB_PASSWORD}@fly-upstash.upstash.io:6379?ssl_cert_reqs=required",
    ],
)
def test_redact_removes_the_secret_value(text: str) -> None:
    out = redact(text)
    for secret in (CENSUS_KEY, SAS_SIG, DB_PASSWORD, TITILER_TOKEN):
        assert secret not in out, out
    # Non-secret structure survives so the line stays debuggable.
    assert "://" in out


def test_redact_leaves_ordinary_text_alone() -> None:
    text = "Census API: no data for tract 08031004107 (response=ok&house=1)"
    assert redact(text) == text


def _capture_logs() -> io.StringIO:
    stream = io.StringIO()
    configure_logging(Settings(database_url="postgresql://t:t@localhost/t", app_env="production"))
    handler = logging.getLogger().handlers[0]
    handler.setStream(stream)
    return stream


def test_logged_httpx_exception_does_not_carry_the_census_key() -> None:
    """The shape that leaked: exc_info=<HTTPStatusError> whose message embeds the URL."""
    stream = _capture_logs()
    request = httpx.Request("GET", f"https://geocoding.geo.census.gov/x?y=1&key={CENSUS_KEY}")
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logging.getLogger("test").error("Census error", exc_info=exc)
        logging.getLogger("test").error("Census error", extra={"error": str(exc)})
        logging.getLogger("test").error("Census error: %s", exc)
    logging.getLogger().handlers[0].flush()

    out = stream.getvalue()
    assert "Census error" in out
    assert "Server error '500" in out
    assert CENSUS_KEY not in out


@pytest.mark.asyncio
async def test_reverse_geocode_error_message_carries_status_not_url() -> None:
    settings = Settings(database_url="postgresql://t:t@localhost/t", census_api_key=CENSUS_KEY)

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    transport = httpx.MockTransport(boom)
    real_client = httpx.AsyncClient

    class _Client(real_client):  # type: ignore[misc, valid-type]  # subclassing to inject the mock transport
        def __init__(self, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(**kwargs)  # type: ignore[arg-type]

    from unittest.mock import patch

    with (
        patch("app.services.geocoder.httpx.AsyncClient", _Client),
        pytest.raises(GeocoderUnavailableError) as exc_info,
    ):
        await reverse_geocode(39.7, -105.0, "1 Main St", settings)

    message = str(exc_info.value)
    assert "HTTP 500" in message
    assert CENSUS_KEY not in message
    assert "geocoding.geo.census.gov" not in message


def test_task_row_error_message_is_scrubbed(db) -> None:  # type: ignore[no-untyped-def]  # db fixture from conftest
    """GET /timeline-requests/{id} serves error_message to clients; scrub at the sink."""
    import uuid

    from sqlalchemy import text

    from app.services.imagery import (
        create_request_tasks,
        get_or_create_timeline_request,
        update_request_task,
        update_timeline_request_status,
    )

    parcel_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude, point) "
            "VALUES (:id, 'x', 39.7, -105.0, 'POINT(-105.0 39.7)')"
        ),
        {"id": str(parcel_id)},
    )
    db.commit()
    request, _ = get_or_create_timeline_request(db, parcel_id)
    (task,) = create_request_tasks(db, request.id, ["landsat"])

    leak = f"Server error '504' for url 'https://x/?key={CENSUS_KEY}&sig={SAS_SIG}'"
    update_request_task(db, task, "failed", error_message=leak)
    update_timeline_request_status(db, request, "failed", error_message=leak)

    assert CENSUS_KEY not in (task.error_message or "")
    assert SAS_SIG not in (task.error_message or "")
    assert CENSUS_KEY not in (request.error_message or "")
