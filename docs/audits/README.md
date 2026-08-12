# Audits

Five reviews of this codebase, each stored as the prompt that commissioned it
and the findings it returned: two architecture audits (2026-05, 2026-08), a
reconciliation of SUPPORTED_COUNTIES.md against the adapter code it describes,
`2026-08-ops-audit/` — a read-only audit of *running production* rather
than of the code, which found that the signing throttle recorded as mitigating
M4 was committed but never deployed, and traced the broken map tiles in
production to the unsigned-href fallback — and
`2026-08-geometry-audit/`, a read-only measurement of a single hypothesis
against every imagery row in the database, which found 33 timeline cards
serving a granule whose footprint excludes the address they are about, and
refuted two of the remedies proposed for it. The git analysis behind
DEVELOPMENT.md's numbers lives in `../provenance/`.

These are records of what was found at the time, not living status documents.
A finding describes the code at the audit's SHA — `c1ac879` (2026-05-22) for the
first audit, `5f5fb42` (2026-07-29) for the second — and line numbers have moved
since. Findings are not edited as the code changes. Where one has been fixed, a
**Resolved:** line naming the commit and date was added above it afterwards;
those annotations are the only later additions to the finding text. The second
audit's findings have a living companion, `2026-08-second-audit/STATUS.md`,
recording each finding's verified status against the current code.

Provenance varies by file. The three PROMPT.md files for the first audit, the
second audit, and the provenance analysis are verbatim. The four findings and
analysis documents are reconstructions from the reported results, with
transmission damage marked inline as *[reconstructed: …]* and *[passage lost in
transcription]*; the second audit's findings and the provenance analysis took
the most damage. The counties reconciliation prompt was never captured and its
PROMPT.md is a stub saying so. The ops audit inverts the usual pattern: its
FINDINGS.md is the delivered report copied verbatim and undamaged, while its
prompt was not captured, so that PROMPT.md is a summary and says so. Some still-open security-relevant findings are
summarized rather than detailed, and say so where that applies. The geometry
audit follows the ops audit's pattern: its FINDINGS.md is the delivered report
copied verbatim and undamaged, and its PROMPT.md is a summary that says so.
That redaction
removed two exploitation passages that themselves contained reconstruction
markers, so a redacted document may carry fewer markers than the reconstruction
it was made from.
