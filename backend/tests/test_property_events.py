"""Tests for Phase 4 — property history events.

Covers address normalization, fuzzy matching, adapter parsing,
permit classification, event deduplication, price history, and
unsupported county handling.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.services.address_normalizer import (
    extract_search_terms,
    is_address_match,
    normalize_address,
)
from app.services.county_adapters import (
    DenverAdapter,
    classify_permit,
    get_adapter_for_county,
    get_supported_counties,
)
from app.services.property_events import (
    PropertyEventRow,
    compute_price_summary,
    get_property_events,
    upsert_property_event,
)

# ── Address Normalization ────────────────────────────────────────────────────


class TestNormalizeAddress:
    def test_basic_normalization(self) -> None:
        assert normalize_address("1600 Pennsylvania Avenue") == "1600 PENNSYLVANIA AVE"

    def test_strips_unit(self) -> None:
        result = normalize_address("100 Main Street Apt 4B")
        assert "APT" not in result
        assert result == "100 MAIN ST"

    def test_strips_suite(self) -> None:
        result = normalize_address("200 Broadway Suite 100")
        assert "SUITE" not in result
        assert result == "200 BROADWAY"

    def test_strips_hash_unit(self) -> None:
        result = normalize_address("300 Oak Drive #5")
        assert "#" not in result
        assert result == "300 OAK DR"

    def test_suffix_standardization(self) -> None:
        assert normalize_address("10 Elm Boulevard") == "10 ELM BLVD"
        assert normalize_address("20 Pine Road") == "20 PINE RD"
        assert normalize_address("30 Cedar Lane") == "30 CEDAR LN"
        assert normalize_address("40 Park Parkway") == "40 PARK PKWY"

    def test_already_abbreviated(self) -> None:
        assert normalize_address("50 Main St") == "50 MAIN ST"

    def test_extra_whitespace(self) -> None:
        assert normalize_address("  100   Main   Street  ") == "100 MAIN ST"


class TestExtractSearchTerms:
    def test_basic_extraction(self) -> None:
        num, name = extract_search_terms("1600 Pennsylvania Avenue NW")
        assert num == "1600"
        assert name == "PENNSYLVANIA"

    def test_directional_prefix(self) -> None:
        num, name = extract_search_terms("E 49th Ave")
        assert num == "E"  # directional at position 0 isn't a street number
        # Actually let's check what happens — "E" is position 0
        # extract_search_terms normalizes then splits: "E 49TH AVE"
        # parts[0] = "E", parts[1] = "49TH" which is a directional? No.
        # Directionals are: N, S, E, W, etc. — "E" is in DIRECTIONALS
        # But parts[0] is the street_number, then parts[1] is checked.
        # "E" at index 0 is treated as street_number.
        # parts[1] = "49TH" — not in DIRECTIONALS, so name = "49TH"
        assert name == "49TH"

    def test_with_leading_directional(self) -> None:
        num, name = extract_search_terms("123 E Colfax Ave")
        assert num == "123"
        assert name == "COLFAX"  # skips the "E" directional

    def test_short_address(self) -> None:
        num, name = extract_search_terms("100")
        assert num == "100"
        assert name == ""


class TestIsAddressMatch:
    def test_exact_match(self) -> None:
        assert is_address_match(
            "1600 Pennsylvania Ave",
            "1600 PENNSYLVANIA AVE",
        )

    def test_match_with_unit(self) -> None:
        assert is_address_match(
            "1600 Pennsylvania Ave",
            "1600 PENNSYLVANIA AV UNIT 3",
        )

    def test_no_match_different_street(self) -> None:
        assert not is_address_match(
            "1600 Pennsylvania Ave",
            "1600 Penn St",
        )

    def test_close_match(self) -> None:
        assert is_address_match(
            "100 Main St",
            "100 MAIN STREET",
        )

    def test_empty_address(self) -> None:
        assert not is_address_match("", "100 Main St")
        assert not is_address_match("100 Main St", "")


# ── Permit Classification ────────────────────────────────────────────────────


class TestClassifyPermit:
    def test_demolition(self) -> None:
        assert classify_permit("DEMO") == "permit_demolition"
        assert classify_permit("Demolition") == "permit_demolition"

    def test_electrical(self) -> None:
        assert classify_permit("ELEC") == "permit_electrical"
        assert classify_permit("Electrical") == "permit_electrical"

    def test_mechanical(self) -> None:
        assert classify_permit("MECH") == "permit_mechanical"

    def test_plumbing(self) -> None:
        assert classify_permit("PLUM") == "permit_plumbing"
        assert classify_permit("Plumbing") == "permit_plumbing"

    def test_building(self) -> None:
        assert classify_permit("BLDR") == "permit_building"
        assert classify_permit("Building") == "permit_building"
        assert classify_permit("NEW CONSTRUCTION") == "permit_building"
        assert classify_permit("ADDITION") == "permit_building"
        assert classify_permit("REMODEL") == "permit_building"

    def test_other(self) -> None:
        assert classify_permit("SIGN") == "permit_other"
        assert classify_permit("") == "permit_other"
        assert classify_permit("FENCE") == "permit_other"


# ── County Adapter Registry ──────────────────────────────────────────────────


class TestAdapterRegistry:
    def test_denver_lookup(self) -> None:
        adapter = get_adapter_for_county("Denver")
        assert adapter is not None
        assert adapter.county_name == "Denver"

    def test_denver_county_suffix(self) -> None:
        adapter = get_adapter_for_county("Denver County")
        assert adapter is not None

    def test_adams_lookup(self) -> None:
        adapter = get_adapter_for_county("Adams")
        assert adapter is not None

    def test_unsupported_county(self) -> None:
        assert get_adapter_for_county("El Paso") is None
        assert get_adapter_for_county("Los Angeles") is None

    def test_supported_counties_list(self) -> None:
        counties = get_supported_counties()
        assert "Denver" in counties
        assert "Adams" in counties


# ── Denver Adapter Parsing ────────────────────────────────────────────────────


class TestDenverAdapterParsing:
    def test_fetch_sales_returns_empty(self) -> None:
        """Denver sales data is no longer available via public API."""
        import asyncio
        adapter = DenverAdapter()
        result = asyncio.get_event_loop().run_until_complete(
            adapter.fetch_sales("123", "MAIN")
        )
        assert result == []

    def test_parse_permit_building(self) -> None:
        adapter = DenverAdapter()
        # ArcGIS row with epoch-ms timestamp
        row = {
            "ADDRESS": "123 N MAIN ST",
            "DATE_ISSUED": 1615334400000,  # 2021-03-10 UTC
            "CLASS": "Alteration/Tenant Finish",
            "VALUATION": 350000,
            "PERMIT_NUM": "2021-COMMCON-001",
            "CONTRACTOR_NAME": "ACME BUILDERS",
        }
        event = adapter._parse_permit(row)
        assert event.event_type == "permit_building"
        assert event.event_date == date(2021, 3, 10)
        assert event.permit_valuation == 350000
        assert event.source == "denver_permits"
        assert event.source_record_id == "2021-COMMCON-001"
        assert "Alteration/Tenant Finish" in event.description

    def test_parse_permit_demolition(self) -> None:
        adapter = DenverAdapter()
        row = {
            "ADDRESS": "789 OAK DR",
            "DATE_ISSUED": 1537574400000,  # 2018-09-22 UTC
            "CLASS": "Demolition",
            "VALUATION": 12000,
            "PERMIT_NUM": "2018-COMMCON-555",
        }
        event = adapter._parse_permit(row)
        assert event.event_type == "permit_demolition"
        assert event.event_date == date(2018, 9, 22)

    def test_parse_permit_no_date(self) -> None:
        adapter = DenverAdapter()
        row = {
            "ADDRESS": "100 TEST ST",
            "DATE_ISSUED": None,
            "CLASS": "Special Event",
            "VALUATION": 500,
            "PERMIT_NUM": "2020-COMMCON-999",
        }
        event = adapter._parse_permit(row)
        assert event.event_date is None
        assert event.event_type == "permit_other"


# ── Property Events DB Operations ────────────────────────────────────────────


class TestPropertyEventsDB:
    def _seed_parcel(self, db: Session) -> uuid.UUID:
        """Insert a test parcel and return its ID."""
        parcel_id = uuid.uuid4()
        from sqlalchemy import text as sa_text

        db.execute(
            sa_text(
                """INSERT INTO parcels (id, address, latitude, longitude, point, county)
                   VALUES (:id, :addr, :lat, :lng, :point, :county)"""
            ),
            {
                "id": str(parcel_id),
                "addr": "123 Main St, Denver, CO",
                "lat": 39.7392,
                "lng": -104.9903,
                "point": "POINT(-104.9903 39.7392)",
                "county": "Denver",
            },
        )
        db.commit()
        return parcel_id

    def test_upsert_and_query(self, db: Session) -> None:
        parcel_id = self._seed_parcel(db)
        was_inserted = upsert_property_event(
            db,
            parcel_id=parcel_id,
            event_type="sale",
            event_date=date(2020, 1, 15),
            sale_price=300000,
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description="Sold for $300,000",
            source="denver_sales",
            source_record_id="REC001",
        )
        assert was_inserted

        events = get_property_events(db, parcel_id)
        assert len(events) == 1
        assert events[0].event_type == "sale"
        assert events[0].sale_price == 300000

    def test_deduplication(self, db: Session) -> None:
        parcel_id = self._seed_parcel(db)
        kwargs = dict(
            parcel_id=parcel_id,
            event_type="sale",
            event_date=date(2020, 1, 15),
            sale_price=300000,
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description="Sold for $300,000",
            source="denver_sales",
            source_record_id="REC001",
        )
        first = upsert_property_event(db, **kwargs)
        second = upsert_property_event(db, **kwargs)
        assert first is True
        assert second is False

        events = get_property_events(db, parcel_id)
        assert len(events) == 1

    def test_filter_by_type(self, db: Session) -> None:
        parcel_id = self._seed_parcel(db)
        upsert_property_event(
            db, parcel_id=parcel_id, event_type="sale",
            event_date=date(2020, 1, 1), sale_price=100000,
            permit_type=None, permit_description=None, permit_valuation=None,
            description="Sale", source="denver_sales", source_record_id="S1",
        )
        upsert_property_event(
            db, parcel_id=parcel_id, event_type="permit_building",
            event_date=date(2021, 6, 1), sale_price=None,
            permit_type="BLDR", permit_description="New build", permit_valuation=50000,
            description="Building permit", source="denver_permits", source_record_id="P1",
        )

        sales = get_property_events(db, parcel_id, event_types=["sale"])
        assert len(sales) == 1
        assert sales[0].event_type == "sale"

        permits = get_property_events(db, parcel_id, event_types=["permit_building"])
        assert len(permits) == 1

    def test_date_range_filter(self, db: Session) -> None:
        parcel_id = self._seed_parcel(db)
        upsert_property_event(
            db, parcel_id=parcel_id, event_type="sale",
            event_date=date(2010, 1, 1), sale_price=100000,
            permit_type=None, permit_description=None, permit_valuation=None,
            description="Sale 1", source="denver_sales", source_record_id="S1",
        )
        upsert_property_event(
            db, parcel_id=parcel_id, event_type="sale",
            event_date=date(2020, 6, 1), sale_price=300000,
            permit_type=None, permit_description=None, permit_valuation=None,
            description="Sale 2", source="denver_sales", source_record_id="S2",
        )

        events = get_property_events(
            db, parcel_id,
            start_date=date(2015, 1, 1),
            end_date=date(2025, 1, 1),
        )
        assert len(events) == 1
        assert events[0].sale_price == 300000


# ── Price History / Appreciation ──────────────────────────────────────────────


class TestPriceSummary:
    def test_appreciation_calculation(self) -> None:
        events = [
            PropertyEventRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), event_type="sale",
                event_date=date(2000, 1, 1), sale_price=100000,
                permit_type=None, permit_description=None, permit_valuation=None,
                description="", source="denver_sales", source_record_id="S1",
            ),
            PropertyEventRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), event_type="permit_building",
                event_date=date(2015, 6, 1), sale_price=None,
                permit_type="BLDR", permit_description="Remodel", permit_valuation=50000,
                description="", source="denver_permits", source_record_id="P1",
            ),
            PropertyEventRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), event_type="sale",
                event_date=date(2020, 6, 1), sale_price=400000,
                permit_type=None, permit_description=None, permit_valuation=None,
                description="", source="denver_sales", source_record_id="S2",
            ),
        ]
        summary = compute_price_summary(events)
        assert summary["total_events"] == 3
        assert summary["total_sales"] == 2
        assert summary["total_permits"] == 1
        assert len(summary["price_history"]) == 2
        assert summary["appreciation"] == "300% since first recorded sale"

    def test_single_sale_no_appreciation(self) -> None:
        events = [
            PropertyEventRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), event_type="sale",
                event_date=date(2020, 1, 1), sale_price=250000,
                permit_type=None, permit_description=None, permit_valuation=None,
                description="", source="denver_sales", source_record_id="S1",
            ),
        ]
        summary = compute_price_summary(events)
        assert summary["appreciation"] is None
        assert len(summary["price_history"]) == 1

    def test_empty_events(self) -> None:
        summary = compute_price_summary([])
        assert summary["total_events"] == 0
        assert summary["appreciation"] is None
        assert summary["price_history"] == []


# ── API Endpoint ──────────────────────────────────────────────────────────────


class TestEventsEndpoint:
    def _seed_parcel_and_events(self, db: Session) -> uuid.UUID:
        parcel_id = uuid.uuid4()
        from sqlalchemy import text as sa_text

        db.execute(
            sa_text(
                """INSERT INTO parcels (id, address, latitude, longitude, point, county)
                   VALUES (:id, :addr, :lat, :lng, :point, :county)"""
            ),
            {
                "id": str(parcel_id),
                "addr": "123 Main St, Denver, CO",
                "lat": 39.7392,
                "lng": -104.9903,
                "point": "POINT(-104.9903 39.7392)",
                "county": "Denver",
            },
        )
        db.commit()

        upsert_property_event(
            db, parcel_id=parcel_id, event_type="sale",
            event_date=date(2018, 3, 15), sale_price=250000,
            permit_type=None, permit_description=None, permit_valuation=None,
            description="Sold for $250,000", source="denver_sales",
            source_record_id="REC100",
        )
        upsert_property_event(
            db, parcel_id=parcel_id, event_type="permit_building",
            event_date=date(2019, 7, 1), sale_price=None,
            permit_type="BLDR", permit_description="Kitchen remodel",
            permit_valuation=45000, description="BLDR — Kitchen remodel ($45,000)",
            source="denver_permits", source_record_id="P100",
        )
        return parcel_id

    def test_get_events(self, client, db: Session) -> None:
        parcel_id = self._seed_parcel_and_events(db)
        resp = client.get(f"/api/v1/parcels/{parcel_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["supported"] is True
        assert data["county"] == "Denver"
        assert len(data["events"]) == 2
        assert data["summary"]["total_events"] == 2
        assert data["summary"]["total_sales"] == 1

    def test_get_events_type_filter(self, client, db: Session) -> None:
        parcel_id = self._seed_parcel_and_events(db)
        resp = client.get(f"/api/v1/parcels/{parcel_id}/events?type=sale")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "sale"

    def test_get_events_parcel_not_found(self, client) -> None:
        fake_id = uuid.uuid4()
        resp = client.get(f"/api/v1/parcels/{fake_id}/events")
        assert resp.status_code == 404

    def test_unsupported_county(self, client, db: Session) -> None:
        parcel_id = uuid.uuid4()
        from sqlalchemy import text as sa_text

        db.execute(
            sa_text(
                """INSERT INTO parcels (id, address, latitude, longitude, point, county)
                   VALUES (:id, :addr, :lat, :lng, :point, :county)"""
            ),
            {
                "id": str(parcel_id),
                "addr": "100 Main St, Colorado Springs, CO",
                "lat": 38.8339,
                "lng": -104.8214,
                "point": "POINT(-104.8214 38.8339)",
                "county": "El Paso",
            },
        )
        db.commit()

        resp = client.get(f"/api/v1/parcels/{parcel_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["supported"] is False
        assert data["county"] == "El Paso"
        assert len(data["events"]) == 0
