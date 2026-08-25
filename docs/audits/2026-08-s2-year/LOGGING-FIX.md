# The scripts had no log handler, and the O6 damage claim

Written 2026-08-25, after `HEAL-SCORECARD-2.md` §11.1 recorded that the
completion sweep ran 112 admission waits and printed none of them. Two
items: the logging defect (fixed, `b05458b`) and a wording check on O6
(read-only measurement, no writes). Nothing here wrote to production. The
only production access was one `SELECT` over `parcels`/`imagery_snapshots`
via `fly ssh console -C`, and 18 read-only searches against Planetary
Computer's STAC API, paced 2 s apart.

---

## 1. Inventory — every entry point in `scripts/`, before the fix

Ten Python entry points, each with both a `main()` and an
`if __name__ == "__main__"` block. `featured_naip_copy_2026-08-13.sql` is
SQL, not an entry point. **None called `configure_logging()` or anything
else that installs a root handler.**

| Script | Root handler before its first log line? | Emits log records? |
|---|---|---|
| `backfill_census_housing.py` | no | yes — via `app.tasks.timeline._fetch_census` |
| `heal_county_fallback.py` | no | yes — via `app.db` / SQLAlchemy paths |
| `heal_tract_vintage_gaps.py` | no | yes — via `_fetch_census` |
| `remove_uncovered_snapshots.py` | `logging.basicConfig(level=INFO, format="%(message)s")` at `:322` (pre-fix), *after* `parse_targets` | yes — own `logger` (`:51`) plus `app.services.stac` |
| `remove_unverified_reverse_parcels.py` | `logging.basicConfig(...)` at `:188` (pre-fix), *after* `parse_args` | yes — own `logger` (`:45`) |
| `requeue_empty_property.py` | no | yes — the admission wait |
| `requeue_parcels.py` | no | yes — the admission wait, and its own `structlog` logger (`:103`) |
| `revalidate_landsat.py` | no | yes — the admission wait; this is the sweep script |
| `seed.py` | no | **no** — pure `urllib` + `print`, imports nothing from `app` |
| `seed_featured.py` | no | yes — `app.services.preview_renderer` and DB paths |

Two consequences, both observed in the sweep:

1. **Root level.** An unconfigured root logger sits at `WARNING`. Module
   loggers are created at `NOTSET` and inherit it, so `logger.info(...)`
   is dropped at the `isEnabledFor` check — before any handler is
   consulted. All 112 `Waiting for an admission slot` lines died here.
2. **Root handler.** With no handler, `logging.lastResort` emits
   `WARNING`-and-above to **stderr**, as the bare message with every
   `extra={...}` field stripped. That is why the 112 `Admission refused`
   warnings arrived as two words.

The two `basicConfig` calls were the closest thing to a fix in the tree and
were not one: `format="%(message)s"` discards the structured fields, and
both ran mid-`main()`, after work that can already log.

### Is `configure_logging()` safe to call from a script?

Almost. It takes a `Settings` and installs one `StreamHandler(sys.stdout)`
on the root logger; nothing in it assumes an ASGI or Celery process, and
`get_settings()` is what the scripts already call for `api_internal_url`.
The one thing that is wrong for a terminal is the renderer: it selects
`JSONRenderer` whenever `app_env == "production"`, which is exactly the
environment a heal script runs in. An operator watching a sweep would get
machine JSON.

So the shared call is a thin variant rather than a straight reuse.
`configure_logging` gained one keyword-only `renderer` parameter
(`backend/app/logging_config.py:19-21, 39-45`) — its default behaviour is
byte-identical — and `configure_script_logging`
(`backend/app/logging_config.py:77-99`) passes a `ConsoleRenderer` with
`colors=sys.stdout.isatty()`, so a redirected run does not fill a file
with escape codes. It lives in `logging_config.py`, called with no
arguments, so no script carries logging boilerplate.

---

## 2. What changed (`b05458b`)

| File | Change |
|---|---|
| `backend/app/logging_config.py` | `configure_logging(settings, *, renderer=None)`; new `configure_script_logging(settings=None)`. |
| 9 scripts | `configure_script_logging()` as the first statement of `main()`. Module-level import where the file already imports from `app` (7); function-local, matching the file's own convention, in `seed_featured.py` and `remove_unverified_reverse_parcels.py`. |
| `remove_uncovered_snapshots.py`, `remove_unverified_reverse_parcels.py` | `logging.basicConfig(...)` removed — a no-op behind the new call, and its format stripped the fields. |
| `scripts/seed.py:41-47` | A comment, not a call. See below. |
| `backend/tests/test_script_logging.py` | New, 2 tests. |

The `extra={...}` fields on the admission-wait line are untouched;
`ExtraAdder` in the shared processor chain is what carries them into the
rendered output, and it was always there.

### The one script that does not call it

`seed.py` imports nothing from `app` — it drives the API over HTTP with
`urllib` — and its docstring documents `python scripts/seed.py` from the
repo root, where `app/` is not importable. Adding the import to buy
logging for a script that emits no log records would break a working
invocation. The exception and the condition that ends it ("add the call
together with the first `app` import this script ever grows") are a
comment at the site, not only here.

---

## 3. Tests

`backend/tests/test_script_logging.py`. Scripts live outside the backend
package, so it loads them by path with `importlib.util.spec_from_file_location`,
the same fixture shape `test_requeue_parcels.py` uses.

**The assertion is on stdout, not `caplog`.** pytest attaches its own
`LogCaptureHandler` to the root logger for every test, so a caplog-based
assertion passes with the fix deleted — it would be testing pytest's
plumbing. Only the script's real output stream distinguishes a configured
root logger from an unconfigured one.

| Test | What it pins |
|---|---|
| `test_admission_wait_reaches_stdout_with_depth_and_cap` | Runs `requeue_parcels.main()` with `inflight_depth` stubbed to report a full queue, so the real `wait_for_admission_slot` logs its real line. Asserts `Waiting for an admission slot`, `depth`, `30` and `cap` all reach stdout. |
| `test_every_script_entry_point_configures_logging` | Every `scripts/*.py` except the named `seed.py` exception contains the call. A future script that logs into the void fails here. |

**Delete-the-fix, run:** removing `configure_script_logging()` from
`requeue_parcels.main()` fails both tests. The wait line does not merely
lose its fields, it vanishes — observed stdout was
`Re-queuing 1 parcel(s). / queued … / Done — queued 1 timeline request(s), skipped 0.`
and nothing else. Restored, both pass.

**Full suite: 485 passed, 2 failed** (from 483 passing before this batch).
Both failures are the known environmental pair and are untouched here:
`test_health::test_health_survives_missing_build_identity` (`GIT_SHA=dev`
in the dev image) and
`test_workflow_pins::test_every_action_is_pinned_to_a_commit_sha`
(`.github/` is not mounted into the container).

`ruff check` / `ruff format --check` over `app/` and `tests/` pass, and
`mypy app/` reports no issues. `scripts/` is not in `make lint`'s target;
running ruff over it anyway gives the same 5 pre-existing errors and the
same one reformat in `seed_featured.py` at this commit as at `ce89676`,
so this batch added none.

---

## 4. O6 — is the 9-row Sentinel-2 shortfall damage?

`HEAL-SCORECARD-2.md` §3 recorded nine parcels at 11 S2 rows, all missing
2015, and O6 called the fleet total "9 rows of S2 damage". The scorecard
itself flagged the reading as unverified: no 2015 archive query had been
run. This is that query.

**Production state, read 2026-08-25** (`SELECT` only, over
`parcels` ⋈ `imagery_snapshots`): the nine parcels are exactly the nine the
scorecard names, each holds 11 `sentinel2` rows, each holds **zero** rows
dated 2015, and each one's earliest S2 row is 2016.

**Archive query.** For each parcel, `point_to_bbox(lat, lng, buffer_m=1500)`
— production's `search_bbox` (`timeline.py:968`) — against
`sentinel-2-l2a` for `2015-01-01/2015-12-31` at `max_items=20`
(`timeline.py:81`), run twice: once **with the cloud filter removed** and
once with production's own `{"eo:cloud_cover": {"lt": 40}}`. Both results
then pass through `filter_items_containing_point`, the strict
point-containment filter S2 uses (`timeline.py:311`).

| Parcel | Lat / Lon | 2015 rows now | Scenes (no cloud filter) | …containing the point | Earliest | Lowest cloud | Qualifying (< 40 %) | Production search returns | Class |
|---|---|---|---|---|---|---|---|---|---|
| `e4a9bed5` | 38.6948, −121.2515 | 0 | 3 | 3 | 2015-11-17 | 87.3 % | 0 | 0 | **cloud-filtered** |
| `fa12be75` | 39.3698, −121.1051 | 0 | 2 | 2 | 2015-11-17 | 85.2 % | 0 | 0 | **cloud-filtered** |
| `1f0c42aa` | 44.6260, −86.2335 | 0 | 3 | 3 | 2015-08-10 | 46.3 % | 0 | 0 | **cloud-filtered** |
| `eab6adf5` | 45.3999, −122.7567 | 0 | 5 | 5 | 2015-10-04 | 42.7 % | 0 | 0 | **cloud-filtered** |
| `ad00ac68` | 45.4772, −122.6209 | 0 | 5 | 5 | 2015-10-04 | 42.7 % | 0 | 0 | **cloud-filtered** |
| `7fb423de` | 45.4990, −122.6011 | 0 | 5 | 5 | 2015-10-04 | 42.7 % | 0 | 0 | **cloud-filtered** |
| `39286f1d` | 45.5648, −122.6423 | 0 | 5 | 5 | 2015-10-04 | 42.7 % | 0 | 0 | **cloud-filtered** |
| `34efa7ae` | 45.6015, −121.1842 | 0 | 3 | 3 | 2015-12-10 | 76.2 % | 0 | 0 | **cloud-filtered** |
| `177681ef` | 47.4765, −120.3603 | 0 | 9 | 5 | 2015-11-17 | 81.8 % | 0 | 0 | **cloud-filtered** |

**Nine of nine are `cloud-filtered`. Zero `pipeline-missed`, zero
`absent`.** Every parcel has 2015 Sentinel-2 coverage in the archive and
not one scene is below the 40 % threshold — the fleet-wide minimum is
42.7 %, on the four Portland parcels that share the 2015-10-04 acquisition.
Production's own filtered search returns an empty pool for all nine, which
is the same answer arrived at independently.

Three things worth keeping:

* **The scorecard's leading explanation was half right.** It read the
  absence as S2A's 2015 ramp — "a northern-tier western-US footprint
  plausibly has no 2015 scene at all". Scenes do exist; the ramp shows up
  instead as *how few and how late* they are (2 to 9 per parcel, earliest
  2015-08-10, most in Oct–Dec), and that thin, late pool is why none of
  them cleared 40 % cloud. Absence upstream: no. Genuine, not loss: yes.
* **The 20-item cap is not implicated.** The largest unfiltered 2015 pool
  was 9 items against a cap of 20, so no parcel-year here was truncated
  and the ordering question (G8) does not arise for 2015.
* **`177681ef` is the only parcel where point containment did work** — 9
  scenes intersect the bbox, 5 contain the point. Its lowest cloud among
  the containing five is 81.8 %; the four it discards are no better on
  cloud, so the filter costs it nothing here either way.

So the 9-row shortfall is not damage, and O6's wording is corrected in
`STATUS.md` (the scorecard is a frozen record and is not edited). This is
also the first case where **M4's `absent` outcome would have made the whole
check unnecessary**: had the 2015 fetch persisted "searched, nothing
qualified" rather than leaving a hole indistinguishable from a failed
fetch, the row count would have carried its own explanation and no archive
query would have been needed to tell absence from loss.

---

## 5. UNVERIFIED register

* **The fix is committed, not deployed.** `b05458b` is on `main` and has
  not been pushed or deployed as of 2026-08-25. No sweep has yet been run
  with logging connected, so the claim that the 112 waits *would now*
  print is inference from the test, not a production observation. The test
  proves the record reaches stdout with `depth` and `cap`; it does not
  prove what a real sweep's output looks like at volume.
* **Nine of ten entry points were checked by reading them; the tenth
  (`seed.py`) is checked by a test.** The inventory's "emits log records?"
  column is by inspection of each script's imports and call graph, not by
  running each script and observing output. `heal_county_fallback.py` in
  particular may emit nothing in practice — it is included because it
  calls into `app.db`, not because a record was observed.
* **The O6 cloud figures are a single read of PC's STAC API on
  2026-08-25.** PC restates `eo:cloud_cover` from the upstream product
  metadata and can revise a collection; a re-run months later could differ.
  The classification would only change if a scene appeared below 40 %.
* **The archive query reproduces production's search parameters; it is not
  production's code path end to end.** It calls the same
  `search_stac` / `point_to_bbox` / `filter_items_containing_point`
  functions with the same arguments `timeline.py` passes, but it does not
  run `select_sentinel_items` or the validation fallback walk. Since the
  candidate pool is empty for all nine, no selector could have produced a
  row from it — the conclusion does not depend on the part not exercised.
* **`fly ssh console -C` reported one machine per invocation** (`lax`).
  Both reads were `SELECT`s against the shared Postgres, so the machine
  identity does not affect the result.
* **The 2015 row counts come from `extract(year from capture_date)`**, the
  same key `validate_sentinel_selection` groups on since `6489018`. A row
  whose `capture_date` disagrees with its STAC item's datetime would be
  miscounted; no such disagreement was checked for.
