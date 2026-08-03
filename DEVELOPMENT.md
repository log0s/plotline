# Developing Plotline

I built this entire application using Claude Code as a way of testing its capabilities when creating full-stack solutions from scratch. The idea was to write as little code myself as possible, relying on the agent to do most or all of the work, and see what the quality of the final product is like. For this particular project I also allowed Claude (specifically Opus 4.6) to design and architect a lot of it with some tweaks of my own, as a way to understand its capabilities.

If you only read one part of this, read the next section: what 110 commits of history say about why bugs survive in agent-written code. The build log below it is the raw material that section is drawn from.

## What I Set Out to Measure, and What I Ended Up Measuring

I started Plotline with a specific question: how far can an AI coding agent get from a human-authored outline? I wrote the architecture, the phase plans, and the constraints. The agent wrote nearly all the code. The interesting part was supposed to be finding the ceiling — where it would stop being able to keep up.

Four and a half months and 110 commits later, I don't think that's the question the project answered. The failures I found at the end weren't the ones I expected, and they weren't about capability.

### What actually kept bugs alive

Two architecture reviews, months apart, found real problems. The obvious explanation is that the second found more because the tooling improved. The commit history says otherwise.

Every High-severity finding in the second review had the same thing in common: **nothing had read those lines since they were written.**

- `logging_config.py` was written in the project's first commit and not touched again for 140 days. Four models worked on this codebase in that window and none of them opened it. Every `extra={...}` field I attached to log calls was silently dropped before reaching the output — the instrumentation existed and produced nothing.
- The Census variable dict that broke the Housing chart sat unmodified for 131 days while seven commits touched the same file.
- The frontend filter that depended on it got relocated into a new component byte-identically — moved without being read.

The clearest example is a pair of twin bugs. One commit introduced the same `Cache-Control: max-age` mistake into two endpoints, the imagery list and the demographics list. Ten weeks later I noticed users weren't seeing late-arriving imagery and fixed it — in one file. The identical bug three files away survived another 72 days, because I fixed the symptom I saw instead of searching for the pattern.

Error handling shows the same thing. One commit narrowed bare `except Exception` handlers across four files and skipped `county_adapters.py`, which has seven of them. Another commit edited `county_adapters.py` in the same period for an unrelated reason and changed no except line. A third edited `health.py` specifically to narrow its bare except — and left in place the per-call Redis client that a later audit flagged.

None of these are capability failures. They're scope failures. Agent-assisted development produces a lot of code that gets reviewed carefully at the moment of writing and then never again, because the review boundary is the diff. The audits worked because they were the first time anything looked at the whole system instead of a change to it.

### The thing that didn't improve

Documentation failed the same way for the whole project, under every model that worked on it — and the history splits cleanly enough to show why.

`SUPPORTED_COUNTIES.md` documented five county integrations. The two sections that shipped in the same commit as their adapter code — Denver and Adams — were accurate. The other three were written three days after their adapters landed, in a separate commit, describing code that already existed on disk. Not one field name in those three sections was correct at the time of writing. DC's section listed `PREMISEADD`, `SALEPRICE`, `SALEDATE`; the adapter had been reading `PROPERTY_ADDRESS`, `LAST_SALE_PRICE`, and `LAST_SALE_DATE` since the day it landed. Those docs didn't drift out of date. They were wrong from the first commit.

Tests had the same failure. The census suite asserted a vacancy-rate calculation using hand-built input the real pipeline could not produce — it validated the formula while the system feeding it was broken. Between the two audits the backend grew by roughly 2,800 lines, 72% of it test code. More tests, aimed at the wrong things.

The common thread: documentation and tests generated from the same description as the code inherit that description's assumptions instead of checking them. Prose written alongside code was right. Prose written about code was wrong. That held regardless of which model wrote it.

### What I can't claim

The obvious version of this section is a capability-improvement story, and the evidence doesn't support one.

The two reviews were run by different model generations, and the second found a class of problem the first missed entirely. But four things changed between them. The second review's prompt was much more aggressive — it asked for adversarial reading, told the model to skip anything done well, and explicitly said not to re-report the first audit's findings. The codebase was larger. The first audit's fixes had already hardened the paths that fail loudly, which is part of why the quiet ones became visible. And my model usage wasn't even chronological — I used a newer model for two days in April, then went back to the previous one for two months.

Four variables, one outcome, n=1. I can't isolate anything from that.

What I can point to is more specific. In June, one model wrote a bare `except Exception` into a county adapter — locally reasonable, since the goal was keeping one county's outage from killing the whole pipeline. In August, the same model ran the review that flagged that exact pattern in that exact file as a high-severity finding, because it converts an API outage into a result indistinguishable from "this parcel has no records."

Same model, same file, two months apart. What changed was what I asked it to do.

That's the finding I'd generalize: **the review stance matters more than the model version.** Writing code to make a feature work and reading code to find where a system lies are different tasks, and the second one doesn't happen unless someone schedules it.

*(Attribution note: this project's commits are inconsistently stamped — about a third carry no model trailer, including some of the remediation work. I know what ran what; the repo doesn't fully record it. That's a process gap I'd close at the start of the next project rather than reconstruct at the end of this one.)*

### What my job turned into

The clearest trend in this project isn't in the code. It's in what I was doing.

In Phase 1, I was the author: architecture, schema, phase plans, the outline everything else grew from. By the middle phases I was the editor — reading output, catching drift, deciding what to keep. By the end I was mostly the adversary: commissioning hostile reviews, arbitrating between them, deciding which findings were real.

That last role turned out to be the one that mattered, and part of it was arguing with the tooling. I was advised to disable the tile server in production to save a few dollars a month, and pushed back — the entire product is zoomable historical imagery. I was advised to switch Redis providers to escape a rate limit, checked, and found the suggested alternative was the same provider underneath. I was handed a CLI command for checking hosting costs that doesn't exist.

None of that required writing code. All of it required knowing the system well enough to notice when a confident answer was wrong.

### What I'd do differently

**Grep for the shape before closing a bug.** A fix isn't done until I've searched the codebase for the same pattern elsewhere. The cache-header twin would have cost thirty seconds to find. It got ten extra weeks instead.

**Derive documentation and tests from the system, not the spec.** Fixtures built from captured real payloads, not idealized ones. Field-name tables generated from — or at least verified against — the parsers that read them.

**Put whole-system reads on the calendar.** Not triggered by a bug. Periodic, adversarial, and aimed at the files nothing has touched in months, because nothing else routes attention there.

**Instrument the silences.** The deepest problem here wasn't any single bug. It was a consistent reflex to turn upstream failure into a smaller success: a county API outage recorded as "complete, 0 records," an unmatched address silently dropped, a partially-failed census marked complete with permanent gaps. Each is defensible alone. Together they meant the system couldn't distinguish "this parcel has no permits" from "the integration has been broken for a month" — and neither could I, because the logging that would have told me was itself silently dropping every field. (The property path was closed after this was written — `256ed32` — which is worth noting mainly because a document arguing for its own correction, and getting it, is the process working.)

## Build Log

> Written phase by phase as the work happened, between March and August 2026.
> Left unrevised. Where a contemporaneous assessment here was later contradicted
> by review — and several were — I've left the original wording and noted the
> correction inline rather than editing the entry.

### Phase 1

*2026-03-16 → 2026-03-17 · Claude Sonnet 4.6 (1 of 3 commits stamped; the other two unstamped)*

Produced a reasonably well-architected back and front end; I did give it fairly specific instructions so that's not surprising. Took ~13 minutes, but that was also with it sometimes waiting for me to approve some commands. Initial thoughts:

* It's very good at following instructions, not necessarily quite as good at following them to their logical conclusion. Example: I gave it the specification "**Error handling** — don't let raw 500s escape. Geocoder down? Return a clear 502 with a message. Bad address? 422 with details." It followed this to the letter, only putting in error returns for a 502 and 422 (but nothing else). Not really surprising, but good to know.
* The original Makefile had some errors in how it was set up, but Claude Code is a surprisingly painless debugger. It sometimes misses the actual issue for something unrelated, but can self-correct. Took about two minutes to diagnose and fix that issue.
* It's good at scaffolding, but not necessarily as amazing at details. Front end had some iffy stuff like empty catch blocks, assuming same base URL for back end, etc. Confirms (to a certain degree) my suspicions that it functions a lot like a junior developer --- eager to help, follows instructions the best it can, but often lacking in some foundational knowledge.
* Thankfully it can debug itself fairly well, given decent instructions/guidance. Able to run basic commands to figure out what's wrong and give its best shot at fixing them.
* README is all over the place, not surprising since I didn't give it very clear instructions for that.

### Phase 2

*2026-03-17 → 2026-03-25 · Claude Sonnet 4.6, Claude Opus 4.6 (1M context) (2 of 6 commits stamped; the other four unstamped)*

Took ~20 minutes to build this phase out completely. Got everything technically built, but this is where it started to struggle a bit more with both correctly hooking everything up together (especially proper URLs) and debugging itself, as well as some strange code choices. Total debugging time was approximately 1.5 hours. I suspect that my bloated CLAUDE.md is an issue, so I plan to trim/rework it after this phase. Definitely the phase where I ended up having to step in and direct debugging efforts the most, as it tended to either put in temporary fixes (missing the core problem entirely) or look in the wrong area.

* Really had a hard time with correctly pointing to the endpoints it made itself.
* Seemed to add a lot of unnecessary code in this step, especially some weird and gratuitous logging in the back end.

  > **Later:** That logging wasn't gratuitous, it was inert — `logging_config.py` shipped in the Phase 1 commit without a `structlog` processor to merge `extra={...}`, so every context field on every log call was dropped before output, for 140 days. Found in the August audit.
* Still very good at certain types of debugging (likely of the well-known issue variety) --- think things like version mismatches, breaking changes in new packages, etc.
* Misses a lot of basic UX stuff (loading indicators, transitions, etc) but I suspect that's more from my lack of direction than anything else. Makes sense to add/address it later anyway.
* Surprisingly good at debugging somewhat complex issues (e.g. found that `extract_cog_url` was pulling in rendered preview PNGs instead of an actual COG, debugged signing expiration issues when hitting external APIs)
* Definitely has the most issues exactly where I expected (GIS/imagery implementation). Not surprising due to it likely having much less training data for that domain. Kept trying to do things like store signed URLs in the DB.

### Phase 3

*2026-03-25 · Claude Opus 4.6 (1M context) (3 of 5 commits stamped; the other two unstamped)*

Took about 20 minutes again to build everything out. Debug took about eight minutes for basic functionality (i.e. things not being completely broken) and another six or so fixing bugs that were introduced, some regressions, etc. Had lots of issues with older data getting saved and not cleaned up after code changes. It did ask once, when addressing a known issue with Landsat 7 imagery having missing sections, but only that one time.

> **Later:** The census work didn't come out of this phase working — the ACS variable dict landed here never requested total housing units, so the Housing chart had nothing to divide by and never rendered, for 131 days across seven commits to the same file. Found in the August audit.

* Started getting some more front-end errors in this one (missing packages, paths off, etc).
* Seems to fairly consistently forget to do things like rebuilding Docker images, but this is probably more an error on my part; planning to make a lot of additions to the global Claude config after this with lessons learned.
* One very common recurring issue is logic around caching; it seems to struggle with knowing what is and is not appropriate to cache, and when to ignore caching even if it is appropriate for some cases/uses. This could also be a configuration thing, but I'm leaning towards it being a general limitation of the tool's capabilities in general, as there's a lot of nuance around this.

  > **Later:** The analysis section reaches the opposite conclusion about this class of problem — the cache bugs that survived weren't capability failures, they were scope failures. This entry is the misdiagnosis it describes.

* Also consistently forgets to clean up after itself (clear out DB, update old implementations stored, etc) with major data changes. Probably worth noting and saving as a global Claude config.
* Related to the above, it frequently misconstrues the actual issue, and tries to patch in fixes for old/missing/misconfigured data instead of just cleaning up.

### Phase 4

*2026-03-25 → 2026-03-26 · Claude Opus 4.6 (1M context) (2 of 4 commits stamped; the other two unstamped)*

Slightly faster this time at only ~16 minutes to build, which makes sense given the tighter scope. Got it mostly right from the jump even with outdated data sources. Took about thirty or so minutes to debug everything, a significant chunk of which was dedicated to finding/updating open data sources. Overall seemed a bit cleaner in this phase, likely as a result of getting the junk out of CLAUDE.md and not polluting context. Speaking of context, this session really showed the power of it; it took ~13 minutes to find a new open data source for Denver, and then barely 3 minutes later to accomplish the same for Adams county.

* Has a tendency to sometimes ignore instructions in order to make tests pass (e.g. changing a TypeScript definition to "any"); hard to say if this is a general tendency or context being overly full without more data, though.
* Actually did a decent job filling in some UX gaps on this one (e.g. loading indicators). Pleasantly surprised.
* Some more basic mistakes, which to be honest I didn't expect --- not closing connections properly after use, blocking cleanup from async calls (not actually doing async), etc.
* Does a good job on thinking through UI data freshness bugs; actually takes the time to follow the logical thread through various issues and find the actual problem. Seems overall much better at this than at semi-equivalent DB issues.
* Can work through some surprisingly complex issues fairly well (e.g. tracking down new open data endpoint for Denver through multiple trails).

### Phase 5

*2026-03-26 → 2026-03-27 · Claude Opus 4.6 (1M context) (10 of 13 commits stamped; the other three unstamped)*

Right around the same time to build as usual at ~22 minutes. Less than ten minutes of debugging to get everything working properly, plus another five or so to pull in some better/more relevant/more fleshed out featured examples. Unsurprisingly, other than the addition of some of the GIS stuff in phase 3 this was the phase that required the most manual intervention; I suspected that the final polish would be the trickiest thing to automate.

* Planning mode is great. Breaks things down into steps on its own, gives reasoning, easy to tweak. Really powerful tool.
* Added a lot of explicit error state handling (especially UI in this one). Handled building them out well once specifically told to do so.
* Noticing more of the tendency to ignore direct instructions at times. Context too full possibly, but at this point it's seeming more and more to be just an inherent property of the system to some extent.
* Makes very basic mistakes (UI infinite redirect due to overlapping/conflicting hooks, not handling URL updates well, etc) but is at least very quick to find/correct them when called out.
* Very useful that it can also do more "research" projects; in this case choosing a new featured spot with better data
* Shockingly smart when given specific directions. Came up with a fairly good caching strategy to speed up tiling that required only minor tweaks.

  > **Later:** The tweaks weren't minor and weren't finished. The same phase's build commit put an identical `Cache-Control: public, max-age=3600` on both the imagery list and the demographics list, which hid late-arriving data behind the browser cache. I fixed the imagery one 58 days later and didn't grep for the twin; the demographics copy survived another 72 days. Found in the August audit.
* Seeing a similar pattern to earlier, where it will often think it has properly fixed the issue (especially if given vague guidance) and have to revisit it several times.
* One outlier - took a *very* long time (and kept getting stuck) trying to do a seemingly simple fix where timeline items were only showing up for featured items. I was getting close to my session limit, so maybe a throttling thing? No obvious reasons for the slowness that I could see in the commands it was running. It did figure it out in the end, but it took almost eighteen minutes and spent a lot of that time seemingly stuck (not consuming tokens, no visible processing going on).
* Random nice bit of UX - it's smart enough to tell which work it did in any specific session and only commit that (within reason, gets confused sometimes if multiple agents running simultaneously are touching similar files).
* Seems to struggle a lot with proper CSS at times and loves to try hacky fixes. To be fair, I was giving it deliberately non-specific instructions to see how it would try and fix things.