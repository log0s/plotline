# Retry/ops batch — scoring sweep

Run 2026-08-27, 18:35:37Z → 19:33:05Z (enqueue), fleet drained 19:44Z.
Scores `PREDICTION.md`, which is not edited. One prod write, under the written
exception in the session prompt, with owner approval at the permission prompt.

Deploy: API and worker both `GH_SHA=7807c4ded325f5152ed78e9da5d08f4ff9446f18`
— the five fix commits (`70437e6`, `8a86fad`, `533bc3b`, `2c3f468`, `6daf621`)
plus the docs commits. `/api/v1/health` agrees, `built 2026-08-27T18:29:57Z`.
`alembic_version` `0012`; the boot log reads
`Migration head check: database=['0012'] scripts=['0012']` — **no migration ran
in this batch**, as expected.

---

## 0. The decidability count, up front

**Zero.** Not one attempt this sweep hit a status the new policy retries.

| client | retried statuses | attempts that hit one | evidence |
|---|---|---:|---|
| SAS signing, `_sas_get` | 429, 500, 502, 503, 504, ConnectError, ReadTimeout, RemoteProtocolError | **0** | `"SAS signing failed; backing off"` ×0; `"retry exceeds wait budget"` ×0 |
| Census API, `_get_with_retry` | ReadTimeout, ConnectError, 500/502/503/504 | **0** | `"Census API request failed; retrying"` ×0 |
| ArcGIS, `query_feature_service` | 429 | **0** | `"ArcGIS rate-limited; backing off"` ×0 |

Corroborated from the ledger, which does not depend on log capture: **zero
`failed` rows written by this sweep**, and zero rows of any outcome carrying
`read_timeout`, `sign_5xx`, `connect_error` or `http_5xx`. Zero error-level
lines in the worker stream, fleet-wide.

**Therefore P-1 is `not exercised`.** It is not confirmed. It stays open and
unmoved until a sweep or user run actually meets a transient upstream failure.
PREDICTION.md §2 wrote that verdict in before the run, and this is it.

**One honest limit on the count.** The worker log capture holds 183
`fetch_imagery_timeline task started` lines against 189 requests in the
database — `fly logs` dropped roughly 3% of the stream. The three counts above
are log-derived and are therefore **lower bounds**. The ledger check is not:
a retry that *exhausted* would have written a `failed` row and none exists. A
retry that *recovered* leaves no database trace at all, so up to six requests'
worth of successful retries could be invisible here. The verdict is unchanged
either way — "not exercised" and "exercised a handful of times, all recovered"
are both short of the evidence P-1 needs.

**The sweep did meet one transient upstream failure**, on the one client this
batch did not widen. See §6, anomaly 1.

---

## 1. Hygiene

| | |
|---|---:|
| exit code | **0** |
| parcels reached | **189 / 189** |
| queued | 189 |
| skipped | 0 |
| unreached | 0 |
| enqueue window | 18:35:37Z → 19:33:05Z (57.5 min) |
| admission refusals | 142 |
| admission wait polls | 672 |
| admission depth/cap | `cap=25 depth=25 hard_cap=30` on **every** line |
| wait budget remaining | 1958 s of 5400 |

Requests by status — **189 `complete`, 0 `partial`, 0 `failed`**. Every one
`origin=heal` with the full scope
`{census,landsat,naip,property,sentinel2,usgs_topo}`.

Tasks by status:

| source | complete | skipped | failed |
|---|---:|---:|---:|
| census | 189 | 0 | 0 |
| landsat | 189 | 0 | 0 |
| naip | 189 | 0 | 0 |
| sentinel2 | 189 | 0 | 0 |
| usgs_topo | 189 | 0 | 0 |
| property | 32 | 157 | 0 |

The 157 property skips are `"Property data not yet available for <X> County"`
— no adapter, which is the correct skip, not a failure.

The heal reserve held for the whole run: `cap=25` on all 814 admission lines,
never reaching the 30 hard cap, so five slots stayed open for the request path
throughout. This is the second measurement of the reserve (heal 3 was the
first) and the first at full fleet scope.

---

## 2. Per-prediction verdicts

| # | prediction | verdict |
|---|---|---|
| **P-1** | `read_timeout` recovery rises above Crawford's 67% | **not exercised** — zero retryable-status attempts (§0) |
| **P-2** | `sign_5xx` still zero, or a small number | **confirmed** — zero |
| **P-3** | census `http_404` unchanged at zero | **confirmed** — zero before, zero after |
| **P-4** | *the falsifier* — zero single-attempt `failed` rows for a retried status | **confirmed** — zero `failed` rows of any kind (§3) |
| **P-5** | `09f35468` landsat 1994 does not heal | **falsified** (§4) |
| **P-6** | NYC `complete:0` moves by 0–4, most likely 0 | **confirmed at 0** (§5) |
| **P-7** | Adams stays `complete:0` | **confirmed**, and Z4's question answered (§5) |
| **P-8** | Denver/DC unchanged; Denver's `failed` does not recur | **confirmed** (§5) |
| **P-9** | Santa Clara untouched | **confirmed** (§5) |

---

## 3. P-4 — the falsifier

**Zero `failed` ledger rows written by this sweep.** No row to inspect, so no
row can carry a single attempt for a retried status. P-4 is confirmed on the
strongest available reading: the batch produced no failure at all, rather than
failures that happened to carry the right attempt counts.

Every ledger row this sweep wrote:

| outcome | reason | rows |
|---|---|---:|
| ok | *(none)* | 14,458 |
| absent | `no_scenes` | 1,892 |
| absent | `api_no_data` | 127 |
| suppressed | `naip_no_point_coverage` | 9 |
| absent | `all_cloud_filtered` | 9 |
| indeterminate | naip item cap | 7 |
| indeterminate | TNM row cap | 2 |

`failed` does not appear. Neither does any `sign_*`, `read_timeout`,
`connect_error` or `http_*` reason.

Because nothing failed, P-4 is confirmed but **not stressed**. It remains the
prediction that can kill the batch, and it has not yet been asked a hard
question.

---

## 4. Crawford `6563dedf`, and P-5

### Crawford's 33 formerly-`failed` groups

All 33 re-attempted, **none re-failed**:

| source | ok | absent/`no_scenes` | failed |
|---|---:|---:|---:|
| landsat 1984–1999 | **16** | 0 | 0 |
| naip 2010–2026 | **6** | 11 | 0 |
| **total** | **22** | **11** | **0** |

**22 / 11 is exactly M3 heal 2's split.** That heal recovered 22 as transient
and confirmed 11 as real absence; this sweep, run independently under new code
a day later, reproduces the same partition group for group. The 11 NAIP
absences are stable, not intermittent — which is what "real absence" was
supposed to mean and had not previously been re-tested.

### P-5 — falsified

`09f35468` landsat 1994, the one `failed` row standing in the whole ledger,
came back **`ok`**. A new snapshot row was written:
`LT05_L2SP_013032_19941028_02_T1`, capture date 1994-10-28.

The prediction was that it would not heal — that it was likely the same shape
as Crawford's 11 real absences. It was not; it was a transient that had
survived one heal and did not survive a second. The guess was recorded so the
outcome could not be read backwards, and the outcome is that the guess was
wrong.

**The ledger now holds zero `failed` rows, fleet-wide.**

This does not rescue P-1. One group healing on a re-run is exactly the
Crawford-era mechanism — a whole second task run — not evidence that in-process
retry did anything. Nothing in the logs shows a retry on this parcel.

---

## 5. Property

189 parcels, one property task each: 32 with an adapter, 157 skipped.

| county | platform | parcels | complete >0 | complete :0 | failed | items |
|---|---|---:|---:|---:|---:|---:|
| Denver | ArcGIS | 11 | 8 | 3 | **0** | 115 |
| District of Columbia | ArcGIS | 7 | 5 | 2 | 0 | 95 |
| New York | Socrata | 6 | 5 | 1 | 0 | 171 |
| Santa Clara | CKAN | 7 | 2 | 5 | 0 | 2 |
| Adams | ArcGIS | 1 | 0 | 1 | 0 | 0 |

Queries run, by client: **ArcGIS 79**, **CKAN 21**, **Socrata 15**. Zero
non-200 responses from any of them. Zero `ArcGISError`, zero `SocrataError`,
zero error-level lines.

- **Socrata 404s (P-6): none.** All 15 Socrata responses were 200. Nine
  returned zero rows, six returned rows (`ipu4-2q9a` 3×100 + 1×82,
  `w2pb-icbu` 123, `usep-8jbt` 11). The three 4x4 ids are live; `2c3f468` is
  insurance against a future retirement, exactly as predicted, and no NYC task
  moved from `complete:0` to failed.
- **ArcGIS 429s (P-8): none.** No retry branch was entered on Denver, DC or
  Adams. Denver's single historical `failed` task did not recur — consistent
  with its cause having been the 2026-08-11 burst.
- **Santa Clara (P-9): untouched.** CKAN returned 200 throughout.

### Adams — Z4's only visible trace, now read

The one Adams parcel ran its one query and the log carries the whole chain:

```
ArcGIS Feature Service query  Building_Permits_Eye_On_Adams/FeatureServer/0
                              where: upper(CombinedAddress) LIKE '12804 %EMERSON%'
ArcGIS response               rows: 0
Property events filtered      raw_count: 0   matched_count: 0
Property history fetch complete  items_saved: 0
```

**`raw_count=0`.** The service answered 200 with zero features. Adams is not a
matcher problem — nothing was returned for the matcher to reject. Of the two
possibilities the STATUS row narrowed to, it is (a): the feature service
returns no features for that WHERE clause.

That is the ten-minute manual check's answer, obtained from the sweep without
touching the portal. What it does not settle is *why* the WHERE clause finds
nothing — a wrong address form, a layer that does not carry this address, or a
parcel with genuinely no permits. The narrowed question survives; it is now
about the clause, not about the pipeline.

---

## 6. Regression

### Imagery

| check | before | after | verdict |
|---|---|---|---|
| landsat rows | 8,126 | 8,127 | +1 — the P-5 heal |
| landsat per parcel | 42×1, 43×188 | **43×189** | conserved at 43 |
| sentinel2 rows | 2,259 | 2,259 | conserved |
| sentinel2 per parcel | 11×9, 12×180 | 11×9, 12×180 | conserved at 12 |
| naip id-md5 | `a0f9d593…0587f` | `a0f9d593…0587f` | **identical** |
| usgs_topo id-md5 | `e30e200f…58892` | `e30e200f…58892` | **identical** |
| sentinel2 id-md5 | `10374d6f…7c63c` | `a968e681…95621` | changed — 7 swaps |
| landsat id-md5 | `a26787f4…31154` | `c436ebc1…681f7` | changed — 2 creates |

**Only 9 imagery rows were created fleet-wide.** Enumerated:

| parcel | source | group | item |
|---|---|---|---|
| `09f35468` | landsat | **1994** | `LT05_L2SP_013032_19941028_02_T1` |
| `134ca8cd` | landsat | 2026 | `LC09_L2SP_013030_20260708_02_T1` |
| `76020cab` | sentinel2 | 2026 | `S2B_MSIL2A_20260212T162309_R040_T16SGC…` |
| `7d3e5258` | sentinel2 | 2026 | `S2B_MSIL2A_20260826T170849_R112_T14RPU…` |
| `6b015022` | sentinel2 | 2026 | `S2B_MSIL2A_20260826T184919_R113_T10SFH…` |
| `079e4f79` | sentinel2 | 2026 | `S2B_MSIL2A_20260826T170849_R112_T14RPU…` |
| `e4a9bed5` | sentinel2 | 2026 | `S2B_MSIL2A_20260826T184919_R113_T10SFH…` |
| `39afc84a` | sentinel2 | 2026 | `S2B_MSIL2A_20260826T170849_R112_T14RPU…` |
| `89488631` | sentinel2 | 2026 | `S2B_MSIL2A_20260826T170849_R112_T14RPU…` |

**Zero closed-group churn.** Eight of the nine are in group **2026**, the open
year, where a swap is the designed behaviour — seven S2 and one landsat, all
net-zero (count unchanged, one row replaced per create). The ninth is
`09f35468` landsat 1994, which is a closed group, and it is not churn: it is
the P-5 heal filling a group that had no row at all. NAIP and topo did not move
a single row by id.

### Census

| check | before | after | verdict |
|---|---|---|---|
| rows created by the sweep | — | **0** | nothing written |
| every dataset/year id-md5 | — | — | **all identical** |
| every dataset/year content-md5 | — | — | **all identical** |
| `decennial` 2010 content (HEAL-3 subset) | `584fa0ed…38d0f` | `584fa0ed…38d0f` | **identical** |
| `decennial` 2020 content (HEAL-3 subset) | `21d3aa8a…1cd6a` | `21d3aa8a…1cd6a` | **identical** |

The census task re-fetched all of `DECENNIAL_YEARS` and `ACS5_YEARS` on all 189
parcels and changed nothing — not one row added, removed or altered in value.

**Y8's interim diff is discharged for this sweep.** The HEAL-3 §5.5 checksums
were recorded over 187 parcels and the fleet is now 189, so the comparison was
made against rows created before heal 3's run window; both reproduce byte for
byte. Y8 (the `updated_at` column) is still owed — this method works only while
someone remembers to restrict by `created_at`, and it cannot detect a
write-then-rewrite-to-the-same-value.

### Request scope and origin

189 of 189 requests carry `origin=heal` and the full six-source `sources`
array. Zero requests with a partial scope. M3's contract held on every request
in the first full-fleet run under it.

### Indeterminate — one new site, a deviation

Expected zero new `indeterminate` sites. Observed **one**:

`e513188c` `usgs_topo` `*` moved **`absent` → `indeterminate`** (TNM row cap).
Fleet-wide `usgs_topo` `indeterminate` went 1 → 2.

This is a deviation from the regression expectation and it is recorded as one.
It is also, on inspection, better data rather than worse: the same run wrote
**nine new `ok` topo decade triples** for that parcel (1880s, 1890s, 1900s,
1930s, 1940s, 1950s, 1960s, 1980s, 1990s) where the ledger previously held a
bare `absent`. TNM answered with rows this time, hit its row cap, and the
ledger said so instead of recording an absence it could not stand behind. The
expectation was written for churn; what happened is a parcel gaining coverage
and an honest truncation marker with it.

`e513188c` is the HEAL-1 parcel. Its NAIP wrong-place card was the M3 heal-1
subject; its topo has now moved too, in a direction nobody predicted either
way.

---

## 7. Ledger transition summary

`BEFORE.txt` and `AFTER.txt` are `scripts/ledger_gaps.py --all`, captured
either side of the run and committed alongside this file. Content is verbatim;
the column padding's trailing whitespace was stripped, which halves the files
and changes nothing a reader or a diff would look at.

| transition | triples |
|---|---:|
| `ok` → `ok` | 14,448 |
| `absent` → `absent` | 2,215 |
| `suppressed` → `suppressed` | 9 |
| `indeterminate` → `indeterminate` | 8 |
| **`failed` → `ok`** | **1** |
| **`absent` → `indeterminate`** | **1** |
| new triples (all `e513188c usgs_topo <decade> ok`) | 9 |
| triples lost | **0** |

Totals: 16,682 → 16,691 triples with a recorded outcome. Stale triples
1,371 → 1,380.

Fleet outcome counts: `ok` 14,448 → 14,458, `absent` 2,216 → 2,215,
`indeterminate` 8 → 9, `suppressed` 9 → 9, **`failed` 1 → 0**.

---

## 8. Request-path overlap — not exercised

**Zero `origin=user` requests were created during the sweep.** No user traffic
arrived in the 69-minute window, so:

- whether a user request is admitted without waiting behind a heal: **not
  observed**. The reserve kept five slots free the whole time, which is the
  mechanism, but nothing arrived to use them. The reserve's effect on user
  traffic remains unmeasured — the same gap heal 3 recorded, unchanged.
- tile 500s / SAS storms (G4's pattern): **none**, because there were zero tile
  requests. The API stream carries 124 lines total, zero 5xx of any kind, and
  two `SAS container token minted` lines both predating the sweep.
- the elapsed-time budget in `_sas_get`: **not exercised.** No signing attempt
  failed anywhere in the run, so no backoff ran and no attempt approached the
  12 s ceiling. There is no longest attempt to quote. The arithmetic in
  PREDICTION.md §4.2 stands untested against production.

Three of this batch's four falsifiers are still waiting for the conditions that
would test them.

---

## 9. Anomalies — flagged, not fixed

1. **A transient upstream failure did occur, on the one client this batch did
   not widen.** One `httpx.ConnectError` reached
   `geocoder.lookup_tract_at_vintage` (`geocoder.py:416`) during the census
   task for tract `36061000900` at 18:55:14Z, became
   `GeocoderUnavailableError`, and was caught by `tasks/timeline.py:1013`,
   which logged `"Vintage tract lookup failed, using stored tract"` at warning
   and carried on with the stored tract. Handled, degraded, no data lost that
   the ledger can see.

   It is worth recording because of what it says about §0: the fleet met
   exactly one transient failure in 69 minutes, and it landed on the vintage
   tract lookup rather than on `CensusFetcher`. N2 widened `CensusFetcher`;
   `lookup_tract_at_vintage` issues a bare `client.get` with no attempt loop.
   The geocoder retries elsewhere (`geocoder.py:30, 139-147`) — this call path
   does not. Filed as a new row in STATUS.md.

2. **Log capture is incomplete.** 183 task-start lines captured against 189
   requests in the database. `fly logs` dropped roughly 3% of the worker
   stream. Every count in this document sourced from the log is a lower bound;
   every count sourced from the database is exact. §0 says where that matters.

3. **Truncation warnings, all pre-existing behaviour:** 3 × Socrata row cap,
   1 × ArcGIS row cap, 1 × STAC item cap, 1 × TNM row cap. The TNM one is the
   `e513188c` `indeterminate` in §6.

---

## 10. Verdict

The batch is deployed, the fleet is swept, and the sweep was quiet.

P-4 confirmed, P-2/P-3/P-6/P-7/P-8/P-9 confirmed, P-5 falsified, **P-1 not
exercised**. One new `indeterminate` site against an expectation of zero, and
it is a parcel gaining data rather than losing it. Zero `failed` rows anywhere
in the ledger for the first time in its life. Zero closed-group churn, zero
census movement, zero request failures, zero task failures.

The thing this sweep does **not** establish is the thing the batch was written
to do. Every retry site shipped in `70437e6`, `8a86fad` and `533bc3b` went
unvisited: no SAS 5xx, no census timeout, no ArcGIS 429. The code paths are
deployed and untested in production. A quiet sweep is not confirmation, and
this document declines to read it as one.
