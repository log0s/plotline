"""What will the property path do for this address? Read-only replay of `_fetch_property`.

Throwaway. Calls the same adapter methods the worker calls (all GETs), and
applies the same coverage gate, search-term extraction and H5 address matcher,
without a database or a task row. Run inside the api container:

    docker compose exec -T api python - "<county>|<normalized address>|<label>" [...] \
        < docs/audits/2026-09-featured-vetting/queries/property_probe.py

Prints the state the task row would land in — ``skipped``/``no_adapter``,
``skipped``/``not_covered``, ``failed`` (all queries failed), ``partial``, or
``complete`` with rows_returned/rows_matched — which is exactly the distinction
STATUS.md's Z3/Z4/AA2 rows are about.
"""

from __future__ import annotations

import asyncio
import sys

from app.services.address_normalizer import city_from_address, extract_search_terms, is_address_match
from app.services.county_adapters import get_adapter_for_county


async def probe(county: str, address: str, label: str) -> None:
    print(f"\n## {label}  county={county!r} address={address!r}")
    adapter = get_adapter_for_county(county)
    if adapter is None:
        print("  -> task 'skipped', coverage='no_adapter', queries_run=0, items_found NULL")
        print(f"     error_message: 'Property data not yet available for {county} County'")
        return
    city = city_from_address(address)
    print(f"  adapter={type(adapter).__name__} display={adapter.display_name!r} city_from_address={city!r}")
    if not adapter.covers(city):
        print("  -> task 'skipped', coverage='not_covered', queries_run=0, items_found NULL")
        return
    number, street = extract_search_terms(address)
    print(f"  search terms: number={number!r} street={street!r}")
    sales = await adapter.fetch_sales(number, street)
    permits = await adapter.fetch_permits(number, street)
    attempted = sales.queries_attempted + permits.queries_attempted
    failed = sales.queries_failed + permits.queries_failed
    events = [*sales.events, *permits.events]
    matched = [e for e in events if not (e.situs_address and not is_address_match(address, e.situs_address))]
    status = "failed (all queries failed)" if attempted and failed == attempted else ("partial" if failed else "complete")
    print(
        f"  queries_run={attempted} queries_failed={failed} rows_returned={len(events)} "
        f"rows_matched={len(matched)} -> task {status!r}, coverage='covered'"
    )
    for e in matched[:10]:
        print(f"    matched: {e.event_type:20s} {str(e.event_date):12s} {e.source:16s} {str(e.situs_address)[:48]!r}")
    unmatched = [e for e in events if e not in matched]
    for e in unmatched[:5]:
        print(f"    rejected by matcher: {str(e.situs_address)[:60]!r}")


async def main() -> None:
    for arg in sys.argv[1:]:
        county, address, label = arg.split("|", 2)
        await probe(county, address, label)


asyncio.run(main())
