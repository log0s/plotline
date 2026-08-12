# Titiler's STAC item cache pins expired SAS tokens

Read-only investigation, 2026-08-12, against running production. No production
state was changed, nothing was re-queued, no deploy was run.

**Fixed in `cf0df2b`** (2026-08-12) — committed, **not deployed** as of
writing. A mitigation that isn't running isn't mitigating; §5 is the
prediction to score once it is.

**The report.** Landsat imagery in the Rodanthe featured area was returning
502s. It is neither of the two 502 mechanisms already on record: not the
signing storm of `a536d07` / `3b7b10e`, and not the post-ingest asset rot that
`scripts/revalidate_landsat.py` exists to heal. Both remedies are inapplicable
here, and running the revalidation script would have churned `stac_item_id`
rows for no benefit.

**Method.** Probed the production API directly (`api.plotline.land`), the
production Titiler (`plotline-titiler.fly.dev`), and Planetary Computer blob
storage, comparing what each returned for the same snapshot. Tile
`14/4757/6457` over the Rodanthe parcel
`cf46ed63-58e0-4308-8bcc-6ebacb225b6e` throughout. Cache-layer identification
was done by reading the pinned `rio_tiler` inside the `titiler:1.2.1` image,
not from documentation. Rotation cost was measured locally against a patched
`_sas_get` — no calls to Planetary Computer.

**Token lifetime, pinned once.** Planetary Computer container tokens
(`sr=c`) are valid for **exactly 45 minutes**. `st` is backdated exactly 24 h
from the mint, so the raw fields read as a ~24 h 45 m span; the usable life is
`se − (st + 24 h)` = 45 m. Verified on three independently observed tokens
(mints at 2026-08-11T23:15:38Z, 2026-08-12T04:15:40Z, 2026-08-12T15:18:50Z).
Any figure other than 45 minutes elsewhere in the record is wrong; this
document supersedes the "~60 min" aside.

---

## 1. The 04:17Z observation

At 2026-08-12T04:17Z, 4 of Rodanthe's 43 Landsat years returned 502 from the
tile proxy, deterministically and repeatedly, in under 1.2 s — fast enough to
rule out a timeout. A repeat sweep ~30 min later returned **5**, a different
set. The failing set drifts; that is itself the signature.

Everything on our side was healthy:

| Check | Result |
|---|---|
| `GET /api/v1/imagery/{id}/stac` | 200, token valid to `se=2026-08-12T05:00:40Z` |
| Same, 20 consecutive calls | byte-identical token — no stale-worker skew |
| `HEAD` on all three signed band hrefs | 200, 200, 200 |

So the assets were fine and the signing was fine. Calling production Titiler
directly with the same STAC callback URL the API uses returned **500**, and
the error body carried a token with `se=2026-08-12T00:00:38Z` — expired 4 h
17 m earlier:

```
'/vsicurl/https://landsateuwest.blob.core.windows.net/landsat-c2/.../
 LT05_L2SP_014035_19841124_20200918_02_T1_SR_B3.TIF?st=2026-08-10T23%3A15%3A38Z
 &se=2026-08-12T00%3A00%3A38Z&...' not recognized as being in a supported file format.
```

That message is GDAL's rendering of a blob 403: with no readable bytes, the
driver probe fails and reports a format error rather than an auth error.

**The `?cb=1` counterfactual.** Appending a meaningless query parameter to the
very same STAC URL returned 200 image/png immediately:

| STAC callback URL | Titiler |
|---|---|
| `…/imagery/4eb53b4e-…/stac` | 500, expired-token format error |
| `…/imagery/4eb53b4e-…/stac?cb=1` | **200 image/png** |
| `…/imagery/4eb53b4e-…/stac?cb=2` | **200 image/png** |

Nothing about the snapshot, its assets, or the signer changed between those
three requests — only the URL string. The stale item is therefore held in a
cache keyed on that string, and the key is the entire lever.

**Corrigendum to a prior observation.** The geometry audit's HEAL-SCORECARD
§4.5 records an expired-token Titiler 500 at 03:34 carrying
`se=2026-08-12T00:00:52Z`. This investigation's 04:17 capture carries
`se=2026-08-12T00:00:38Z`. These are **not the same token** — they are two
tokens minted 14 s apart in the same window, both expiring ~00:00:4xZ. That
distinction strengthens the finding rather than weakening it: two independent
cache entries each pinned their own token, which is what per-URL caching of
per-snapshot items predicts, and what a single shared stale token would not.

---

## 2. Mechanism

Landsat is the only source whose Titiler request URL does not contain the SAS
token.

Landsat's three bands are separate single-band COGs, so the tile proxy cannot
hand Titiler one signed COG URL. It instead points Titiler at an indirection —
`{api_internal_url}/api/v1/imagery/{snap.id}/stac` — which serves the STAC item
with freshly signed band hrefs. That URL was **constant for a given snapshot,
forever**. Every other source embeds the signed blob URL, token and all,
directly in the Titiler request.

Titiler fetches that URL through `rio_tiler.io.stac.fetch`, caches the
resulting item under it, and reuses the item — including the band hrefs and
therefore the token frozen inside them — on every later tile for that
snapshot. Once the pinned token passes its 45-minute expiry, every tile for
that snapshot 502s until the entry is evicted. `_fetch_titiler` converts
Titiler's 500 into our 502 "Titiler upstream error".

`warmup_cog` built the same constant URL and called `/stac/info`, so the
once-per-session warmup was itself a primary poisoning vector: it seeded the
entry that later tile requests reused.

### 2.1 The cache layer, identified

Read from the running image (`ghcr.io/developmentseed/titiler:1.2.1`,
rio-tiler **8.0.5**, titiler.core 1.2.1, Python 3.14.3):

```python
# /usr/local/lib/python3.14/site-packages/rio_tiler/io/stac.py:100-102
@cached(  # type: ignore
    LRUCache(maxsize=512),
    key=lambda filepath, **kargs: hashkey(filepath, json.dumps(kargs)),
)
def fetch(filepath: str, **kwargs: Any) -> dict:
```

Reached from `STACReader.__attrs_post_init__` at `rio_tiler/io/stac.py:255-256`
(`fetch(self.input, **self.fetch_options)`), i.e. once per `/stac/tiles`
request, keyed on the item URL.

Three consequences, all load-bearing:

1. **It is an `LRUCache`, not a `TTLCache`. There is no expiry.** An entry
   lives until 512-slot eviction or process restart. A 4-hour-old entry is not
   an anomaly to be explained — it is the documented behaviour of the
   structure. This dissolves the "a 4 h entry shouldn't be possible under a
   300 s TTL" flag raised in the first pass, which rested on rio-tiler 3.x/4.x
   `CacheSettings`. That class does not exist in 8.0.5: `grep -rl CacheSettings
   rio_tiler/` returns 0 files.
2. **`RIO_TILER_CACHE_TTL` does not exist.** `grep -rn RIO_TILER_CACHE` across
   the entire site-packages tree of the running image returns **0** matches.
   A first-pass draft of this fix added that variable to `fly.titiler.toml`.
   It would have been a config line nothing reads. It was removed before
   commit and replaced with a comment naming the real layer.
3. **It explains why production self-cleared.** The 04:17Z sweep and the
   subsequent `?cb=` probes churned the cache; by 15:5xZ, RiNo measured 0/43
   failing where it had been 16/43. Eviction and process restarts, not repair.
   A clean sweep proves nothing on its own — see the prediction block.

### 2.2 Blast radius at 04:17Z

Not Rodanthe-specific. Same tile geometry, all six featured parcels, 258
Landsat snapshots:

| Location | Landsat years | 502ing |
|---|---|---|
| RiNo Art District | 43 | 16 |
| Rodanthe, Outer Banks | 43 | 5 |
| Stapleton / Central Park | 43 | 2 |
| Hudson Yards | 43 | 1 |
| Green Valley Ranch | 43 | 0 |
| Navy Yard / Capitol Riverfront | 43 | 0 |

---

## 3. Every Titiler call site and `/stac` consumer

Enumerated exhaustively across the backend and frontend. There are five
Titiler call sites, all in the backend; the frontend constructs no Titiler URL
at all — `applyImageryLayer.ts:80,92` build only our own proxy path
(`/api/v1/imagery/{id}/tiles/{z}/{x}/{y}`), so the browser never holds a
credential and nothing there needs versioning.

| # | Site | Titiler endpoint | `url` parameter form | Token in URL? | `?v=`? | Why safe |
|---|---|---|---|---|---|---|
| 1 | `imagery.py:552` `_proxy_landsat_tile` | `/stac/tiles/…` | our `/imagery/{id}/stac` indirection | **no** | **yes** | key rotates with the token it pins — the fix |
| 2 | `imagery.py:635` `warmup_cog` (landsat) | `/stac/info` | same indirection, same builder | **no** | **yes** | byte-identical URL to #1, asserted by test |
| 3 | `imagery.py:485` `_proxy_cog_tile` (naip, sentinel2) | `/cog/tiles/…` | signed blob URL | **yes** | n/a | token is *in* the key; rotates automatically |
| 4 | `imagery.py:655` `warmup_cog` (non-landsat) | `/cog/info` | signed blob URL | **yes** | n/a | same as #3 |
| 5 | `preview_renderer.py:97` `_fetch_tile` | `/cog/bbox/…` | signed blob URL | **yes** | n/a | same as #3; see note below |

Two rows deserve their own sentence, because neither was covered in the first
report:

- **`preview_renderer.py` (#5)** renders the featured-card JPEGs. It signs
  each COG with `SIGN_WAIT_BATCH` and passes the signed URL as `url`, so the
  token is in the key. It is also structurally out of reach of this bug for a
  second, independent reason: it calls `/cog/bbox`, which uses rasterio's
  `Reader`, not `STACReader` — it never touches the item LRU. And it runs
  offline from `seed_featured.py`, behind no request deadline, once per seed.
- **`usgs_topo`** takes route #3 with `sign=False`
  (`imagery.py:590`): its COGs are public USGS S3 objects with no expiring
  credential, so there is nothing for a cache to pin stale. Its URL is
  genuinely constant and genuinely safe.

The distinction that matters: a cache key is safe if it either contains the
credential (#3, #4, #5) or contains no credential because none exists (#5's
`usgs_topo` sibling). Landsat was the sole case of a *constant key naming a
document that contains a rotating credential*, which is precisely the
combination that poisons.

---

## 4. Fix

The URL is the only lever, and it defeats every URL-keyed cache at once —
rio-tiler's LRU, GDAL's `/vsicurl`, and any intermediate HTTP cache — without
depending on which one is responsible.

`_landsat_stac_url()` (`imagery.py:495-524`) appends `?v={container token
expiry}` to the callback URL, so the cache key changes exactly when the token
it pins does, and never otherwise. It is used at **both** call sites #1 and #2;
warmup pointing at a different key than tiles read would prime an entry nothing
consumes and leave the first tile paying the cold fetch anyway.

The expiry comes from `stac_service.container_token_expiry()`
(`stac.py:387-395`), which reads the `se` field off the container token already
cached in Redis under `sas-token:{account}/{container}` — the same key the
callback will read moments later when it signs the bands.

**The helper never raises.** The tile path previously did no signing and so had
no signing failure mode; that property is preserved. A dead signer, dead Redis,
or socket error degrades to a 10-minute wall-clock bucket (`t{epoch//600}`) and
a `"Landsat SAS token expiry unavailable"` warning, and the tile proceeds. The
callback still signs freshly and still 502s honestly if *it* cannot. Computing
a cache key must not become a terminal error for a request that could
otherwise succeed.

Why the real expiry rather than a bare time bucket: the key derives from the
exact thing that expires, so a cached copy provably cannot outlive its token no
matter what any upstream cache's eviction policy is. A bucket only bounds
staleness to `bucket + cache_ttl`, and breaks silently if `_SAS_CACHE_TTL` or
PC's token lifetime changes. The race is one-directional — if the Redis key
expires between computing `v` and the callback signing, the item receives a
*newer*, longer-lived token, never a worse one. `se` is not a secret; only
`sig` is, and that is not in the URL.

Also shipped: `/imagery/{id}/stac` now sends `Cache-Control` bounded by its own
token's remaining life (`private, max-age=…`, capped at 900 s, `no-store` once
expired). It carried no freshness headers at all, which licenses any
intermediate cache to apply heuristic freshness to a document that goes stale
the moment its token does. This is instrumentation of an assumption, not the
remedy — rio-tiler's LRU consults no headers.

### 4.1 Rotation cost

Because every Landsat snapshot shares one container token, every `/stac` cache
key now rotates at the same instant. The refetch that follows is **one PC
container-token round-trip plus local derivations, not per-band signing** — the
`3b7b10e` model holds. Measured against a patched `_sas_get`, 120 band
signings (40 snapshots × 3 bands) on a warm container token made **0** PC
round-trips: each is a Redis `GET` plus a string concatenation.

### 4.2 New, unfixed: no single-flight on a cold container token

The same measurement on a *cold* token made **120** PC round-trips — one per
band signing. `_container_token` has no single-flight, so concurrent misses
each mint their own token. This was observed live: a first attempt at the
measurement, run against the real endpoint, drew an immediate `429` from
`/api/sas/v1/token/landsateuwest/landsat-c2`.

This predates the fix and is a property of `_container_token`, not of the URL
versioning. But the versioning sharpens the simultaneity — a whole timeline's
keys now rotate together — so the two interact. It is bounded, not unbounded:
`PC_SIGNING_CONCURRENCY` (4) caps in-flight calls and `a536d07` retries 429s
with backoff. Recorded as an open item in STATUS.md rather than fixed here;
bundling a concurrency change into a cache-key fix would make both harder to
score.

---

## 5. Prediction, for post-deploy scoring

Written before deploy, per the record rules. Not to be edited afterward — the
observed result goes beside it with a verdict.

The fix (`cf0df2b`) is committed and **not yet deployed** at time of writing.
Deploy and heal execution belong to Ryan.

1. **Expired-`se` Titiler 500s cease within one token lifetime (45 min) of
   deploy.** Specifically: no Titiler 500 whose error body carries an `se`
   earlier than the time of the request. Other 500s (rate limiting, G4) are
   *not* covered by this prediction and may continue.
2. **`?v` observed rotating across a token boundary.** Sampling
   `_landsat_stac_url` output — or the `url` parameter in a Titiler request —
   more than 45 min apart yields two different values, and two samples inside
   one token's life yield the same value. A `?v=t…` form appearing instead
   means the fallback bucket is live and the Redis/signer path needs a look.
3. **Unfixed production would re-poison.** Any freshly browsed Landsat
   snapshot whose item is not currently cached would acquire a pinned token and
   begin 502ing within ~45 min of that first view. This is the control: the
   post-sweep clean reading (RiNo 0/43 at 15:5xZ, down from 16/43) is
   consistent with cache churn, **not** with repair, so a clean sweep taken
   sooner than 45 min after a browse proves nothing. Score item 1 against a
   sweep taken *after* at least one full token lifetime of real traffic.

Scoring note: the drift observed at 04:17Z (4 failing, then 5 half an hour
later, a different set) means single-snapshot spot checks are not evidence
either way. Sweep the full 43 × 6, and sweep twice, ≥45 min apart.

---

## Addendum, 2026-08-12 — provenance correction to §2.1

§2.1 item 1 attributes the first pass's "300 s TTL" memory to a
`CacheSettings` class in **rio-tiler 3.x/4.x**. That attribution is wrong;
the rest of item 1 (rio-tiler 8.0.5 caches STAC items in a `maxsize=512`
`LRUCache` with no expiry, and `grep -rl CacheSettings rio_tiler/` returns 0
files) stands unchanged.

`CacheSettings` has never lived in rio-tiler. Checked the sdists/wheels for
rio-tiler 3.1.6, 4.1.13, 6.7.0, 8.0.5 and 9.4.2: `CacheSettings` appears in
**none** of them. The class is in **`titiler.pgstac.settings`** — read from
`titiler-pgstac` 3.1.0:

```python
class CacheSettings(BaseSettings):
    ttl: int = 300       # TTL of the cache in seconds
    maxsize: int = 512   # Maximum size of the LRU cache
    disable: bool = False
    model_config = SettingsConfigDict(env_prefix="TITILER_PGSTAC_CACHE_", ...)
```

So the 300 s default is real, and so are the `TITILER_PGSTAC_CACHE_TTL` /
`_MAXSIZE` / `_DISABLE` knobs — but they belong to a package **this
deployment does not run**. We run `ghcr.io/developmentseed/titiler:1.2.1`
(titiler.core), not titiler-pgstac. This is the likely source of the
first-pass memory, and it is the second config knob in this investigation
that would have been a line nothing reads (see item 2 on
`RIO_TILER_CACHE_TTL`).

The operational conclusion is unaffected: no environment variable available
to this deployment bounds the STAC item cache.
