# Developing Plotline

I built this entire application using Claude Code as a way of testing its capabilities when creating full-stack solutions from scratch. The idea was to write as little code myself as possible, relying on the agent to do most or all of the work, and see what the quality of the final product is like. For this particular project I also allowed Claude (specifically Opus 4.6) to design and architect a lot of it with some tweaks of my own, as a way to understand its capabilities.

If you only have time for one section, the next one is probably the most useful; it's what I pulled out of the first 110 commits of history about why bugs stuck around in agent-written code. The build log further down is the raw material I drew that from, written phase by phase as I went.

## What I Set Out to Measure, and What I Ended Up Measuring

I started Plotline with a pretty specific question in mind: how far can an AI coding agent get from a human-authored outline? I wrote the architecture, the phase plans, and the constraints, and the agent wrote nearly all of the code. I figured the interesting part would be finding the ceiling, i.e. the point where it stopped being able to keep up.

Four and a half months and 110 commits later, I don't really think that's the question the project ended up answering. (The numbers throughout this section are as of the August 3 audit, when this was written; the repo has kept moving since then and I'm not planning on keeping them current.) The failures I found at the end weren't the ones I expected, and honestly they weren't really about capability at all. The audit prompts and findings are in [docs/audits/](docs/audits/), and the git analysis behind every number below is in [docs/provenance/](docs/provenance/). One caveat there: the findings documents are reconstructions with the damaged passages marked, since the originals were never preserved.

### What actually kept bugs alive

Two architecture reviews, months apart, both found real problems. The obvious explanation for the second one finding more is that the tooling got better, but the commit history doesn't really support that.

Every High-severity finding in the second review had one thing in common: **none of those lines had been read by anything since the day they were written.**

- `logging_config.py` was written in the Phase 1 foundation commit and then not touched again for 140 days. Five different models worked on this codebase in that window and none of them opened it. Every `extra={...}` field I attached to log calls was being silently dropped before it ever reached the output, so the instrumentation existed but produced nothing.
- The Census variable dict that broke the Housing chart sat unmodified for 131 days while seven other commits touched the same file.
- The frontend filter that depended on it got relocated into a new component byte-identically; moved without ever being read.

The clearest example is probably a pair of twin bugs. One commit introduced the same `Cache-Control: max-age` mistake into two endpoints, the imagery list and the demographics list. Eight weeks later I noticed users weren't seeing late-arriving imagery and fixed it, but only in the one file. The identical bug three files away survived for another 72 days because I fixed the symptom I happened to see instead of searching for the pattern.

Error handling shows pretty much the same thing. One commit narrowed bare `except Exception` handlers across five files and skipped `county_adapters.py`, which has seven of them. That same commit narrowed `health.py`'s specifically and still left in place the per-call Redis client that a later audit flagged. Another commit edited `county_adapters.py` in the same period for an unrelated reason and didn't change a single except line. A later cleanup sweep narrowed one more of the same catches in `db.py` and edited `county_adapters.py` in the same commit, and again changed no except lines there.

I don't think any of these are capability failures; they're scope failures. Agent-assisted development produces a ton of code that gets reviewed carefully at the moment of writing and then never again, because the review boundary is the diff. I feel like the audits worked mainly because they were the first time anything had looked at the whole system instead of at a change to it.

### The thing that didn't improve

Documentation failed the same way for the entire project, under every model that worked on it, and the history splits cleanly enough to show why (I think).

`SUPPORTED_COUNTIES.md` documented five county integrations. The two sections that shipped in the same commit as their adapter code (Denver and Adams) were accurate. The other three were written three days after their adapters landed, in a separate commit, describing code that already existed on disk. In two of those three sections (DC and San Jose) not one field name was correct at the time of writing; New York's listed fields were right, although incomplete. DC's section listed `PREMISEADD`, `SALEPRICE`, and `SALEDATE`, while the adapter had been reading `PROPERTY_ADDRESS`, `LAST_SALE_PRICE`, and `LAST_SALE_DATE` since the day it landed. So those docs didn't drift out of date over time, they were just wrong from the very first commit.

Tests had basically the same failure. The census suite asserted a vacancy-rate calculation using hand-built input that the real pipeline couldn't actually produce, so it validated the formula while the system feeding it was broken. Between the two audits the backend grew by roughly 2,800 lines, 72% of it test code, and a good chunk of that was more tests aimed at the wrong things.

The common thread as far as I can tell is that documentation and tests generated from the same description as the code inherit that description's assumptions instead of checking them. Prose that was written alongside the code was generally right, prose written after the fact about the code was generally wrong, and that held regardless of which model wrote it.

### What I can't claim

The obvious version of this section would be a capability-improvement story, and the evidence honestly doesn't support one.

The two reviews were run by different model generations, and the second one found a class of problem the first missed entirely. But four things changed between them. The second review's prompt was much more aggressive; it asked for adversarial reading, told the model to skip anything done well, and explicitly said not to re-report the first audit's findings. The codebase was larger. The first audit's fixes had already hardened the paths that fail loudly, which is probably part of why the quiet ones became visible. And my model usage wasn't even chronological, since I used a newer model for two days in April and then went back to the previous one for two months.

Four variables, one outcome, and n=1. I can't really isolate anything from that.

What I can point to is a bit more specific. In June, one model wrote a bare `except Exception` into a county adapter, which was locally reasonable since the goal was keeping one county's outage from killing the whole pipeline. In August, that same model ran the review that flagged that exact pattern in that exact file as a high-severity finding, because it converts an API outage into a result that's indistinguishable from "this parcel has no records."

Same model, same file, two months apart, and the only thing that changed was what I asked it to do. If there's one thing I'd generalize from this project it's that **the review stance seems to matter a lot more than the model version.** Writing code to make a feature work and reading code to find where a system is lying to you are pretty different tasks, and the second one just doesn't happen unless someone actually schedules it.

*(Attribution note: this project's commits are inconsistently stamped; as of the audit about a third carried no model trailer. Going back through them later, most of those are pretty clearly my own hand edits (phase prompts, dev log tweaks, cleaning up CLAUDE.md, that kind of thing), but a handful are agent work where the trailer just got dropped, including two of the remediation fixes from the audit itself. Stamping only got consistent from around mid-August on. I know what ran what, but the repo doesn't fully record it. That's a process gap I'd rather close at the start of the next project than try to reconstruct at the end of this one.)*

### What my job turned into

Honestly the biggest change over the course of the project was probably in what I was actually doing day to day rather than anything in the code. Early on I was writing the architecture, schema, and phase plans (basically the outline everything else grew from). By the middle phases I'd shifted to mostly reading output, catching drift, and deciding what to keep. By the end a good chunk of my time was spent commissioning hostile reviews, arbitrating between them, and figuring out which findings were actually real.

That last role turned out to be the one that mattered most, and a decent amount of it was just arguing with the tooling. I was advised to disable the tile server in production to save a few dollars a month and pushed back, since the entire product is zoomable historical imagery. I was advised to switch Redis providers to escape a rate limit, checked, and found that the suggested alternative was the same provider underneath. I was handed a CLI command for checking hosting costs that doesn't exist.

I didn't write any code for any of that, but I did need to know the system well enough to notice when a confident-sounding answer was wrong.

### What I'd do differently

* Grep for the shape of a bug before closing it. I don't consider a fix done anymore until I've searched the codebase for the same pattern elsewhere. The cache-header twin would have taken about thirty seconds to find and instead it got an extra ten weeks.
* Derive documentation and tests from the actual system rather than the spec. Fixtures built from captured real payloads instead of idealized ones, and field-name tables generated from (or at the very least verified against) the parsers that actually read them.
* Put whole-system reads on the calendar rather than waiting for a bug to trigger them. Periodic, adversarial, and specifically aimed at the files nothing has touched in months, because as far as I can tell nothing else routes attention there.
* Instrument the silences. The deepest problem here wasn't really any single bug so much as a consistent reflex to turn upstream failure into a smaller success: a county API outage recorded as "complete, 0 records," an unmatched address silently dropped, a partially-failed census marked complete with permanent gaps. Each of those is defensible on its own. Together they meant the system couldn't tell the difference between "this parcel has no permits" and "the integration has been broken for a month," and honestly neither could I, because the logging that would have told me was itself silently dropping every field. (The property path was closed after this was written, in `256ed32`, which I mostly note because a document arguing for its own correction and then actually getting it feels like the process working.)

## Build Log

> Written phase by phase as the work happened, between March and August 2026.
> Left unrevised. Where something I wrote at the time was later contradicted by
> a review (and several were), I've left the original wording alone and added a
> note inline rather than editing the entry.

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

  > **Later:** That logging turned out to be inert rather than gratuitous. `logging_config.py` shipped in the Phase 1 commit without a `structlog` processor to merge `extra={...}`, so every context field on every log call was being dropped before output, and that went on for 140 days. Found in the August audit ([H2](docs/audits/2026-08-second-audit/FINDINGS.md)).
* Still very good at certain types of debugging (likely of the well-known issue variety) --- think things like version mismatches, breaking changes in new packages, etc.
* Misses a lot of basic UX stuff (loading indicators, transitions, etc) but I suspect that's more from my lack of direction than anything else. Makes sense to add/address it later anyway.
* Surprisingly good at debugging somewhat complex issues (e.g. found that `extract_cog_url` was pulling in rendered preview PNGs instead of an actual COG, debugged signing expiration issues when hitting external APIs)
* Definitely has the most issues exactly where I expected (GIS/imagery implementation). Not surprising due to it likely having much less training data for that domain. Kept trying to do things like store signed URLs in the DB.

### Phase 3

*2026-03-25 · Claude Opus 4.6 (1M context) (3 of 5 commits stamped; the other two unstamped)*

Took about 20 minutes again to build everything out. Debug took about eight minutes for basic functionality (i.e. things not being completely broken) and another six or so fixing bugs that were introduced, some regressions, etc. Had lots of issues with older data getting saved and not cleaned up after code changes. It did ask once, when addressing a known issue with Landsat 7 imagery having missing sections, but only that one time.

> **Later:** The census work didn't actually come out of this phase working. The ACS variable dict that landed here never requested total housing units, so the Housing chart had nothing to divide by and never rendered, and it stayed that way for 131 days across seven commits to the same file. Found in the August audit ([H1](docs/audits/2026-08-second-audit/FINDINGS.md)).

* Started getting some more front-end errors in this one (missing packages, paths off, etc).
* Seems to fairly consistently forget to do things like rebuilding Docker images, but this is probably more an error on my part; planning to make a lot of additions to the global Claude config after this with lessons learned.
* One very common recurring issue is logic around caching; it seems to struggle with knowing what is and is not appropriate to cache, and when to ignore caching even if it is appropriate for some cases/uses. This could also be a configuration thing, but I'm leaning towards it being a general limitation of the tool's capabilities in general, as there's a lot of nuance around this.

  > **Later:** The analysis section up top ends up at pretty much the opposite conclusion about this class of problem; the cache bugs that survived weren't capability failures, they were scope failures. This entry is basically the misdiagnosis that section describes.

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

  > **Later:** The tweaks weren't minor, and they weren't finished either. The same phase's build commit put an identical `Cache-Control: public, max-age=3600` on both the imagery list and the demographics list, which hid late-arriving data behind the browser cache. I fixed the imagery one 58 days later and didn't grep for the twin, so the demographics copy survived another 72 days. Found in the August audit ([H3](docs/audits/2026-08-second-audit/FINDINGS.md)).
* Seeing a similar pattern to earlier, where it will often think it has properly fixed the issue (especially if given vague guidance) and have to revisit it several times.
* One outlier - took a *very* long time (and kept getting stuck) trying to do a seemingly simple fix where timeline items were only showing up for featured items. I was getting close to my session limit, so maybe a throttling thing? No obvious reasons for the slowness that I could see in the commands it was running. It did figure it out in the end, but it took almost eighteen minutes and spent a lot of that time seemingly stuck (not consuming tokens, no visible processing going on).
* Random nice bit of UX - it's smart enough to tell which work it did in any specific session and only commit that (within reason, gets confused sometimes if multiple agents running simultaneously are touching similar files).
* Seems to struggle a lot with proper CSS at times and loves to try hacky fixes. To be fair, I was giving it deliberately non-specific instructions to see how it would try and fix things.

### Post-analysis addendum: a coordination failure the analysis didn't predict

*2026-08-03 · Claude Opus 5, two concurrent sessions*

Two sessions were working the repo at the same time on the last day: one wiring the audit documents into this file and the README, the other finishing the H6 imagery-reconciliation fix that landed as 96a7962 at 15:48. The wiring session was told to leave `docs/` uncommitted, since whether or not to commit the audit trail was my call to make, and the staging notes it was working from said the same thing.

`docs/` got committed anyway, as 436cf85 at 15:52, four minutes after the other session's commit. It carries a `Co-Authored-By: Claude Opus 5` trailer, which is the same trailer the wiring session's own commits carry, so the trailer marks it as agent work without saying which agent. The wiring session reported `docs/` left untracked, though, so it pretty clearly came from the other one. The content itself was correct (nine files, all additions, exactly the audit trail and none of the wiring that was still in progress), and what went out is what I would have committed anyway. So the boundary that got crossed was procedural rather than substantive.

The lesson is a pretty narrow one but I think it's worth writing down regardless. Per-session instructions don't compose across concurrent sessions; telling one session "don't commit this, it's the owner's call" doesn't do anything to bind a second session with its own context and its own view of the working tree. Every boundary that actually matters has to either be restated in every session that could cross it or enforced structurally (a branch per session, for example) rather than verbally. This is a different failure mode from everything else in this document, since the analysis section is about code nobody read and this is about an instruction that just didn't transfer. I noted back in Phase 5 that the agent is good at committing only its own session's work, with the caveat that it gets confused when several are touching the same files at once. Turns out this entry is that caveat playing out.