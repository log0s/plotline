# Served property rows: what the pages read after migration 0014

*2026-09-11, Claude Opus 5. Read-only throughout. Code read at HEAD
`332b5e6`, whose `backend/`, `frontend/` and `scripts/` are byte-identical to
`bac725c`, the SHA both API machines run (`fly image show`, `GH_SHA`). Three
production probes, no writes. Tracked in
`../2026-08-second-audit/STATUS.md` as **AA5** and **AA6**.*

## Prompts (verbatim)

1. "Are there any featured locations that don't have a county adapter?"
2. "Log it" — the reply to an offer to record in STATUS.md that Rodanthe's
   property row predates migration 0014.

§1 answers the first. Sizing the population for the second produced §2, and
turned up §3's second mechanism on the adapter side.

## 1. Featured locations vs adapters

One featured location has no adapter: **Rodanthe, Outer Banks** (`cf46ed63`,
Dare County, NC). The seed list (`scripts/seed_featured.py`) and production's
`featured_locations` hold the same six slugs. The county is `parcels.county`
as the geocoder wrote it; the adapter is the deployed registry's answer for it.

| slug | `parcels.county` | adapter |
|---|---|---|
| stapleton-central-park | Denver | `DenverAdapter` |
| rino-art-district | Denver | `DenverAdapter` |
| green-valley-ranch | Denver | `DenverAdapter` |
| navy-yard-capitol-riverfront | District of Columbia | `DCAdapter` |
| rodanthe-outer-banks | Dare | — |
| hudson-yards | New York | `NewYorkCountyAdapter` |

Rodanthe's page shows the unsupported-county banner, "Property records not
yet available for Dare County". That flag is computed from the adapter
registry on every `/events` call (`backend/app/api/v1/events.py:63`), not read
from a task row, so §2 does not affect it. The other five featured parcels
are among §3's 27 covered parcels.

## 2. No-adapter parcels: 157 of 161 serve the pre-0014 shape (AA5)

A page serves the property task on the parcel's latest **full-scope** request:
`_find_reusable_request` (`backend/app/services/imagery.py:183-205`). A deep
link reaches it through `POST /parcels/{id}/timeline`
(`backend/app/api/v1/imagery.py:83-107`, `frontend/src/pages/ExplorePage.tsx:67-90`),
and a search reaches it through the geocode response
(`backend/app/api/v1/geocode.py:285-300`, `ExplorePage.tsx:56`). Probe 2
walked all 194 parcels through that function:

| county has adapter | served property task | `coverage` | `items_found` | parcels |
|---|---|---|---|---|
| no | `skipped` | NULL | 0 | **157** |
| no | `skipped` | `no_adapter` | NULL | 4 |
| yes | `complete` | NULL | non-NULL | **32** |
| yes | `skipped` | `not_covered` | NULL | 1 |

The 157 span 109 counties in 33 states; Rodanthe is one of them. Every one of
their served tasks completed 2026-08-27 between 18:35:42Z and 19:42:17Z. That
is inside the retry/ops batch's full-fleet sweep
(`../2026-08-ops-batch/SWEEP-SCORECARD.md`: enqueue 18:35:37Z → 19:33:05Z,
189/189 parcels), which ran under `7807c4d`, four hours before `fbdc2f7`
deployed 0014 at 23:17Z. Across all requests there are 670 `skipped` property
rows with NULL `coverage`, none with NULL `items_found`, the last completed
19:42:17Z. There are 4 `no_adapter` rows, completed 2026-08-31 00:20Z →
2026-09-11 15:50Z.

All 189 parcels that existed at the sweep serve that sweep's request (157
here, 32 in §3). The five parcels created since serve post-0014 rows.

**Why they stay.** 0014 added its columns with no backfill
(`../2026-08-property-outcomes/REPORT.md` §2). `maybe_refetch_for_backfill`'s
property trigger only runs when the county has an adapter
(`imagery.py:637-640`), the short-circuit STATUS.md's Crawford entry already
walks. So deviation 4 of that report (§10 item 4: `items_found` NULL for
`no_adapter`, argued for as covering "the larger of the two populations")
reaches new parcels only.

**What it costs.** On the page it is cosmetic: the task row reads "skipped"
where a post-0014 row reads "not covered"
(`frontend/src/components/ParcelInfo.tsx:35-50`). The banner is unaffected
(§1). In the database, `coverage = 'no_adapter'` finds 4 of the 161
no-adapter parcels.

**What moves one.** Any full-scope run. Deploying an adapter for the county
triggers one on the parcel's next page view, through the trigger above.

## 3. Adapter-county parcels: the scoring requeue's outcomes are not served (AA6)

The property-outcomes scoring run made one write:
`scripts/requeue_parcels.py <32 ids> --sources property`
(`../2026-08-property-outcomes/SCORECARD.md`, 2026-08-27T23:48Z). `--sources`
creates a scoped `heal` request (`scripts/requeue_parcels.py:468-470`), and
`_find_reusable_request` never serves a scoped request. That is deliberate:
STATUS.md's M3 entry under *Deferred, not accepted* and its *Notes for future
readers* explain that it stops a scoped backfill from firing the topo trigger
forever. So all 32 pages still
serve their sweep request from before 0014. Columns in the task cells are
`status` · `coverage` · `items_found` · `queries_run`; times are UTC.

| parcel | county | served request, created | served task | latest property request | latest task |
|---|---|---|---|---|---|
| `ebe38b44` | Adams | `4a4a5803` 08-27 18:48 | `complete` · NULL · 0 · NULL | `79051e5d` 08-27 23:48, `heal`, `[property]` | `skipped` · not_covered · NULL · 0 |
| `1a67b7ae` | Denver | `6411a5de` 08-27 19:28 | `complete` · NULL · 12 · NULL | `8124bbca` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 12 · 2 |
| `2758a216` | Denver | `526bbeb2` 08-27 18:46 | `complete` · NULL · 0 · NULL | `b5546638` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 0 · 2 |
| `2a4ca7b9` | Denver | `fc3190a5` 08-27 18:42 | `complete` · NULL · 10 · NULL | `e125f38a` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 10 · 2 |
| `2e34406d` | Denver | `60f8ccb7` 08-27 19:00 | `complete` · NULL · 1 · NULL | `5dcfcc84` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 1 · 2 |
| `39fc3efc` | Denver | `ddf164f6` 08-27 19:13 | `complete` · NULL · 33 · NULL | `260b2900` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 33 · 2 |
| `71d85fbd` | Denver | `b3640617` 08-27 19:32 | `complete` · NULL · 33 · NULL | `63592d69` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 33 · 2 |
| `7397388e` | Denver | `4caa89a9` 08-27 19:28 | `complete` · NULL · 0 · NULL | `f9187a41` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 0 · 2 |
| `742fc436` | Denver | `e2d7cbe5` 08-27 19:18 | `complete` · NULL · 0 · NULL | `e2de8426` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 0 · 2 |
| `7ef10b5c` | Denver | `10fa579e` 08-27 18:35 | `complete` · NULL · 2 · NULL | `654e66db` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 2 · 2 |
| `af8dcdf3` | Denver | `06366abd` 08-27 18:49 | `complete` · NULL · 11 · NULL | `cc723f20` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 11 · 2 |
| `bdf4bdcc` | Denver | `a5a48ceb` 08-27 19:15 | `complete` · NULL · 13 · NULL | `40006e94` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 13 · 2 |
| `0e0abf8c` | District of Columbia | `9e674a38` 08-27 19:10 | `complete` · NULL · 10 · NULL | `8e358409` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 10 · 8 |
| `7096731a` | District of Columbia | `2e9f1f92` 08-27 19:09 | `complete` · NULL · 1 · NULL | `47549f0b` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 1 · 8 |
| `8d9ee137` | District of Columbia | `05e9b3cb` 08-27 19:17 | `complete` · NULL · 5 · NULL | `ac7f93a4` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 5 · 8 |
| `a3628fd4` | District of Columbia | `f2e2c33e` 08-27 18:54 | `complete` · NULL · 0 · NULL | `b3b1af82` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 0 · 8 |
| `c829ed3c` | District of Columbia | `15c1a135` 08-27 18:35 | `complete` · NULL · 10 · NULL | `9cb91fbb` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 10 · 8 |
| `dc493cc5` | District of Columbia | `8ed9b997` 08-27 18:48 | `complete` · NULL · 69 · NULL | `bd09c8d3` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 69 · 8 |
| `ec9e29e1` | District of Columbia | `313d72b7` 08-27 18:44 | `complete` · NULL · 0 · NULL | `c0c3c0ad` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 0 · 8 |
| `09f35468` | New York | `f87501f9` 08-27 18:35 | `complete` · NULL · 0 · NULL | `83619554` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 0 · 3 |
| `1074e64b` | New York | `632e713a` 08-27 19:05 | `complete` · NULL · 7 · NULL | `0805ba38` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 7 · 3 |
| `64a47cd8` | New York | `c7eb8b0e` 08-27 18:48 | `complete` · NULL · 64 · NULL | `8fec6810` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 64 · 3 |
| `9c35ceb0` | New York | `62bfc4fd` 08-27 18:38 | `complete` · NULL · 37 · NULL | `cf9c52cf` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 37 · 3 |
| `d9b1aab9` | New York | `0073b064` 08-27 18:40 | `complete` · NULL · 15 · NULL | `3fa9769e` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 15 · 3 |
| `e513188c` | New York | `0582b1e3` 08-27 18:43 | `complete` · NULL · 48 · NULL | `1ec63905` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 48 · 3 |
| `099336a2` | Santa Clara | `f49bc124` 08-27 18:35 | `complete` · NULL · 0 · NULL | `ba02532c` 08-27 23:48, `heal`, `[property]` | `skipped` · not_covered · NULL · 0 |
| `189ff067` | Santa Clara | `8386f1c8` 08-27 18:37 | `complete` · NULL · 1 · NULL | `109e66f6` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 1 · 3 |
| `2e30825d` | Santa Clara | `49a9a425` 08-27 18:47 | `complete` · NULL · 0 · NULL | `ebb8081d` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 0 · 3 |
| `7f8bd819` | Santa Clara | `66620e86` 08-27 19:28 | `complete` · NULL · 0 · NULL | `a12e9131` 08-27 23:48, `heal`, `[property]` | `skipped` · not_covered · NULL · 0 |
| `9c128ab5` | Santa Clara | `0ed3cb8f` 08-27 19:24 | `complete` · NULL · 1 · NULL | `b4e51ade` 08-27 23:48, `heal`, `[property]` | `complete` · covered · 1 · 3 |
| `b7c0f9aa` | Santa Clara | `f8e782ad` 08-27 19:02 | `complete` · NULL · 0 · NULL | `8cea3d95` 08-27 23:48, `heal`, `[property]` | `skipped` · not_covered · NULL · 0 |
| `e4146d5f` | Santa Clara | `61ea620b` 09-03 17:20 | `skipped` · not_covered · NULL · 0 | *(the served one)* | `skipped` · not_covered · NULL · 0 |
| `f247edea` | Santa Clara | `16e2fed9` 08-27 18:51 | `complete` · NULL · 0 · NULL | `97f5d292` 08-27 23:48, `heal`, `[property]` | `skipped` · not_covered · NULL · 0 |

- **27 covered parcels.** Served and requeued `items_found` are equal on every
  row, so the page reads the same. The served row lacks 0014's columns.
- **The five the requeue resolved `not_covered`** (Adams `ebe38b44`; Santa
  Clara `099336a2`, `7f8bd819`, `b7c0f9aa`, `f247edea`) still serve `complete`
  with `items_found` 0. `TaskRow` renders that as "0 items"
  (`ParcelInfo.tsx:35-50`). `NotCoveredBanner` never renders, because
  `ParcelInfo.tsx:299` passes the served task's `coverage` (NULL) and
  `DemographicsPanel.tsx:171` renders the banner only for `not_covered`. That
  is the conflation the batch existed to remove, on exactly the parcels it
  resolved.
- **`e4146d5f`** (Santa Clara, a full-scope `user` request of 2026-09-03) is
  the one adapter-county page serving `not_covered`. The gate works when its
  row is the one served.

**Why they stay.** The served task is `complete`, which the property trigger
never retries (`imagery.py:661`). Only a full-scope run moves a page.

**What SCORECARD.md said.** It scored the rows the requeue wrote, and those
rows are right. It never claims the pages changed, and nothing in it is false.
Nobody checked which row the page reads.

## 4. Not checked

- **The rendered pages.** Every UI statement above is read from code at HEAD.
  `frontend/` is unchanged since `bac725c`; the Cloudflare Pages deploy was not
  checked.
- **The census and topo tasks on the 32 served requests.** An incidental
  full-scope refetch through those triggers is not ruled out for the future.
  It has not happened yet: all 32 still serve their 2026-08-27 request as of
  21:39Z.
- **Logs.** None read.

## 5. Probes

All three ran on `log0s-plotline-api` machine `48e0de9a713918` through
`fly ssh console -C`, piped in as base64, so no file was written on the
machine:

    B64=$(base64 -w0 probe.py)
    fly ssh console -a log0s-plotline-api -C "sh -c 'cd /app && echo $B64 | base64 -d | python -'"

Each probe is one transaction opened with `SET TRANSACTION READ ONLY`. Inside
it, `UPDATE … WHERE false` ran on a savepoint and was refused all three times
(`ReadOnlySqlTransaction: cannot execute UPDATE in a read-only transaction`),
and the transaction was then rolled back. No session-level `SET` was issued.

| # | transaction start (`now()`) | reads | `audit_probe` |
|---|---|---|---|
| 1 | 21:28:53Z | six featured rows → `parcels` → latest request with a property task | **none.** Any `seq_scan` moved on `featured_locations`, `parcels` or `timeline_requests` at 21:28:53Z is this probe's. |
| 2 | 21:37:33Z | all `skipped` property rows by coverage; every parcel through `_find_reusable_request` | `timeline_request_tasks`, `parcels`: `AA4 record: pre-0014 no-adapter property row shape, 2026-09-11` |
| 3 | 21:39:41Z | the 33 adapter-county parcels, served vs latest property task | `parcels`: `AA4/AA5 record: served vs latest property task, 2026-09-11` |

The purpose strings say "AA4" and "AA4/AA5" because they were written before
the rows were numbered. AA4 turned out to be taken (the Cupertino row), so the
rows are AA5 and AA6. The strings are left as they ran, since they are what a
grep of the `audit_probe` events will find.

Probe 1 reads the latest request *with a property task*, which for the five
covered featured parcels is the scoped requeue request, not the served one.
§1 takes only county and adapter from it.

### Probe 1

```python
"""Featured locations vs. county adapters. Read-only, transaction-scoped."""
import json

from sqlalchemy import text as sa_text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.db import SessionLocal
from app.services.address_normalizer import city_from_address
from app.services.county_adapters import get_adapter_for_county

out = {}
with SessionLocal() as db:
    db.execute(sa_text("SET TRANSACTION READ ONLY"))

    try:
        with db.begin_nested():
            db.execute(sa_text("UPDATE featured_locations SET slug = slug WHERE false"))
        out["read_only_proof"] = "FAILED - the UPDATE was accepted"
    except (InternalError, ProgrammingError) as exc:
        out["read_only_proof"] = type(exc.orig).__name__ + ": " + str(exc.orig).strip()

    rows = db.execute(sa_text("""
        SELECT f.display_order, f.slug, f.parcel_id::text AS parcel_id,
               p.normalized_address, p.county, p.state_fips,
               lt.status AS property_status, lt.coverage, lt.items_found,
               lt.error_message, lt.requested_at
        FROM featured_locations f
        JOIN parcels p ON p.id = f.parcel_id
        LEFT JOIN LATERAL (
            SELECT t.status, t.coverage, t.items_found, t.error_message,
                   tr.created_at AS requested_at
            FROM timeline_requests tr
            JOIN timeline_request_tasks t
              ON t.timeline_request_id = tr.id AND t.source = 'property'
            WHERE tr.parcel_id = p.id
            ORDER BY tr.created_at DESC
            LIMIT 1
        ) lt ON true
        ORDER BY f.display_order
    """)).mappings().all()

    out["featured"] = []
    for r in rows:
        row = dict(r)
        adapter = get_adapter_for_county(row["county"]) if row["county"] else None
        row["deployed_adapter"] = type(adapter).__name__ if adapter else None
        city = city_from_address(row["normalized_address"] or "")
        row["city"] = city
        row["adapter_covers_city"] = adapter.covers(city) if adapter else None
        out["featured"].append(row)

    out["now"] = str(db.execute(sa_text("SELECT now()")).scalar())
    db.rollback()

print(json.dumps(out, indent=2, default=str))
```

### Probe 2

```python
"""Pre-0014 vs post-0014 no-adapter property rows. Read-only, transaction-scoped."""
import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.db import SessionLocal
from app.logging_config import configure_script_logging
from app.models.parcels import Parcel, TimelineRequestTask
from app.services.county_adapters import get_adapter_for_county
from app.services.imagery import _find_reusable_request
from scripts.shared.probe import audit_probe

PURPOSE = "AA4 record: pre-0014 no-adapter property row shape, 2026-09-11"

configure_script_logging()
out = {}
with SessionLocal() as db:
    db.execute(sa_text("SET TRANSACTION READ ONLY"))

    try:
        with db.begin_nested():
            db.execute(sa_text("UPDATE parcels SET county = county WHERE false"))
        out["read_only_proof"] = "FAILED - the UPDATE was accepted"
    except (InternalError, ProgrammingError) as exc:
        out["read_only_proof"] = type(exc.orig).__name__ + ": " + str(exc.orig).strip()

    audit_probe("timeline_request_tasks", purpose=PURPOSE)
    out["all_skipped_property_rows_by_coverage"] = [
        dict(r) for r in db.execute(sa_text(
            "SELECT coverage, (items_found IS NULL) AS items_found_null, count(*) AS n,"
            " min(completed_at) AS first_completed, max(completed_at) AS last_completed"
            " FROM timeline_request_tasks"
            " WHERE source = 'property' AND status = 'skipped'"
            " GROUP BY 1, 2 ORDER BY 1, 2"
        )).mappings()
    ]

    audit_probe("parcels", purpose=PURPOSE)
    parcels = db.execute(select(Parcel)).scalars().all()
    out["parcels_total"] = len(parcels)

    buckets = Counter()
    stuck = []
    for p in parcels:
        has_adapter = bool(p.county and get_adapter_for_county(p.county))
        req = _find_reusable_request(db, p.id)
        if req is None:
            buckets[(has_adapter, "no_reusable_request", None, None)] += 1
            continue
        task = db.execute(
            select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == req.id)
            .where(TimelineRequestTask.source == "property")
        ).scalars().first()
        if task is None:
            buckets[(has_adapter, "no_property_task", None, None)] += 1
            continue
        key = (has_adapter, task.status, task.coverage, task.items_found is None)
        buckets[key] += 1
        if not has_adapter and task.status == "skipped" and task.coverage is None:
            stuck.append({
                "parcel": str(p.id)[:8],
                "county": p.county,
                "state_fips": p.state_fips,
                "items_found": task.items_found,
                "completed_at": str(task.completed_at),
            })

    out["current_request_property_buckets"] = [
        {"has_adapter": k[0], "status": k[1], "coverage": k[2],
         "items_found_null": k[3], "parcels": n}
        for k, n in sorted(buckets.items(), key=lambda kv: str(kv[0]))
    ]
    out["no_adapter_old_shape_parcels"] = len(stuck)
    out["no_adapter_old_shape_counties"] = len({(s["county"], s["state_fips"]) for s in stuck})
    out["no_adapter_old_shape_latest_completed"] = max((s["completed_at"] for s in stuck), default=None)
    out["no_adapter_old_shape_items_found"] = dict(Counter(str(s["items_found"]) for s in stuck))
    out["rodanthe_in_list"] = any(s["parcel"] == "cf46ed63" for s in stuck)
    out["stuck"] = stuck

    out["now"] = str(db.execute(sa_text("SELECT now()")).scalar())
    db.rollback()

print(json.dumps(out, indent=2, default=str))
```

### Probe 3

```python
"""Adapter-county parcels: served property task vs latest property task. Read-only."""
import json

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.exc import InternalError, ProgrammingError

from app.db import SessionLocal
from app.logging_config import configure_script_logging
from app.models.parcels import Parcel, TimelineRequest, TimelineRequestTask
from app.services.county_adapters import get_adapter_for_county
from app.services.imagery import _find_reusable_request
from scripts.shared.probe import audit_probe

PURPOSE = "AA4/AA5 record: served vs latest property task, 2026-09-11"


def _task(db, req_id):
    t = db.execute(
        select(TimelineRequestTask)
        .where(TimelineRequestTask.timeline_request_id == req_id)
        .where(TimelineRequestTask.source == "property")
    ).scalars().first()
    if t is None:
        return None
    return {
        "status": t.status,
        "coverage": t.coverage,
        "items_found": t.items_found,
        "queries_run": t.queries_run,
        "completed_at": str(t.completed_at),
    }


configure_script_logging()
out = {}
with SessionLocal() as db:
    db.execute(sa_text("SET TRANSACTION READ ONLY"))

    try:
        with db.begin_nested():
            db.execute(sa_text("UPDATE parcels SET county = county WHERE false"))
        out["read_only_proof"] = "FAILED - the UPDATE was accepted"
    except (InternalError, ProgrammingError) as exc:
        out["read_only_proof"] = type(exc.orig).__name__ + ": " + str(exc.orig).strip()

    audit_probe("parcels", purpose=PURPOSE)
    rows = []
    for p in db.execute(select(Parcel)).scalars().all():
        if not (p.county and get_adapter_for_county(p.county)):
            continue
        served = _find_reusable_request(db, p.id)
        latest = db.execute(
            select(TimelineRequest)
            .join(TimelineRequestTask, TimelineRequestTask.timeline_request_id == TimelineRequest.id)
            .where(TimelineRequest.parcel_id == p.id)
            .where(TimelineRequestTask.source == "property")
            .order_by(TimelineRequest.created_at.desc())
            .limit(1)
        ).scalars().first()
        rows.append({
            "parcel": str(p.id)[:8],
            "county": p.county,
            "address": p.normalized_address,
            "served_req": str(served.id)[:8] if served else None,
            "served_req_created": str(served.created_at) if served else None,
            "served_req_sources": list(served.sources) if served else None,
            "served_task": _task(db, served.id) if served else None,
            "latest_req": str(latest.id)[:8] if latest else None,
            "latest_req_created": str(latest.created_at) if latest else None,
            "latest_req_sources": list(latest.sources) if latest else None,
            "latest_req_origin": latest.origin if latest else None,
            "latest_task": _task(db, latest.id) if latest else None,
        })

    out["adapter_parcels"] = rows
    out["now"] = str(db.execute(sa_text("SELECT now()")).scalar())
    db.rollback()

print(json.dumps(out, indent=2, default=str))
```
