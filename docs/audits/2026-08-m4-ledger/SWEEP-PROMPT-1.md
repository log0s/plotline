> Sweep prompt, first issue. Written against deploy `ce307e352bfcbf0b81be9f444b4dc25fdecad24e` (the 2026-08-26 00:52Z boot that logged `Running upgrade 0010 -> 0011` and rolled it back). This is the run that stopped at Phase 1 line 2 and produced `GATE-STOP.md`. Never ran the sweep. Recovered from the authoring chat 2026-08-26; not previously in the repo.

---

# M4 ledger — first production sweep, execute and score (EXPLICIT HEAL EXCEPTION)

## Context

Commits `0814d7e` (migration 0011, `TimelineTaskYear`), `ef2d0a2` (recorder, seven loop sites, `ledger_gaps.py`), `8ad20e6` (docs, `PREDICTION.md`, STATUS.md) plus the logging fix `b537953` are deployed at `ce307e352bfcbf0b81be9f444b4dc25fdecad24e`. The ledger starts empty; this is the sweep that populates it for all 184 parcels, and `docs/audits/2026-08-m4-ledger/PREDICTION.md` was written before deploy and is the thing being scored.

**This session runs the sweep**, under the written exception the last two scorecards used, bounded by the gate in phase 1. It is also the first production run of three instruments: the ledger itself, `_classify_empty_chunk`'s re-query, and the admission-wait log line with `depth`/`cap` (`b537953` — inert in its first version, fixed under CI's production-like env, never yet seen in production).

Deliverables: `docs/audits/2026-08-m4-ledger/HEAL-SCORECARD.md` in the established shape, and `docs/audits/2026-08-m4-ledger/BASELINE.txt` — the full `ledger_gaps.py --all` output, which every later sweep diffs against and which cannot be reconstructed afterwards.

## Constraints

- The only prod write is one invocation of `scripts/revalidate_landsat.py`, full fleet. No re-runs, no per-parcel heals, no fixes. Stop and report on anything unexpected.
- All other prod access per `CLAUDE.md`: `fly ssh console -C`, `SELECT` only, `fly logs`. Never a local process against prod.
- No code changes. One commit, model trailer. Do not push.
- Every number states its source and capture coverage. Deviations recorded, not rounded.

## Phase 1 — Gate. Every line must hold.

1. `fly image show -a plotline-worker` and `-a log0s-plotline-api` both report GH_SHA = `ce307e352bfcbf0b81be9f444b4dc25fdecad24e`; `GET /api/v1/health` agrees. Otherwise stop.
2. `alembic_version` on prod reads `0011`. `timeline_task_years` exists, has the expected columns, constraints, and indexes, and holds zero rows. Otherwise stop — a non-empty ledger before the sweep means something already ran.
3. No `timeline_requests` row is `queued` or `processing`.
4. Dry-run: `fly ssh console -a log0s-plotline-api -C "python scripts/revalidate_landsat.py --dry-run"` lists exactly 184 parcels.
5. Record the before-state: per parcel, per source, snapshot row count and `(group, stac_item_id)` set; census rows per parcel per dataset per year. Timestamp it.
6. Start the continuous `fly logs -a plotline-worker` stream to a file, plus the 60 s `--no-tail` polls. Also stream `-a log0s-plotline-api` — the sweep script's own stdout (the wait lines) comes from the API machine, not the worker. Record both start times.

## Phase 2 — Sweep

`python scripts/revalidate_landsat.py --max-wait-minutes 90` inside the API machine, once, with the exit code captured (`; echo "exit=$?"` — the last scorecard could not report it). 184 parcels against a cap of 30 means ~150 admission waits; record each wait's `depth` and `cap` **from the log line**, not reconstructed. Wait for every created request to reach a terminal state by polling the DB. Record start, end, exit code. Non-zero exit or any non-terminal request 45 minutes past the last enqueue: stop waiting, carry into phase 3 as the first anomaly.

## Phase 3 — Scorecard

1. **Capture coverage.** Both streams; gap map; poll reconciliation.
2. **Sweep hygiene.** Parcels reached, tasks by status, exit code, admission waits — count, longest, total, and **whether the `depth`/`cap` fields appeared in the log**. This line is the production verification of `b537953`; a yes or a no, with the first captured line quoted.
3. **Ledger population.** Rows per source fleet-wide and per parcel (min/median/max), scored against `PREDICTION.md`'s per-source expectations. Outcome distribution per source (`ok` / `failed` / `absent` / `suppressed` / `indeterminate`) with reasons.
4. **The falsifier.** Count of served snapshot rows whose `(parcel_id, source, group_key)` has no `ok` ledger row from this sweep. Predicted zero. Any non-zero result is listed row by row — it means a loop was wired wrong, and which one is the finding.
5. **The inverse.** `ok` ledger rows with no served snapshot row. Predicted zero for imagery; for census, reconcile against `census_snapshots`.
6. **`absent` and its reasons.** The nine 2015 S2 parcels from `LOGGING-FIX.md` §2 predicted `absent/all_cloud_filtered` — list them by id with what the ledger says. Count of `_classify_empty_chunk` re-queries fired (from the log), scored against the prediction's budget.
7. **`failed`.** Every `failed` row with source, group, reason. Cross-check against the log: every signing failure, STAC 403/5xx, census timeout in the capture should have a ledger row, and vice versa. Report both directions of the diff.
8. **`indeterminate`.** Count and sites; compare to the sites `REPORT.md` listed.
9. **Topo `*` rows.** How many, and whether the per-decade rows under them match served topo rows.
10. **Snapshot churn.** Rows created/deleted per source from the before-state diff. Expected minimal — the fleet was swept days ago — and open-year only. Any closed-group change is a finding.
11. **Census.** Rows gained per dataset; any parcel whose census year set changed. Racebrook Rd `2f1b332e` specifically: what does the ledger now say about its missing years — this is the parcel M4 was scheduled on.
12. **Baseline.** At the end, after everything is terminal: `fly ssh console -a log0s-plotline-api -C "python scripts/ledger_gaps.py --all"` to `BASELINE.txt`, with the timestamp and SHA in a header line. Also `--outcome failed` and `--outcome indeterminate` as separate files if the flags support it.
13. **Anomalies.** Flag, do not investigate.

## Report

Scorecard sectioned as above, verdict line at the end. STATUS.md: M4 row observed line citing the scorecard and the baseline; G9 first-production-verification line; Racebrook's status under "to investigate" updated to whatever the ledger says. `BASELINE.txt` committed alongside. One commit. Do not push.