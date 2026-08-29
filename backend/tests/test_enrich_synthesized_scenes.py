"""Tests for scripts/enrich_synthesized_scenes.py.

The script lives outside the backend package, so it is loaded by path the way
``test_remove_uncovered_snapshots.py`` loads its subject. **No network:** the
STAC layer
is one injected object with two methods, and every test supplies a fake whose
catalog is a dict. That is deliberate — a pass whose acceptance criterion is
"the item's image href equals this row's ``cog_url``" is exactly the thing a
live catalog would make untestable, because the real catalog can change under
the test.

Delete-the-fix, one clause per test:

* the ``extract_cog_url(item, ...) == row.cog_url`` check in ``resolve_row``'s
  GET branch — remove it and ``test_plausible_item_with_a_different_cog_url``
  writes another item's id, footprint and bbox onto the row, which is the
  whole failure the ``cog_url`` criterion exists to prevent.
* the search fallback — remove it and
  ``test_prefix_candidate_is_corrected_by_search`` leaves the row in the queue
  with its candidate id, since its GET is a 404.
* the collision branch in ``apply_resolutions`` — remove it and
  ``test_collision_merges_and_repoints_references`` fails on
  ``uq_scenes_collection_item`` instead of merging.
* ``_merge_scene``'s repointing loop — remove it and the same test finds a
  ``mosaic_scene_ids`` entry pointing at a deleted scene.
* the ``item is None`` early continue — remove it and
  ``test_forbidden_item_is_left_in_the_queue`` raises instead of reporting
  ``unmatched-403``.
* the ``WHERE provenance = 'mosaic_url'`` filter in ``load_queue`` — remove it
  and ``test_second_run_is_a_no_op`` re-fetches and re-writes rows that are
  already enriched.
* ``_SEARCH_RETRYABLE_STATUSES`` including 403 — put it back to
  ``_ITEM_RETRYABLE_STATUSES`` (NORM-10) and
  ``test_search_403_retries_and_succeeds`` fails: the first 403 would raise
  straight out of ``search`` instead of being retried.
* ``_ITEM_RETRYABLE_STATUSES`` *not* including 403 — add it and
  ``test_item_403_does_not_retry_falls_through_to_search`` fails: the item
  GET would retry three more times instead of returning ``(403, None)`` on
  the first response.
* the ``FETCH_ATTEMPTS`` bound in ``_request``'s retry loop — remove it (loop
  forever) and ``test_search_403_exhausts_retry_budget_is_an_error`` hangs
  instead of raising once the budget runs out.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

_HERE = Path(__file__).resolve()
_SCRIPT = next(
    p / "scripts" / "enrich_synthesized_scenes.py"
    for p in _HERE.parents
    if (p / "scripts" / "enrich_synthesized_scenes.py").exists()
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("enrich_synthesized_scenes", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["enrich_synthesized_scenes"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

PARCEL = "81b2d663-1851-438d-a9fa-58d665e32e25"
_NAIP_BASE = "https://naipeuwest.blob.core.windows.net/naip/v002/nj/2023/nj_030cm_2023/40074"

# The primary tile of a mosaic: a real snapshot row, so `provenance` is
# 'snapshot' and it is not in the queue.
PRIMARY_ITEM = "nj_m_4007309_sw_18_030_20230820_20231019"
PRIMARY_URL = f"{_NAIP_BASE}/m_4007309_sw_18_030_20230820_20231019.tif"

# An additional tile, synthesized from its URL. Its filename carries the
# publication date, so its candidate id is already the catalogued one.
EXACT_URL = f"{_NAIP_BASE}/m_4007424_ne_18_030_20230820_20231019.tif"
EXACT_ITEM = "nj_m_4007424_ne_18_030_20230820_20231019"

# The common shape: the filename omits the publication date the id carries,
# so the candidate is a proper prefix and the item GET 404s.
PREFIX_URL = f"{_NAIP_BASE}/m_4007416_se_18_030_20230820.tif"
PREFIX_CANDIDATE = "nj_m_4007416_se_18_030_20230820"
PREFIX_CATALOGUED = "nj_m_4007416_se_18_030_20230820_20231019"

GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74.0, 40.8], [-74.0, 40.7]]],
}


def _item(
    item_id: str, href: str, *, capture: str = "2023-08-20", gsd: float = 0.6
) -> dict[str, Any]:
    return {
        "id": item_id,
        "geometry": GEOMETRY,
        "bbox": [-74.0, 40.7, -73.9, 40.8],
        "properties": {"datetime": f"{capture}T00:00:00Z", "gsd": gsd},
        "assets": {
            "image": {
                "href": href,
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            }
        },
    }


class FakeStac:
    """The two PC calls, served from dicts. Counts every request it answers."""

    def __init__(
        self,
        *,
        items: dict[str, dict[str, Any]] | None = None,
        statuses: dict[str, int] | None = None,
        search_results: list[dict[str, Any]] | None = None,
    ) -> None:
        self.items = items or {}
        self.statuses = statuses or {}
        self.search_results = search_results or []
        self.gets: list[str] = []
        self.searches: list[tuple[str, str]] = []
        self.closed = False

    async def get_item(self, collection: str, item_id: str) -> tuple[int, dict[str, Any] | None]:
        self.gets.append(item_id)
        if item_id in self.items:
            return 200, self.items[item_id]
        return self.statuses.get(item_id, 404), None

    async def search(
        self, collection: str, bbox: tuple[float, float, float, float], datetime_range: str
    ) -> list[dict[str, Any]]:
        self.searches.append((collection, datetime_range))
        return self.search_results

    async def aclose(self) -> None:
        self.closed = True


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _insert_parcel(db: Session, parcel_id: str = PARCEL) -> None:
    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude)"
            " VALUES (:id, :address, :lat, :lng)"
        ),
        {
            "id": parcel_id,
            "address": "350 5th Ave, New York, NY 10118",
            "lat": 40.75,
            "lng": -73.99,
        },
    )


def _insert_scene(
    db: Session,
    *,
    item_id: str,
    cog_url: str,
    provenance: str,
    capture_date: str = "2023-08-20",
) -> str:
    scene_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date, cog_url,"
            " provenance, fetched_at)"
            " VALUES (:id, 'naip', 'naip', :item_id, :capture_date, :cog_url,"
            " :provenance, :now)"
        ),
        {
            "id": scene_id,
            "item_id": item_id,
            "capture_date": capture_date,
            "cog_url": cog_url,
            "provenance": provenance,
            "now": "2026-08-01 12:00:00",
        },
    )
    return scene_id


def _insert_parcel_scene(db: Session, *, scene_id: str, mosaic: list[str]) -> str:
    row_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO parcel_scenes (id, parcel_id, source, group_key, scene_id,"
            " mosaic_scene_ids, selected_at)"
            " VALUES (:id, :parcel_id, 'naip', '2023', :scene_id, :mosaic, :now)"
        ),
        {
            "id": row_id,
            "parcel_id": PARCEL,
            "scene_id": scene_id,
            "mosaic": script.json.dumps(mosaic) if mosaic else None,
            "now": "2026-08-01 12:00:00",
        },
    )
    return row_id


def _one_mosaic_scene(db: Session, *, item_id: str, cog_url: str) -> tuple[str, str, str]:
    """A parcel, a primary snapshot scene, and one synthesized tile it mosaics."""
    _insert_parcel(db)
    primary = _insert_scene(db, item_id=PRIMARY_ITEM, cog_url=PRIMARY_URL, provenance="snapshot")
    synthesized = _insert_scene(db, item_id=item_id, cog_url=cog_url, provenance="mosaic_url")
    row = _insert_parcel_scene(db, scene_id=primary, mosaic=[synthesized])
    return primary, synthesized, row


def _run(db: Session, stac: Any, tmp_path: Path, *, execute: bool = True) -> Any:
    return script.run(
        db,
        execute=execute,
        report_path=tmp_path / "report.md",
        lookup=stac,
    )


def _scene(db: Session, scene_id: str) -> Any:
    return db.execute(
        text(
            "SELECT item_id, capture_date, footprint, bbox, resolution_m, provenance"
            " FROM scenes WHERE id = :id"
        ),
        {"id": scene_id},
    ).first()


def _mosaic_ids(db: Session, row_id: str) -> list[str]:
    value = db.execute(
        text("SELECT mosaic_scene_ids FROM parcel_scenes WHERE id = :id"), {"id": row_id}
    ).scalar_one()
    return script._id_array(value)


# ── The two matching paths ────────────────────────────────────────────────────


def test_exact_candidate_enriches_in_place(db: Session, tmp_path: Path) -> None:
    """An id-endpoint hit whose href matches fills the item facts, keeps the id."""
    _, synthesized, _ = _one_mosaic_scene(db, item_id=EXACT_ITEM, cog_url=EXACT_URL)
    stac = FakeStac(items={EXACT_ITEM: _item(EXACT_ITEM, EXACT_URL)})

    out = _run(db, stac, tmp_path)

    assert (out.enriched, out.already_exact, out.id_corrected) == (1, 1, 0)
    assert stac.searches == []  # the GET settled it; no search was spent
    row = _scene(db, synthesized)
    assert row.item_id == EXACT_ITEM
    assert row.provenance == "enriched"
    assert row.footprint is not None
    assert row.bbox is not None
    assert row.resolution_m == 0.6


def test_prefix_candidate_is_corrected_by_search(db: Session, tmp_path: Path) -> None:
    """A 404 on the candidate id falls through to the search, which matches."""
    _, synthesized, _ = _one_mosaic_scene(db, item_id=PREFIX_CANDIDATE, cog_url=PREFIX_URL)
    stac = FakeStac(
        search_results=[
            _item("nj_m_9999999_ne_18_030_20230820_20231019", f"{_NAIP_BASE}/other.tif"),
            _item(PREFIX_CATALOGUED, PREFIX_URL),
        ]
    )

    out = _run(db, stac, tmp_path)

    assert (out.enriched, out.id_corrected) == (1, 1)
    assert stac.searches == [("naip", "2023-01-01T00:00:00Z/2023-12-31T23:59:59Z")]
    row = _scene(db, synthesized)
    assert row.item_id == PREFIX_CATALOGUED
    assert row.provenance == "enriched"
    assert row.footprint is not None


def test_plausible_item_with_a_different_cog_url_does_not_match(
    db: Session, tmp_path: Path
) -> None:
    """The criterion is cog_url equality, not "an item came back".

    Both lookups return a real, same-year, same-quad NAIP item — everything a
    date- or id-based matcher would accept — whose image href is another
    tile's. Nothing may be written.
    """
    _, synthesized, _ = _one_mosaic_scene(db, item_id=PREFIX_CANDIDATE, cog_url=PREFIX_URL)
    decoy = _item(PREFIX_CANDIDATE, f"{_NAIP_BASE}/m_4007416_se_18_030_20230819.tif")
    stac = FakeStac(items={PREFIX_CANDIDATE: decoy}, search_results=[decoy])

    out = _run(db, stac, tmp_path)

    assert (out.enriched, out.merged, out.unmatched) == (0, 0, 1)
    assert out.rows[0][1] == "unmatched-nomatch"
    row = _scene(db, synthesized)
    assert row.item_id == PREFIX_CANDIDATE
    assert row.provenance == "mosaic_url"
    assert row.footprint is None
    assert row.resolution_m is None


def test_forbidden_item_is_left_in_the_queue(db: Session, tmp_path: Path) -> None:
    """A 403 on the item endpoint, with no search match, changes nothing.

    The geometry audit hit six NAIP items PC answers 403 for, so a nonzero
    remainder is expected rather than exceptional; the row stays in the queue
    for a later run and the status is reported.
    """
    _, synthesized, _ = _one_mosaic_scene(db, item_id=PREFIX_CANDIDATE, cog_url=PREFIX_URL)
    stac = FakeStac(statuses={PREFIX_CANDIDATE: 403})

    out = _run(db, stac, tmp_path)

    assert (out.enriched, out.unmatched, out.errors) == (0, 1, 0)
    assert out.rows[0][1] == "unmatched-403"
    row = _scene(db, synthesized)
    assert row.provenance == "mosaic_url"
    assert row.item_id == PREFIX_CANDIDATE
    queue = db.execute(
        text("SELECT count(*) FROM scenes WHERE provenance = 'mosaic_url'")
    ).scalar_one()
    assert queue == 1


# ── Collisions ────────────────────────────────────────────────────────────────


def test_collision_merges_and_repoints_references(db: Session, tmp_path: Path) -> None:
    """One item under two ids becomes one row, with no dangling reference.

    This is NORM-7's shape reached from the other side: the catalogued id the
    synthesized row resolves to is already held by a `snapshot` row, because
    the same tile is reachable under two URLs and the backfill matched exact
    strings. Merging is the only outcome that leaves the table with one row
    per item and every mosaic reference still resolving.
    """
    _insert_parcel(db)
    # The catalogued row, reached under a different URL.
    catalogued = _insert_scene(
        db,
        item_id=PREFIX_CATALOGUED,
        cog_url=f"{_NAIP_BASE}/m_4007416_se_18_030_20230820_20231019.tif",
        provenance="snapshot",
    )
    primary = _insert_scene(db, item_id=PRIMARY_ITEM, cog_url=PRIMARY_URL, provenance="snapshot")
    synthesized = _insert_scene(
        db, item_id=PREFIX_CANDIDATE, cog_url=PREFIX_URL, provenance="mosaic_url"
    )
    row = _insert_parcel_scene(db, scene_id=primary, mosaic=[synthesized])

    stac = FakeStac(search_results=[_item(PREFIX_CATALOGUED, PREFIX_URL)])
    out = _run(db, stac, tmp_path)

    assert (out.merged, out.enriched) == (1, 0)
    assert len(out.merges) == 1
    assert _scene(db, synthesized) is None
    assert _mosaic_ids(db, row) == [catalogued]

    # No mosaic_scene_ids entry points at a scene that no longer exists.
    live = {str(r.id) for r in db.execute(text("SELECT id FROM scenes")).all()}
    for ref in script.load_mosaic_refs(db):
        assert set(ref.mosaic_scene_ids) <= live


def test_merge_does_not_duplicate_an_existing_reference(db: Session, tmp_path: Path) -> None:
    """A row already referencing the merge target keeps one reference, not two."""
    _insert_parcel(db)
    catalogued = _insert_scene(
        db,
        item_id=PREFIX_CATALOGUED,
        cog_url=f"{_NAIP_BASE}/m_4007416_se_18_030_20230820_20231019.tif",
        provenance="snapshot",
    )
    primary = _insert_scene(db, item_id=PRIMARY_ITEM, cog_url=PRIMARY_URL, provenance="snapshot")
    synthesized = _insert_scene(
        db, item_id=PREFIX_CANDIDATE, cog_url=PREFIX_URL, provenance="mosaic_url"
    )
    row = _insert_parcel_scene(db, scene_id=primary, mosaic=[catalogued, synthesized])

    _run(db, FakeStac(search_results=[_item(PREFIX_CATALOGUED, PREFIX_URL)]), tmp_path)

    assert _mosaic_ids(db, row) == [catalogued]


# ── Modes and idempotence ─────────────────────────────────────────────────────


def test_dry_run_plans_the_write_without_making_it(db: Session, tmp_path: Path) -> None:
    _, synthesized, _ = _one_mosaic_scene(db, item_id=EXACT_ITEM, cog_url=EXACT_URL)
    stac = FakeStac(items={EXACT_ITEM: _item(EXACT_ITEM, EXACT_URL)})

    out = _run(db, stac, tmp_path, execute=False)

    assert out.enriched == 1
    row = _scene(db, synthesized)
    assert row.provenance == "mosaic_url"
    assert row.footprint is None


def test_second_run_is_a_no_op(db: Session, tmp_path: Path) -> None:
    """The queue shrinks by exactly the enriched count and nothing is re-touched."""
    _, synthesized, _ = _one_mosaic_scene(db, item_id=EXACT_ITEM, cog_url=EXACT_URL)
    catalog = {EXACT_ITEM: _item(EXACT_ITEM, EXACT_URL)}

    first = _run(db, FakeStac(items=catalog), tmp_path)
    before = _scene(db, synthesized)

    second_stac = FakeStac(items=catalog)
    second = _run(db, second_stac, tmp_path)

    assert first.enriched == 1
    assert (second.enriched, second.merged, second.unmatched, second.errors) == (0, 0, 0, 0)
    assert second_stac.gets == []  # an empty queue costs no requests
    after = _scene(db, synthesized)
    assert (after.item_id, after.provenance, after.resolution_m) == (
        before.item_id,
        before.provenance,
        before.resolution_m,
    )


def test_report_is_written_to_the_given_path(db: Session, tmp_path: Path) -> None:
    """The report is a file in both modes — a killed ssh client keeps no stdout."""
    _one_mosaic_scene(db, item_id=EXACT_ITEM, cog_url=EXACT_URL)
    report = tmp_path / "nested" / "report.md"

    script.run(
        db,
        execute=False,
        report_path=report,
        lookup=FakeStac(items={EXACT_ITEM: _item(EXACT_ITEM, EXACT_URL)}),
    )

    body = report.read_text(encoding="utf-8")
    assert "already-exact" in body
    assert EXACT_ITEM in body


def test_capture_date_disagreement_is_reported(db: Session, tmp_path: Path) -> None:
    """The filename date and the item's datetime should agree; if not, say so."""
    _, synthesized, _ = _one_mosaic_scene(db, item_id=EXACT_ITEM, cog_url=EXACT_URL)
    stac = FakeStac(items={EXACT_ITEM: _item(EXACT_ITEM, EXACT_URL, capture="2023-08-21")})

    out = _run(db, stac, tmp_path)

    assert len(out.date_disagreements) == 1
    assert "2023-08-20" in out.date_disagreements[0]
    assert str(_scene(db, synthesized).capture_date) == "2023-08-21"


# ── NORM-10: retry policy differs by endpoint, and pacing ─────────────────────
#
# These exercise ``StacLookup`` itself rather than the ``FakeStac`` the tests
# above use — ``FakeStac`` replaces the whole lookup and has no retry logic to
# get wrong. httpx's transport is mocked at ``_client.get`` / ``_client.post``
# so no network is touched.


def _response(
    status: int,
    url: str,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    retryable: bool = False,
) -> httpx.Response:
    """A fake httpx response. ``retryable=True`` sets ``Retry-After: 0`` so a

    retried request's backoff sleep is instant instead of the 1s default —
    tests assert *that* a retry happened, not how long it waited.
    """
    request = httpx.Request(method, url)
    headers = {"retry-after": "0"} if retryable else None
    return httpx.Response(
        status, request=request, json=json_body or {"id": "unused"}, headers=headers
    )


def test_search_403_retries_and_succeeds() -> None:
    """A /search 403 is the PC throttle (NORM-10), not a permanent refusal."""
    lookup = script.StacLookup(concurrency=1, min_interval_s=0)
    calls = 0

    async def fake_post(url: str, *, json: dict[str, Any]) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response(403, url, method="POST", retryable=True)
        return _response(200, url, method="POST", json_body={"features": [{"id": "found"}]})

    lookup._client.post = fake_post

    features = asyncio.run(lookup.search("naip", (-1.0, -1.0, 1.0, 1.0), "2023"))

    assert calls == 2
    assert [f["id"] for f in features] == ["found"]
    asyncio.run(lookup.aclose())


def test_item_403_does_not_retry_falls_through_to_search() -> None:
    """A 403 from the item endpoint is a permanent per-item refusal (geometry audit); one try only."""
    lookup = script.StacLookup(concurrency=1, min_interval_s=0)
    calls = 0

    async def fake_get(url: str) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(403, url)

    lookup._client.get = fake_get

    status, item = asyncio.run(lookup.get_item("naip", "some_item"))

    assert (status, item) == (403, None)
    assert calls == 1  # no retry: a second 403 here would mean the fix regressed
    asyncio.run(lookup.aclose())


def test_search_403_exhausts_retry_budget_is_an_error() -> None:
    """A /search 403 that never clears surfaces as a failure, not a swallowed row."""
    lookup = script.StacLookup(concurrency=1, min_interval_s=0)
    calls = 0

    async def fake_post(url: str, *, json: dict[str, Any]) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(403, url, method="POST", retryable=True)

    lookup._client.post = fake_post

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(lookup.search("naip", (-1.0, -1.0, 1.0, 1.0), "2023"))

    assert calls == script.FETCH_ATTEMPTS
    asyncio.run(lookup.aclose())


async def test_pacing_does_not_exceed_configured_concurrency() -> None:
    """More requests than the concurrency cap never run at once, pacing on or off."""
    lookup = script.StacLookup(concurrency=2, min_interval_s=0)
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_get(url: str) -> httpx.Response:
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0)  # yield so other tasks can overlap before this one finishes
        async with lock:
            active -= 1
        return _response(200, url, json_body={"id": "x"})

    lookup._client.get = fake_get

    await asyncio.gather(*(lookup.get_item("naip", f"item-{i}") for i in range(6)))
    await lookup.aclose()

    assert max_active <= 2
