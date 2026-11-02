# Production probes — for Ryan to run

None of these were run by the session. Each one is read-only against the
public endpoint, anonymous unless stated, and triggers no upstream fetch. The
"expected" columns come from running the **deployed image digests** locally
(`lab/`), so they predict what each outcome means.

Run them in this order. P1 decides how bad SEC-17 and SEC-18 are, and it also
decides whether the M9 accept's precondition holds.

## P1 — Is Titiler's access token set? (gates SEC-17, SEC-18, M9)

```sh
curl -sS -w '\n%{http_code}\n' https://plotline-titiler.fly.dev/healthz
```

| Response | Meaning |
|---|---|
| `401` + `{"detail":"Missing \`access_token\`"}` | `TITILER_API_GLOBAL_ACCESS_TOKEN` is set. In titiler 1.2.1 the token is an app-wide dependency, so it guards `/healthz` too (lab: `lab/probe-out.txt`, "token instance"). SEC-17/18 are MEDIUM, and the M9 accept's precondition holds. |
| `200` + `{"versions":…}` | The token is **not** set. Anyone can make Titiler fetch and decode any `.tif` URL, and every parser in SEC-17/18 is internet-reachable. SEC-1 is still open in production. Finish `DEPLOY-SEC-1.md` steps 1–3 before anything else in this audit. |

## P2 — Does Fly's proxy forward a malformed `Host` to the API? (BadHost, CVE-2026-48710)

```sh
curl -sS -D- -o /dev/null \
  -H 'Host: log0s-plotline-api.fly.dev/api/v1/health?x=' \
  https://log0s-plotline-api.fly.dev/api/v1/featured
```

curl takes SNI from the URL, so Fly can still route the request by SNI.

| Response | Meaning |
|---|---|
| A 4xx with a non-JSON body. The API only ever answers JSON, so this came from Fly's proxy | Fly rejects the header before the app sees it. BadHost is mitigated at the proxy for both apps. |
| `200` (the normal featured list) | Fly forwards the malformed Host. The API is still fine: starlette 1.6.0 is patched (it falls back to the server address, `lab/badhost-starlette-unit.txt`), and the limiter keys on the route template (`lab/badhost-api.txt`: four requests with four different Host values all landed in one bucket). Run P3. |

There is no "patched vs unpatched" difference to observe on the API, because
no API endpoint reflects `request.url`.

*Later (2026-11-02): as written, P2 and P3 negotiate HTTP/2, and Fly resets
the stream (`curl: (92) … PROTOCOL_ERROR`), so they never reach the app. Add
`--http1.1`: with it, Fly forwards the malformed Host to both apps. Results:
`../VERIFY-SEC-17-19.md`.*

## P3 — Does unpatched Starlette in Titiler reflect it? (only if P2 returned 200)

If P1 returned 401, append `&access_token=<the Titiler token>` or `?access_token=…`.
You hold the token; the session never saw it.

```sh
curl -sS -H 'Host: plotline-titiler.fly.dev/badhost-probe?x=' \
  'https://plotline-titiler.fly.dev/tileMatrixSets' | head -c 400
```

| Response | Meaning |
|---|---|
| Links like `http://plotline-titiler.fly.dev/badhost-probe/tileMatrixSets/…` | Unpatched (starlette 0.52.1) behaviour reached production. The local digest returns exactly this (`lab/badhost-titiler-reflect.txt`). Impact is reflection into generated links. It does not bypass the token, which is a query-parameter dependency on every route. |
| Links like `http://plotline-titiler.fly.dev/tileMatrixSets/…` | Fly normalized the header. |
| A Fly proxy 4xx | Same as P2's first row. |

## P4 — Does Fly overwrite a client-sent `Fly-Client-IP`? (the M2 premise, UNVERIFIED since 2026-08-22)

121 cheap requests. A warmup for a snapshot id that doesn't exist does one DB
lookup and returns 204 (`api/v1/imagery.py:668-676`). The limit is 120/min per
IP on that route.

```sh
for i in $(seq 1 121); do
  curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
    -H "Fly-Client-IP: 10.$((RANDOM%250)).$((RANDOM%250)).$((RANDOM%250))" \
    https://log0s-plotline-api.fly.dev/api/v1/imagery/00000000-0000-0000-0000-000000000001/warmup
done | sort | uniq -c
```

| Response | Meaning |
|---|---|
| `120 204` and `1 429` | Fly overwrites the header, so every request counted against your real IP. The M2 accept's premise is verified. Your IP is locked out of `/warmup` for under 60 s. |
| `121 204` | The header is client-controllable. The M2 accept's premise is **false**, and every per-IP limit is bypassable with one header. Reopen M2. |

## P5 — Optional, needs `fly ssh` (yours): is userfaultfd available on the Titiler machine? (SEC-18)

The netCDF driver opens `/vsicurl/` bytes only when it can use userfaultfd.
Docker's default seccomp blocks it locally. A Fly microVM running Titiler as
root probably allows it, but this is unverified.

```sh
fly ssh console -a plotline-titiler -C "python -c 'import ctypes;print(ctypes.CDLL(None).syscall(323, 0))'"
```

| Output | Meaning |
|---|---|
| An integer ≥ 0 (a new fd) | userfaultfd works. The netCDF parser (CVE-2026-49014, GDAL < 3.13.1) is reachable through a `.tif` URL that serves netCDF bytes. |
| `-1` | Not available. Only the HDF5 path from SEC-18 remains. |

## P6 — Secrets per app (names only)

`fly secrets list` was denied to this session. Compare its output against what the
code reads (FINDINGS.md "Checked and clean", step 9):

```sh
for a in log0s-plotline-api plotline-worker plotline-titiler; do echo "== $a"; fly secrets list -a $a; done
```

| App | Should hold | Should NOT hold |
|---|---|---|
| `log0s-plotline-api` | `DATABASE_URL`, `REDIS_URL`, `CENSUS_API_KEY`, `CORS_ORIGINS`, `TITILER_ACCESS_TOKEN` | — |
| `plotline-worker` | `DATABASE_URL`, `REDIS_URL`, `CENSUS_API_KEY`, (`SOCRATA_APP_TOKEN`, optional) | `TITILER_ACCESS_TOKEN` (the worker never calls Titiler), `CORS_ORIGINS` (unused) |
| `plotline-titiler` | `TITILER_API_GLOBAL_ACCESS_TOKEN` only | `DATABASE_URL`, `REDIS_URL`, `CENSUS_API_KEY`, anything else |
