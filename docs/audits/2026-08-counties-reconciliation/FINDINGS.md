# Counties Reconciliation — Findings

*Run 2026-08-03 (Claude Fable 5). SUPPORTED_COUNTIES.md was rewritten from
code-derived ground truth and committed as c296b3a. This is the discrepancy
report that accompanied the rewrite, reconstructed with transmission damage
marked. Note the reviewer's verification caveat at the end: the test suite
could not be executed (stack down, psycopg2 unbuildable on host), so query
shapes were corroborated statically against test_county_adapters.py.*

---

## Discrepancies: doc vs. code

**Resolved:** c296b3a, 2026-08-03 — every discrepancy in this section and in
"Cross-cutting" below is a doc-vs-code mismatch, corrected by the
SUPPORTED_COUNTIES.md rewrite this report accompanied. Item 13 (row caps)
describes code behavior that is now documented but still unchanged.

### District of Columbia

1. Sales fields: doc said PREMISEADD, SALEPRICE, SALEDATE. The code queries and parses SSL, PROPERTY_ADDRESS, LAST_SALE_PRICE, LAST_SALE_DATE (with DEED_DATE fallback), LAND_USE_DESCRIPTION (county_adapters.py:351-355, 363-386). Git archaeology shows these doc fields never matched — the adapter used PROPERTY_ADDRESS from the day it landed (2f73500).

2. Sales matching: doc said upper(PREMISEADD) LIKE '%{number} {street}%' (leading wildcard). Code: upper(PROPERTY_ADDRESS) LIKE '{number} %{street}%' — anchored at the start, wildcard between number and street (county_adapters.py:344-346). The leading-wildcard version existed until commit 86aae50 removed it because '%100 X%' also matched "1100 X". Permits same shape on FULL_ADDRESS (:398).

3. Permits fields: doc omitted PERMIT_SUBTYPE_NAME (feeds classification), DESC_OF_WORK, and PERMIT_ID (the record id); it also didn't say FEES_PAID is stored as the event's valuation (:418-447).

4. Undocumented semantics: the sales layer is an assessment table — at most one sale (the last) per property, rows without a price dropped, cap 20 rows (:356-361); permit layer ids are non-contiguous (2, 3, 14–18 for 2020–2026), 50 rows/layer (:321-329, 407).

### Santa Clara / San Jose

5. Fields: doc listed ADDRESS, ISSUED_DATE, DESCRIPTION, VALUATION, STATUS — none exist in the parser. Actual: gx_location, ISSUEDATE, WORKDESCRIPTION→FOLDERDESC, FOLDERNAME, PERMITVALUATION, CONTRACTOR, FOLDERNUMBER (:517-550). Wrong since day one. No status field is read — status is implied by which of the three resources returned the row.

6. Matching: doc said "filters by ADDRESS field". Actually a CKAN full-text datastore_search q="{number} {street}" (searches all columns; CKAN has no per-field LIKE), followed by a client-side filter requiring the first token of gx_location to equal the street number (:495-521, ckan.py:54-55).

7. Undocumented: the "3/8/2026 12:00:00 AM" date format (:553-568) and the unordered 100-row/resource cap [reconstructed: — results are not "most recent 100"].

### New York County

8. Doc listed only usep-8jbt (rolling). Code queries two sales datasets in parallel: w2pb-icbu (Annualized, 2016+ history) plus usep-8jbt (trailing ~12 months, the only current-year source) — added in 86aae50 (:587-590, 622). Overlap dedupes via the {block}-{lot}-{sale_date} record id (:639-643) + ON CONFLICT DO NOTHING (property_events.py:74).

9. Permit fields omitted job__ (record id), owner_s_business_name, filing_status, the permit_type fallback, and the NB/A1/A2/A3/DM job-type label mapping (:686-719). Matching clauses in the doc were correct (:606, 668).

### Denver

10. Doc listed ADDRESS_NUMBER [reconstructed: and STREET_NAME] as key fields; the parser never reads them (only ADDRESS, DATE_ISSUED, CLASS, VALUATION, PERMIT_NUM, CONTRACTOR_NAME, :186-201), making the "ADDRESS_NUMBER is integer" note moot. URLs, matching pattern, and [reconstructed: dataset history] were all accurate.

### Adams

11. Same pattern: HouseNumber/StreetName listed but unused; actual fields CombinedAddress, CaseOpened, TypeOfWork→ClassOfWork fallback, Description, RecordID_ (:271-287). No valuation column exists, so Adams permits never carry one; event date is case-opened, not issued.

## Cross-cutting (was missing entirely, now documented)

12. The broad-LIKE + fuzzy-match pipeline: extract_search_terms reduces to number + first street word, and every record is checked with is_address_match (exact number + ≥0.7 token overlap) (timeline.py:642-648, address_normalizer.py:62-111).

13. Row caps with no pagination in any client (Denver 100/layer, Adams 100, DC 20 sales / 50 per year-layer, SJ 100/resource, NYC 200/sales resource + 100 permits) — overflow is silently dropped.

14. Socrata 404 → warning + empty result, not an error (socrata.py:72-77).

15. Unsupported counties [reconstructed: — any county not in the] registry keys — Clark County/Las Vegas named as the notable example — get the property task skipped with a "not yet available" message (county_adapters.py:796-808, timeline.py:567-579). [fragment lost in transcription]

16. The "Socrata Notes" heading said "for future counties still on Socrata" — NYC is on Socrata now.

## The rewrite

Same skeleton and tone (intro → per-county tables → Adding a New County → client notes), with a new "How queries and matching work" section up front, a "Known coverage gaps" section, and CKAN client notes. "Key Fields" columns became "Fields Read" and list only what the parsers consume. Historical notes (dead hmrh-5s3x, defunct data.adcogov.org, the silent-redirect lesson) are preserved but explicitly marked History. Stamp updated to 2026-08-03, and it's now true.

## Code oddities flagged, not fixed

- county_adapters.py:1-4 [reconstructed: docstring says the] adapters isolate "Socrata API quirks"; only NYC is Socrata now.
- **Resolved:** 256ed32, 2026-08-03 — Every adapter query catches bare Exception (e.g. :176, :266, :358, :505) — deliberate resilience, but [reconstructed: violates the repo's "catch specific exceptions" standard]. *(Addressed post-report by the property-outage fix.)*
- DC sales requests APPRAISED_VALUE_CURRENT_TOTAL but never uses it outside raw_data (:354).
- parse_date docstring (:45) says "from Socrata" though it serves all sources.

## Verification caveat

The test suite runs inside the Docker api container (make test) and the stack was down; the host can't build psycopg2 (no pg_config), so the tests could not be executed. The rewrite is doc-only so it can't affect them, and test_county_adapters.py statically corroborates every query shape documented here (exact WHERE clauses, [reconstructed: 2 NYC] sales resources, 3 SJ resources).
