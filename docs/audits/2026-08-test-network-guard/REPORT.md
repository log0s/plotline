# Test suite network guard — `pytest-socket`

2026-08-26. Closes the STATUS.md finding "a rename can turn a mocked test
into a live one, and the suite has no network guard"
(`docs/audits/2026-08-second-audit/STATUS.md:1041`), logged 2026-08-25 while
wiring the M4 ledger (`docs/audits/2026-08-m4-ledger/REPORT.md:440-447`).

## 1. What was installed

- `pytest-socket>=0.7.0` added to `[project.optional-dependencies].dev` in
  `backend/pyproject.toml`.
- `addopts = "--disable-socket --allow-hosts=127.0.0.1,localhost,::1"` added
  to `[tool.pytest.ini_options]` in the same file.

Allowlist derivation: `docker-compose.yml` points the app containers at
`postgres`/`redis` hostnames, but that's container-to-container DNS — the
test process itself, whether run on a dev machine or in CI, connects to
Postgres via `TEST_POSTGRES_URL`/`DATABASE_URL`, and both resolve to
`localhost:5432` (`.github/workflows/deploy.yml:92`,
`test_migrations_postgres.py:18`). `localhost`/`127.0.0.1`/`::1` covers every
host the suite legitimately dials — no other hostname appears in a test
fixture or `TEST_POSTGRES_URL` default.

## 2. First run with the guard on — failure table

| test | host it tried to reach | cause |
|---|---|---|
| — | — | none. 530 passed, 2 skipped (the 2 skips are `test_migrations_postgres.py` cases gated on `TEST_POSTGRES_URL` being unset — expected, not a guard failure). |

Zero failures, not "nothing to report": the three topo tests the M4 ledger
audit found reaching `tnmaccess.nationalmap.gov` were already fixed in that
same pass (`e6afa9b`-adjacent work) — their patches now target
`topo_service.search_usgs_topo_products`, the function the code actually
calls (`app/tasks/timeline.py:25,759` imports and calls it as
`topo_service.search_usgs_topo_products`). This is a "complete with zero"
result: the guard confirms the earlier fix holds, not that there was nothing
to find.

## 3. Fixes

None needed — see above. No test in the suite requires
`@pytest.mark.enable_socket`; every fixture that touches a real service
(`test_migrations_postgres.py`) does so over `localhost`, already covered by
the allowlist.

## 4. Delete-the-fix

Target: `tests/test_timeline.py::test_fetch_usgs_topo_skips_products_without_source_id`
(line 1211 area), one of the three tests the M4 audit named. Its
`search_usgs_topo_products` patch was temporarily renamed back to the stale
`search_usgs_topo` target (line 1309) to reproduce the exact defect the
guard exists to catch — `select_topo_items` is mocked separately with a
fixed `return_value`, so the live call's actual response is discarded and
the test's assertions still hold, which is exactly how it went unnoticed
before.

**Without `--disable-socket`** (`pytest -o addopts=""`):

```
tests/test_timeline.py::test_fetch_usgs_topo_skips_products_without_source_id PASSED
========================= 1 passed, 1 warning in 1.21s =========================
```

Passed live, hitting the real TNM API.

**With the guard** (default `addopts`):

```
pytest_socket.SocketConnectBlockedError: A test tried to use socket.socket.connect()
with host "2600:9000:24ce:f000:a:dd06:6c00:93a1" (allowed: "127.0.0.1,::1,localhost (127.0.0.1)").
...
FAILED tests/test_timeline.py::test_fetch_usgs_topo_skips_products_without_source_id
======================== 1 failed, 3 warnings in 0.45s =========================
```

Blocked, as intended. The stale patch target was reverted immediately after
(`git diff` on `test_timeline.py` is empty — confirmed post-revert).

## 5. Stale-target sweep

Script (not committed, run ad hoc): walks `tests/*.py`, extracts every
`patch("a.b.c")` / `patch.object("a.b.c")` / `monkeypatch.setattr("a.b.c")`
string target, and resolves it by importing progressively shorter module
prefixes and `getattr`-walking the remainder — the same failure mode as the
topo rename (a real module, stale attribute).

```
72 unique targets checked
all resolved
```

No stale target found. Full list available by re-running the check; omitted
here as it's 72 lines of exact matches.

## 6. CI

Confirmed locally under CI's own env, not just inferred from config:

```
CI=true TEST_POSTGRES_URL=postgresql://plotline:plotline@localhost:5432/plotline \
  pytest -q
...
532 passed, 2 warnings in 9.02s
```

532 (530 + the 2 migration tests that skip without `TEST_POSTGRES_URL`, which
CI always sets). The 3 `test_migrations_postgres.py` tests ran against a real
local Postgres (`docker ps` showed `plotline-postgres-1` listening on
`0.0.0.0:5432`, confirming the allowlist is exercised against a genuine
service, not just permitted in theory). `pytest.ini_options.addopts` is
version-controlled, so the same flags apply in the actual GitHub Actions run;
this wasn't independently re-verified against a live CI log (see UNVERIFIED).

## UNVERIFIED

- CI's actual GitHub Actions collection line ("--disable-socket" in the
  pytest invocation banner) was not pulled from a real Actions run — the
  local reproduction under `CI=true` plus the version-controlled `addopts`
  is the evidence. If a future CI config strips `addopts` on the invocation
  (e.g. `pytest -c /dev/null`), the guard would silently stop applying there.

## Notes for future readers

Every "N passing" reported before this commit — including counts elsewhere
in this audit trail — may include tests that made live network calls their
assertions happened not to notice. This commit is the first point after
which a passing count means what it says.
