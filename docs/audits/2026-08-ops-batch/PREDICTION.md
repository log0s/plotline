# Retry/ops batch — prediction

Written 2026-08-27, **before deploy**, against the ledger baseline below.
Nothing here is edited once the sweep runs; the observed result lands beside
it with a verdict.

Code state: commits `70437e6`, `8a86fad`, `533bc3b`, `2c3f468`, `6daf621` on
`main`, **not pushed and not deployed**. Production API and worker both run
`GH_SHA=5f3aa7d` (`fly image show`, 2026-08-27), which is 12 commits behind
`HEAD` — the five above plus seven docs commits. Every number in this file is
a prediction about the **first full fleet sweep after those five deploy**.

---

## 1. Baseline (production, read-only, 2026-08-27)

`scripts/ledger_gaps.py --outcome failed`, run inside the API machine:

    parcel    source   group  outcome  reason        n  retry  reasons seen
    09f35468  landsat  1994   failed   read_timeout  1  retry  read_timeout

    1 (parcel, source, group) triples with a recorded outcome.
      failed         1
      landsat        failed  1

`--all`, for scale: **16,510** triples with a recorded outcome — 14,302 `ok`,
2,190 `absent`, 8 `indeterminate`, 9 `suppressed`, **1 `failed`**. Plus 1,361
stale triples (never selected).

Every reason ever written to `timeline_task_years`, across all rows and not
only the latest per triple:

| outcome | reason | rows |
|---|---|---|
| ok | *(none)* | 15,578 |
| absent | `no_scenes` | 1,912 |
| absent | `api_no_data` | 532 |
| **failed** | **`read_timeout`** | **34** |
| suppressed | `naip_no_point_coverage` | 10 |
| absent | `all_cloud_filtered` | 9 |
| indeterminate | naip cap | 7 |
| indeterminate | TNM cap | 1 |

**The load-bearing fact: `read_timeout` is the only failure reason the ledger
has ever recorded.** Zero `sign_5xx`, zero `sign_429`, zero `connect_error`,
zero `http_<status>`. 33 of the 34 are Crawford `6563dedf`, of which the M3
heal recovered **22 as transient** and confirmed **11 as real absence**
(`../2026-08-m3/`, heal 2). The 34th is the one row still standing above.

That baseline constrains what this batch can be observed to do, and the
predictions below are shaped around the constraint rather than around what the
fixes are capable of.

---

## 2. Imagery ledger — what the next full sweep should show

**P-1. `read_timeout` re-attempt recovery rises above the Crawford rate.**

> **P-1 scores on three verdicts, not two: confirmed / falsified / not
> exercised.** If the scoring sweep records zero `read_timeout`, `sign_5xx` and
> `http_5xx` *attempts*, P-1 is **not exercised** — P-4 alone is scored for that
> sweep, and P-1 stays open, unmoved, until the first sweep or user run that
> actually meets a transient upstream failure. A quiet sweep is not evidence
> either way and must never be written up as confirmation.

Crawford's 22/33 = **67%** was measured with *no in-process retry at all*:
every recovery came from a whole second task run days later. After `70437e6` a
worker-path timeout is retried up to `pc_signing_attempts` (4) times inside
`SIGN_WAIT_BATCH`, so a fraction of what became a `read_timeout` row never
becomes one. Predicted: of groups that would have recorded `read_timeout`,
**more than 67% end the sweep `ok`**, and the count of new `failed`/`read_timeout`
rows written per sweep falls relative to the Crawford-era rate.

*Confounded, and said so up front:* the fleet currently carries one such row.
A sweep that writes zero new `read_timeout` rows is consistent with the fix
working and equally consistent with PC simply being healthy that hour. P-1 is
only decidable if the sweep produces timeouts at all; if it produces none,
that is the **not exercised** verdict above — not confirmation.

**P-2. `sign_5xx` may appear where nothing appeared before, and that is the fix
working, not a regression.** Before `70437e6` a 503 on the signing endpoint
raised on attempt 1, `_validate_asset` returned the reason, and the walk
re-signed every same-year candidate against the same dead endpoint — so a
signer outage was recordable as `sign_5xx` in principle and never has been.
Predicted: **still zero, or a small number.** A large number means PC's signer
is unhealthy, which is information the ledger could not previously carry.

**P-3. `failed`/`http_404` is unchanged — by design.** The census client does
not retry 4xx (`_RETRYABLE_STATUSES` is 5xx only). There are zero `http_404`
rows today and there should be zero after; if `1990/dec/sf1` re-enters the
fetch set it should record `http_404` once per parcel-year, not three times.

**P-4 — the falsifier. Zero `failed` rows whose `detail` shows a single
attempt for a status the new policy retries.** Concretely: after the sweep, no
`failed` row may carry `sign_5xx`, `read_timeout` or `connect_error` on the
imagery path, or `http_500`/`502`/`503`/`504` on the census path, having been
produced by one upstream call. This is the prediction that can kill the batch:
if such a row appears, either the retry did not run where it was supposed to,
or a call site bypasses the retrying client. It is checkable from the row plus
the worker logs for that request (`"SAS signing failed; backing off"`,
`"Census API request failed; retrying"` — each retry logs).

**P-5. The one standing row, `09f35468` landsat 1994, is not predicted to
heal.** It is a single `read_timeout` that has survived a heal already. It may
be the same shape as Crawford's 11 real absences. Recording the guess so the
outcome is not read backwards.

---

## 3. Property tasks — what changes and what does not

Baseline, `timeline_request_tasks WHERE source='property'` (2026-08-27):

| status | items_found = 0 | tasks |
|---|---|---|
| skipped | yes | 512 |
| complete | no | 87 |
| **complete** | **yes** | **52** |
| failed | yes | 1 |

By adapter county:

| county | platform | complete, >0 | complete, 0 | failed |
|---|---|---|---|---|
| Denver | ArcGIS | 41 | 12 | 1 |
| District of Columbia | ArcGIS | 21 | 12 | 0 |
| New York | **Socrata** | 18 | **4** | 0 |
| Santa Clara | CKAN | 7 | 16 | 0 |
| Adams | ArcGIS | 0 | **8** | 0 |

**P-6. New York County is the only county whose `complete:0` rows can move,
and at most 4 of them can.** `2c3f468` changes exactly one thing: a Socrata
404 raises instead of returning `[]`. `query_socrata` is called by
`NewYorkCountyAdapter` alone. Predicted: **0 to 4** NYC property tasks change
from `complete:0` to a failed sales or permits query. The most likely number is
**0** — a 404 means the 4x4 resource id is dead, and NYC's `w2pb-icbu` /
`usep-8jbt` / `ipu4-2q9a` were live enough to produce 18 non-zero tasks. The
fix is insurance against a future retirement, not a diagnosis of a current one.
A non-zero result means one of the three datasets has already been retired and
the fleet was recording it as "Manhattan has no records".

**P-7. Adams is already distinguished, and this batch does not change it.**
This is the answer the "to investigate" row asked for, and it is available from
the baseline without any code:

- Adams runs **one** query, through `query_feature_service`.
- Before this batch, *every* non-200 from that client — 429 included — already
  raised `ArcGISError`. One query, one failure, `all_queries_failed` true,
  task `failed` (`tasks/timeline.py:1291`).
- All 8 Adams tasks are `complete`. **Therefore no Adams query has ever
  errored.** The portal answered 200.

So Adams's emptiness is *not* a swallowed error, and never was. It is one of:
(a) the feature service returns zero features for that WHERE clause, or (b) it
returns rows the address matcher rejects. The task row cannot tell those apart
— `items_found` counts persisted events, and the raw/matched split is only in
the worker log line `"Property events filtered"`. Predicted: **Adams stays
`complete:0` after this batch.** The remaining ten-minute manual check the row
asks for is still owed, and is now a narrower question: *does the Eye On Adams
service return features for this address at all?*

**P-8. Denver and DC `complete:0` counts are unchanged by the 404 fix and may
fall by at most 1 from the 429 branch.** Neither is Socrata. `533bc3b` only
changes the outcome of a 429 — and a 429 was already terminal, so the branch
converts *failures into successes*, never the reverse. Predicted: Denver's 12
and DC's 12 `complete:0` rows are unchanged, and Denver's single `failed` task
does not recur if its cause was a 429 (unknown; it may have been the
2026-08-11 burst).

**P-9. Santa Clara is untouched.** CKAN never collapsed a status to `[]`.
16 `complete:0` before, 16 after.

---

## 4. What would falsify the batch

In descending severity:

1. **P-4 fires** — a single-attempt `failed` row for a retried status. The
   retry is not where the code says it is.
2. **A request-path tile times out where it did not before.** The elapsed-time
   budget in `_sas_get` is what prevents this; worst case is one attempt's
   10 s timeout plus `SIGN_WAIT_REQUEST`, so ~12 s of signing ahead of the
   Titiler call. A rise in 502s from `/imagery/{id}/tiles/...` after deploy
   falsifies the arithmetic.
3. **A census task hits the Celery soft limit (1800 s).** Worst case is
   ~841 s; a `SoftTimeLimitExceeded` on a census-carrying request means the
   9-request assumption is wrong.
4. **Property tasks start failing in counties other than New York.** Nothing
   in this batch makes an ArcGIS or CKAN query fail that did not already.
