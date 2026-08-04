# Second Audit — Status

Companion to `FINDINGS.md`, which is frozen as a record of what the code
looked like at 5f5fb42 (2026-07-29). This file is the living half: what each
finding's status is now, and where the open ones stand.

**Verified against HEAD e1006df on 2026-08-03** by reading each cited site,
not by trusting the annotations. The fourteen items triaged FIX NOW were then
executed in the five commits cited below, and their rows reflect that. Line
numbers are HEAD's, not the audit's.

Nothing was incidentally resolved between the audit and the verification pass.
M6, L2, L5 and all six L12 items were checked specifically against the commits
most likely to have caught them — the Redis, reconciliation, and
geocoder-guard work — and none had.

## Summary

| | Resolved | Partially resolved | Open |
|---|---|---|---|
| High (6) | 6 | 0 | 0 |
| Medium (12) | 4 | 4 | 4 |
| Low (12) | 6 | 2 | 4 |

"Partially resolved" here always means the remainder is an explicit accept or
an explicit deferral, both recorded below — never an unfinished edit.

## The fix commits

| Hash | Covers |
|---|---|
| dd99cee | M6, M10 (advisory lock), L11 |
| 3269bbf | L5 |
| ffb71b2 | L2, L4, L6 (source id), L7, L9 |
| ae5793a | M2 (atomicity), M3 (cooldown), counties item 13 |
| 56d6647 | M9 (exposure), L12 (CORS) |

## High — all resolved

| # | Commit | Verified at |
|---|---|---|
| H1 Housing chart | 6def10c, 1c1c069 | `census.py:57-64`; `scripts/backfill_census_housing.py` |
| H2 Log context | 90ea416 | `logging_config.py:28`; `celery_app.py:61-72` |
| H3 Demographics cache | 90ea416 | `demographics.py:37` |
| H4 Property outage | 256ed32 | `county_adapters.py:33-40,106-121`; `timeline.py:683-697` |
| H5 Address matcher | add8102 | `address_normalizer.py:34-52,76-87`; `tests/test_address_normalizer.py` |
| H6 Landsat duplicates | 96a7962 | `imagery.py:414-503`; `timeline.py:365,454`; `revalidate_landsat.py:65-77` |

## Medium

| # | Status | Where it stands |
|---|---|---|
| M1 Geocoder decode | Resolved (949c1b3) | `geocoder.py:158,196`. The finding's retry-asymmetry aside (only timeouts retried) is unchanged; it was flagged as defensible, not as a defect. |
| M2 Rate limiting | Partially resolved (ae5793a) | INCR and EXPIRE now ship in one pipeline with `EXPIRE … NX`, so a death between them can no longer leave an immortal counter. The X-Forwarded-For handling is accepted — see below. |
| M3 Backfill scope | Partially resolved (ae5793a) | A cooldown (`backfill_cooldown_hours`, default 6) bounds the per-visit cost and logs each suppression. The cooldown is dispatch-anchored — it reads the latest `TimelineRequest.created_at`, which includes a request the current visit may have just created — not completion-anchored; correct for cost-bounding, and the per-source work inherits it unless it deliberately changes it. Per-source scope is deferred, not accepted — see below. |
| M4 Partial census/Landsat failures | Open | `timeline.py:234-259`, `:588-658` (the census year loop moved into `_fetch_census_years` in b5a306a) — failures counted, never persisted, so nothing can target the gaps. Sharper than the finding states on the census half: a year the API has no data for returns `{}` and is skipped by `if data:` (`:598` decennial, `:625` ACS5) **without** incrementing `failed_requests` (`:612`, `:639`), so the all-failed check at `:651` cannot see it either. The gap is not merely unpersisted — it is invisible to the task's own failure arithmetic, which is why a parcel could sit at `complete` with four of six ACS years missing. One instance of that shape — years lost to the 2020 tract redistricting — is healed by b5a306a and its `scripts/heal_tract_vintage_gaps.py`; the general problem of persisting per-year failures is untouched. |
| M5 Sync I/O on the loop | Open | `geocode.py:55-57,146-151`; `timeline.py:310-360`. The worker half is accepted; the autocomplete half is not. |
| M6 Redis socket timeouts | Resolved (dd99cee) | `socket_timeout` and `socket_connect_timeout` of 2s on both clients, matching the DB probe's `statement_timeout`. |
| M7 ORM/schema drift | Open | Partial indexes in `0009:49`, `0010:67,83` absent from `models/parcels.py`; `conftest.py:55-190` still hand-written DDL. |
| M8 DO NOTHING freezes records | Open | `property_events.py:74`; `county_adapters.py:466,734`. |
| M9 Titiler callback path | Partially resolved (56d6647) | `/warmup` (30/min) and `/{id}/stac` (600/min) now carry rate limits. The routing itself is accepted — see below. |
| M10 Migration on boot | Partially resolved (dd99cee) | A session-scoped `pg_advisory_lock` in `alembic/env.py` serializes concurrent boots. The worker-ahead-of-schema window is accepted — see below. |
| M11 Failures vanish from UI | Resolved (256ed32) | `ParcelInfo.tsx:131-133,268-275`; `DemographicsPanel.tsx:78-95`. |
| M12 Celery config | Resolved (05bb263) | `celery_app.py:29-31,53`; `timeline.py:950-958`. |

## Low

| # | Status | Where it stands |
|---|---|---|
| L1 STAC pagination loop | Open | `stac.py:141-163` — still no page counter. |
| L2 strict-zip landmine | Resolved (ffb71b2) | Groups filtered once, zipped over the filtered list; test covers an empty group. |
| L3 WHERE-clause escaping | Open | `county_adapters.py:46-56` escapes quotes only; anchoring still differs between `:236,:332,:425,:480` and `:697,:759`. |
| L4 STAC fetch host | Resolved (ffb71b2) | Allowlisted to `planetarycomputer.microsoft.com`, the only host any Landsat row carries. |
| L5 Geocoder county fallback | Resolved (3269bbf) | Fallback removed on both paths; `scripts/heal_county_fallback.py` clears rows already carrying one. Dev had zero. |
| L6 TNM caps and ids | Partially resolved (ffb71b2) | Products with no `sourceId` are skipped instead of colliding on `stac_item_id=""`. Pagination accepted — see below. |
| L7 `_fetch_source` coordinates | Resolved (ffb71b2) | Defaults removed; two test call sites were relying on them. |
| L8 Autocomplete self-DoS | Open | `useAddressAutocomplete.ts:12` (150ms); `SearchInput.tsx:35,44,57,112` still clears the input before the geocode resolves. |
| L9 Tile-proxy input | Resolved (ffb71b2) | `z` capped at 0–24; `x`/`y` given one generous static bound, since anything inside it but outside the COG extent already returns a transparent tile. |
| L10 Raw error strings | Open | `schemas/imagery.py:25,38`; `timeline.py:198,402,650`. |
| L11 Prefork engine | Resolved (dd99cee) | `worker_process_init` → `engine.dispose(close=False)`. |
| L12 Misc | Partially resolved (56d6647) | CORS `allow_credentials` dropped. Still open: JSON vs JSONB (`models/parcels.py:323`/`:398`), "declined 0%" (`demographics.py:203-211`), the URL-normalization chain (`config.py:83-89` **and** `alembic/env.py:36-42`), `Dockerfile.fly` running as root with gcc, and DC's hardcoded permit layers (`county_adapters.py:396-404`). |

## Counties reconciliation

Items 1–12 and 14–16 are resolved by c296b3a; `SUPPORTED_COUNTIES.md` was
spot-checked against the adapters and matches, and its 2026-08-03 stamp is
true.

**Item 13 (row caps)** is partially resolved by ae5793a. Pagination is
accepted: five caps spread across three shared clients, built against a
hypothesis about overflow that nothing has yet confirmed. The half that
mattered is implemented instead — each client now logs a warning when a query
returns exactly its cap, naming the resource and the cap, so truncation is no
longer indistinguishable from a complete answer. If those warnings start
appearing in production, that is the evidence pagination was waiting for.

Of the "code oddities": the bare-`Exception` item is resolved by 256ed32; the
module docstring (`county_adapters.py:1-9`, still "Socrata API quirks" for a
registry that is now 3 ArcGIS, 1 CKAN, 1 Socrata), `parse_date`'s docstring
(`:59`), and DC's unused `APPRAISED_VALUE_CURRENT_TOTAL` (`:434`) remain open.
e1006df separately fixed the frontend's hardcoded county list, which the
reconciliation flagged in spirit (item 15) but not as a code finding.

## Accepted, with reasons

- **M2, client identification.** `Fly-Client-IP` takes precedence and Fly's
  proxy overwrites it on every inbound request, so the spoofable
  `X-Forwarded-For` branch is unreachable in production. This makes the
  deployment topology load-bearing, and the assumption is written into
  `rate_limit.py` at the branch itself so nobody has to find this document to
  learn it.
- **M9, routing.** Internal `.internal` addressing was implemented and
  reverted in c6213d5 — Fly private DNS is IPv6-only and it broke
  API→Titiler. The doubled public request load is the price of that
  constraint, not an oversight. Recorded next to `API_INTERNAL_URL` in
  `fly.toml` as well as here, because the temptation to "fix" it recurs.
- **M10, worker-ahead-of-schema.** Migrations to date are additive, the window
  is seconds, and closing it means serializing two deploy jobs to prevent a
  failure that has not occurred.
- **M5, worker half.** The sync persist phase stalls sibling coroutines but
  cannot deadlock; at one worker it costs seconds per run.
- **L6, TNM pagination.** The audit never verified that a real quad exceeds
  100 products. Not building against an unverified premise.
- **L10.** Traced and confirmed no credential leak; exposing upstream URLs is
  hygiene, and curated messages cost more than the disclosure is worth.
- **L12, JSON vs JSONB.** Cosmetic; costs a migration and a column rewrite.
  `CensusSnapshot.raw_data` is never queried by content.
- **L12, DC permit layers.** An annual manual chore. The honest mitigation is
  a reminder, not code.

## Deferred, not accepted

- **M3, per-source scope.** The cooldown bounds the cost; it does not fix the
  shape. The open decision is whether scope lives as a `sources` column on
  `TimelineRequest` or is derived per-run from the previous request's task
  rows.
- **M9, authenticating the Titiler callback.** The rate limits in 56d6647 are
  an interim mitigation, and the batch that added them established that a
  counter is the wrong instrument here: every legitimate call to `/stac`
  arrives from Titiler's single egress IP, so a per-IP limit is one shared
  bucket for all users rather than a per-visitor budget, and 600/min is set
  loose enough not to throttle real tile serving. Properly distinguishing
  Titiler from the public needs a shared secret or a signed callback. The
  routing half stays accepted regardless — this is about who may call the
  endpoint, not where the traffic goes.
- **H1's decennial half — the Housing chart still cannot show a decennial
  year.** 6def10c fixed the ACS side of the impossible-combination finding;
  the other side of the same sentence in FINDINGS.md is still true.
  `_DECENNIAL_CONFIGS` (`census.py:27-56`) fetches population and total units
  only, and `HousingChart.tsx:33-37` requires a total *plus* an owner/renter
  split, so 1990/2000/2010/2020 rows are structurally excluded from the chart
  even when fully populated. Confirmed again during the tract-vintage work,
  which is what made it visible: Stapleton's 2010 row exists and carries
  1,773 units, and the chart still will not draw it. The prerequisite is
  verifying occupancy variable names against the live Census API per vintage
  — names drift across decades, the known pattern being P001001 (2000/2010)
  vs P1_001N (2020), and an unavailable variable makes the API reject the
  whole request. Worth doing: it would extend the Housing chart from ~2009
  back to 1990.
- **M4, M7, M8, M5 (autocomplete half), L1, L3, L8, L10 hygiene, L12
  Dockerfile.** Real, and larger than a one-liner or touching shared surface.
  See the second audit's triage for the design decision each one turns on.

## Notes for future readers

- **M9 reads as an oversight; it isn't.** See the accept rationale above —
  c6213d5 predates the audit by three months.
- **L12's URL-normalization item cites no file.** The code is
  `config.py:83-89`, duplicated verbatim in `alembic/env.py:36-42`. Both
  copies miss `ssl=True` capitalization.
- **H4 is resolved, but bare excepts are not gone.** The adapters are clean;
  the pattern persists in the caller — `timeline.py:196, 400, 501, 650, 997,
  1000, 1024`, `imagery.py:603`, `preview_renderer.py:103`.
- **Test coverage.** `maybe_refetch_for_backfill` gained two cases via 256ed32
  and two more with the cooldown; its full decision table is still not
  covered.
