"""Capture the served-row shape from the OLD read path, before it is deleted.

ADR 0001 step 3. ``tests/fixtures/step3_served_shape.json`` is the contract
the listing endpoint, the preview renderer and the Titiler callback all build
their responses out of, and the only moment it can be captured from
``get_imagery_snapshots`` is before that function is deleted. This module is
that moment; it is deleted by the cutover commit, and
``test_read_cutover.py`` asserts the *new* path against the same file
afterwards.

Run with ``STEP3_CAPTURE=1`` to rewrite the file; without it, the test
asserts the old path still produces it.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import imagery as imagery_service

from .test_read_cutover import GOLDEN, PARCEL_ID

# The four served periods of test_read_cutover's fixture, as the rows
# imagery_snapshots would hold for them. The two rows that fixture seeds on
# one side only are deliberately absent: this is a capture of the shape, not
# of the set, and the set is what the cutover tests assert.
_MIRROR = (
    {
        "source": "usgs_topo",
        "capture_date": "1965-01-01",
        "stac_item_id": "CO_Denver_1965",
        "stac_collection": "usgs-topo",
        "cog_url": "https://example.com/topo-1965.tif",
        "additional_cog_urls": None,
        "thumbnail_url": None,
        "resolution_m": None,
        "cloud_cover_pct": None,
    },
    {
        "source": "landsat",
        "capture_date": "2020-07-04",
        "stac_item_id": "LC08_L2SP_2020",
        "stac_collection": "landsat-c2-l2",
        "cog_url": "https://example.com/landsat-2020.json",
        "additional_cog_urls": None,
        "thumbnail_url": None,
        "resolution_m": 30.0,
        "cloud_cover_pct": 3.5,
    },
    {
        "source": "naip",
        "capture_date": "2021-08-01",
        "stac_item_id": "co_m_naip_2021",
        "stac_collection": "naip",
        "cog_url": "https://example.com/naip-2021-primary.tif",
        # On PostgreSQL this column is TEXT[] and the read hands back a list.
        # The test database has no array type, so the mirror stores the same
        # list as JSON and _freeze decodes it — a storage artifact of SQLite,
        # not a difference between the two read paths. The paths' agreement on
        # this field was measured on PostgreSQL over 148 mosaic rows
        # (docs/audits/2026-08-normalization/step3-parity-local.md).
        "additional_cog_urls": json.dumps(
            [
                "https://example.com/naip-2021-tile-a.tif",
                "https://example.com/naip-2021-tile-b.tif",
            ]
        ),
        "thumbnail_url": "https://example.com/naip-2021.png",
        "resolution_m": 0.6,
        "cloud_cover_pct": None,
    },
    {
        "source": "sentinel2",
        "capture_date": "2024-05-05",
        "stac_item_id": "S2A_new_only_2024",
        "stac_collection": "sentinel-2-l2a",
        "cog_url": "https://example.com/s2-2024.tif",
        "additional_cog_urls": None,
        "thumbnail_url": None,
        "resolution_m": 10.0,
        "cloud_cover_pct": None,
    },
)


def _freeze(rows: list[imagery_service.ImagerySnapshotRow]) -> list[dict[str, object]]:
    out = []
    for row in rows:
        d = asdict(row)
        d["id"] = "<served-id>"
        d["parcel_id"] = str(d["parcel_id"])
        d["capture_date"] = d["capture_date"].isoformat()
        if isinstance(d["additional_cog_urls"], str):
            d["additional_cog_urls"] = json.loads(d["additional_cog_urls"])
        out.append(d)
    return out


@pytest.fixture
def mirrored(db: Session) -> Session:
    db.execute(
        text(
            "INSERT INTO parcels (id, address, normalized_address, latitude, longitude)"
            " VALUES (:id, :a, :a, 39.7, -105.0)"
        ),
        {"id": str(PARCEL_ID), "a": "1 Cutover St, Denver, CO 80202"},
    )
    for row in _MIRROR:
        db.execute(
            text(
                "INSERT INTO imagery_snapshots (id, parcel_id, source, capture_date,"
                " stac_item_id, stac_collection, cog_url, additional_cog_urls,"
                " thumbnail_url, resolution_m, cloud_cover_pct)"
                " VALUES (:id, :parcel_id, :source, :capture_date, :stac_item_id,"
                " :stac_collection, :cog_url, :additional_cog_urls, :thumbnail_url,"
                " :resolution_m, :cloud_cover_pct)"
            ),
            {"id": str(uuid.uuid4()), "parcel_id": str(PARCEL_ID), **row},
        )
    db.flush()
    return db


def test_the_old_read_path_produces_the_frozen_shape(mirrored: Session) -> None:
    captured = _freeze(imagery_service.get_imagery_snapshots(mirrored, PARCEL_ID))
    if os.environ.get("STEP3_CAPTURE"):
        Path(GOLDEN).parent.mkdir(parents=True, exist_ok=True)
        Path(GOLDEN).write_text(json.dumps(captured, indent=2) + "\n")
    assert captured == json.loads(Path(GOLDEN).read_text())
