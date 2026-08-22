# DEPLOY-SEC-1 — gating Titiler with its access token

Companion to `URGENT.md` / `FINDINGS.md` SEC-1. The code half landed in
Group A of `REMEDIATION-1.md`; this is the ordered operator sequence. Every
step is Ryan's; nothing here was executed by the session.

**Why the order is safe.** With `TITILER_ACCESS_TOKEN` unset the API's
Titiler requests are byte-identical to today (`app/services/titiler.py`,
test `test_titiler_params_unset_is_byte_identical`). With it set, every
Titiler call carries `?access_token=` (test
`test_every_titiler_call_site_sends_the_token`). Titiler ignores an
`access_token` parameter until `TITILER_API_GLOBAL_ACCESS_TOKEN` is set on
its side (titiler 1.2.1 — `APIKeyQuery(name="access_token")` is only
installed when the setting is non-empty). So: API first, then Titiler. The
other order breaks every tile until the API deploy finishes.

**Does `fly secrets set` restart the machine on its own?** Yes. On a
Machines app `fly secrets set NAME=VALUE` stages the secret *and* performs
a release (restarts the machines) unless `--stage` is passed (`fly secrets
set --help`: "--stage  Set secrets but skip deployment for machine apps").
So step 3 is one action — and step 2 must already be green, because step 3
immediately starts rejecting tokenless requests.

`TITILER_API_DISABLE_MOSAIC=TRUE` is already in `fly.titiler.toml` `[env]`
(not a secret — it disables a route set nothing in Plotline uses). It
deploys with the Titiler job in CI the next time that file is pushed; it
does not depend on the token and can go first or together.

## Sequence

```sh
# 0. Generate the token once; keep it in your password manager. Never in a toml.
TOKEN=$(openssl rand -hex 32)

# 1. API carries the token setting. Titiler still ignores it.
#    (CI deploys on push to main; this is the manual equivalent if needed.)
fly secrets set TITILER_ACCESS_TOKEN="$TOKEN" -a log0s-plotline-api
#    Only the API talks to Titiler. The worker never does (grep -rn titiler
#    backend/app/tasks → 0 hits), and the preview renderer runs from
#    scripts/seed_featured.py on the API machine (Makefile `featured`
#    target), so it inherits the API's secret.
#    Wait for the release to finish:
fly status -a log0s-plotline-api
curl -s https://api.plotline.land/api/v1/health | jq .   # sha should be the Group A commit or later

# 2. Verify a tile renders THROUGH THE API with the token being sent but not yet required.
#    Pick any featured snapshot id from https://api.plotline.land/api/v1/featured
SNAP=<a naip or landsat snapshot id>
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' \
  "https://api.plotline.land/api/v1/imagery/$SNAP/tiles/14/4757/6457"
#    expect: 200 image/png   (or 200 with a 68-byte transparent PNG if that z/x/y is outside the scene — pick a tile inside it)

# 3. Titiler starts requiring the token. One action: this restarts plotline-titiler.
fly secrets set TITILER_API_GLOBAL_ACCESS_TOKEN="$TOKEN" -a plotline-titiler
fly status -a plotline-titiler     # wait for the machine to be "started" with the new release

# 4. Verify: the proxied tile still renders, and a direct unauthenticated fetch is refused.
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' \
  "https://api.plotline.land/api/v1/imagery/$SNAP/tiles/14/4757/6457"
#    expect: 200 image/png
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://plotline-titiler.fly.dev/cog/info?url=https://example.com/x.tif"
#    expect: 401 (not 500 — 500 would mean GDAL tried to fetch example.com, i.e. the token is not enforced)
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://plotline-titiler.fly.dev/mosaicjson/info?url=https://example.com/m.json"
#    expect: 404 (route disabled) once fly.titiler.toml's DISABLE_MOSAIC has deployed; 401 before that

# 5. Rollback if step 4 breaks tiles (one command; restarts Titiler; tiles are back tokenless within a minute):
fly secrets unset TITILER_API_GLOBAL_ACCESS_TOKEN -a plotline-titiler
#    The API keeps sending access_token= — harmless, Titiler ignores it again. Nothing else to undo.
```

## Verification after each deploy

- After 1: `/api/v1/health` sha advanced; one tile 200 via the API.
- After 3: one tile 200 via the API; `/cog/info?url=` direct → 401.
- If the API tile 502s after 3 with log line `Titiler returned 401`, the two
  secret values differ — re-run step 1 with the same `$TOKEN` (or step 5).

## Not covered here

Flycast / private addressing (URGENT.md step 3) — deferred with the M9
re-open; the token is the interim and closes the open-fetcher finding on its
own.
