# Git Provenance Analysis — Prompt

*Issued 2026-08. Run in Claude Code plan mode at maximum effort. This is the
extraction whose output underlies every number in the DEVELOPMENT.md analysis
section. Reproduced verbatim.*

---

I'm writing a DEVELOPMENT.md section about how this project's AI-assisted workflow changed over its lifetime. Each commit is stamped with the model that authored it. I need factual extraction from git history — no analysis, no narrative, just the data. Where something is ambiguous or unattributable, say so rather than guessing.

Produce the following:

## 1. Chronology by model
For each distinct model that appears in commit stamps: first commit date, last commit date, total commit count, and a one-line summary of what work happened in that window (derived from commit subjects, not from files changed).

## 2. Bug provenance — the important one
For each of these findings from the second architecture audit, use git log -L / git blame on the cited lines to determine:
  (a) which commit and model introduced the code
  (b) the date it was introduced
  (c) how many subsequent commits touched that same file, and by which models
  (d) whether any subsequent commit modified the specific lines and left the bug intact

Findings to trace:
- H1: missing B25001_001E in _ACS5_VARIABLES (backend/app/services/census.py) and the HousingChart filter (frontend/src/components/demographics/HousingChart.tsx)
- H2: missing ExtraAdder in backend/app/logging_config.py; absent logging setup in backend/app/tasks/celery_app.py
- H3: Cache-Control max-age on backend/app/api/v1/demographics.py — and separately, find the commit that fixed the identical bug in list_imagery, note its date and model, and whether demographics was touched after that fix landed
- H4: bare except Exception handlers in backend/app/services/county_adapters.py
- H5: DIRECTIONALS defined but unused for normalization in backend/app/services/address_normalizer.py
- H6: conflict target in backend/app/services/imagery.py and the direct TimelineRequest insert in scripts/revalidate_landsat.py

Do the same for the first audit's Tier 1 findings (psycopg2-binary, missing lock file, Titiler latest pin, duplicated SOURCE_LABELS, missing Celery timeout, health endpoint Redis client).

## 3. Rework signal
List commits whose subject indicates fixing/reverting prior work (fix:, revert:, or similar). For each, identify which model authored the commit being fixed. Summarize: how often did each model fix its own prior work vs. a different model's?

## 4. Codebase size at each review point
Backend and frontend LOC and file counts at: the commit immediately before the first audit, and the commit immediately before the second audit. Use git checkout or git show against those SHAs — don't estimate.

## 5. Documentation provenance
For SUPPORTED_COUNTIES.md specifically: for each county section, find the commit that added it and the commit that added the corresponding adapter code. Report whether they were the same commit, and by which model. I want to know whether the doc-vs-code drift was born wrong or drifted over time.

## 6. Human vs agent commits
If commits are distinguishable by author or trailer, report the split. If they aren't distinguishable, say so — don't infer from commit message style.

Output as tables where the data is tabular. Flag anything you couldn't determine.
