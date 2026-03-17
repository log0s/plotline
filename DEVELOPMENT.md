*Developing Plotline*

I built this entire application using Claude Code as a way of testing its capabilities when creating full-stack solutions from scratch. The idea is to write as little code myself as possible, relying on the agent to do most/all of the work and see what the quality of the final product is like. This document is meant to be an honest account of that process: what worked, what didn't, and what I learned about AI-assisted development as a senior engineer.

I've preserved the original CLAUDE.md file that I started with as ORIGINAL_PROMPT.md and will iterate with a new prompt file at each step.

**Phase Breakdowns**

***Phase 1***

Produced a reasonably well-architected back and front end; I did give it fairly specific instructions so that's not surprising. Took ~13 minutes, but that was also with it sometimes waiting for me to approve some commands Initial thoughts:

* It's very good at following instructions, not necessarily quite as good at following them to their logical conclusion. Example: I gave it the specification "**Error handling** — don't let raw 500s escape. Geocoder down? Return a clear 502 with a message. Bad address? 422 with details." It followed this to the letter, only putting in error returns for a 502 and 422 (but nothing else). Not really surprising, but good to know.
* The original Makefile had some errors in how it was set up, but Claude Code is a surprisingly painless debugger. It sometimes misses the actual issue for something unrelated, but can self-correct. Took about two minutes to diagnose and fix that issue.
* It's good at scaffolding, but not necessarily as amazing at details. Front end had some iffy stuff like empty catch blocks, assuming same base URL for back end, etc. Confirms (to a certain degree) my suspicions that it functions a lot like a junior developer --- eager to help, follows instructions the best it can, but often lacking in some foundational knowledge.
* Thankfully it can debug itself fairly well, given decent instructions/guidance. Able to run basic commands to figure out what's wrong and give its best shot at fixing them.