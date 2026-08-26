"""Global admission control: kill switch and in-flight cap (security audit SEC-2)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.parcels import TimelineRequest
from app.services.admission import AdmissionRefused, ensure_admission, inflight_depth


def _settings(**overrides: object) -> Settings:
    # The reserve defaults to 0 here so the cap-boundary tests below keep
    # measuring the cap. Production's default is 5, and the tests that are
    # about the reserve set it explicitly.
    overrides.setdefault("user_admission_reserve", 0)
    return Settings(database_url="postgresql://t:t@localhost/t", **overrides)  # type: ignore[arg-type]  # test overrides are Settings fields


def _insert_parcel(db: Session, parcel_id: uuid.UUID) -> None:
    from sqlalchemy import text

    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude, point) "
            "VALUES (:id, 'x', 39.7, -105.0, 'POINT(-105.0 39.7)')"
        ),
        {"id": str(parcel_id)},
    )
    db.commit()


def _fill_queue(db: Session, n: int, status: str = "queued") -> None:
    for _ in range(n):
        pid = uuid.uuid4()
        _insert_parcel(db, pid)
        db.add(TimelineRequest(id=uuid.uuid4(), parcel_id=pid, status=status))
    db.commit()


# ── Cap boundary ──────────────────────────────────────────────────────────────


def test_admits_below_the_cap_and_refuses_at_it(db: Session) -> None:
    settings = _settings(max_inflight_timeline_requests=3)
    _fill_queue(db, 2)
    ensure_admission(db, settings, what="parcel")  # depth 2 < 3

    _fill_queue(db, 1)
    assert inflight_depth(db) == 3
    with pytest.raises(AdmissionRefused) as exc_info:
        ensure_admission(db, settings, what="parcel")
    assert exc_info.value.reason == "queue_full"
    assert exc_info.value.depth == 3


def test_complete_and_failed_requests_do_not_count(db: Session) -> None:
    settings = _settings(max_inflight_timeline_requests=1)
    _fill_queue(db, 5, status="complete")
    _fill_queue(db, 5, status="failed")
    ensure_admission(db, settings, what="parcel")


# ── Kill switch ───────────────────────────────────────────────────────────────


def test_kill_switch_refuses_with_an_empty_queue(db: Session) -> None:
    with pytest.raises(AdmissionRefused) as exc_info:
        ensure_admission(db, _settings(accept_new_parcels=False), what="parcel")
    assert exc_info.value.reason == "kill_switch"


def test_kill_switch_off_is_the_default(db: Session) -> None:
    assert _settings().accept_new_parcels is True
    ensure_admission(db, _settings(), what="parcel")


def test_kill_switch_is_an_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCEPT_NEW_PARCELS", "false")
    assert Settings(database_url="postgresql://t:t@localhost/t").accept_new_parcels is False


# ── The gate is on creation only; existing parcels stay browsable ─────────────


def test_existing_parcel_is_returned_under_the_kill_switch(db: Session) -> None:
    from app.services.geocoder import GeocodeResult
    from app.services.parcels import get_or_create_parcel

    existing = SimpleNamespace(
        id=uuid.uuid4(), census_tract_id="x", county="Denver", state_fips="08"
    )
    result = GeocodeResult("1 Main", 39.7, -105.0, "x", "Denver", "08")
    with patch("app.services.parcels.find_nearby_parcel", return_value=existing):
        parcel, is_new = get_or_create_parcel(
            db, "1 Main", result, _settings(accept_new_parcels=False)
        )
    assert parcel is existing
    assert is_new is False


def test_new_parcel_is_refused_under_the_kill_switch(db: Session) -> None:
    from app.services.geocoder import GeocodeResult
    from app.services.parcels import get_or_create_parcel

    result = GeocodeResult("1 Main", 39.7, -105.0, "x", "Denver", "08")
    with (
        patch("app.services.parcels.find_nearby_parcel", return_value=None),
        pytest.raises(AdmissionRefused),
    ):
        get_or_create_parcel(db, "1 Main", result, _settings(accept_new_parcels=False))


def test_timeline_route_reuses_a_complete_request_under_the_kill_switch(
    client: TestClient, db: Session
) -> None:
    """A deep link to an existing parcel still loads: the explore page
    POSTs /timeline on every such load, and it must not 503."""
    from app.services.imagery import get_or_create_timeline_request, update_timeline_request_status

    pid = uuid.uuid4()
    _insert_parcel(db, pid)
    req, _ = get_or_create_timeline_request(db, pid)
    update_timeline_request_status(db, req, "complete")

    with (
        patch(
            "app.services.imagery.get_settings",
            return_value=_settings(accept_new_parcels=False),
        ),
        # The route's backfill lookup loads the Parcel ORM row, which needs
        # PostGIS; None skips it, which is also what the kill switch would do.
        patch.object(db, "get", return_value=None),
    ):
        resp = client.post(f"/api/v1/parcels/{pid}/timeline")

    assert resp.status_code == 202
    assert resp.json()["timeline_request_id"] == str(req.id)


def test_timeline_route_503s_for_a_never_run_parcel_under_the_kill_switch(
    client: TestClient, db: Session
) -> None:
    pid = uuid.uuid4()
    _insert_parcel(db, pid)

    with patch(
        "app.services.imagery.get_settings", return_value=_settings(accept_new_parcels=False)
    ):
        resp = client.post(f"/api/v1/parcels/{pid}/timeline")

    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "120"


def test_backfill_is_suppressed_quietly_when_refused(db: Session) -> None:
    """Optional work on a parcel that already renders: log, return None, no error."""
    from datetime import UTC, datetime, timedelta

    from app.models.parcels import TimelineRequestTask
    from app.services.imagery import maybe_refetch_for_backfill

    pid = uuid.uuid4()
    _insert_parcel(db, pid)
    req = TimelineRequest(
        id=uuid.uuid4(),
        parcel_id=pid,
        status="complete",
        created_at=datetime.now(UTC) - timedelta(hours=48),
    )
    db.add(req)
    db.add(
        TimelineRequestTask(
            id=uuid.uuid4(), timeline_request_id=req.id, source="usgs_topo", status="complete"
        )
    )
    db.commit()
    parcel = SimpleNamespace(id=pid, census_tract_id="08031000100", county=None)

    with patch(
        "app.services.imagery.get_settings", return_value=_settings(accept_new_parcels=False)
    ):
        assert maybe_refetch_for_backfill(db, parcel, req) is None  # type: ignore[arg-type]  # SimpleNamespace stands in for Parcel
    assert inflight_depth(db) == 0


def test_refusal_is_logged_with_its_reason(db: Session, caplog: pytest.LogCaptureFixture) -> None:
    with (
        caplog.at_level("WARNING", logger="app.services.admission"),
        pytest.raises(AdmissionRefused),
    ):
        ensure_admission(db, _settings(accept_new_parcels=False), what="parcel")
    record = next(r for r in caplog.records if r.getMessage() == "Admission refused")
    assert record.reason == "kill_switch"  # type: ignore[attr-defined]  # extra= field
    assert record.what == "parcel"  # type: ignore[attr-defined]  # extra= field


# ── Redis down, per path class (REMEDIATION-1.md G2) ─────────────────────────


def _limited_client(client: TestClient) -> TestClient:
    from app.config import get_settings

    client.app.dependency_overrides[get_settings] = lambda: _settings(rate_limit_enabled=True)  # type: ignore[attr-defined]  # TestClient.app is typed as the ASGI protocol, not FastAPI
    return client


def test_geocode_fails_closed_when_redis_is_down(client: TestClient) -> None:
    from redis.exceptions import RedisError

    redis = MagicMock()
    redis.pipeline = MagicMock(side_effect=RedisError("down"))
    with (
        patch("app.api.rate_limit.get_async_redis", return_value=redis),
        patch("app.api.v1.geocode.geocoder_service.geocode_address") as geocode,
    ):
        resp = _limited_client(client).post(
            "/api/v1/geocode", json={"address": "1600 Pennsylvania Ave NW, Washington DC"}
        )
    assert resp.status_code == 503
    geocode.assert_not_called()


def test_autocomplete_fails_open_when_redis_is_down(client: TestClient) -> None:
    import httpx
    from redis.exceptions import RedisError

    redis = MagicMock()
    redis.pipeline = MagicMock(side_effect=RedisError("down"))
    with (
        patch("app.api.rate_limit.get_async_redis", return_value=redis),
        patch("app.api.v1.geocode.get_redis", side_effect=RedisError("down")),
        patch(
            "app.api.v1.geocode.httpx.AsyncClient",
            side_effect=httpx.ConnectError("offline"),
        ),
    ):
        resp = _limited_client(client).get("/api/v1/geocode/autocomplete?q=1600+Penn")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Batch callers wait out a full queue ───────────────────────────────────────
#
# Delete-the-fix: remove the ``except AdmissionRefused`` branch in
# ``create_queued_request_waiting`` (or point the scripts back at
# ``_create_queued_request``) and
# ``test_waiting_create_retries_after_a_refusal`` fails with the refusal that
# stopped the 2026-08-25 sweep at 30 of 184 parcels.


def _drain(db: Session) -> None:
    from sqlalchemy import text

    db.execute(text("UPDATE timeline_requests SET status = 'complete'"))
    db.commit()


def test_wait_returns_once_a_slot_opens(db: Session) -> None:
    from app.services.admission import wait_for_admission_slot

    settings = _settings(max_inflight_timeline_requests=1)
    _fill_queue(db, 1)
    naps: list[float] = []

    def sleeper(seconds: float) -> None:
        naps.append(seconds)
        _drain(db)

    opened = wait_for_admission_slot(
        db, settings, deadline=100.0, poll_seconds=5.0, sleeper=sleeper, clock=lambda: 0.0
    )

    assert opened is True
    assert naps == [5.0]


def test_wait_gives_up_when_the_budget_runs_out(db: Session) -> None:
    from app.services.admission import wait_for_admission_slot

    settings = _settings(max_inflight_timeline_requests=1)
    _fill_queue(db, 1)
    ticks = iter([0.0, 10.0, 20.0])
    naps: list[float] = []

    opened = wait_for_admission_slot(
        db,
        settings,
        deadline=15.0,
        poll_seconds=5.0,
        sleeper=naps.append,
        clock=lambda: next(ticks),
    )

    assert opened is False
    # Two naps inside the budget (clock 0 and 10 against a deadline of 15),
    # then the third check finds the budget spent and refuses.
    assert naps == [5.0, 5.0]


def test_wait_does_not_ride_out_the_kill_switch(db: Session) -> None:
    from app.services.admission import wait_for_admission_slot

    settings = _settings(max_inflight_timeline_requests=1, accept_new_parcels=False)
    _fill_queue(db, 1)
    naps: list[float] = []

    opened = wait_for_admission_slot(
        db, settings, deadline=1e9, poll_seconds=5.0, sleeper=naps.append, clock=lambda: 0.0
    )

    assert opened is False
    assert naps == []


def test_waiting_create_retries_after_a_refusal(db: Session) -> None:
    """The fix, end to end: a full queue costs a wait, not the rest of the batch."""
    from app.services import imagery as imagery_service

    settings = _settings(max_inflight_timeline_requests=1)
    _fill_queue(db, 1)
    target = uuid.uuid4()
    _insert_parcel(db, target)
    naps: list[float] = []

    def sleeper(seconds: float) -> None:
        naps.append(seconds)
        _drain(db)

    with patch("app.services.imagery.get_settings", return_value=settings):
        request, created = imagery_service.create_queued_request_waiting(
            db,
            target,
            deadline=100.0,
            poll_seconds=1.0,
            sleeper=sleeper,
            clock=lambda: 0.0,
        )

    assert created is True
    assert request.parcel_id == target
    assert naps == [1.0], "the refusal must cost exactly one wait, not an abort"


def test_waiting_create_raises_once_the_budget_is_spent(db: Session) -> None:
    from app.services import imagery as imagery_service

    settings = _settings(max_inflight_timeline_requests=1)
    _fill_queue(db, 1)
    target = uuid.uuid4()
    _insert_parcel(db, target)

    with (
        patch("app.services.imagery.get_settings", return_value=settings),
        pytest.raises(AdmissionRefused) as exc_info,
    ):
        imagery_service.create_queued_request_waiting(
            db,
            target,
            deadline=-1.0,
            sleeper=lambda _: None,
            clock=lambda: 0.0,
        )

    assert exc_info.value.reason == "queue_full"


def test_waiting_create_does_not_wait_out_the_kill_switch(db: Session) -> None:
    from app.services import imagery as imagery_service

    settings = _settings(accept_new_parcels=False)
    target = uuid.uuid4()
    _insert_parcel(db, target)
    naps: list[float] = []

    with (
        patch("app.services.imagery.get_settings", return_value=settings),
        pytest.raises(AdmissionRefused) as exc_info,
    ):
        imagery_service.create_queued_request_waiting(
            db, target, deadline=1e9, sleeper=naps.append, clock=lambda: 0.0
        )

    assert exc_info.value.reason == "kill_switch"
    assert naps == []


# ── The user reserve (M3 item 5) ─────────────────────────────────────────────


def test_reserve_refuses_a_heal_while_still_admitting_a_user_request(db: Session) -> None:
    """25 in flight, cap 30, reserve 5: user gets in, heal does not.

    At the gate a first-time visitor's geocode and a six-year-old Landsat gap
    being retried were byte-identical until ``TimelineRequest.origin`` existed
    — and only the geocode's refusal is a 503 someone is looking at. Delete
    the ``origin`` branch from ``effective_cap`` and the heal is admitted.
    """
    settings = _settings(max_inflight_timeline_requests=30, user_admission_reserve=5)
    _fill_queue(db, 25)

    ensure_admission(db, settings, what="timeline_request", origin="user")

    for origin in ("backfill", "heal"):
        with pytest.raises(AdmissionRefused) as exc_info:
            ensure_admission(db, settings, what="timeline_request", origin=origin)
        assert exc_info.value.reason == "queue_full"
        assert exc_info.value.depth == 25


def test_reserve_admits_non_user_work_below_the_reduced_cap(db: Session) -> None:
    settings = _settings(max_inflight_timeline_requests=30, user_admission_reserve=5)
    _fill_queue(db, 24)

    ensure_admission(db, settings, what="timeline_request", origin="heal")


def test_reserve_at_or_above_the_cap_refuses_rather_than_spins(db: Session) -> None:
    """A reserve that leaves no slots is a refusal, not an unbounded wait."""
    from app.services.admission import effective_cap, wait_for_admission_slot

    settings = _settings(max_inflight_timeline_requests=2, user_admission_reserve=9)
    assert effective_cap(settings, "heal") == 0

    naps: list[float] = []
    opened = wait_for_admission_slot(
        db,
        settings,
        deadline=1e9,
        origin="heal",
        poll_seconds=1.0,
        sleeper=naps.append,
        clock=lambda: 0.0,
    )

    assert opened is False
    assert naps == [], "waiting on a cap of zero can never succeed"
