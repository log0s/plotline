# Developing Plotline

I built this entire application using Claude Code as a way of testing its capabilities when creating full-stack solutions from scratch. The idea is to write as little code myself as possible, relying on the agent to do most/all of the work and see what the quality of the final product is like. For this particular project I also allowed Claude (specifically Opus 4.6) to design/architect a lot of it with some tweaks of my own as a way to understand its capabilities; my next project will be something I spec out entirely by myself.

I've preserved the original CLAUDE.md file that I started with as ORIGINAL_PROMPT.md and will iterate with a new prompt file at each step.

## Phase Breakdowns

### Phase 1

Produced a reasonably well-architected back and front end; I did give it fairly specific instructions so that's not surprising. Took ~13 minutes, but that was also with it sometimes waiting for me to approve some commands. Initial thoughts:

* It's very good at following instructions, not necessarily quite as good at following them to their logical conclusion. Example: I gave it the specification "**Error handling** — don't let raw 500s escape. Geocoder down? Return a clear 502 with a message. Bad address? 422 with details." It followed this to the letter, only putting in error returns for a 502 and 422 (but nothing else). Not really surprising, but good to know.
* The original Makefile had some errors in how it was set up, but Claude Code is a surprisingly painless debugger. It sometimes misses the actual issue for something unrelated, but can self-correct. Took about two minutes to diagnose and fix that issue.
* It's good at scaffolding, but not necessarily as amazing at details. Front end had some iffy stuff like empty catch blocks, assuming same base URL for back end, etc. Confirms (to a certain degree) my suspicions that it functions a lot like a junior developer --- eager to help, follows instructions the best it can, but often lacking in some foundational knowledge.
* Thankfully it can debug itself fairly well, given decent instructions/guidance. Able to run basic commands to figure out what's wrong and give its best shot at fixing them.
* README is all over the place, not surprising since I didn't give it very clear instructions for that.

### Phase 2

Took ~20 minutes to build this phase out completely. Got everything technically built, but this is where it started to struggle a bit more with both correctly hooking everything up together (especially proper URLs) and debugging itself, as well as some strange code choices. Total debugging time was approximately 1.5 hours. I suspect that my bloated CLAUDE.md is an issue, so I plan to trim/rework it after this phase. Definitely the phase where I ended up having to step in and direct debugging efforts the most, as it tended to either put in temporary fixes (missing the core problem entirely) or look in the wrong area.

* Really had a hard time with correctly pointing to the endpoints it made itself.
* Seemed to add a lot of unnecessary code in this step, especially some weird and gratuitous logging in the back end.
* Still very good at certain types of debugging (likely of the well-known issue variety) --- think things like version mismatches, breaking changes in new packages, etc.
* Misses a lot of basic UX stuff (loading indicators, transitions, etc) but I suspect that's more from my lack of direction than anything else. Makes sense to add/address it later anyway.
* Surprisingly good at debugging somewhat complex issues (e.g. found that `extract_cog_url` was pulling in rendered preview PNGs instead of an actual COG, debugged signing expiration issues when hitting external APIs)
* Definitely has the most issues exactly where I expected (GIS/imagery implementation). Not surprising due to it likely having much less training data for that domain. Kept trying to do things like store signed URLs in the DB.

### Phase 3

Took about 20 minutes again to build everything out. Debug took about eight minutes for basic functionality (i.e. things not being completely broken) and another six or so fixing bugs that were introduced, some regressions, etc. Had lots of issues with older data getting saved and not cleaned up after code changes. It did ask once, when addressing a known issue with Landsat 7 imagery having missing sections, but only that one time.

* Started getting some more front-end errors in this one (missing packages, paths off, etc).
* Seems to fairly consistently forget to do things like rebuilding Docker images, but this is probably more an error on my part; planning to make a lot of additions to the global Claude config after this with lessons learned.
* One very common recurring issue is logic around caching; it seems to struggle with knowing what is and is not appropriate to cache, and when to ignore caching even if it is appropriate for some cases/uses. This could also be a configuration thing, but I'm leaning towards it being a general limitation of the tool's capabilities in general, as there's a lot of nuance around this.
* Also consistently forgets to clean up after itself (clear out DB, update old implementations stored, etc) with major data changes. Probably worth noting and saving as a global Claude config.
* Related to the above, it frequently misconstrues the actual issue, and tries to patch in fixes for old/missing/misconfigured data instead of just cleaning up.

### Phase 4

Slightly faster this time at only ~16 minutes to build, which makes sense given the tighter scope. Got it mostly right from the jump even with outdated data sources. Took about thirty or so minutes to debug everything, a significant chunk of which was dedicated to finding/updating open data sources. Overall seemed a bit cleaner in this phase, likely as a result of getting the junk out of CLAUDE.md and not polluting context. Speaking of context, this session really showed the power of it; it took ~13 minutes to find a new open data source for Denver, and then barely 3 minutes later to accomplish the same for Adams county.

* Has a tendency to sometimes ignore instructions in order to make tests pass (e.g. changing a TypeScript definition to "any"); hard to say if this is a general tendency or context being overly full without more data, though.
* Actually did a decent job filling in some UX gaps on this one (e.g. loading indicators). Pleasantly surprised.
* Some more basic mistakes, which to be honest I didn't expect --- not closing connections properly after use, blocking cleanup from async calls (not actually doing async), etc.
* Does a good job on thinking through UI data freshness bugs; actually takes the time to follow the logical thread through various issues and find the actual problem. Seems overall much better at this than at semi-equivalent DB issues.
* Can work through some surprisingly complex issues fairly well (e.g. tracking down new open data endpoint for Denver through multiple trails).

### Phase 5

Right around the same time to build as usual at ~22 minutes. Less than ten minutes of debugging to get everything working properly, plus another five or so to pull in some better/more relevant/more fleshed out featured examples. Unsurprisingly, other than the addition of some of the GIS stuff in phase 3 this was the phase that required the most manual intervention; I suspected that the final polish would be the trickiest thing to automate.

* Planning mode is great. Breaks things down into steps on its own, gives reasoning, easy to tweak. Really powerful tool.
* Added a lot of explicit error state handling (especially UI in this one). Handled building them out well once specifically told to do so.
* Noticing more of the tendency to ignore direct instructions at times. Context too full possibly, but at this point it's seeming more and more to be just an inherent property of the system to some extent.
* Makes very basic mistakes (UI infinite redirect due to overlapping/conflicting hooks, not handling URL updates well, etc) but is at least very quick to find/correct them when called out.
* Very useful that it can also do more "research" projects; in this case choosing a new featured spot with better data
* Shockingly smart when given specific directions. Came up with a fairly good caching strategy to speed up tiling that required only minor tweaks.
* Seeing a similar pattern to earlier, where it will often think it has properly fixed the issue (especially if given vague guidance) and have to revisit it several times.
* One outlier - took a *very* long time (and kept getting stuck) trying to do a seemingly simple fix where timeline items were only showing up for featured items. I was getting close to my session limit, so maybe a throttling thing? No obvious reasons for the slowness that I could see in the commands it was running. It did figure it out in the end, but it took almost eighteen minutes and spent a lot of that time seemingly stuck (not consuming tokens, no visible processing going on).
* Random nice bit of UX - it's smart enough to tell which work it did in any specific session and only commit that (within reason, gets confused sometimes if multiple agents running simultaneously are touching similar files).
* Seems to struggle a lot with proper CSS at times and loves to try hacky fixes. To be fair, I was giving it deliberately non-specific instructions to see how it would try and fix things.