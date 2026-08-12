# Ops audit — the prompt

Not captured verbatim. The prompt was given in a Claude Code session on
2026-08-12 and lives in that conversation record, not in this repository;
what follows is a summary written from the audit's own account of what it
was asked to do.

The brief was a **read-only** operational audit of production: no fixes, no
config changes, no writes of any kind, everything drawn from the Fly log
buffers and read-only queries against the production database. It asked for
a health check of the running system rather than of the code — which
instrumentation added by the recent fix batches is actually firing, whether
the 2026-08-11 Landsat signing incident had left damage or recurred, whether
any parcel's imagery or census coverage looks short of what its county peers
hold, whether the property adapters return plausible results per county
(with a cluster of empty results from a single county called out as
suspicious in advance), and what the traffic shape looks like, including
whether a spike could be attributed to a referral. It supplied a rough
threshold for damaged Landsat ("flag anything complete under ~35 years") and
asked that assumptions of that kind be stated and challenged rather than
applied silently — §8 of the findings is the answer to that instruction. It
also asked for anomalies outside the brief (§6) and for an explicit account
of what the audit could not see (§7).

The findings document is the audit's report, copied verbatim.
