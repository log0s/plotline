# URGENT — written at the stop gate, before the rest of the assessment

**Date:** 2026-08-22. **HEAD / deployed:** `dacbcbf` (API + worker). Titiler
`ghcr.io/developmentseed/titiler:1.2.1` (digest `9cc74708…`).

## The finding (SEC-1 in FINDINGS.md)

`https://plotline-titiler.fly.dev` is the **stock** Titiler image with no
access token, no route disabled and no URL restriction
(`fly.titiler.toml:10-23` sets only GDAL tuning; the image's settings class
— read from the running image, not guessed — has `global_access_token`,
`disable_cog`, `disable_stac`, `disable_mosaic`, all at their defaults).
Its full route set is served publicly (probe-log #12: `/cog/*`, `/stac/*`,
`/mosaicjson/*`, `/api.html`). Every one of those takes an arbitrary `url=`
and hands it to GDAL/vsicurl from inside Plotline's Fly organisation.

That is an unauthenticated open fetcher:

- any host on the internet, with Plotline's egress IP on the request;
- any `.internal` 6PN address of the API or worker apps (IPv6 only — the
  reason internal routing was reverted, but GDAL has no such difficulty);
- any file on the Titiler container (`url=/etc/hostname` is a local path to
  GDAL — `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` restricts only `/vsicurl/`);
- a free COG/STAC/mosaic renderer: `/mosaicjson/tiles/…` fans out to every
  asset a caller-supplied mosaic document lists.

No secret is reachable from the Titiler container (`fly secrets list -a
plotline-titiler` is empty), so the immediate damage is cost, upstream
standing (PC/S3 reads from Plotline's IP) and GDAL driver exposure, not
credential theft. It is at the gate because it is confirmed, public, zero
inside knowledge, and the fix is one environment variable.

## Immediate mitigation (no code deploy for the first step)

1. **Gate Titiler with its built-in token.** Set
   `TITILER_API_GLOBAL_ACCESS_TOKEN=<random>` as a Fly secret on
   `plotline-titiler`. Titiler 1.2.1 then rejects every route without
   `?access_token=<value>` (401; verified in the image: `APIKeyQuery(name=
   "access_token")` applied as an app-level dependency). **This breaks tile
   serving until step 2 ships**, so do both in one window, or set
   `TITILER_API_DISABLE_MOSAIC=TRUE` alone first (harmless today — nothing in
   Plotline uses `/mosaicjson`) and take the token in the next deploy.
2. **Pass the token from the API.** Add `access_token` to the Titiler params
   at the four call sites (`api/imagery.py:484, 556, 647, 667`) and the
   preview renderer (`preview_renderer.py:113-116`), read from a new setting.
   Size S. Titiler→API `/stac` callbacks are unaffected (they go the other
   way).
3. **Alternative or addition:** take Titiler off the public internet —
   `fly ips allocate-v4 --private -a plotline-titiler` (Flycast, IPv4, so
   the c6213d5 IPv6-only problem does not recur), point `TITILER_URL` at
   it, then `fly ips release` the public v4/v6. This also closes the
   Titiler half of M9 without a shared secret. It needs a test that
   Titiler→API still resolves the public API host from the private network.

Nothing to rotate. Continue to FINDINGS.md for the rest.
