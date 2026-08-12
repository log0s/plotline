# Prompt — Landsat 502 investigation (2026-08-12)

Both prompts below are verbatim. This investigation was not commissioned as an
audit; it began as a bug report and became one, which is why the ask is two
messages rather than one brief.

---

## 1. The commissioning report

> Seeing a lot of 502s for Landsat imagery in the Rodanthe featured area. Look
> into that

That is the whole of it. Everything in FINDINGS.md §1–§2 — the parcel, the
tile, the `?cb=1` counterfactual, the cache-layer identification — followed
from that sentence; none of it was specified.

---

## 2. The follow-up brief, after a first pass had produced the fix

Issued once the root cause and the URL-versioning fix were established but
uncommitted. It is the reason §2.1 (cache-layer identification), §3 (the call
site table), §4.1–4.2 (rotation cost) and §5 (the prediction block) exist.

> Follow-up to the Landsat /stac cache-poisoning work (uncommitted: ?v=
> token-expiry versioning, /stac Cache-Control, fly.titiler.toml, 8 tests). The
> root cause and the URL-versioning fix stand. Six items before this commits;
> item 1 changes a file you touched.
>
> 1. RIO_TILER_CACHE_TTL is almost certainly a no-op — verify, then fix the
>    toml. rio-tiler's STAC item cache is a module-level `LRUCache(maxsize=512)`
>    in rio_tiler/io/stac.py — size-bounded, no TTL — and no RIO_TILER_CACHE_TTL
>    env var exists in rio-tiler or titiler. Confirm against the installed
>    version: read the pinned rio_tiler inside the titiler image (or its
>    requirements) and report the exact cache declaration with file:line. If it
>    is the TTL-less LRU, remove the env var from fly.titiler.toml or replace it
>    with a comment naming the real layer — do not ship a config line nothing
>    reads. Note this dissolves the "4-hour entry shouldn't be possible" flag:
>    LRU entries have no expiry; they live until 512-slot eviction or process
>    restart, which is also why production self-cleared after the sweep churned
>    the cache.
> 2. Grep for the shape. Enumerate every site that constructs or consumes the
>    /imagery/{id}/stac indirection and every Titiler call site — tile proxy,
>    warmup_cog, preview_renderer.py, and any frontend-constructed Titiler URL.
>    Produce a table: site, URL form, carries token in URL / carries ?v /
>    neither (and for "neither", why it's safe — e.g. usgs_topo has no expiring
>    credential). preview_renderer is the one the report didn't mention.
> 3. Confirm rotation cost. All Landsat snapshots share one container token, so
>    every /stac cache key rotates at the same instant it expires. Confirm the
>    refetch that follows is one PC container-token round-trip plus local
>    derivations (the 3b7b10e model), not per-band PC signing calls. One line in
>    the report.
> 4. Report as a file, not a paste. Write the full investigation to
>    docs/audits/2026-08-titiler-cache/FINDINGS.md, same shape as the other
>    audit dirs: method, the 04:17Z observation and the ?cb=1 counterfactual,
>    mechanism, fix, the cache-layer identification from (1), and a prediction
>    block for post-deploy scoring — expired-se Titiler 500s cease within one
>    token lifetime of deploy; ?v observed rotating across a token boundary;
>    unfixed prod would re-poison any freshly browsed snapshot within ~1
>    lifetime. Pin the actual token lifetime once — the paste said ~45 min in
>    one place and ~60 in another.
> 5. STATUS.md in the same batch:
>    - G5: cause identified — Titiler's rio-tiler item LRU pinning the token
>      under the constant /stac URL. Same token (se=2026-08-12T00:00:52Z)
>      observed at 03:34 (HEAL-SCORECARD §4.5) and 04:17 (this investigation).
>      Cite the fix commit and the report file. Pending deploy.
>    - G4: note some of its 115 Titiler 500s may be this mechanism rather than
>      rate limiting; attribution testable post-deploy.
>    - New row for this finding in the ops-audit table.
> 6. Tests: confirm the signer/Redis-dead fallback (10-minute wall-clock bucket
>    + warning) has its own test, and run the delete-the-fix check on the
>    two-expiries-two-URLs regression — state what fails when _landsat_stac_url
>    stops appending ?v.
>
> Constraints: do not run scripts/revalidate_landsat.py; do not touch
> production; no deploys — those are mine. Commit with the model trailer when
> 1–6 are done; do not push.
>
> Report back via the commit and FINDINGS.md, not terminal paste: the call-site
> table, the installed-package cache declaration with file:line, test names,
> files changed.

---

## Departures from the brief, and why

Two, both recorded rather than silently absorbed:

1. **Item 5's "same token" is not what was observed.** The brief has
   `se=2026-08-12T00:00:52Z` at both 03:34 and 04:17. The 04:17 capture is
   `se=2026-08-12T00:00:38Z` — a different token, minted 14 s from the other.
   Recorded as a corrigendum in FINDINGS.md §1 and in the G5 row, because the
   distinction is evidence *for* the mechanism: two independent cache entries
   each pinning their own token is what per-URL caching predicts, and a single
   shared stale token is not.
2. **Item 3's confirmation surfaced a new defect.** The warm-token cost is as
   the brief expected (0 PC round-trips for 120 band signings). The cold-token
   path is not: `_container_token` has no single-flight, so the same 120
   signings made 120 round-trips, and a live attempt drew a 429. Filed as G7,
   unfixed — see FINDINGS.md §4.2.
