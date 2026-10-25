# Odin audit: Thor on A1, A2, A3, B1

Audit only: no code, schema, prompt or config was changed, and **0 LLM calls** were made. All
data was read from the live state store (Supabase Postgres, `STATE_BACKEND=supabase`) and
compared with the `.txt` files in `bundle/contracts/`. STD was used only to check incorporation
links and the clauses that are cited in it.

## Step 0: what exists

1. **Thor:** built and run. A1, A2, A3 and B1 are `complete` in Supabase, and `outputs/thor/*.json` exist.
2. **Supabase store:** built and live (migrations applied, private `contracts` bucket, 8 documents).
3. **Norns:** NOT BUILT. **Clock:** NOT BUILT. Only `clock.json` is loaded, as 4 `clock_checkpoints` rows; there is no clock logic.
4. **Worst case:** NOT BUILT.
5. **Groq/Gemma writeup:** NOT BUILT. Thor ran on Groq `openai/gpt-oss-20b`; there is no writeup and no Gemma run.

Part B (B1–B8) is therefore skipped.

## 1. Results

| Check | Result | Evidence |
|---|---|---|
| A1 Segmentation | **PASS** | All numbered clauses in the .txt are stored: A1 12, A2 23, A3 3, B1 25. None are missing, merged, split or overlapping, and every `clause.text == text[start:end]`. The `"3.1"`/`"3.2"` quoted inside A3 are correctly not treated as clauses. |
| A2 Accuracy | **PARTIAL** | Of 24 key fields: 16 correct, 8 partial, 0 wrong (tables below). |
| A3 Citations | **PARTIAL** | 93 citations checked: 91 pass, 2 fail (both in A3:1, paraphrased by the model). The independent check agrees with the stored `verified` flag on all 93. |
| A4 Misses | **FAIL** | Key amounts were not extracted: B1 99.9% uptime target, B1 20% credit cap, B1 insurance limits ($2M/$3M), A2 maintenance limits and exclusions, and A2's term. |
| A5 Hallucinations | **PARTIAL** | No fabricated values: every number and date exists in its document. 7 values are inferred rather than stated. |
| A6 Flags | **FAIL** | 17 open flags: 9 real, 8 false (they claim terms or sections are missing that exist). 4 obvious ambiguities were never flagged. |
| A7 Relations | **FAIL** | No `A3 amends A2` (§3.1, §3.2) or `A3 amends A1` (§B) edge. The STD incorporations (A1 and B1) are correct and verified. |
| A8 Status honesty | **PARTIAL** | All 4 are `complete` with 100% coverage, and their 5 LLM calls had no errors. But A3 is "complete" while its 3 amendment operations never became relations (4 open flags say so). |
| B1 Due dates | NOT BUILT | Norns does not exist. |
| B2 Business days | NOT BUILT | Norns does not exist. |
| B3 Ledger | NOT BUILT | Norns does not exist. The ledger is loaded (`ledger_entries`, 25 rows) but nothing reads it. |
| B4 Amendment timing | NOT BUILT | Norns does not exist. |
| B5 No future leakage | NOT BUILT | No clock logic. |
| B6 Determinism | NOT BUILT | No `compute()`. |
| B7 Worst case | NOT BUILT | Not built. |
| B8 Writeup | NOT BUILT | No writeup. |

### A2: key fields

Verdicts: **C** = correct, **P** = partial, **W** = wrong.

**A1**

| Field | Thor value | Contract text | Clause | Verdict |
|---|---|---|---|---|
| Parties | provider StratoNode Inc.; customer Quillhub Inc. (addresses, notice addresses) | "Legal Name: StratoNode Inc." / "Legal Name: Quillhub Inc." | A1:provider-information, A1:customer-information | C |
| Effective date / term | 2026-08-01; 24 months, 2026-08-01 to 2028-07-31 | "Effective Date: August 1, 2026 / Initial Subscription Period: 24 months (ending July 31, 2028)" | A1:B | C |
| Renewal + notice | auto-renews; 12-month periods; 90 days' written notice to the Notice Address; day_type unspecified | "successive 12-month periods … at least 90 days before the end of the then-current Subscription Period" | A1:B | C (as written; A3 §3 changes it to 60 days from 2027-01-01, see A7) |
| Payment | $8,000.00 USD monthly; invoice on the first business day; due 30 days from invoice; 1.5%/month interest | "Monthly Fee: $8,000.00 … Payment Period: 30 days from invoice date … interest at 1.5% per month" | A1:C | C |
| Penalty / credit | `missing` | "overdue amounts accrue interest at 1.5% per month" (§C) | — | P (the interest is stored only inside the payment row; the penalty row says missing) |
| Termination | `missing` | A1 has no termination clause of its own (it relies on STD 5.2); I.2 covers migration after termination | — | C |

**A2**

| Field | Thor value | Contract text | Clause | Verdict |
|---|---|---|---|---|
| Parties | StratoNode = Provider, Quillhub = Customer | "between StratoNode Inc. ("Provider") and Quillhub Inc. ("Customer")" | A2:preamble | C |
| Effective date / term | effective 2026-08-01 (raw "Effective Date of the Agreement"); term `missing` | "This SLA is effective as of the Effective Date of the Agreement and will remain in effect for the duration of the Agreement, including any renewal periods." | A2:closing | P (the ISO date is not in the cited clause; it comes from the preamble's "dated August 1, 2026". Term marked missing although this sentence states it.) |
| Renewal + notice | `missing` | none in A2 (it follows the Agreement) | — | C |
| Payment | Monthly Fee $8,000 USD | "currently Eight Thousand U.S. Dollars ($8,000.00)" | A2:3.1 | C |
| Penalty / credit | tiers 10/25/50%; cap 50%; claim window 30 days, day_type calendar; sole_remedy true | 3.1 table; 3.3 "will not exceed fifty percent (50%)"; 3.2 "within thirty (30) days after the end of the calendar month"; 3.4 "sole and exclusive remedy … except as otherwise provided in the Agreement" | A2:3.1 only | P (cap, window and sole remedy come from uncited 3.2–3.4; "calendar" days is not stated; the sole-remedy carve-out was dropped) |
| Termination | 2 consecutive months; 30 days' written notice; prorated refund; day_type calendar | "terminate the Agreement upon thirty (30) days' written notice … prorated portion of any prepaid Fees" | A2:6.1 | P ("calendar" days is not stated) |

**A3**

| Field | Thor value | Contract text | Clause | Verdict |
|---|---|---|---|---|
| Parties | StratoNode = Provider, Quillhub = Customer | preamble | A3:preamble | C |
| Effective date | 2027-01-01 | "AMENDMENT EFFECTIVE DATE: January 1, 2027" | A3:amendment-effective-date | C |
| Renewal + notice | auto-renews, 12 months, 60 days' written notice | "at least 60 days before the end of the then-current Subscription Period" | A3:3 | C |
| Credit request (new 3.2) | request within 15 days after month end; reply within 10 business days | "within fifteen (15) days after the end of the calendar month … respond within ten (10) business days" | A3:1, **both citations unverified**, confidence 0.3 | P (values right, quotes paraphrased) |
| Penalty / credit (new 3.1) | tiers 10/25/50% plus 5% for one incident over 60 consecutive minutes | "additional Service Credit equal to five percent (5%) … This additional credit is subject to the maximum credit in Section 3.3." | A3:2 | P (the cap condition was dropped) |
| Amendment operations | rows cross_ref_1/2/3: scope "Section 3.2" → A2, "Section 3.1" → A2, "Section B" → A1, with new_text; but **no `ref_type`, `operation` or `target_clause`** | "Section 3.2 of the SLA is deleted in its entirety and replaced…" / "Section 3.1 … deleted … replaced" / "Section B of the Cover Page … is amended" | A3:1, A3:2, A3:3 | P (content right, but not typed as amendments, so no relations were written) |

**B1**

| Field | Thor value | Contract text | Clause | Verdict |
|---|---|---|---|---|
| Parties | Quillhub = provider; Harbor Retail Group LLC = customer | "Legal Name: Quillhub Inc." / "Legal Name: Harbor Retail Group LLC" | B1:provider-information, B1:customer-information | C |
| Effective date / term | 2026-09-15; 36 months to 2029-09-14 | "Effective Date: September 15, 2026 / 36 months (ending September 14, 2029)" | B1:B | C |
| Renewal + notice | auto-renews; 24-month periods; 180 days | "successive 24-month periods … at least 180 days before the end" | B1:B | C |
| Payment | $40,000 monthly; invoice on the first business day; due 45 days from invoice; +3% on each anniversary | "Monthly Fee: $40,000.00 … 45 days from invoice date … increase by three percent (3%) on each anniversary" | B1:C | C (the "$41,200.00 from September 15, 2027" example is not stored) |
| Penalty / credit | 15% of the Monthly Fee; sole_remedy false; no cap | "§3.3 … fifteen percent (15%) of the Monthly Fee" / "§3.4 … will not exceed twenty percent (20%)" | B1:3.3 | P (the 20% cap is missing; nothing says sole_remedy=false) |
| Termination | persistent SLA failure (2 consecutive months, written notice, prorated refund); insurance lapse (15-day cure, then immediate) | §8.1, §8.2 | B1:8.1, B1:8.2 | C |

### A3: citation failures (2 of 93)

| Doc | Field | Cited | Model quote | Text |
|---|---|---|---|---|
| A3 | obligation/obligation_credit_request | A3:1 | "…within fifteen days after the end of the calendar month…" | "…within fifteen\n (15) days after the end of the calendar month…" |
| A3 | obligation/obligation_review_request | A3:1 | "Provider will review the request and respond within ten business days." | "…respond within ten\n (10) business days." |

Both are correctly stored as `verified=false`, capped at confidence 0.3, and flagged.

How the 93 citations matched:
- 27 exact, 64 after whitespace and quote normalisation, 2 not found.
- 4 of the model's quotes needed the verifier's extra tolerance (dropped or swapped quote marks, a trailing comma).

## 2. Failure details

### A4: important content not extracted (FAIL)

| Doc | Contract text | Thor |
|---|---|---|
| B1 | §3.1 "at least ninety-nine and nine-tenths percent (99.9%) of the minutes in each calendar month" | `obligation_uptime_commitment` = "maintain uptime", **no target value** |
| B1 | §3.4 "will not exceed twenty percent (20%) of the Monthly Fee for that month" | not extracted anywhere |
| B1 | §7.1 "limits of at least $2,000,000 per occurrence … at least $3,000,000 per claim … certificates of insurance … within ten (10) business days" | `obligation_insurance_maintenance` = "maintain insurance", **no limits, no 10-business-day duty** |
| B1 | §7.2 "A lapse in required insurance coverage constitutes a material breach" | not extracted |
| B1 | §3.1 scheduled maintenance: "at least 72 hours in advance … not exceed two (2) hours … not … more than once per calendar month" | not extracted |
| B1 | §6.1 exclusivity scope: "Pacific Northwest retail grocery sector … headquartered in … Washington and Oregon" | `obligation_exclusivity` = "grant exclusivity", **no scope** |
| A2 | 1.3 "at least 48 hours in advance … not exceed four (4) hours per occurrence … not … more than twice per calendar month" | not extracted (affects downtime and credit maths) |
| A2 | 5.1–5.5 exclusions from Downtime Minutes (maintenance, Customer-caused, unauthorised use, Force Majeure, third parties) | not extracted |
| A2 | closing: "will remain in effect for the duration of the Agreement, including any renewal periods" | term = `missing` |
| A3 | §1 new 3.2 request contents "(c) evidence from Customer's own monitoring systems … (d) the calculated Monthly Uptime Percentage" | not captured (new conditions for receiving a credit) |
| A1 | §D response targets: Sev 1 1 hour, Sev 2 4 hours, Sev 3 1 business day, Sev 4 2 business days; "not contractual commitments" | not extracted (nothing records that they are non-binding either) |

### A6: false flags and missed ambiguities (FAIL)

False flags, where the text contradicts the flag:

| Flag | Contract text |
|---|---|
| A3:3 "Reference to Section B of the Cover Page … not present in the provided documents" | A1 line 47: "Section B — Subscription Period and Renewal" (stored as clause `A1:B`) |
| A3:3 "Reference to Section 5.1 of the Standard Terms … not present in the provided documents" | STD line 160: "5.1 Subscription Period. …" (clause `STD:5.1`) |
| A3:2 "Section 3.3 … not present in this amendment" | it isn't supposed to be: A2 3.3 "Maximum Credit … fifty percent (50%)" |
| A3:1 / A3:3 "Provider's Notice Address … not defined in this amendment" (×2) | A3: "Capitalized terms not defined in this Amendment have the meanings given in the SLA, the Agreement, or the Standard Terms." The Notice Addresses are in A1 (Provider / Customer Information). |
| A3:2 "Uptime Target … not defined" | A2 2.1: "…(the "Uptime Target")" |
| A3:2 "Monthly Uptime Percentage … not defined" | A2 1.1: ""Monthly Uptime Percentage" means…" |
| B1 "No compliance clauses are present in the document" | B1 §5.1 data-breach notice within 24 hours and §7.1 insurance requirements are both compliance categories in Thor's own schema |

Real flags (9):
- A1 "No termination" (correct for A1's own text).
- A3: 2 unverified citations, and 4 amendment-wording flags.
- A3 "Downtime … not defined": true across the whole bundle, since A2 defines only "Downtime Minutes" and STD defines neither.
- B1 "No indemnity".

Missed ambiguities (no flag raised):
1. **A3 §2, the +5% credit:** "if Downtime in a single incident exceeds sixty (60) consecutive minutes … five percent (5%) of the Monthly Fee for that month". Two incidents in one month could mean one 5% credit or two. It is capped by A2 3.3 at 50%.
2. **Business vs calendar days:**
   - Several deadlines say only "days": A1 "30 days from invoice date" and "90 days"; A3 "fifteen (15) days" next to "ten (10) business days" in the same clause; B1 "45 days" and the "fifteen (15) days" cure.
   - None is flagged. In A2, Thor instead set `day_type: calendar` five times, although the text never says calendar days.
   - "First business day" (A1 §C, B1 §C) and A1 §D "StratoNode-observed holidays" refer to a holiday calendar that does not exist.
3. **B1 insurance lapse:** §7.2 makes a lapse "a material breach", which under STD 5.2(a) gives 30 days to cure ("fails to cure a material breach following 30 days' written notice"). §8.2 gives 15 days ("does not cure the lapse within fifteen (15) days"). Two cure periods apply to the same event.
4. **A2 3.4 sole remedy:** "sole and exclusive remedy … except as otherwise provided in the Agreement", while 6.1 grants termination "in addition to any Service Credits". Thor stored `sole_remedy: true` without the carve-out.

The bundle contains no literal "notwithstanding". The precedence ("controls") clauses were extracted correctly: A1 preamble, A1 §E, A2 preamble, A3 preamble.

### A7: amendment relations missing (FAIL)

| Contract text | Expected relation | In `doc_relations` |
|---|---|---|
| A3 §1: "Section 3.2 of the SLA is deleted in its entirety and replaced with the following" | A3 amends A2 → 3.2 (replace), effective 2027-01-01 | **absent** |
| A3 §2: "Section 3.1 of the SLA is deleted in its entirety and replaced with the following" | A3 amends A2 → 3.1 (replace) | **absent** |
| A3 §3: "Section B of the Cover Page (Contract ID: QH-STRATO-2026-001) is amended as follows" | A3 amends A1 → B (modify: 90 → 60 days) | **absent** |

What the system has instead:
- Extraction rows `cross_ref_1/2/3` carry the right `to_doc` and `scope`, plus `new_text`.
- They have no `ref_type`, so Thor's relation writer skipped them.
- The four "amendment wording … even after a re-check" flags record the gap.

Correct relations (verified against the text):
- **A1 incorporates STD** (A1 preamble: "incorporates by reference the … Standard Terms … maintained at STD.txt").
- **B1 incorporates STD** (same wording in B1).
- **A1 incorporates A2:** from A1 §E, the A2 preamble and the A3 preamble.
- **A2 references STD**, **A3 references STD §5.1**, **B1 references STD §5.1** and **STD §3.3**.
- A2 and A3 correctly do **not** incorporate STD; they only refer to it.

## 3. Top 5 fixes, by impact (not applied)

1. **Turn A3's amendments into `amends` edges.**
   - Require `ref_type` on every `cross_reference` field in Thor's output schema; a missing one triggers the existing re-prompt.
   - Derive `operation` and `target_clause` from wording such as "Section 3.2 of the SLA is deleted … and replaced" and "is amended". Store the effective date (2027-01-01) on the edge.
   - Then re-run A3. The main pass is cached; it costs about one follow-up call.
   - Without this, Loki and Norns treat A1's 90-day notice and A2's 30-day credit window as current after 2027-01-01.
2. **Recall check for numbers.** After extraction, assert that every percentage, money amount and duration in a clause appears in some extraction citing that clause. Re-extract the clauses that fail through the existing `reextract` / `handle_messages` path. This catches B1's 99.9% target, 20% cap and $2M/$3M limits, A2's maintenance limits and exclusions, and A3's "subject to the maximum credit in Section 3.3".
3. **Day types and ambiguity flags.** Keep `day_type` "unspecified" unless "business" or "calendar" qualifies the days (this fixes A2's five "calendar" values). Raise an `ambiguous` flag for unqualified day counts that drive deadlines or cures, for the +5% per-incident question, and for the B1 §7.2 / §8.2 vs STD 5.2(a) cure periods.
4. **Remove the false flags.**
   - Before saying a section is "not present", look it up in the resolved target document (A1 §B and STD §5.1 exist).
   - Don't raise "not defined in this amendment" when the document says its defined terms come from other documents; resolve them across the contract family instead.
   - Give the model the category hints that keep B1 from reporting "no compliance" while it has insurance and breach-notification duties.
5. **Complete and verbatim citations.**
   - Require a verified citation for each clause a value comes from: A2's penalties use 3.2–3.4 but cite only 3.1, and A2's effective date cites the closing for a date that is in the preamble.
   - Lower confidence when a numeric or date value appears in none of its verified quotes.
   - Re-ask A3:1 for verbatim quotes (the two failures dropped "(15)" and "(10)").

NO-GO: doc_relations has no "A3 amends A2/A1" edges, so Loki would review superseded terms (90-day notice, 30-day credit window) as if they were still in force.
