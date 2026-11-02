"""Titiler's image pin and GDAL driver allowlist (security audit SEC-17, SEC-18)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_FLY_TOML = _ROOT / "fly.titiler.toml"
_COMPOSE = _ROOT / "docker-compose.yml"

_PINNED_DIGEST = "sha256:5b739117ff60d3cef9b0e0b8d9f4d628032c00a4965117e3f745cadc79fa7287"

# Every driver registered in the pinned image, read with rasterio.Env().drivers()
# inside it. A digest bump fails test_image_is_the_pinned_digest until this
# list is regenerated, so a new image cannot bring in drivers GDAL_SKIP misses.
_DRIVERS_IN_IMAGE = frozenset(
    {
        'AAIGrid', 'ACE2', 'ADRG', 'AIG', 'AVCBin', 'AVCE00', 'AirSAR', 'BAG',
        'BIGGIF', 'BMP', 'BSB', 'BT', 'BYN', 'CALS', 'CEOS', 'COASP', 'COG', 'COSAR',
        'CPG', 'CTG', 'DAAS', 'DERIVED', 'DIMAP', 'DOQ1', 'DOQ2', 'DTED', 'ECRGTOC',
        'EEDA', 'EEDAI', 'EHdr', 'EIR', 'ENVI', 'ERS', 'ESAT', 'ESRI Shapefile',
        'ESRIC', 'ESRIJSON', 'FAST', 'GDALG', 'GFF', 'GIF', 'GNMDatabase', 'GNMFile',
        'GPKG', 'GRASSASCIIGrid', 'GRIB', 'GS7BG', 'GSAG', 'GSBG', 'GSC', 'GTI', 'GTX',
        'GTiff', 'GXF', 'GenBin', 'GeoJSON', 'GeoJSONSeq', 'HDF5', 'HDF5Image', 'HF2',
        'HFA', 'HTTP', 'ILWIS', 'IRIS', 'ISCE', 'ISG', 'ISIS2', 'ISIS3', 'JAXAPALSAR',
        'JDEM', 'JP2OpenJPEG', 'JPEG', 'KMLSUPEROVERLAY', 'KRO', 'L1B', 'LAN', 'LCP',
        'LIBERTIFF', 'LOSLAS', 'Leveller', 'MAP', 'MBTiles', 'MEM', 'MFF', 'MFF2',
        'MRF', 'MSGN', 'MVT', 'MiraMonRaster', 'NDF', 'NGSGEOID', 'NITF', 'NOAA_B',
        'NSIDCbin', 'NTv2', 'NWT_GRC', 'NWT_GRD', 'OSM', 'PAux', 'PCIDSK', 'PCRaster',
        'PDF', 'PDS', 'PDS4', 'PLMOSAIC', 'PNG', 'PNM', 'PRF', 'RCM', 'RIK', 'RMF',
        'ROI_PAC', 'RPFTOC', 'RRASTER', 'RS2', 'RST', 'S102', 'S104', 'S111', 'SAFE',
        'SAGA', 'SAR_CEOS', 'SENTINEL2', 'SIGDEM', 'SNAP_TIFF', 'SNODAS', 'SQLite',
        'SRP', 'SRTMHGT', 'STACIT', 'STACTA', 'TGA', 'TIL', 'TSX', 'Terragen',
        'TopoJSON', 'USGSDEM', 'VICAR', 'VRT', 'WCS', 'WEBP', 'WMS', 'WMTS', 'XYZ',
        'ZMap', 'Zarr', 'netCDF',
    }
)  # fmt: skip

# VRT is here only because rasterio's warp needs it; see fly.titiler.toml.
_ALLOWED = frozenset({"GTiff", "JPEG", "MEM", "PNG", "VRT"})

pytestmark = pytest.mark.skipif(
    not _FLY_TOML.exists(),
    reason=(
        f"{_FLY_TOML} not present; the compose test container only mounts "
        "./backend and ./scripts, not the repo root"
    ),
)


def _fly() -> dict[str, dict[str, object]]:
    with _FLY_TOML.open("rb") as f:
        return tomllib.load(f)


def _gdal_skip(value: object) -> list[str]:
    assert isinstance(value, str), "GDAL_SKIP missing from fly.titiler.toml [env]"
    return value.split(",")


def _compose_titiler_service() -> str:
    m = re.search(r"^  titiler:\n((?:    .*\n|\s*\n)+)", _COMPOSE.read_text(), re.M)
    assert m, "titiler service not found in docker-compose.yml"
    return m.group(1)


def test_image_is_the_pinned_digest() -> None:
    image = _fly()["build"]["image"]
    assert image == f"ghcr.io/developmentseed/titiler@{_PINNED_DIGEST}"


def test_gdal_skip_is_the_complement_of_the_allowlist() -> None:
    skip = _gdal_skip(_fly()["env"].get("GDAL_SKIP"))
    assert len(skip) == len(set(skip))
    # GDAL tokenizes on "," without stripping, so " HDF5" would skip nothing.
    assert all(name == name.strip() and name for name in skip)
    assert set(skip) == _DRIVERS_IN_IMAGE - _ALLOWED


def test_the_audit_reproduced_drivers_are_skipped() -> None:
    skip = set(_gdal_skip(_fly()["env"].get("GDAL_SKIP")))
    assert {"HDF5", "HDF5Image", "netCDF", "Zarr", "GRIB"} <= skip


def test_titiler_2_surface_and_port() -> None:
    fly = _fly()
    env = fly["env"]
    assert env.get("TITILER_API_DISABLE_MOSAIC") == "TRUE"
    assert env.get("TITILER_API_DISABLE_ZARR") == "TRUE"
    assert env.get("PORT") == str(fly["http_service"]["internal_port"])


def test_compose_mirrors_production() -> None:
    service = _compose_titiler_service()
    fly = _fly()
    assert f"image: {fly['build']['image']}\n" in service
    assert f"- GDAL_SKIP={fly['env']['GDAL_SKIP']}\n" in service
    assert "- TITILER_API_DISABLE_ZARR=TRUE\n" in service
