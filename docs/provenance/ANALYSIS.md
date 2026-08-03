# Git Provenance Analysis — Results

*Run 2026-08 against 110 commits (HEAD 6def10c at session start; HEAD advanced
to 9ec0285 during analysis). Reconstructed with transmission damage marked.
Several tables came through with broken cells; every figure cited in the
DEVELOPMENT.md analysis section survived intact and is reproduced here.*

## Method & caveats (reviewer's own, verbatim)

- Model attribution comes solely from Co-Authored-By: trailers. 76 of 110 commits are stamped; 34 have no trailer.
- Neither audit is recorded in the repo (no audit doc, no commit references one by name). Audit dates were inferred from the commits that remediate the findings — flagged in §4.
- Claude Opus 4.6 and Claude Opus 4.6 (1M context) are distinct stamps but the same underlying model. Reported separately, with a collapsed view where it changes the conclusion.

## 1. Chronology by model

**Claude Sonnet 4.6** — 2026-03-16 → 03-17, 2 commits (feat ×2). Greenfield foundation only — Phase 1 geocode pipeline, Phase 2 STAC imagery timeline. Zero fixes.

**Claude Opus 4.6 (1M context)** — 2026-03-25 → 04-15, 34 commits (fix 19, feat 12, other 2, chore 1). [reconstructed: The bulk] of Phases 3–5 (Census demographics, property-history events, Polish & Presentation), county adapters for DC/Santa Clara/NYC, address autocomplete, sidebar/compare redesign, featured locations and preview rendering — closing with a dense same-day UI/deploy fix cluster on 2026-04-15.

**Claude Opus 4.7 (1M context)** — 2026-04-20 → 04-21, 9 commits (perf 3, chore 2, test 1, refactor 1, fix 1, other 1). A two-day, explicitly numbered backend remediation program — "Phase 1 correctness → Phase 2 perf → Phase 3 chore → Phase 4a test" — plus React Query state consolidation and a 102-error ruff cleanup.

**Claude Opus 4.6** — 2026-04-21 → 06-16, 29 commits (fix 22, feat 2, refactor 2, perf 1, style 1, test 1). Longest window. Mobile-adaptive layout and USGS historical topo source, tile-502 / event-loop production fixes, then the 2026-05-22→23 hardening block (dependency pinning, schema constraints, runtime safety, mypy/lint/test sweeps), tapering to isolated perf and autocomplete fixes.

**Claude Fable 5** — 2026-06-12 → 08-03, 2 commits (fix 1, docs 1). Two review-driven commits only: second-pass code review remediation, and the SUPPORTED_COUNTIES.md doc/code reconciliation.

**(unstamped)** — 2026-03-16 → 08-03, 34 commits (other 31, fix 2, ci 1). CLAUDE.md and phase prompts, DEVELOPMENT.md journal entries, README/[fragment lost], GitHub CI setup and CI fixes — plus 3 of the 4 commits dated 2026-08-03.

*(Post-analysis note from the project owner: the unstamped August commits were authored by Claude Opus 5 running the remediation; the audit that produced the findings was run by Claude Fable 5. Recorded here because the trailers don't capture it.)*

## 2. Bug provenance

### H1 — missing B25001_001E

**Backend (census.py):** (a) Introduced by 7e5df04 — Claude Opus 4.6 (1M context). (b) 2026-03-25. (c) 7 subsequent commits touched the file before the fix — Opus 4.6 ×4, Opus 4.6 (1M) ×1, Opus 4.7 (1M) ×[cell damaged; total of 7 confirmed]. (d) No. git log -L on the _ACS5_VARIABLES block returns [reconstructed: exactly two commits —] creation and 6def10c (the fix, 2026-08-03). The dict sat unmodified for 131 days.

**Frontend (HousingChart.tsx):** (a) Filter predicate written in 7e5df04 — Claude Opus 4.6 (1M) — [reconstructed: originally inside] DemographicsPanel.tsx. The current file was created by 3d7c414 — Claude Opus 4.6. (b) 2026-03-25 (predicate); 2026-05-23 (current file). (c) 2 total — 3d7c414 (creation), 0fc9207 (Opus 4.6, formatting). (d) [reconstructed: No —] 3d7c414 relocated the filter byte-identically into the new file. Diff of the two versions is nil.

The filter itself is unchanged since 03-25; [reconstructed: the fix addressed] only the backend half.

### H2 — logging

**logging_config.py:** (a) 99d0b0a — Claude Sonnet 4.6. (b) 2026-03-16. (c) 0 subsequent commits before fix. (d) N/A — file untouched for 140 days between creation and 90ea416.

**celery_app.py:** (a) 99d0b0a — Claude Sonnet 4.6. (b) 2026-03-16. (c) 2 — 372aa25 (unstamped, 2026-04-13), 0fc9207 (Opus 4.6, 2026-05-23). (d) Neither added logging setup. 372aa25 added Redis SSL URL handling; 0fc9207 removed a blank line.

logging_config.py is the cleanest signal in the dataset: written once by the first model on the project, [reconstructed: never opened by any of] the four models that followed.

### H3 — Cache-Control: max-age (the twin-bug case)

**demographics.py:** (a) 6205150 — Claude Opus 4.6 (1M context). (b) 2026-03-26. (c) 1 — 0fc9207 (Opus 4.6, formatting only). (d) No. The header line's full history is two commits: 6205150 (added) and 90ea416 (→ no-cache).

**The identical bug in list_imagery:** Fixed by aa8abdb — "fix: prevent browser cache from hiding late-arriving imagery" — 2026-05-23, Claude Opus 4.6. Was demographics touched after that fix? No. demographics.py had zero commits between aa8abdb (2026-05-23) and 90ea416 (2026-08-03) — 72 days.

The sharpest provenance fact in the set: both headers were written by the same commit. 6205150 introduced [reconstructed: the identical header in] demographics.py and in list_imagery. One was diagnosed and fixed; its twin, three files away, went untouched for another ten weeks.

(Not a regression: 86aae50 also changed a max-age in imagery.py, but on the STAC-item endpoint at line 341, not the fixed list_imagery header.)

### H4 — bare except Exception (county_adapters.py)

| Line | Introduced by | Date | Model |
|------|--------------|------|-------|
| 266 | 4544f10 | 2026-03-25 | Claude Opus 4.6 (1M context) |
| 176 | 4c54c3a | 2026-03-26 | Claude Opus 4.6 (1M context) |
| 358, 409, 505, 678 | 2f73500 | 2026-03-27 | Claude Opus 4.6 (1M context) |
| 618 | 86aae50 | 2026-06-12 | Claude Fable 5 |

(c) 8 subsequent commits touched the file after 4544f10: Opus 4.7 (1M) ×3, Opus 4.6 (1M) ×2, Opus 4.6 ×2, Fable 5 ×1.

(d) No commit modified any [reconstructed: of the except lines after they] were written — blame still resolves each to its introducing commit. Two commits explicitly narrowed bare excepts elsewhere and skipped this file: 24cab5b (Opus 4.7, "narrow excepts" — health.py, geocode.py, imagery.py, stac.py) and ed16cff (Opus 4.6, narrowed the Redis health-check catch). [reconstructed: A third commit edited county_ada]pters.py in that same commit — error-message leakage — but changed no except line. And line 618 was added by a review-remediation commit.

### H5 — DIRECTIONALS in address_normalizer.py

(a) Introduced by 4544f10 — Claude Opus 4.6 (1M context). (b) 2026-03-25. (c) 1 subsequent commit — 86aae50 (Fable 5, 2026-06-12). (d) Partially. 86aae50 rewrote normalize_address() (the \b unit-designator regex fix) without adding directional handling; [reconstructed: the DIRECTIONALS set itself is unmodifi]ed since creation.

Precision note: DIRECTIONALS [reconstructed: is not entirely unrefere]nced — it is used once, at line 76 in extract_search_terms(), to skip a directional token when choosing the street-name word for search. [reconstructed: It is never u]sed by normalize_address(), so NORTH↔N is never canonicalized. Both the set and its single use shipped in the same commit.

### H6 — conflict target + direct TimelineRequest insert

**revalidate_landsat.py:** (a) bef2742 — Claude Opus 4.6. (b) 2026-04-23. (c) 0 — the file has exactly one commit in its entire history. (d) N/A.

The script constructs TimelineRequest(parcel_id=…, status="queued") directly (lines 57–60) with no IntegrityError handling. [reconstructed: Later,] 86aae50 (Fable 5) added the partial unique index uq_timeline_requests_parcel_inflight (one in-flight request per parcel) plus the IntegrityError-recovery path in _create_queued_request — and did not update the script. Written before the constraint existed, never revisited after.

**⚠️ imagery.py — could not disambiguate.** Two conflict targets exist, and both match a declared unique constraint, so a target/index mismatch could not be confirmed from the code:

- ON CONFLICT (parcel_id, stac_item_id) — introduced bc4b76d, 2026-03-17, Claude Sonnet 4.6; matching constraint uq_imagery_snapshots_parcel_stac_item, same commit.
- ON CONFLICT (timeline_request_id, source) — introduced 86aae50, 2026-06-12, Claude Fable 5; matching constraint uq_trt_request_source (migration 0010), same commit.

*(The audit meant the first — (parcel_id, stac_item_id) — which is the target that cannot replace a broken scene whose re-selection picks a different stac_item_id.)*

### First audit — Tier 1 findings

| Finding | Introduced by | Date | Model | Fixed by | Fix date / model | Days |
|---------|--------------|------|-------|----------|------------------|------|
| psycopg2-binary | 99d0b0a | 2026-03-16 | Sonnet 4.6 | 430a2a6 | 2026-05-22 / Opus 4.6 | 67 |
| Missing lock file | (absence — pyproject.toml by 99d0b0a with no lock) | 2026-03-16 | n/a | 430a2a6 (adds uv.lock) | 2026-05-22 / Opus 4.6 | 67 |
| Titiler latest pin | 372aa25 (fly.titiler.toml) | 2026-04-13 | (unstamped) | 430a2a6 (→ 1.2.1) | 2026-05-22 [reconstructed: / Opus 4.6] | 39 |
| Duplicated SOURCE_LABELS | 4 copies, accreted (see below) | — | — | 3d7c414 | 2026-05-23 / Opus 4.6 | — |
| Missing Celery timeout | 99d0b0a (timeline.py decorator) | 2026-03-16 | Sonnet 4.6 | bc40127 | 2026-05-23 / Opus 4.6 | 68 |
| Health endpoint Redis client | 99d0b0a (health.py) | 2026-03-16 | Sonnet 4.6 | bc40127 | 2026-05-23 / Opus 4.6 | 68 |

SOURCE_LABELS accreted rather than being born duplicated:

| Copy | Commit | Date | Model |
|------|--------|------|-------|
| MapView.tsx (original) | bc4b76d | 2026-03-17 | Claude Sonnet 4.6 |
| CompareView.tsx | 6205150 | 2026-03-26 | Claude Opus 4.6 (1M context) |
| ParcelInfo.tsx | 055c9ef | 2026-03-27 | Claude Opus 4.6 (1M context) |
| Timeline.tsx | [commit cell damaged] | [date cell damaged] | Claude Opus 4.6 (1M context) |

Four of six Tier 1 findings trace to 99d0b0a, the Phase 1 foundation commit. Intervening near-miss: 24[cab5b — reconstructed] edited health.py specifically to narrow its bare except, and left the per-call Redis client in place.

## 3. Rework signal

51 of 110 commits match fix:/revert:/Fix/Revert. Attribution method: for each, the lines it removed or replaced in its parent were blamed and the model owning the plurality taken. 6 commits were pure additions with no attributable removed lines (0ba2852, 0c3b9eb, 908aab4, f0d491b, bef2742, c1ac879) and are excluded.

By stamp as recorded:

| Fixer stamp | Fixed own | Fixed other | Total | Self-fix % |
|-------------|-----------|-------------|-------|------------|
| Claude Opus 4.6 (1M context) | 10 | 7 | 17 | 59% |
| Claude Opus 4.6 | 2 | 17 | 19 | 11% |
| Claude Opus 4.7 (1M context) | [cells damaged] | | 1 | 0% |
| Claude Fable 5 | 0 | 1 | 1 | 0% |
| (unstamped) | 3 | 4 | 7 | 43% |

Collapsing the 1M-context variants (same underlying model) changes the picture substantially — most of Opus 4.6's "fixed other" was its own earlier 1M-context work:

| Model | Fixed own | Fixed other | Total | Self-fix % |
|-------|-----------|-------------|-------|------------|
| Claude Opus 4.6 | 22 | 14 | 36 | 61% |
| Claude Opus 4.7 | 0 | 1 | 1 | 0% |
| Claude Fable 5 | 0 | 1 | 1 | 0% |
| (unstamped) | 3 | [cell damaged] | | 43% |

Cross-model rework, collapsed: Opus 4.6 → Sonnet 4.6 ×9; Opus 4.6 → Opus 4.7 ×3; Opus 4.7 → Opus 4.6 ×1; Fable 5 → Opus 4.6 ×1; unstamped → Opus 4.6 ×3, → Sonnet 4.6 ×1.

Largest single rework: 86aae50 (Fable 5) replaced 743 lines of Opus 4.6 work.

## 4. Codebase size at each review point

⚠️ Audit dates are inferred, not recorded. First audit → the last commit before the 430a2a6 remediation block; second audit → the last commit before the c296b3a/90ea416/6def10c block. Counts are raw lines from git show at each SHA (blank/comment lines included).

**Before first audit — c1ac879, 2026-05-22:**

| Scope | Files | LOC |
|-------|-------|-----|
| Backend .py total | 61 | 9,999 |
| ├ backend/app | 41 | 6,834 |
| ├ backend/tests | 11 | 2,483 |
| └ backend/alembic | 9 | 682 |
| Frontend .ts/.tsx | 33 | 4,831 |
| ├ .tsx | 20 | 4,002 |
| └ .ts | 13 | 829 |
| scripts/*.py | 3 | 427 |

**Before second audit — 5f5fb42, 2026-07-29:**

| Scope | Files | LOC | Δ |
|-------|-------|-----|---|
| Backend .py total | 66 | [cell damaged — Δ figures below imply ~12,822] | |
| ├ backend/app | 42 | 7,480 | +1 / +646 |
| ├ backend/tests | 13 | [cell damaged — Δ +2,022 per summary line] | |
| └ backend/alembic | 11 | 837 | +2 / +155 |
| Frontend .ts/.tsx | 43 | [cell damaged] | |
| ├ .tsx | 28 | 4,299 | +8 / +297 |
| └ .ts | 15 | 949 | +2 / +120 |
| scripts/*.py | 3 | 427 | 0 / 0 |

Between audits, 72% of backend growth was test code (+2,022 of +2,823).

## 5. Documentation provenance — SUPPORTED_COUNTIES.md

| County section | Doc added | Code added | Same commit? | Model(s) |
|----------------|-----------|------------|--------------|----------|
| Denver | 4544f10 (2026-03-25) | 4544f10 (2026-03-25) | Yes | Opus 4.6 (1M context) |
| Adams | 4544f10 (2026-03-25) | 4544f10 (2026-03-25) | Yes | Opus 4.6 (1M context) |
| District of Columbia | a873772 (2026-03-30) | 2f73500 (2026-03-27) | No — doc 3 days later | code: Opus 4.6 (1M) · doc: (unstamped) |
| Santa Clara / San Jose | a873772 (2026-03-30) | 2f73500 (2026-03-27) | No — doc 3 days later | code: Opus 4.6 (1M) · doc: (unstamped) |
| New York County | a873772 (2026-03-30) | 2f73500 (2026-03-27) | No — doc 3 days later | code: Opus 4.6 (1M) · doc: (unstamped) |

**Born wrong or drifted? Both — and it splits cleanly along that boundary.**

The three sections written after their code (a873772, an unstamped commit whose subject is "Update README, add hero video, add license, fix supported counties docs") were wrong [reconstructed: field-]by-field, against the code that already existed:

| County | Doc claimed (2026-03-30) | Code already did (2026-03-27) |
|--------|--------------------------|-------------------------------|
| DC | PREMISEADD, SALEPRICE, SALEDATE | PROPERTY_ADDRESS, LAST_SALE_PRICE, LAST_SALE_DATE |
| San Jose | ADDRESS, ISSUED_DATE, DESCRIPTION, VALUATION, STATUS | gx_location, ISSUEDATE, WORKDESCRIPTION, PERMITVALUATION, FOLDERNAME |

Not one documented field name for DC or San Jose was correct at the moment of writing.

The two sections shipped in the same commit as their adapter (4544f10) were accurate at birth — Denver's [reconstructed: documented fields (sale_d]ate, sale_price, reception_num, issue_date, [reconstructed: descri]ption, valuation, permit_num) all match what the parser reads, with the single exception of address, used only in the query filter and never read by the parser.

Genuine later drift is [reconstructed: limited: DC's matching pa]ttern was correctly documented as leading-wildcard in 2026-03-30 and only became start-anchored in 86aae50 (2026-06-12); NYC's annualized dataset was added by the same commit. So: the doc was largely born wrong for the counties documented after the fact, and drifted only where a later commit changed behavior. c296b3a (Fable 5) reconciled all of it on 2026-08-03 — 126 days after the doc's own "last verified" stamp of 2026-03-26.

## 6. Human vs agent commits

Not distinguishable. All 110 commits have identical author and committer (the project owner's name and email, 110/110). The Co-Authored-By: trailer is the only signal, and it is one-directional: it marks a model's involvement when present but proves nothing when absent. There is no Generated-with trailer, no Signed-off-by, no distinct email or GPG signature.

| | Commits | Share |
|---|---------|-------|
| Carries a model trailer | 76 | 69% |
| No trailer | 34 | 31% |

The 34 unstamped commits should not be read as human-authored. [reconstructed: Evidence] against that reading: 372aa25 (unstamped) introduced the Titiler latest pin that became a Tier 1 audit finding, and three of the [reconstructed: four commits dated 2026-08-0]3 — including 90ea416 and 6def10c, which remediate H1/H2/H3 and carry detailed multi-paragraph bodies in the same register as the stamped ones — have no trailer, while their sibling c296b3a is stamped Fable 5. Stamping is inconsistent within a single day's work. Per instruction, authorship was not inferred from message style.

Consequence for §2: the [reconstructed: unstamped findings cannot be attri]buted to a model from git alone.
