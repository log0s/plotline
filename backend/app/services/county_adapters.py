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
    """Adapter for Denver County open data (data.denvergov.org)."""

    DOMAIN = "data.denvergov.org"
    # Denver Real Property Sales
    SALES_RESOURCE = "hmrh-5s3x"
    # Denver Building Permits
    PERMITS_RESOURCE = "jea5-cqgq"

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
        where = f"upper(address) LIKE '{street_number} {street_name}%'"
        try:
            rows = await query_socrata(
                self.DOMAIN,
                self.SALES_RESOURCE,
                where=where,
                order="sale_date DESC",
                app_token=app_token,
            )
        except Exception as exc:
            logger.warning(f"Denver sales query failed: {exc}")
            return []
        return [self._parse_sale(row) for row in rows]

    def _parse_sale(self, row: dict[str, Any]) -> PropertyEventData:
        return PropertyEventData(
            event_type="sale",
            event_date=parse_date(row.get("sale_date")),
            sale_price=safe_int(row.get("sale_price")),
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description=self._format_sale_description(row),
            source="denver_sales",
            source_record_id=row.get("reception_num") or row.get("id", ""),
            raw_data=row,
        )

    def _format_sale_description(self, row: dict[str, Any]) -> str:
        price = safe_int(row.get("sale_price"))
        if price and price > 0:
            return f"Sold for ${price:,}"
        return "Property sale recorded (price not disclosed)"

    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        where = f"upper(address) LIKE '{street_number} {street_name}%'"
        try:
            rows = await query_socrata(
                self.DOMAIN,
                self.PERMITS_RESOURCE,
                where=where,
                order="issue_date DESC",
                app_token=app_token,
            )
        except Exception as exc:
            logger.warning(f"Denver permits query failed: {exc}")
            return []
        return [self._parse_permit(row) for row in rows]

    def _parse_permit(self, row: dict[str, Any]) -> PropertyEventData:
        return PropertyEventData(
            event_type=classify_permit(row.get("permit_type", "")),
            event_date=parse_date(row.get("issue_date")),
            sale_price=None,
            permit_type=row.get("permit_type"),
            permit_description=row.get("project_description"),
            permit_valuation=safe_int(row.get("valuation")),
            description=self._format_permit_description(row),
            source="denver_permits",
            source_record_id=row.get("permit_num") or row.get("id", ""),
            raw_data=row,
        )

    def _format_permit_description(self, row: dict[str, Any]) -> str:
        parts: list[str] = []
        ptype = row.get("permit_type", "Permit")
        parts.append(ptype)
        desc = row.get("project_description")
        if desc:
            parts.append(f"— {desc[:120]}")
        val = safe_int(row.get("valuation"))
        if val and val > 0:
            parts.append(f"(${val:,} valuation)")
        return " ".join(parts)


# ── Adams County adapter ──────────────────────────────────────────────────────


class AdamsCountyAdapter(CountyAdapter):
    """Adapter for Adams County open data (data.adcogov.org).

    Adams County's data portal is less standardized than Denver's.
    Resource IDs may need verification against the portal.
    """

    DOMAIN = "data.adcogov.org"
    # These resource IDs should be verified against the portal
    SALES_RESOURCE = "s3yg-wa5f"
    PERMITS_RESOURCE = "37ih-ctda"

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
        where = f"upper(situs_address) LIKE '{street_number} {street_name}%'"
        try:
            rows = await query_socrata(
                self.DOMAIN,
                self.SALES_RESOURCE,
                where=where,
                order="sale_date DESC",
                app_token=app_token,
            )
        except Exception as exc:
            logger.warning(f"Adams County sales query failed: {exc}")
            return []
        return [self._parse_sale(row) for row in rows]

    def _parse_sale(self, row: dict[str, Any]) -> PropertyEventData:
        price = safe_int(row.get("sale_price"))
        desc = f"Sold for ${price:,}" if price and price > 0 else "Property sale recorded"
        return PropertyEventData(
            event_type="sale",
            event_date=parse_date(row.get("sale_date")),
            sale_price=price,
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description=desc,
            source="adams_sales",
            source_record_id=row.get("reception_number") or row.get("id", ""),
            raw_data=row,
        )

    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        where = f"upper(address) LIKE '{street_number} {street_name}%'"
        try:
            rows = await query_socrata(
                self.DOMAIN,
                self.PERMITS_RESOURCE,
                where=where,
                order="issue_date DESC",
                app_token=app_token,
            )
        except Exception as exc:
            logger.warning(f"Adams County permits query failed: {exc}")
            return []
        return [self._parse_permit(row) for row in rows]

    def _parse_permit(self, row: dict[str, Any]) -> PropertyEventData:
        raw_type = row.get("type") or row.get("permit_type", "")
        return PropertyEventData(
            event_type=classify_permit(raw_type),
            event_date=parse_date(row.get("issue_date")),
            sale_price=None,
            permit_type=raw_type,
            permit_description=row.get("description"),
            permit_valuation=safe_int(row.get("valuation")),
            description=f"{raw_type} — {row.get('description', '')[:120]}".strip(" —"),
            source="adams_permits",
            source_record_id=row.get("permit_number") or row.get("id", ""),
            raw_data=row,
        )


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
    if any(k in raw for k in ("BUILD", "BLDR", "NEW", "ADDITION", "REMODEL")):
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
