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
from app.services.ckan import query_ckan_datastore
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
        event_date = _parse_epoch_ms(row.get("DATE_ISSUED"))

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
        event_date = _parse_epoch_ms(row.get("CaseOpened"))

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


# ── District of Columbia adapter ──────────────────────────────────────────────


class DCAdapter(CountyAdapter):
    """Adapter for District of Columbia open data (ArcGIS Hub).

    DC publishes property data via DCGIS ArcGIS REST services:
    - Sales: ITSPE FACTS table (Property and Land MapServer, layer 56)
    - Permits: DCRA Building Permits split by year (FEEDS/DCRA MapServer)
    """

    _PROPERTY_BASE = (
        "https://maps2.dcgis.dc.gov/dcgis/rest/services"
        "/DCGIS_DATA/Property_and_Land_WebMercator/MapServer"
    )
    SALES_URL = f"{_PROPERTY_BASE}/56"  # ITSPE FACTS — address + last sale

    _PERMITS_BASE = (
        "https://maps2.dcgis.dc.gov/dcgis/rest/services/FEEDS/DCRA/MapServer"
    )
    # Year-specific permit layers (query recent years for reasonable coverage)
    PERMIT_LAYERS: list[tuple[int, str]] = [
        (18, "2026"),
        (17, "2025"),
        (16, "2024"),
        (15, "2023"),
        (14, "2022"),
        (3, "2021"),
        (2, "2020"),
    ]

    @property
    def county_name(self) -> str:
        return "District of Columbia"

    async def fetch_sales(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        where = (
            f"upper(PROPERTY_ADDRESS) LIKE '%{street_number} %{street_name}%'"
        )
        try:
            rows = await query_feature_service(
                self.SALES_URL,
                where=where,
                out_fields=(
                    "SSL,PROPERTY_ADDRESS,LAST_SALE_PRICE,LAST_SALE_DATE,"
                    "DEED_DATE,LAND_USE_DESCRIPTION,"
                    "APPRAISED_VALUE_CURRENT_TOTAL"
                ),
                result_record_count=20,
            )
        except Exception as exc:
            logger.warning(f"DC sales query failed: {exc}")
            return []
        return [self._parse_sale(row) for row in rows if row.get("LAST_SALE_PRICE")]

    def _parse_sale(self, row: dict[str, Any]) -> PropertyEventData:
        raw_date = row.get("LAST_SALE_DATE") or row.get("DEED_DATE")
        event_date = _parse_epoch_ms(raw_date)
        price = safe_int(row.get("LAST_SALE_PRICE"))

        parts: list[str] = ["Property sale"]
        if price and price > 0:
            parts.append(f"for ${price:,}")
        land_use = row.get("LAND_USE_DESCRIPTION")
        if land_use:
            parts.append(f"({land_use})")

        return PropertyEventData(
            event_type="sale",
            event_date=event_date,
            sale_price=price,
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description=" ".join(parts),
            source="dc_sales",
            source_record_id=row.get("SSL") or "",
            raw_data=row,
        )

    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        where = f"upper(FULL_ADDRESS) LIKE '%{street_number} %{street_name}%'"
        results: list[PropertyEventData] = []
        for layer_id, year_label in self.PERMIT_LAYERS:
            url = f"{self._PERMITS_BASE}/{layer_id}"
            try:
                rows = await query_feature_service(
                    url,
                    where=where,
                    order_by="ISSUE_DATE DESC",
                    result_record_count=50,
                )
            except Exception as exc:
                logger.warning(f"DC permits {year_label} query failed: {exc}")
                continue
            results.extend(self._parse_permit(row) for row in rows)
        return results

    def _parse_permit(self, row: dict[str, Any]) -> PropertyEventData:
        event_date = _parse_epoch_ms(row.get("ISSUE_DATE"))

        # Combine type and subtype for richer classification
        raw_type = row.get("PERMIT_TYPE_NAME") or "Permit"
        subtype = row.get("PERMIT_SUBTYPE_NAME") or ""
        classify_input = f"{raw_type} {subtype}".strip()

        desc_of_work = row.get("DESC_OF_WORK") or ""
        parts: list[str] = [raw_type]
        if subtype:
            parts.append(f"— {subtype}")
        if desc_of_work:
            parts.append(f": {desc_of_work[:120]}")
        fees = safe_int(row.get("FEES_PAID"))
        if fees and fees > 0:
            parts.append(f"(${fees:,} fees)")

        return PropertyEventData(
            event_type=classify_permit(classify_input),
            event_date=event_date,
            sale_price=None,
            permit_type=raw_type,
            permit_description=desc_of_work or None,
            permit_valuation=fees,
            description=" ".join(parts),
            source="dc_permits",
            source_record_id=row.get("PERMIT_ID") or "",
            raw_data=row,
        )


# ── Santa Clara County adapter (San Jose) ────────────────────────────────────


class SantaClaraAdapter(CountyAdapter):
    """Adapter for Santa Clara County / City of San Jose open data (CKAN).

    San Jose publishes building permits on data.sanjoseca.gov (CKAN-based).
    Property sales data is not publicly available via API.

    Note: This adapter covers City of San Jose addresses. Other cities in
    Santa Clara County (Sunnyvale, Mountain View, Cupertino, etc.) may have
    their own portals or no public data.
    """

    DOMAIN = "data.sanjoseca.gov"
    # Multiple permit datasets cover different statuses
    PERMIT_RESOURCES: list[tuple[str, str]] = [
        ("761b7ae8-3be1-4ad6-923d-c7af6404a904", "active"),
        ("89ccdad9-7309-4826-a5f3-2fcf1fcb20fa", "under_inspection"),
        ("df4b8461-0c7a-4d16-b85d-ff7f71c5fed5", "expired"),
    ]

    @property
    def county_name(self) -> str:
        return "Santa Clara"

    async def fetch_sales(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        # Santa Clara County property sales are not available via public API
        return []

    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        # CKAN full-text search across gx_location field
        search_term = f"{street_number} {street_name}"
        results: list[PropertyEventData] = []
        for resource_id, label in self.PERMIT_RESOURCES:
            try:
                rows = await query_ckan_datastore(
                    self.DOMAIN,
                    resource_id,
                    q=search_term,
                    limit=100,
                )
            except Exception as exc:
                logger.warning(f"San Jose {label} permits query failed: {exc}")
                continue
            # Filter to rows that actually match the address
            for row in rows:
                location = (row.get("gx_location") or "").upper()
                if street_number in location and street_name.upper() in location:
                    results.append(self._parse_permit(row))
        return results

    def _parse_permit(self, row: dict[str, Any]) -> PropertyEventData:
        event_date = self._parse_sj_date(row.get("ISSUEDATE"))

        raw_type = row.get("WORKDESCRIPTION") or row.get("FOLDERDESC") or "Permit"
        folder_name = row.get("FOLDERNAME") or ""

        parts: list[str] = [raw_type]
        if folder_name:
            parts.append(f"— {folder_name[:120]}")
        val = safe_int(row.get("PERMITVALUATION"))
        if val and val > 0:
            parts.append(f"(${val:,} valuation)")
        contractor = row.get("CONTRACTOR")
        if contractor:
            parts.append(f"by {contractor[:60]}")

        return PropertyEventData(
            event_type=classify_permit(raw_type),
            event_date=event_date,
            sale_price=None,
            permit_type=raw_type,
            permit_description=folder_name or None,
            permit_valuation=safe_int(row.get("PERMITVALUATION")),
            description=" ".join(parts),
            source="san_jose_permits",
            source_record_id=row.get("FOLDERNUMBER") or "",
            raw_data=row,
        )

    @staticmethod
    def _parse_sj_date(value: str | None) -> date | None:
        """Parse San Jose date format: '3/8/2026 12:00:00 AM'."""
        if not value:
            return None
        try:
            # Take only the date part before the space
            date_part = value.split(" ")[0]
            parts = date_part.split("/")
            if len(parts) == 3:
                month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
                return date(year, month, day)
        except (ValueError, TypeError, IndexError):
            pass
        # Fall back to ISO parse
        return parse_date(value)


# ── New York County (Manhattan) adapter ──────────────────────────────────────


class NewYorkCountyAdapter(CountyAdapter):
    """Adapter for New York County (Manhattan) via NYC Open Data (Socrata).

    NYC publishes comprehensive property data on data.cityofnewyork.us:
    - Sales: NYC Citywide Rolling Calendar Sales (usep-8jbt), filtered to
      borough 1 (Manhattan).
    - Permits: DOB Permit Issuance (ipu4-2q9a), filtered to borough MANHATTAN.
    """

    DOMAIN = "data.cityofnewyork.us"
    SALES_RESOURCE = "usep-8jbt"
    PERMITS_RESOURCE = "ipu4-2q9a"

    @property
    def county_name(self) -> str:
        return "New York"

    async def fetch_sales(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        where = (
            f"borough='1' AND upper(address) LIKE '%{street_number} {street_name}%' "
            f"AND sale_price > '0'"
        )
        try:
            rows = await query_socrata(
                self.DOMAIN,
                self.SALES_RESOURCE,
                where=where,
                order="sale_date DESC",
                limit=100,
                app_token=app_token,
            )
        except Exception as exc:
            logger.warning(f"NYC sales query failed: {exc}")
            return []
        return [self._parse_sale(row) for row in rows]

    def _parse_sale(self, row: dict[str, Any]) -> PropertyEventData:
        event_date = parse_date(row.get("sale_date"))
        price = safe_int(row.get("sale_price"))

        parts: list[str] = ["Property sale"]
        if price and price > 0:
            parts.append(f"for ${price:,}")
        neighborhood = row.get("neighborhood")
        if neighborhood:
            parts.append(f"in {neighborhood.title()}")
        bldg_class = row.get("building_class_category")
        if bldg_class:
            parts.append(f"({bldg_class.strip()})")

        # Unique ID from block + lot + sale date
        block = row.get("block", "")
        lot = row.get("lot", "")
        sale_dt = row.get("sale_date", "")[:10]
        source_id = f"{block}-{lot}-{sale_dt}"

        return PropertyEventData(
            event_type="sale",
            event_date=event_date,
            sale_price=price,
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description=" ".join(parts),
            source="nyc_sales",
            source_record_id=source_id,
            raw_data=row,
        )

    async def fetch_permits(
        self,
        street_number: str,
        street_name: str,
        *,
        app_token: str | None = None,
    ) -> list[PropertyEventData]:
        where = (
            f"borough='MANHATTAN' AND house__='{street_number}' "
            f"AND upper(street_name) LIKE '%{street_name}%'"
        )
        try:
            rows = await query_socrata(
                self.DOMAIN,
                self.PERMITS_RESOURCE,
                where=where,
                order="issuance_date DESC",
                limit=100,
                app_token=app_token,
            )
        except Exception as exc:
            logger.warning(f"NYC permits query failed: {exc}")
            return []
        return [self._parse_permit(row) for row in rows]

    def _parse_permit(self, row: dict[str, Any]) -> PropertyEventData:
        event_date = self._parse_nyc_date(row.get("issuance_date"))

        job_type = row.get("job_type", "")
        permit_type_raw = row.get("permit_type", "")
        # Map NYC DOB job types to human-readable labels
        job_type_labels = {
            "NB": "New Building",
            "A1": "Major Alteration",
            "A2": "Minor Alteration",
            "A3": "Minor Alteration",
            "DM": "Demolition",
        }
        readable_type = job_type_labels.get(job_type, permit_type_raw or "Permit")

        parts: list[str] = [readable_type]
        owner = row.get("owner_s_business_name")
        if owner:
            parts.append(f"— {owner[:80]}")
        filing = row.get("filing_status")
        if filing and filing != "INITIAL":
            parts.append(f"({filing})")

        return PropertyEventData(
            event_type=classify_permit(readable_type),
            event_date=event_date,
            sale_price=None,
            permit_type=readable_type,
            permit_description=None,
            permit_valuation=None,
            description=" ".join(parts),
            source="nyc_permits",
            source_record_id=row.get("job__") or "",
            raw_data=row,
        )

    @staticmethod
    def _parse_nyc_date(value: str | None) -> date | None:
        """Parse NYC DOB date format: 'MM/DD/YYYY' or ISO-8601."""
        if not value:
            return None
        # Try ISO first (some fields use it)
        iso_result = parse_date(value)
        if iso_result:
            return iso_result
        # Try MM/DD/YYYY
        try:
            parts = value.split("/")
            if len(parts) == 3:
                month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
                return date(year, month, day)
        except (ValueError, TypeError, IndexError):
            pass
        return None


# ── Shared epoch-ms date parser ──────────────────────────────────────────────


def _parse_epoch_ms(value: Any) -> date | None:
    """Parse an ArcGIS epoch-millisecond timestamp to a date."""
    if value is None:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date()
    except (ValueError, TypeError, OSError):
        return parse_date(str(value))


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
    "district of columbia": DCAdapter(),
    "santa clara": SantaClaraAdapter(),
    "new york": NewYorkCountyAdapter(),
}


def get_adapter_for_county(county: str) -> CountyAdapter | None:
    """Return the appropriate adapter, or None if the county isn't supported."""
    normalized = county.lower().replace(" county", "").strip()
    return COUNTY_ADAPTERS.get(normalized)


def get_supported_counties() -> list[str]:
    """Return list of supported county names."""
    return [adapter.county_name for adapter in COUNTY_ADAPTERS.values()]
