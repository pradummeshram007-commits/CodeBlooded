# Data notes: Odin dev pack

Written after reading `README.md`, `docs/format_spec.md`, `bundle/manifest.json`,
`company/context.txt`, all eight `contracts/*.txt` (the PDFs were ignored, per
format_spec the `.txt` is canonical), and after skimming `clock.json`, `data/*.csv` and
`events/*.jsonl`. Line numbers refer to the `.txt` files.

The pack lives at `02_Ragnarok Odin The Contract War Room/Pack/odin_dev_pack/`, not
`./odin_dev_pack/`; `config.yaml -> paths.bundle_dir` points there.

## 0. File facts that matter for citations

- All eight contracts are UTF-8, LF line endings, no BOM, no tabs, straight ASCII quotes.
  The only non-ASCII characters are `—` (em dash, all files), `–` (en dash, A1 and D1),
  `§` (B1, C1) and `≥` (D1). Offsets are Python string indices into the decoded text.
- Text is hard-wrapped with deep indentation, so a natural quote usually crosses
  `\n` plus 5–8 spaces. Verification therefore normalises whitespace, quote characters,
  dashes and case. The stored quote is always the exact substring of the `.txt`, so it
  is findable with plain text search (format_spec requirement).
- Citation format (format_spec): Document ID = filename stem (`A1`), Clause Reference =
  the number or heading as written (`§3.1`, `Section 4.3`), plus a verbatim quote.
  format_spec defines no combined ID, so `clause_id` uses `A1:4.2`. The as-written
  reference is stored separately in `clauses.ref` / `citations.clause_ref`.

## 1. Clause numbering per document

| Doc | Structure | Example refs | clause_id examples |
|---|---|---|---|
| STD | `USING THIS AGREEMENT` intro; `SECTION N — TITLE` between dashed rules; clauses `N.M` at column 0 (`12.10 ` and `13.x` use a single space); sub-items `(a)`, `(i)` stay inside the clause; §13 = 28 definitions | "Section 4.4 of the Standard Terms" | `STD:using-this-agreement`, `STD:4`, `STD:4.4`, `STD:13.16` |
| A1, B1, C1 | Cover pages: preamble, `PROVIDER INFORMATION`, `CUSTOMER INFORMATION`, `KEY TERMS` banner, lettered `Section A — …` to `Section K`, `SIGNATURES` | "Section B of the Cover Page" | `A1:B`, `B1:J`, `C1:signatures` |
| A1 | Inside Section I: `I.1`–`I.3` (column 0) | | `A1:I.1` |
| B1 | Inside lettered sections: `§3.1`–`§8.2` (indented 2). **§ numbers restart the STD numbering scheme**: Section D = §3.x, E = §4.x, F = §5.x, G = §6.x, H = §7.x, I = §8.x. Sections A–C, J, K have no § clauses | "Section 3.5 of the Cover Page" (event E-17) | `B1:3.1` (parent `B1:D`) |
| C1 | Same style: Section D = §3.1–§3.3, E = §4.1; Section H = `H.1`–`H.3`; a `NOTE:` paragraph after the signatures | | `C1:3.2`, `C1:H.3`, `C1:note` |
| A2 | `SECTION N — TITLE` + `N.M` like STD; Section 5 has intro text before 5.1; a closing paragraph after the last rule | | `A2:5`, `A2:5.1`, `A2:closing` |
| A3 | `SECTION 1–3`, each quoting replacement text that contains A2/A1 clause numbers (`"3.2  Credit Request…"`, `"3.1  If the…"`); an `AMENDMENT EFFECTIVE DATE:` line block | | `A3:1`, `A3:amendment-effective-date` (no `A3:3.2`!) |
| B2 | `SECTION N` + `N.M`; table in 4.2; a `[NOTE: …]` after the signatures | | `B2:4.2`, `B2:note` |
| D1 | Standalone agreement: `SECTION 1–10` + `N.M`; `EXHIBIT A — STATEMENT OF WORK` with milestone blocks `M1 — …` to `M5 — …` and an `Acceptance Criteria:` list | | `D1:ExA`, `D1:ExA.M3`, `D1:ExA.acceptance-criteria` |

The segmenter (`odin/ingest/segmenter.py`) recognises exactly these patterns. It skips
decorative `====` / `----` rules and `END OF …` / `KEY TERMS` banners, and falls back to
paragraph chunks plus an `unparseable` flag for anything it cannot read. All eight
documents segment with 0 uncovered characters (276 clauses in total).

## 2. How documents reference each other (from the text, not the manifest)

The manifest only lists paths and titles. Every link below is stated in the documents
themselves, by file name or by a printed `CONTRACT ID` / `DOCUMENT ID`.

| From | Wording | To | Type |
|---|---|---|---|
| A1, B1, C1 preamble | "incorporates by reference the Common Paper Cloud Service Agreement Standard Terms Version 2.0, a copy of which is maintained at STD.txt" | STD | incorporates |
| A1 §E | "Service Level Agreement attached hereto … (document QH-STRATO-2026-SLA), which is incorporated into this Agreement by reference" | A2 | incorporates |
| A2 preamble | "is incorporated by reference into the Cloud Service Agreement … (Contract ID: QH-STRATO-2026-001" | A1 incorporates A2 | incorporates |
| A3 §1, §2 | "Section 3.2 of the SLA is deleted in its entirety and replaced" / "Section 3.1 of the SLA is deleted …" | A2 §3.2, §3.1 | amends (replace) |
| A3 §3 | "Section B of the Cover Page (Contract ID: QH-STRATO-2026-001) is amended" | **A1 §B** | amends (modify) |
| B2 preamble | "supplements the Cloud Service Agreement … (Contract ID: QH-HARBOR-2026-001 …). This Addendum is incorporated into and forms part of the Agreement." | B1 incorporates B2 | incorporates |
| B2 §3.1, §8.1 | "Data Breach (as defined in Section 5.1 of the Agreement)", "Unlimited Claims as specified in Section J of the Cover Page" | B1 §5.1, §J | references |
| D1 §4.2 | "holiday schedule provided by Company (data/holidays.csv in this bundle)" | data/holidays.csv | references |
| D1 §1.1, §1.2 | "Statement of Work attached as Exhibit A … is incorporated into this Agreement" | D1 Exhibit A (internal) | n/a |
| STD | Generic: "Cover Page", "Order Form", "DPA" (3.1), "Use Limitations" (2.1) | nothing specific; no Order Form exists in the bundle | unresolved |

Discovered contract families: **{A1, A2, A3, STD}**, **{B1, B2, STD}**, **{C1, STD}**,
**{D1}** (D1 does not incorporate STD).

### Precedence and override clauses

There is no literal "notwithstanding" anywhere in the bundle. Override and priority
rules are written as "controls" / "except as":

1. STD intro: "If the Cover Page and these Standard Terms conflict, the Cover Page controls." Repeated in the A1, B1 and C1 preambles.
2. A1 §E and A2 preamble: SLA controls over the Agreement "with respect to uptime commitments and service credits" (scoped).
3. A3 preamble: "In the event of a conflict between this Amendment and the SLA, this Amendment controls." Only vs. the SLA, although A3 §3 also amends the Cover Page.
4. B2 preamble: Addendum controls over B1 *and STD* "with respect to data processing, security, and breach notification obligations" (scoped).
5. STD 3.1: a DPA "will control in the event of any conflict" as to Personal Data.
6. Carve-outs: A2 3.4 "sole and exclusive remedy … except as otherwise provided in the Agreement"; STD 8.1/8.2 "Except as provided in Section 8.3"; B1 §5.1 "in addition to and does not replace" STD 3.3; A1 I.1 "in addition to" STD 3.3.
7. "For the avoidance of doubt" / "For clarity" restatements: C1 §B (definition of written notice), C1 H.1, A3 §3 (restated renewal clause), B1 §C (fee escalation example).

## 3. Date and amount formats

- Dates in contracts: `Month D, YYYY` ("August 1, 2026"). Ranges use an en dash
  ("October 1, 2026 – March 31, 2027", D1 Exhibit A). Signature dates differ from
  effective dates (A1 signed July 15/18, effective August 1, 2026).
- Durations: "24 months (ending July 31, 2028)"; "36 months (ending September 14, 2029)";
  "24 months from the Effective Date" (C1, relative); D1 "until December 31, 2027".
- Blank or conditional dates: C1 "Effective Date: [TO BE INSERTED UPON GO-LIVE]",
  defined only in the post-signature NOTE as the date Quillhub "confirms in writing that
  the Platform is available for production use".
- Numbers: words plus digits ("thirty (30) days", "ninety-nine and one-half percent (99.5%)"), or digits only ("72 hours", "90 days").
- Money: "$8,000.00 (Eight Thousand U.S. Dollars)"; words-first "Sixty-Five Thousand U.S. Dollars ($65,000.00)" (D1 3.1); no decimals in tables ("$10,000"); "$2,000,000 per occurrence". Currency is always USD; STD 4.1 makes USD the default.
- Data files use ISO dates (`2027-03-15`) and plain decimals (`8000.00`). Events use ISO-8601 UTC timestamps.

## 4. Business-day vs calendar-day wording

| Doc / clause | Period | Wording |
|---|---|---|
| STD 2.2, 4.3, 4.6, 5.2, 5.3, 5.4, 6.4 | 30 / 15 / 60 / 45 days | **"days"**, unspecified |
| STD 12.4 | notice deemed given "two days after mailing" | unspecified |
| STD 3.3 | Security Incident notice | 72 hours |
| A1 §B, §C | non-renewal 90 days; payment 30 days | unspecified |
| A1 §C | invoices "first business day of each calendar month" | business |
| A1 §D | Sev 3: "1 business day", Sev 4: "2 business days"; support hours exclude "StratoNode-observed holidays" (no StratoNode holiday list exists) | business |
| A1 I.1 | disruption notice "within four (4) hours" ("commercially reasonable efforts") | hours |
| A2 1.3 | maintenance notice "at least 48 hours in advance" | hours |
| A2 3.2 | credit request "within thirty (30) days after the end of the calendar month" | unspecified (replaced by A3) |
| A3 §1 | credit request 15 days; Provider response "within ten (10) business days" | unspecified / business |
| A3 §3 | non-renewal 60 days | unspecified |
| B1 §3.5 | credit request 45 days; §4.2 RCA 5 business days; §5.1 breach 24 hours; §7.1 certificates 10 business days; §7.2 lapse notice 5 business days; §8.2 cure 15 days | mixed |
| B2 | breach 24 hours; vuln remediation 30 days; subprocessor notice 30 days, objection 15 days; audit notice 60 days; deletion 60 days | unspecified |
| C1 | payment 30 days; credit request 30 days; integration support "first six (6) months" | unspecified |
| D1 3.2 | invoice "within five (5) business days" after acceptance; payment "within twenty (20) business days of receipt" | business |
| D1 4.2–4.4 | review 10 business days; corrections 5 business days | **business, defined**: excludes Saturdays, Sundays and holidays in data/holidays.csv |
| D1 9.1, 9.2 | convenience notice 30 calendar days; cure 15 calendar days | **calendar** (explicit) |
| D1 10.2 | mail notice "two (2) business days after mailing" | business |

Only D1 defines "business days". Every other "business day" (A1, A3, B1) is undefined,
and every bare "days" is unspecified. Thor records `day_type` exactly as written and
never assumes one.

## 5. Things that look like deliberate traps

1. **Silent supersession across documents.** A3 is titled "Amendment No. 1 to Service
   Level Agreement", but its §3 amends the **A1 Cover Page**: the Non-Renewal Notice
   Period drops from 90 to 60 days. A1 still reads 90 days. It also shortens the SLA
   credit-request window from 30 to 15 days (§1), adds evidence requirements, adds a
   10-business-day response, and adds a +5% credit for any single incident over 60
   minutes (§2). Effective January 1, 2027 (signed December 20/22, 2026).
2. **Ambiguous new credit.** A3's replacement §3.1 says "Additionally, if Downtime in a
   single incident exceeds sixty (60) consecutive minutes, Customer will receive an
   additional Service Credit …". It sits inside a paragraph that opens "If the Monthly
   Uptime Percentage falls below the Uptime Target …". It is unclear whether the 5%
   applies when the monthly target is met (e.g. March 3: 190 minutes, 99.57% > 99.5%).
3. **§-numbering collisions.** B1/C1 "§3.3" (Service Credits) is not STD "Section 3.3"
   (Security Incident Notification). B1 §5.1 (Data Breach) is not STD 5.1 (Subscription
   Period). In B1 Section J, "Data Breach obligations under Section 5" means B1 §5.x,
   while "Section 2.1 of the Standard Terms" means STD. In B1 §8.2, "Section 7" means B1
   §7.x. In B2, "Section 5.1 of the Agreement" means B1 §5.1.
4. **Conflicting breach triggers.** B1 §5.1 counts "actual or reasonably suspected"
   access and gives 24 hours to notify the General Counsel. B2 3.1 also gives 24 hours,
   but starts the clock only at "a reasonable degree of certainty", and B2 controls on
   breach notification. Upstream, StratoNode only owes notice within 72 hours (A1 §F /
   STD 3.3) and disruption notice within 4 hours on a "commercially reasonable efforts"
   basis (A1 I.1).
5. **Unlimited-claim scope mismatch.** B2 8.1 calls B2 §3 obligations "Unlimited Claims
   as specified in Section J of the Cover Page", but B1 §J lists "Data Breach obligations
   under Section 5" (B1 §5), not B2 §3.
6. **Upstream/downstream SLA gap.** Upstream (A2/A3): 99.5%, credits 10/25/50% of
   $8,000, capped at 50%, sole remedy, 15-day claim window after A3. Downstream: B1
   99.9%, 15% of $40,000 = $6,000, cap 20%, 45-day window, maintenance only with 72 hours
   notice, at most 2 hours, once a month. C1: 99.5%, 10% of $18,500, no cap, 30-day
   window. Scheduled-maintenance definitions differ in all three.
7. **Overlapping exclusivity.** B1 §6.1 grants Harbor exclusivity for Route Optimizer
   Enterprise in Pacific NW retail grocery (HQ in WA/OR). C1 §4.1 grants Vantage
   exclusivity for **all tiers, including Enterprise**, in Pacific NW third-party
   logistics (HQ in WA/OR, warehousing plus last-mile). C1 H.3 limits it to the Route
   Optimizer product line. B1 never states that Harbor *is* a grocery company.
8. **Placeholder effective date.** C1's Effective Date is blank. Its term, exclusivity
   and integration-support window all run from it, while the $12,000 Setup Fee is
   "payable upon execution" (November 2026).
9. **Notice formalities.** C1 §B defines "written notice" as STD 12.4 delivery to the
   Notice Address only; "informal communications … do not constitute written notice".
   A2 1.3 requires maintenance notices to go to the "Operations contact or … status
   page" (A1 I.1 names ops@quillhub.io as the Operations contact).
10. **Insurance dependency.** B1 §7 requires $2M CGL and $3M E&O/Cyber, makes a lapse a
    material breach, requires lapse notice within 5 business days, and allows
    termination after a 15-day cure (§8.2). company/context.txt: both policies expire
    June 30, 2027, and "No renewal confirmation has been received".
11. **Incomplete document.** B2 ends with "[NOTE: The remainder of this document,
    including Exhibit A … and Exhibit B …, was not included in this copy. The document
    appears to be incomplete.]"
12. **Undefined template variables.** STD relies on Cover Page variables. Some are never
    defined anywhere: "Provider Covered Claims" / "Customer Covered Claims" (STD 9.1/9.2;
    no cover page defines them, so the indemnity scope is empty), "Use Limitations"
    (2.1), "Additional Warranties" (6.1(d)), "Order Form" (1.2, 3.2). C1 "Unlimited
    Claims: None specified" means everything is under the cap.
13. **D1 stands alone.** D1 does not incorporate STD but uses "Applicable Laws", which
    only STD defines. Its 3.1 table column "Due" means the *payment* trigger ("Upon
    execution"/"Upon acceptance"), while Exhibit A "Due Date" means the *delivery* date.
    M1 is payable "upon execution" but §3.2 says invoices follow acceptance. Late
    interest is 1.0%/month (STD: 1.5%). The SOW duration ends March 31, 2027; the term
    ends December 31, 2027.
14. **Names differ between manifest and text.** Manifest: "Harbor Retail *Solutions*
    LLC", "Vantage Logistics Corp."; contracts and ledger: "Harbor Retail *Group* LLC",
    "Vantage Logistics Corporation". The text is the authority.
15. **Holiday file is not the real calendar.** holidays.csv puts Thanksgiving 2026 on
    Saturday Nov 28 (actual: Thursday Nov 26), MLK Day 2027 on Wednesday Jan 20 (actual:
    Jan 18), and Presidents' Day 2027 on Wednesday Feb 17 (actual: Feb 15). D1 4.2
    binds business days to *this file*, so use it as-is. `observed_by` distinguishes
    `All` from `Quillhub`-only days. No StratoNode list exists although A1 §D refers to
    "StratoNode-observed holidays".
16. **Signatory authority.** company/context.txt: only the CEO and the VP Legal may bind
    Quillhub. Every Quillhub signature matches. Counterparty signers' authority is not
    stated (Harbor and B2: SVP Supply Chain; StratoNode: VP Sales).

## 6. Operational data (for Norns / Heimdall, not processed in step 1)

- `clock.json`: start 2027-01-15; checkpoints 2027-03-15, 2027-06-01, 2027-09-15.
- `events_drop2.jsonl` line 8 is not JSON ("this is a malformed event line …"), sitting
  between E-17 and E-18. `odin.ingest.loader.load_events` keeps it with `parse_error`.
- Events mix noise (E-06 marketing newsletter) with operative facts (E-04/E-12 outages,
  E-14 written Go-Live confirmation for C1 on May 15, 2027, E-16 insurance lapse
  warning, E-17 formal credit request to the Notice Address). E-08 is an informal
  non-renewal hint to a non-Notice address; E-10 is a phone log with no written
  extension.
- Event inconsistencies: E-10 is logged 2027-04-15 but promises M4 "by March 7, 2027".
  E-03 submits M3 on Feb 28 (due Jan 31) while the ledger shows M3 paid on Feb 18.
  E-15 calls May the "second consecutive" Harbor miss after March, but April is not
  reported. E-17 itself says March and May "are not consecutive".
- Ledger: the Harbor April 2027 fee is `overdue` on 2027-04-08, although E-09 states a
  May 17 due date. The September 2026 Harbor row is labelled "partial month prorated"
  yet is the full $40,000. There are no Vantage rows and no M4/M5 payments.
- Event schema: `event_id, timestamp, channel (email|system|status_log|phone), from, to,
  subject, body`. Ledger: `date, from, to, amount, reference, status (paid|overdue|pending)`;
  contract IDs are embedded in `reference`. Holidays: `date, name, observed_by`.
