## Verdict

**None of (a), (b), or (c). There is no mechanism, because there is no loss — a net loss of census rows is structurally impossible for this sweep.** The premise also disagrees with the record in both direction and scale.

### 1. The premise contradicts every recorded number

| | Premise | Record |
|---|---|---|
| Direction | net **loss** of 3 | **gain** of 3 |
| Parcels affected | 44 swept | 3 rows across **2** parcels; sweep covered **57** |

`HEAL-SCORECARD.md:220` — "**3 census rows gained across 2 parcels** during the sweep". `docs/audits/2026-08-second-audit/STATUS.md:63` independently repeats it: "Only 3 census rows across 2 parcels were **gained** sweep-wide". `HEAL-SCORECARD.md:49` puts the sweep at 57/57 parcels. "44" appears in no audit document; the local DB is 41 parcels (`FINDINGS.md:102`, confirmed: local `parcels` = 41), production is 57. Nothing in the system is 44.

### 2. `census_snapshots` is append-only — proof, not inference

I enumerated every deletion path in the codebase and every one in the live schema:

- **Application code**: exactly one `DELETE` statement exists in the entire backend — `imagery.py:654`, inside `reconcile_source_snapshots`, hard-scoped to `imagery_snapshots`. The only other delete anywhere is `seed_featured.py:216`, which prunes `featured_locations` rows (no cascade to parcels). **No code deletes a census row, ever.**
- **Schema** (verified live): no triggers, no rules on `census_snapshots`. Its only delete-capable constraint is `census_snapshots_parcel_id_fkey ... ON DELETE CASCADE`. So the *sole* deletion path is deleting a parcel — and nothing in the sweep deletes parcels.
- **`created_at` is immutable**: it is absent from the `ON CONFLICT DO UPDATE SET` list (`demographics.py:85-97`), so it is a true birth timestamp. That is what makes the window arithmetic sound — and it means `current_count − created_in_window = before_count`, always. The count is monotonic by construction.

Local `pg_stat_user_tables` corroborates: `census_snapshots` lifetime ins/upd/del = **326/646/10**, against `parcels` del = **1**. One parcel deleted, ten cascaded census rows — consistent to the row. `imagery_snapshots` shows 257 deletes, because it actually has a delete path.

### 3. The three hypotheses, dispatched

**(a) Transient re-failure — not a loss mechanism.** A year that 404s or times out on re-fetch produces net **zero**, not −1. The pre-existing row is never touched: the upsert only fires when `if data:` passes (`timeline.py:623`, `:650`), and a failure means no statement runs at all. The prior row survives with its original `created_at`. Re-failure is invisible in row counts — which is precisely M4's complaint.

**(b) No unpredicted deletion path exists.** See §2. `reconcile_source_snapshots` is the only reconciliation-like thing in the system and it cannot see census rows.

**(c) The vintage heal cannot drop rows.** The unique key is `(parcel_id, dataset, year)` — `tract_fips` is *not* in it (`0003_census_snapshots.py:69-73`, confirmed live). An ancestor-tract fetch for a year that already exists therefore **overwrites in place**; it can never insert alongside and never removes. The heal is add-or-refresh only, and `heal_tract_vintage_gaps.py` is pure `SELECT` plus a call to `_fetch_census`.

Your step-3 hedge — "a changed `tract_fips` making a row count differently" — is closed twice over: `tract_fips` is not in the unique key, *and* it is not updated on conflict (below).

### 4. What I did find — flagged, since it bears directly on your step 2

**`tract_fips` is omitted from the upsert's `DO UPDATE SET` clause.** `backend/app/services/demographics.py:85-97` refreshes all eleven demographic columns plus `raw_data`, but not `tract_fips`.

Consequence: when `_VintageTracts.tract_for` (`timeline.py:570-597`) resolves a *different* ancestor tract on a re-run, the row's demographic values are replaced with the new tract's data while `tract_fips` keeps the original tract's label. The row silently mislabels its own provenance.

This is a correctness/provenance defect, not a data-loss one — no count changes. But it makes **the diff key you specified blind**: keying on `(dataset, year, tract_fips)` cannot detect a vintage re-resolution, because `tract_fips` never moves once written. Any before/after diff on that key will report "no change" for exactly the case the heal exists to produce. The existing test (`test_census.py:560-574`) passes the same `tract_fips` both times, so the changed-tract case is untested.

Local data shows the heal's footprint: 16 parcels carry two distinct `tract_fips` values across their rows (e.g. `11001006202`/`11001980000`, `08031001600`/`08031001601`) — ancestor/current pairs, written on first insert per year, and frozen there.

### 5. Blocked, and what would close it

`flyctl ssh console` into `log0s-plotline-api` was denied by the permission classifier, so I could not run the prod-side confirmation. Everything above is code + schema + local-DB evidence, which is sufficient for the structural verdict but does not independently re-derive the "3".

If you want the prod number verified, the read-only query is:

```sql
SELECT COUNT(*) FROM census_snapshots
 WHERE created_at BETWEEN '2026-08-12 03:38:30+00' AND '2026-08-12 03:52:17+00';
SELECT n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables
 WHERE relname IN ('census_snapshots','parcels');
```

I expect **3** and a `census_snapshots` `n_tup_del` attributable entirely to parcel cascades. If prod's `n_tup_del` exceeds what parcel deletions can account for, that would overturn §2 and I'd want to see it — but nothing in the code can produce it.

**No M4 occurrence data to report from this**, since the mechanism isn't (a). The M4 occurrence from this sweep remains the one already on the books: `2f1b332e` Racebrook Road, 5 census years, cause unknowable by design.
