"""County open data adapters for property history.

Each adapter isolates a county's Socrata API quirks (field names, resource IDs,
data formats) behind a common interface. This makes it straightforward to add
new counties without changing the core pipeline.

Architecture:
    CountyAdapter (ABC) → DenverAdapter, AdamsCountyAdapter, ...
    COUNTY_ADAPTERS registry → get_adapter_for_county(county_name)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.arcgis import query_feature_service
from app.services.socrata import query_socrata

logger = logging.getLogger(__name__)


# ── Shared helpers ────────────────────────────────────────────────────────────


def parse_date(value: str | None) -> date | None:
    """Parse a date string from Socrata (ISO-8601 or date-only)."""
    if not value:
        return None
    try:
        # Socrata often returns "2020-01-15T00:00:00.000"
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def safe_int(value: Any) -> int | None:
    """Coerce a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


# ── Normalized event dataclass ────────────────────────────────────────────────


@dataclass
class PropertyEventData:
    """Normalized property event from any county source."""

    event_type: str
    event_date: date | None
    sale_price: int | None
    permit_type: str | None
    permit_description: str | None
    permit_valuation: int | None
    description: str
    source: str
    source_record_id: str
    raw_data: dict[str, Any]


# ── Base adapter ──────────────────────────────────────────────────────────────


class CountyAdapter(ABC):
    """Base class for county open data adapters."""

    @property
    @abstractmethod
    def county_name(self) -> str:
        """Human-readable county name."""
        ...

    @abstractmethod
    async def fetch_sales(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        """Fetch property sale records matching the address."""
        ...

    @abstractmethod
    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        """Fetch building permit records matching the address."""
        ...


# ── Denver County adapter ─────────────────────────────────────────────────────


class DenverAdapter(CountyAdapter):
    """Adapter for Denver County open data (ArcGIS Hub).

    Denver migrated from Socrata (data.denvergov.org) to ArcGIS Hub in ~2025.
    Permits are available via ArcGIS Feature Services (residential + commercial).
    Property sales data is no longer available via public API.
    """

    _ARCGIS_BASE = "https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services"
    RESIDENTIAL_PERMITS_URL = f"{_ARCGIS_BASE}/ODC_DEV_RESIDENTIALCONSTPERMIT_P/FeatureServer/316"
    COMMERCIAL_PERMITS_URL = f"{_ARCGIS_BASE}/ODC_DEV_COMMERCIALCONSTPERMIT_P/FeatureServer/317"

    @property
    def county_name(self) -> str:
        return "Denver"

    async def fetch_sales(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        # Denver property sales are no longer available via public API
        # (Socrata dataset hmrh-5s3x was retired when Denver moved to ArcGIS Hub)
        return []

    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        # Use the full ADDRESS field with LIKE — handles directional prefixes
        # (e.g. "1437 N BANNOCK ST") and case variations reliably.
        where = f"upper(ADDRESS) LIKE '{street_number} %{street_name}%'"
        results: list[PropertyEventData] = []
        for url, label in [
            (self.RESIDENTIAL_PERMITS_URL, "residential"),
            (self.COMMERCIAL_PERMITS_URL, "commercial"),
        ]:
            try:
                rows = await query_feature_service(
                    url,
                    where=where,
                    order_by="DATE_ISSUED DESC",
                    result_record_count=100,
                )
            except Exception as exc:
                logger.warning(f"Denver {label} permits query failed: {exc}")
                continue
            results.extend(self._parse_permit(row) for row in rows)
        return results

    def _parse_permit(self, row: dict[str, Any]) -> PropertyEventData:
        # ArcGIS returns epoch-ms timestamps for date fields
        raw_date = row.get("DATE_ISSUED")
        event_date: date | None = None
        if raw_date is not None:
            try:
                from datetime import datetime, timezone
                event_date = datetime.fromtimestamp(
                    int(raw_date) / 1000, tz=timezone.utc
                ).date()
            except (ValueError, TypeError, OSError):
                event_date = parse_date(str(raw_date))

        raw_type = row.get("CLASS") or "Permit"
        return PropertyEventData(
            event_type=classify_permit(raw_type),
            event_date=event_date,
            sale_price=None,
            permit_type=raw_type,
            permit_description=None,
            permit_valuation=safe_int(row.get("VALUATION")),
            description=self._format_permit_description(row, raw_type),
            source="denver_permits",
            source_record_id=row.get("PERMIT_NUM") or "",
            raw_data=row,
        )

    def _format_permit_description(self, row: dict[str, Any], ptype: str) -> str:
        parts: list[str] = [ptype]
        val = safe_int(row.get("VALUATION"))
        if val and val > 0:
            parts.append(f"(${val:,} valuation)")
        contractor = row.get("CONTRACTOR_NAME")
        if contractor:
            parts.append(f"— {contractor[:80]}")
        return " ".join(parts)


# ── Adams County adapter ──────────────────────────────────────────────────────


class AdamsCountyAdapter(CountyAdapter):
    """Adapter for Adams County open data (ArcGIS Hub).

    Adams County migrated from Socrata (data.adcogov.org) to ArcGIS Hub.
    Building permits are available via the "Eye On Adams" Feature Service.
    Property sales data is not available via public API.

    Note: Adams County only covers unincorporated areas. Municipalities like
    Thornton, Westminster, etc. issue their own permits, so addresses within
    those cities may return no results.
    """

    PERMITS_URL = (
        "https://services3.arcgis.com/4PNQOtAivErR7nbT/arcgis/rest/services"
        "/Building_Permits_Eye_On_Adams/FeatureServer/0"
    )

    @property
    def county_name(self) -> str:
        return "Adams"

    async def fetch_sales(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        # Adams County property sales are not available via public API
        return []

    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        where = f"upper(CombinedAddress) LIKE '{street_number} %{street_name}%'"
        try:
            rows = await query_feature_service(
                self.PERMITS_URL,
                where=where,
                order_by="CaseOpened DESC",
                result_record_count=100,
            )
        except Exception as exc:
            logger.warning(f"Adams County permits query failed: {exc}")
            return []
        return [self._parse_permit(row) for row in rows]

    def _parse_permit(self, row: dict[str, Any]) -> PropertyEventData:
        # ArcGIS returns epoch-ms timestamps
        raw_date = row.get("CaseOpened")
        event_date: date | None = None
        if raw_date is not None:
            try:
                from datetime import datetime, timezone
                event_date = datetime.fromtimestamp(
                    int(raw_date) / 1000, tz=timezone.utc
                ).date()
            except (ValueError, TypeError, OSError):
                event_date = parse_date(str(raw_date))

        raw_type = row.get("TypeOfWork") or row.get("ClassOfWork") or "Permit"
        description_text = row.get("Description") or ""
        return PropertyEventData(
            event_type=classify_permit(raw_type),
            event_date=event_date,
            sale_price=None,
            permit_type=raw_type,
            permit_description=description_text or None,
            permit_valuation=None,
            description=self._format_permit_description(row, raw_type, description_text),
            source="adams_permits",
            source_record_id=row.get("RecordID_") or "",
            raw_data=row,
        )

    def _format_permit_description(
        self, row: dict[str, Any], ptype: str, description: str,
    ) -> str:
        parts: list[str] = [ptype]
        if description:
            parts.append(f"— {description[:120]}")
        return " ".join(parts)


# ── Permit classification ─────────────────────────────────────────────────────


def classify_permit(raw_type: str) -> str:
    """Normalize a raw permit type string into our event_type enum."""
    raw = raw_type.upper()
    if "DEMO" in raw:
        return "permit_demolition"
    if "ELEC" in raw:
        return "permit_electrical"
    if "MECH" in raw:
        return "permit_mechanical"
    if "PLUM" in raw:
        return "permit_plumbing"
    if any(k in raw for k in (
        "BUILD", "BLDR", "NEW", "ADDITION", "REMODEL",
        "ALTERATION", "TENANT FINISH", "RENOVATION",
    )):
        return "permit_building"
    return "permit_other"


# ── Adapter registry ──────────────────────────────────────────────────────────

COUNTY_ADAPTERS: dict[str, CountyAdapter] = {
    "denver": DenverAdapter(),
    "adams": AdamsCountyAdapter(),
}


def get_adapter_for_county(county: str) -> CountyAdapter | None:
    """Return the appropriate adapter, or None if the county isn't supported."""
    normalized = county.lower().replace(" county", "").strip()
    return COUNTY_ADAPTERS.get(normalized)


def get_supported_counties() -> list[str]:
    """Return list of supported county names."""
    return [adapter.county_name for adapter in COUNTY_ADAPTERS.values()]
