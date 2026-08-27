"""Reading the ledger: latest outcome per group, and the retry policy.

The write side is ``test_year_ledger.py``. This is the read side — the query
``ledger_gaps.py``, ``maybe_refetch_for_backfill`` and ``requeue_parcels.py
--from-ledger`` all go through, and the table that decides what any of them
would act on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.parcels import TimelineRequest
from app.services import ledger as ledger_service
from app.services import year_ledger


def _run(
    factory: sessionmaker[Session],
    parcel_id: uuid.UUID,
    *,
    sources: tuple[str, ...],
    age_hours: float,
    declared: list[str] | None = None,
) -> dict[str, uuid.UUID]:
    """One timeline request with task rows, at a chosen age. Returns task ids."""
    request_id = uuid.uuid4()
    task_ids: dict[str, uuid.UUID] = {}
    created = datetime.now(UTC) - timedelta(hours=age_hours)
    with factory() as db:
        db.add(
            TimelineRequest(
                id=request_id,
                parcel_id=parcel_id,
                status="complete",
                sources=declared if declared is not None else list(sources),
                origin="user",
                created_at=created,
            )
        )
        db.commit()
        for source in sources:
            task_id = uuid.uuid4()
            task_ids[source] = task_id
            db.execute(
                text(
                    "INSERT INTO timeline_request_tasks"
                    " (id, timeline_request_id, source, status)"
                    " VALUES (:id, :request_id, :source, 'complete')"
                ).bindparams(bindparam("id", type_=Uuid()), bindparam("request_id", type_=Uuid())),
                {"id": task_id, "request_id": request_id, "source": source},
            )
        db.commit()
    return task_ids


def _parcel(factory: sessionmaker[Session]) -> uuid.UUID:
    parcel_id = uuid.uuid4()
    with factory() as db:
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude)"
                " VALUES (:id, '1 Test St', 39.5, -104.5)"
            ),
            {"id": str(parcel_id)},
        )
        db.commit()
    return parcel_id


def _record(
    factory: sessionmaker[Session],
    task_id: uuid.UUID,
    source: str,
    group_key: str,
    outcome: str,
    reason: str | None = None,
    detail: str | None = None,
) -> None:
    with factory() as db:
        year_ledger.record_year_outcome(db, task_id, source, group_key, outcome, reason, detail)


# ── Latest outcome across runs ───────────────────────────────────────────────


def test_the_second_run_wins(committing_db: sessionmaker[Session]) -> None:
    """A group healed on run 2 reads ok, and counts two attempts.

    "Latest" is by the request's created_at. Ordering by task id instead
    would be arbitrary — task ids are uuid4, random rather than monotonic —
    and this fixture is built so a wrong ordering picks the wrong row half
    the time rather than never.
    """
    parcel_id = _parcel(committing_db)
    first = _run(committing_db, parcel_id, sources=("landsat",), age_hours=48)
    second = _run(committing_db, parcel_id, sources=("landsat",), age_hours=1)
    _record(committing_db, first["landsat"], "landsat", "1993", "failed", "read_timeout")
    _record(committing_db, second["landsat"], "landsat", "1993", "ok")

    with committing_db() as db:
        groups = ledger_service.latest_outcomes(db, parcel_id=parcel_id)

    assert len(groups) == 1
    assert groups[0].outcome == "ok"
    assert groups[0].attempts == 2


def test_a_group_that_regressed_reads_failed(committing_db: sessionmaker[Session]) -> None:
    """ok on run 1, failed ever since — the direction that matters."""
    parcel_id = _parcel(committing_db)
    first = _run(committing_db, parcel_id, sources=("landsat",), age_hours=48)
    second = _run(committing_db, parcel_id, sources=("landsat",), age_hours=1)
    _record(committing_db, first["landsat"], "landsat", "1993", "ok")
    _record(committing_db, second["landsat"], "landsat", "1993", "failed", "read_timeout")

    with committing_db() as db:
        groups = ledger_service.latest_outcomes(db, parcel_id=parcel_id)

    assert groups[0].outcome == "failed"
    assert ledger_service.is_retryable(groups[0]) is True


def test_a_source_a_scoped_run_did_not_touch_keeps_its_old_answer(
    committing_db: sessionmaker[Session],
) -> None:
    """Scope safety: a run writes no rows for a source it did not run, so the
    previous run's row stays latest — which is the correct answer."""
    parcel_id = _parcel(committing_db)
    first = _run(committing_db, parcel_id, sources=("landsat", "naip"), age_hours=48)
    second = _run(committing_db, parcel_id, sources=("landsat",), age_hours=1, declared=["landsat"])
    _record(committing_db, first["landsat"], "landsat", "1993", "failed", "read_timeout")
    _record(committing_db, first["naip"], "naip", "2019", "failed", "read_timeout")
    _record(committing_db, second["landsat"], "landsat", "1993", "ok")

    with committing_db() as db:
        by_key = {
            (g.source, g.group_key): g
            for g in ledger_service.latest_outcomes(db, parcel_id=parcel_id)
        }

    assert by_key[("landsat", "1993")].outcome == "ok"
    assert by_key[("naip", "2019")].outcome == "failed"


def test_sources_filter_is_on_the_ledger_source(committing_db: sessionmaker[Session]) -> None:
    """One census task writes two ledger sources; selection tells them apart."""
    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("census",), age_hours=1)
    _record(committing_db, tasks["census"], "census_decennial", "2000", "absent", "api_no_data")
    _record(committing_db, tasks["census"], "census_acs5", "2009", "absent", "api_no_data")

    with committing_db() as db:
        groups = ledger_service.latest_outcomes(db, sources={"census_decennial"})

    assert [(g.source, g.group_key) for g in groups] == [("census_decennial", "2000")]
    assert groups[0].task_source == "census", "a census_decennial retry needs a census task"


# ── The retry policy table, every row ────────────────────────────────────────


def _group(
    outcome: str, reason: str | None = None, attempts: int = 1
) -> ledger_service.LedgerGroup:
    return ledger_service.LedgerGroup(
        parcel_id=uuid.uuid4(),
        source="naip",
        group_key="2019",
        outcome=outcome,
        reason=reason,
        detail=None,
        run_at=None,
        attempts=attempts,
    )


@pytest.mark.parametrize(
    ("outcome", "reason", "expected"),
    [
        ("failed", "read_timeout", ledger_service.RETRY),
        ("failed", "connect_error", ledger_service.RETRY),
        ("failed", "sign_429", ledger_service.RETRY),
        ("failed", "http_500", ledger_service.RETRY),
        ("failed", "validation_failed", ledger_service.RETRY),
        ("suppressed", "naip_no_point_coverage", ledger_service.NEVER),
        ("suppressed", "no_cog_url", ledger_service.NEVER),
        ("absent", "no_scenes", ledger_service.NEVER),
        ("absent", "no_covering_item", ledger_service.NEVER),
        ("absent", "all_cloud_filtered", ledger_service.NEEDS_CLOUD_FLAG),
        ("absent", "api_no_data", ledger_service.NEEDS_ABSENT_API_FLAG),
        ("indeterminate", "naip item cap", ledger_service.RETRY_ONCE),
        ("ok", None, ledger_service.NEVER),
    ],
)
def test_every_retry_policy_row(outcome: str, reason: str | None, expected: str) -> None:
    assert ledger_service.retry_policy(outcome, reason) == expected


def test_an_unclassified_pair_is_never_and_says_so(caplog: pytest.LogCaptureFixture) -> None:
    """A reason added to the vocabulary without a decision here must announce
    itself. Silence would sweep it into "no" and nobody would know."""
    with caplog.at_level("WARNING", logger="app.services.ledger"):
        assert ledger_service.retry_policy("absent", "brand_new_reason") == ledger_service.NEVER

    record = next(r for r in caplog.records if "Retry policy gap" in r.getMessage())
    assert record.reason == "brand_new_reason"  # type: ignore[attr-defined]  # extra= field


def test_the_flag_gated_classes_need_their_flag() -> None:
    cloud = _group("absent", "all_cloud_filtered")
    absent_api = _group("absent", "api_no_data")

    assert ledger_service.is_retryable(cloud) is False
    assert ledger_service.is_retryable(cloud, include_cloud_filtered=True) is True
    assert ledger_service.is_retryable(absent_api) is False
    assert ledger_service.is_retryable(absent_api, include_absent_api=True) is True
    # The flags are not interchangeable.
    assert ledger_service.is_retryable(cloud, include_absent_api=True) is False
    assert ledger_service.is_retryable(absent_api, include_cloud_filtered=True) is False


def test_indeterminate_is_retried_once_and_then_never() -> None:
    """Re-running under the same response cap reproduces the same
    uncertainty, so the second answer is a code fix, not a third attempt."""
    assert ledger_service.is_retryable(_group("indeterminate", "item cap", attempts=1)) is True
    assert ledger_service.is_retryable(_group("indeterminate", "item cap", attempts=2)) is False


def test_a_suppressed_group_is_never_retried(committing_db: sessionmaker[Session]) -> None:
    """e513188c's NAIP 2023: retrying re-suppresses. Reconciliation is the answer."""
    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("naip",), age_hours=1)
    _record(
        committing_db,
        tasks["naip"],
        "naip",
        "2023",
        "suppressed",
        "naip_no_point_coverage",
        "selected tiles do not contain the parcel: nj_m_4007309_sw_18_030_20230820_20231019",
    )

    with committing_db() as db:
        assert ledger_service.retryable_groups(db, parcel_id=parcel_id) == []


# ── Stale groups: current code no longer attempts them (Y3) ─────────────────


def test_attempted_group_keys_excludes_a_retired_year() -> None:
    """e6afa9b dropped 1990 from DECENNIAL_YEARS; 2000 stayed."""
    attempted = ledger_service.attempted_group_keys("census_decennial")
    assert "1990" not in attempted
    assert "2000" in attempted


def test_attempted_group_keys_rejects_an_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown ledger source"):
        ledger_service.attempted_group_keys("not_a_real_source")


def test_imagery_start_years_agree_with_the_timeline_task() -> None:
    """attempted_group_keys' floor and tasks/timeline.py's _SOURCES floor
    must never drift apart — see IMAGERY_SOURCE_START_YEAR in imagery.py.
    """
    from app.services import imagery as imagery_service
    from app.tasks.timeline import _SOURCES

    by_source = {entry["source"]: entry for entry in _SOURCES}
    for source, start_year in imagery_service.IMAGERY_SOURCE_START_YEAR.items():
        attempted = ledger_service.attempted_group_keys(source)
        assert min(attempted) == imagery_service.encode_group_key("year", start_year)

        entry = by_source[source]
        if "start_year" in entry:
            assert entry["start_year"] == start_year
        else:
            assert entry["start_date"] == f"{start_year}-01-01"


def test_a_stale_group_is_never_selected_even_with_every_flag(
    committing_db: sessionmaker[Session],
) -> None:
    """The Y3 fixture: a retired-year row and a live-year row, same outcome.

    Only the live year selects. Delete ``is_stale`` from ``is_retryable`` and
    both select — 187 parcels' worth of 1990 rows staying "retryable"
    forever is exactly the defect this guards against.
    """
    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("census",), age_hours=2)
    _record(committing_db, tasks["census"], "census_decennial", "1990", "absent", "api_no_data")
    _record(committing_db, tasks["census"], "census_decennial", "2000", "absent", "api_no_data")

    with committing_db() as db:
        selected = ledger_service.retryable_groups(db, parcel_id=parcel_id, include_absent_api=True)

    assert [(g.source, g.group_key) for g in selected] == [("census_decennial", "2000")]


def test_is_stale_matches_attempted_group_keys() -> None:
    stale = _group("absent", "api_no_data")
    assert ledger_service.is_stale(
        ledger_service.LedgerGroup(
            parcel_id=stale.parcel_id,
            source="census_decennial",
            group_key="1990",
            outcome="absent",
            reason="api_no_data",
            detail=None,
            run_at=None,
            attempts=1,
        )
    )
    assert not ledger_service.is_stale(
        ledger_service.LedgerGroup(
            parcel_id=stale.parcel_id,
            source="census_decennial",
            group_key="2000",
            outcome="absent",
            reason="api_no_data",
            detail=None,
            run_at=None,
            attempts=1,
        )
    )


# ── Per-source dispatch history ──────────────────────────────────────────────


def test_last_attempt_is_per_source(committing_db: sessionmaker[Session]) -> None:
    """A census-only backfill at T must not block a landsat backfill.

    That is exactly what a single per-parcel max(created_at) did.
    """
    parcel_id = _parcel(committing_db)
    _run(committing_db, parcel_id, sources=("landsat",), age_hours=48, declared=["landsat"])
    _run(committing_db, parcel_id, sources=("census",), age_hours=1, declared=["census"])

    with committing_db() as db:
        last = ledger_service.last_attempt_by_source(db, parcel_id)

    now = datetime.now(UTC)
    assert set(last) == {"landsat", "census"}
    landsat_age = (now - last["landsat"].replace(tzinfo=UTC)).total_seconds() / 3600
    census_age = (now - last["census"].replace(tzinfo=UTC)).total_seconds() / 3600
    assert landsat_age > 24
    assert census_age < 2


def test_a_full_scope_run_marks_every_source(committing_db: sessionmaker[Session]) -> None:
    parcel_id = _parcel(committing_db)
    _run(
        committing_db,
        parcel_id,
        sources=("landsat",),
        age_hours=1,
        declared=list(TimelineRequest.FULL_SCOPE),
    )

    with committing_db() as db:
        last = ledger_service.last_attempt_by_source(db, parcel_id)

    assert set(last) == set(TimelineRequest.FULL_SCOPE)


# ── Selection folds onto the sources that would re-run it ────────────────────


def test_crawford_shape_selects_landsat_and_naip_only(
    committing_db: sessionmaker[Session],
) -> None:
    """6563dedf: 16 failed landsat years, 17 failed naip years, everything
    else fine, request reading complete. The selection is a two-source
    request, not a full pipeline re-run."""
    parcel_id = _parcel(committing_db)
    tasks = _run(
        committing_db,
        parcel_id,
        sources=("landsat", "naip", "sentinel2", "census", "usgs_topo"),
        age_hours=12,
        declared=list(TimelineRequest.FULL_SCOPE),
    )
    for year in range(1984, 2000):
        _record(committing_db, tasks["landsat"], "landsat", str(year), "failed", "read_timeout")
    for year in range(2010, 2027):
        _record(committing_db, tasks["naip"], "naip", str(year), "failed", "read_timeout")
    _record(committing_db, tasks["sentinel2"], "sentinel2", "2015", "absent", "all_cloud_filtered")
    _record(committing_db, tasks["census"], "census_decennial", "2000", "absent", "api_no_data")
    _record(committing_db, tasks["usgs_topo"], "usgs_topo", "1960s", "ok")

    with committing_db() as db:
        selected = ledger_service.group_by_task_source(
            ledger_service.retryable_groups(db, parcel_id=parcel_id)
        )

    assert sorted(selected) == ["landsat", "naip"]
    assert len(selected["landsat"]) == 16
    assert len(selected["naip"]) == 17

    with committing_db() as db:
        with_flags = ledger_service.group_by_task_source(
            ledger_service.retryable_groups(
                db,
                parcel_id=parcel_id,
                include_cloud_filtered=True,
                include_absent_api=True,
            )
        )
    assert sorted(with_flags) == ["census", "landsat", "naip", "sentinel2"]
