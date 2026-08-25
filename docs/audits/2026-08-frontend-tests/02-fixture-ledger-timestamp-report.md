# Item 1 -- the fixture was wrong, and worse than suspected

The status field you asked me to report does not exist. demographics-empty.ts:13-20 contained only parcel_id, tract_fips, snapshots, subtitles, notes -- the demographics endpoint returns no task status. Same for events-empty.ts:12-31. The status was never in a fixture at all: it was typed into the test as a literal, DemographicsPanel.test.tsx:29-30 (censusStatus="complete" propertyStatus="complete").

So your inference was right, by a different route. And the DB settles it -- that parcel's tasks finished:

    census    complete   7 items
    property  complete   9 items

The parcel was never a complete-with-zero case. My capture won a race against a task that went on to find plenty. The test named "complete+zero -> no-records state" was exercising the in-flight branch, exactly as you guessed.

Your prescribed fix doesn't work as written, and this is worth knowing: the Adams parcel's census side is complete, but its demographics payload has 9 snapshots, not zero. Re-pointing the test there wouldn't produce the empty branch at all. Checking further -- no parcel in the DB yields empty demographics with a completed census task (0 of them; the minimum is 3 snapshots). The "No census or property records found for this address." string at DemographicsPanel.tsx:105 appears unreachable for this dataset. Whether it's reachable in prod, I don't know.

Related and separately useful: 8 census tasks show items_found: 0 while their tracts hold snapshots -- for census, items_found counts inserts, not available data. It is not an emptiness signal.

What I did instead: retargeted the M11 test to the banner path, where a real complete-with-zero parcel exists. Adams e032a469 -- 9 snapshots, zero events, property complete at 0 -- payloads and task rows from one run. Then captured a genuinely coherent in-flight triple (request processing, all tasks queued, both payloads empty, all three in one instant) for the third state, which DemographicsPanel.tsx:86-91 does render distinctly. Tests now read status via a statusOf() helper out of a captured timeline fixture rather than typing literals. The one cross-parcel borrow -- the failed status, since no Adams request failed -- is commented at the site.

Revert-and-confirm: 2 of 9 fail against pre-256ed32 code (both "failed source is flagged" tests). The other two hold either way -- correct, and worth stating: pre-fix the panel showed the in-flight message for every empty case, so in-flight is the one state the old code got right by accident.

# Item 2 -- committed

Hashes verified, all three ancestors of HEAD: 1a8bb3c (harness), 7a273fd (fixtures+tests), 256ed32. They match my earlier report.

Ledger commit: b4c3a2b. Added to STATUS.md: the harness note with the blocking condition (L8 test lands or 2026-09-30, whichever first, plus the caveat that blocking constrains nothing while the frontend deploys via Cloudflare Pages outside deploy.yml); a note on the fixture-pairing error and its correction; the intentionally-failing H1 test; the TimelineRequestTask drift, flagged as deliberately unfixed pending your grep-the-shape sweep; and the Recharts trap -- also as a comment at src/test/setup.ts:11-13. Plus the "To investigate" entry below. Full text is in the commit.

# Item 3 -- no code path can produce that row

Every writer of timeline_request_tasks.status/error_message:

| Path | file:line | Sets | started_at | completed_at |
|---|---|---|---|---|
| update_request_task | imagery.py:263-276 | status, items_found, error_message | yes, iff processing | YES, iff terminal |
| _fail_open_tasks (janitor) | imagery.py:441-445 | status, error_message | no | YES |
| Janitor orphan branch | imagery.py:522-526 | status, error_message | no | YES |
| create_request_tasks (raw upsert) | imagery.py:216-228 | status, items_found, error_message | NULLs it | NULLs it |
| update_timeline_request_status | imagery.py:278-291 | request status, error_message | -- | request's, iff terminal |

No bulk update(), no other raw SQL, no data migration touches these tables. TimelineRequestTask has no updated_at column (models/parcels.py:158-199); TimelineRequest.updated_at uses SQLAlchemy-side onupdate, which raw SQL wouldn't fire.

I flagged maybe_refetch_for_backfill and requeue_empty_property.py -- neither updates anything. Both create new requests.

The row: task 39e83483, request 377e9f11, parcel 70a496c7. error_message = "All Denver County property queries failed", built at timeline.py:840 and absent from the tree at 9ea33d9 (the commit 16 minutes after the row's timestamp -- I checked that tree directly). Timestamps 2026-03-26; parent updated_at 2026-05-23. The second failed row (71448f76) is fully self-consistent at 2026-08-03 20:57 -- minutes before 256ed32's commit timestamp, which is normal for code running locally pre-commit. Local worker logs cover only the current container; March logs are long gone.

Verdict: no path produces this combination, because every writer that sets error_message sets completed_at in the same statement. The DB is otherwise consistent with code history -- usgs_topo rows begin 2026-05-22, the exact day that feature landed, and zero tasks complete before their request was created. That argues against systemic timestamp corruption and for a one-off. The likeliest remaining explanation is a manual psql edit during development -- plausibly someone forcing the failed state to eyeball the M11 UI.

This corrects my previous report. I speculated a backfill rewrote status in place without refreshing timestamps. No such path exists; that was wrong.

Item 12 -- janitor exposure: none. _is_stale_inflight (imagery.py:89-95) and the orphan branch (imagery.py:524) both read TimelineRequest.updated_at, which does not advance as tasks progress -- update_request_task writes only the task row. But timeline.py:943 sets the request to processing at run start, so updated_at ~= run start, and _STALE_INFLIGHT (45 min, imagery.py:67) sits above the 35-minute hard limit (time_limit=2100, timeline.py:1104) with 10 minutes of margin. A healthy run cannot age past the threshold. The docstring's "untouched for longer than" is loose phrasing -- it tracks run start, not activity -- but the numbers hold. No fix needed, so I'm not describing one.

One thing outside your three items: scripts/requeue_empty_property.py exists but isn't in CLAUDE.md's file listing.
