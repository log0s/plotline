"""Tests for scripts/remove_uncovered_snapshots.py.

The script lives outside the backend package, so it is loaded by path.
Nothing here touches Planetary Computer: ``fetch_stac_item`` is patched with
canned items whose geometry is chosen to contain, or exclude, the parcel
point.

Delete-the-fix: removing the ``if covering: raise EvidenceError`` guard in
``verify_uncovered`` makes ``test_covering_item_blocks_execution`` fail —
the run proceeds and deletes a row whose imagery does cover the parcel,
which is exactly the Hudson Yards shape the audit found rescued by its
second tile.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

_HERE = Path(__file__).resolve()
# Repo layout puts scripts/ beside backend/; the container copies it to /app/scripts.
_SCRIPT = next(
    p / "scripts" / "remove_uncovered_snapshots.py"
    for p in _HERE.parents
    if (p / "scripts" / "remove_uncovered_snapshots.py").exists()
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("remove_uncovered_snapshots", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["remove_uncovered_snapshots"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

# 350 5th Ave, and the New Jersey quad the 2026-08 geometry audit condemned.
PARCEL = "81b2d663-1851-438d-a9fa-58d665e32e25"
OTHER_PARCEL = "5c27245c-5827-430b-ad43-baae66e69335"
LAT, LNG = 40.7478486, -73.9850771
NJ_PRIMARY = "nj_m_4007309_sw_18_030_20230820_20231019"
NJ_EXTRA = "nj_m_4007424_ne_18_030_20230820_20231019"
_BASE = "https://naipeuwest.blob.core.windows.net/naip/v002/nj/2023/nj_030cm_2023/40074"


def _square(lng: float, lat: float, size: float = 0.02) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lng - size, lat - size],
                [lng + size, lat - size],
                [lng + size, lat + size],
                [lng - size, lat + size],
                [lng - size, lat - size],
            ]
        ],
    }


# A footprint well west of the parcel — New Jersey, in the real case.
EXCLUDING = _square(LNG - 0.2, LAT)
COVERING = _square(LNG, LAT)


def _url(item_id: str) -> str:
    return f"{_BASE}/{item_id.removeprefix('nj_')}.tif"


def _insert_parcel(db: Session, parcel_id: str, lat: float, lng: float) -> None:
    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude)"
            " VALUES (:id, :address, :lat, :lng)"
        ),
        {"id": parcel_id, "address": "350 5th Ave, New York, NY 10118", "lat": lat, "lng": lng},
    )


def _scene_id(db: Session, *, source: str, item_id: str, capture_date: str, cog_url: str) -> str:
    """Get-or-create the ``scenes`` row for one item.

    Get-*or-create*, not create: two parcels serving the same NAIP tile share
    one ``scenes`` row, which is the whole point of the split and is exactly
    what the ``seeded`` fixture below sets up. A helper that always inserted
    would hit ``UNIQUE (collection, item_id)`` on the second parcel.
    """
    existing = db.execute(
        text("SELECT id FROM scenes WHERE collection = :c AND item_id = :i"),
        {"c": source, "i": item_id},
    ).scalar()
    if existing is not None:
        return str(existing)
    scene_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date, cog_url,"
            " provenance, fetched_at)"
            " VALUES (:id, :source, :source, :item_id, :capture_date, :cog_url,"
            " 'selection', :now)"
        ),
        {
            "id": scene_id,
            "source": source,
            "item_id": item_id,
            "capture_date": capture_date,
            "cog_url": cog_url,
            "now": "2026-08-01 12:00:00",
        },
    )
    return scene_id


def _insert_served(
    db: Session,
    *,
    parcel_id: str,
    source: str,
    capture_date: str,
    stac_item_id: str,
    extras: list[str] | None = None,
) -> str:
    """One served period, and a ``scenes`` row per tile it composites."""
    primary = _scene_id(
        db,
        source=source,
        item_id=stac_item_id,
        capture_date=capture_date,
        cog_url=_url(stac_item_id),
    )
    mosaic = [
        _scene_id(
            db,
            source=source,
            item_id=_item_id_from_url(url),
            capture_date=capture_date,
            cog_url=url,
        )
        for url in (extras or [])
    ]
    served_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO parcel_scenes (id, parcel_id, source, group_key, scene_id,"
            " mosaic_scene_ids, selected_at, selected_by)"
            " VALUES (:id, :parcel_id, :source, :group_key, :scene_id, :mosaic, :now, NULL)"
        ),
        {
            "id": served_id,
            "parcel_id": parcel_id,
            "source": source,
            "group_key": capture_date[:4],
            "scene_id": primary,
            "mosaic": json.dumps(mosaic) if mosaic else None,
            "now": "2026-08-01 12:00:00",
        },
    )
    return served_id


def _item_id_from_url(url: str) -> str:
    """The NAIP item id ``_url`` built the URL from, recovered.

    The fixture's tiles are addressed by URL because that is how the old shape
    stored a mosaic; the new shape needs each one to be a scene with an id, so
    the fixture inverts its own ``_url``. The script under test derives item
    ids from URLs itself (``naip_item_id_from_url``) and is not what is being
    reused here — a fixture that called the code under test to build its own
    input would be proving the derivation against itself.
    """
    return url.rsplit("/", 1)[-1].removesuffix(".tif")


@pytest.fixture
def seeded(db: Session) -> dict[str, str]:
    """One condemnable 2023 NAIP row, plus neighbours that must survive."""
    _insert_parcel(db, PARCEL, LAT, LNG)
    _insert_parcel(db, OTHER_PARCEL, 40.7538955, -73.9997349)
    ids = {
        "target": _insert_served(
            db,
            parcel_id=PARCEL,
            source="naip",
            capture_date="2023-08-20",
            stac_item_id=NJ_PRIMARY,
            extras=[_url(NJ_EXTRA)],
        ),
        "adjacent_year": _insert_served(
            db,
            parcel_id=PARCEL,
            source="naip",
            capture_date="2022-07-19",
            stac_item_id="ny_m_4007317_nw_18_060_20220719",
        ),
        "other_source": _insert_served(
            db,
            parcel_id=PARCEL,
            source="landsat",
            capture_date="2023-06-01",
            stac_item_id="LC09_L2SP_013032_20230601_02_T1",
        ),
        "other_parcel": _insert_served(
            db,
            parcel_id=OTHER_PARCEL,
            source="naip",
            capture_date="2023-08-20",
            stac_item_id=NJ_PRIMARY,
            extras=[_url(NJ_EXTRA)],
        ),
    }
    return ids


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch,
    geometries: dict[str, dict[str, Any]],
    calls: list[str] | None = None,
) -> None:
    async def _fetch(collection: str, item_id: str) -> dict[str, object]:
        if calls is not None:
            calls.append(item_id)
        if item_id not in geometries:
            raise script.EvidenceError(f"PC returned 404 for {item_id}; cannot verify")
        return {"id": item_id, "geometry": geometries[item_id]}

    monkeypatch.setattr(script, "fetch_stac_item", _fetch)


def _remaining(db: Session) -> set[str]:
    return {str(r.id) for r in db.execute(text("SELECT id FROM parcel_scenes")).all()}


# ── Argument handling ─────────────────────────────────────────────────────────


def test_refuses_without_all_three_arguments() -> None:
    import argparse

    args = argparse.Namespace(parcel_id=[PARCEL], source=["naip"], year=None)
    with pytest.raises(SystemExit):
        script.parse_targets(args)


def test_refuses_mismatched_argument_counts() -> None:
    import argparse

    args = argparse.Namespace(parcel_id=[PARCEL, OTHER_PARCEL], source=["naip"], year=[2023])
    with pytest.raises(SystemExit):
        script.parse_targets(args)


# ── Dry run ───────────────────────────────────────────────────────────────────


def test_dry_run_deletes_nothing(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _patch_fetch(monkeypatch, {NJ_PRIMARY: EXCLUDING, NJ_EXTRA: EXCLUDING}, calls)

    before = _remaining(db)
    deleted = script.run(db, [script.Target(PARCEL, "naip", 2023)], execute=False)

    assert deleted == 0
    assert _remaining(db) == before
    # A dry run makes no network calls either: it reports, it does not verify.
    assert calls == []


# ── Execution ─────────────────────────────────────────────────────────────────


def test_execute_deletes_only_the_named_group(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch(monkeypatch, {NJ_PRIMARY: EXCLUDING, NJ_EXTRA: EXCLUDING})

    deleted = script.run(db, [script.Target(PARCEL, "naip", 2023)], execute=True)

    assert deleted == 1
    assert _remaining(db) == {
        seeded["adjacent_year"],
        seeded["other_source"],
        seeded["other_parcel"],
    }


def test_execute_deletes_both_named_parcels(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch(monkeypatch, {NJ_PRIMARY: EXCLUDING, NJ_EXTRA: EXCLUDING})

    deleted = script.run(
        db,
        [script.Target(PARCEL, "naip", 2023), script.Target(OTHER_PARCEL, "naip", 2023)],
        execute=True,
    )

    assert deleted == 2
    assert _remaining(db) == {seeded["adjacent_year"], seeded["other_source"]}


def test_execute_with_no_matching_rows_deletes_nothing(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch(monkeypatch, {NJ_PRIMARY: EXCLUDING, NJ_EXTRA: EXCLUDING})

    deleted = script.run(db, [script.Target(PARCEL, "naip", 2019)], execute=True)

    assert deleted == 0
    assert _remaining(db) == set(seeded.values())


# ── The evidence guard ────────────────────────────────────────────────────────


def test_covering_item_blocks_execution(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Hudson Yards shape: the mosaic's second tile does contain the point."""
    _patch_fetch(monkeypatch, {NJ_PRIMARY: EXCLUDING, NJ_EXTRA: COVERING})

    with pytest.raises(script.EvidenceError, match="contains the parcel point"):
        script.run(db, [script.Target(PARCEL, "naip", 2023)], execute=True)

    assert _remaining(db) == set(seeded.values())


def test_primary_covering_blocks_execution(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch(monkeypatch, {NJ_PRIMARY: COVERING, NJ_EXTRA: EXCLUDING})

    with pytest.raises(script.EvidenceError, match="contains the parcel point"):
        script.run(db, [script.Target(PARCEL, "naip", 2023)], execute=True)

    assert _remaining(db) == set(seeded.values())


def test_unfetchable_tile_blocks_execution(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tile PC will not serve is unverified, not innocent — refuse the run."""
    _patch_fetch(monkeypatch, {NJ_PRIMARY: EXCLUDING})

    with pytest.raises(script.EvidenceError, match="cannot verify"):
        script.run(db, [script.Target(PARCEL, "naip", 2023)], execute=True)

    assert _remaining(db) == set(seeded.values())


def test_one_covering_row_aborts_the_whole_run(
    db: Session, seeded: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification precedes every delete, so a bad target saves the good ones."""
    _patch_fetch(monkeypatch, {NJ_PRIMARY: EXCLUDING, NJ_EXTRA: COVERING})

    with pytest.raises(script.EvidenceError):
        script.run(
            db,
            [script.Target(PARCEL, "naip", 2023), script.Target(OTHER_PARCEL, "naip", 2023)],
            execute=True,
        )

    assert _remaining(db) == set(seeded.values())


# ── Item-id derivation ────────────────────────────────────────────────────────


def test_mosaic_item_ids_recovers_extra_tiles() -> None:
    row = script.Row(
        id="x",
        parcel_id=PARCEL,
        address="",
        latitude=LAT,
        longitude=LNG,
        source="naip",
        year=2023,
        capture_date="2023-08-20",
        stac_item_id=NJ_PRIMARY,
        stac_collection="naip",
        cog_url=_url(NJ_PRIMARY),
        additional_cog_urls=[_url(NJ_EXTRA)],
    )
    assert script.mosaic_item_ids(row) == [NJ_PRIMARY, NJ_EXTRA]


def test_unmappable_tile_url_refuses() -> None:
    row = script.Row(
        id="x",
        parcel_id=PARCEL,
        address="",
        latitude=LAT,
        longitude=LNG,
        source="naip",
        year=2023,
        capture_date="2023-08-20",
        stac_item_id=NJ_PRIMARY,
        stac_collection="naip",
        cog_url="https://example.invalid/somewhere/else.tif",
        additional_cog_urls=[_url(NJ_EXTRA)],
    )
    with pytest.raises(script.EvidenceError):
        script.mosaic_item_ids(row)


def test_non_naip_mosaic_refuses() -> None:
    row = script.Row(
        id="x",
        parcel_id=PARCEL,
        address="",
        latitude=LAT,
        longitude=LNG,
        source="landsat",
        year=2023,
        capture_date="2023-06-01",
        stac_item_id="LC09_L2SP_013032_20230601_02_T1",
        stac_collection="landsat-c2-l2",
        cog_url="https://landsateuwest.blob.core.windows.net/landsat-c2/x.TIF",
        additional_cog_urls=["https://landsateuwest.blob.core.windows.net/landsat-c2/y.TIF"],
    )
    with pytest.raises(script.EvidenceError, match="mosaic tiles"):
        script.mosaic_item_ids(row)
