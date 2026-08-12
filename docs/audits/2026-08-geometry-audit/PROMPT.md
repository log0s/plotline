# Prompt — summary

The prompt that commissioned this investigation was not captured verbatim.
This is a summary, written from the report it produced.

It asked for a read-only measurement of one hypothesis: that the imagery
point filter tested each STAC item's bbox envelope rather than its real
footprint, and so admitted granules that do not cover the parcel. Nothing
was to be changed and nothing re-queued.

The questions put to it:

- **How big is the class?** For every `imagery_snapshots` row, refetch the
  STAC item and compare the bbox test the pipeline ran against a
  point-in-footprint test. Report per source, and separately count items
  carrying no `geometry` field at all.
- **Is it recoverable?** For each failure, re-run the production search and
  ask whether a covering item was in the pool the pipeline already had, and
  at what cloud-cover cost.
- **Which featured locations are affected?** They are the public demo
  surface.
- **Ocean County NJ (`e0cb3db9`), and the requeue ordering.** Whether that
  parcel's sparse Landsat is this defect or the signing incident of
  2026-08-11, and whether its heal should wait for a fix.
- **What is the deletion wave** a post-fix re-run would produce, predicted
  before it runs?
- **Which remedies do the numbers justify**, and which do they refute?

Two limits the report is explicit about, both worth carrying forward:

1. **Ocean NJ was not measured.** The parcel exists only in production, and
   the investigation declined to query production without sign-off. Its
   verdict is structural — the bbox filter cannot delete a year, so the
   missing years are the signing incident — not observational. There is no
   Ocean NJ appendix in `FINDINGS.md`; the run that would have produced one
   was never authorised.
2. **`usgs_topo` is excluded**, not assessed and passed: its rows come from
   the USGS TNM API and have no STAC item to fetch. The denominator is the
   2,897 PC-backed rows.
