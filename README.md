# Odin: contract intelligence war room

Multi-agent system over the Quillhub contract bundle. **Step 1:** shared state, schemas,
LLM wrapper, config/limits, ingestion and **Thor** (extraction). **Step 2A:** the shared
state moves to **Supabase** (Postgres + private Storage), with document upload and a
"See the contract" viewer. **Step 3:** **Loki** reviews each contract as the counterparty's
lawyer. **Step 4:** **Heimdall** maps the event drops to contracts and clauses, reassesses
exposure through Norns, raises alerts and keeps a task board. Tyr and the rest of the
dashboard plug into the same state store.

| Agent | Role | Status |
|---|---|---|
| Odin | orchestrator | later |
| **Thor** | clause-cited extraction, cross-document references | **done** |
| **Norns** | timeline, simulated clock, worst case | **done** (A1, B1 families) |
| **Loki** | adversarial review per document (FR4.1, FR4.3); cross-contract conflicts and questions to Thor via `messages` later | **done** (per-document review) |
| **Heimdall** | event monitoring per drop (FR5.1), alerts (FR5.3), task board + progress tracker | **done** |
| Tyr | arbitration, drafted notices | later |

## Run it

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env              # then fill in provider, model, key (+ Supabase, see below)

# Supabase backend (STATE_BACKEND=supabase)
python scripts/db_migrate.py            # apply supabase/migrations/*.sql (safe to re-run)
python scripts/seed_bundle.py           # 8 contract pairs, context, ledger, holidays, clock, event files
python scripts/run_thor.py --details    # extract all 8 documents, print flags/relations
python scripts/run_thor.py --relink --docs A3   # re-derive relations from stored extractions (no LLM)
python scripts/clock.py checkpoint 1    # Norns: move the clock, recompute, store a snapshot
python scripts/clock.py play --step 7d --until 2027-06-01
python scripts/worst_case.py --checkpoint 2     # exposure items, chart data, writeup
python scripts/run_loki.py --docs A1,A2 --checkpoint 1   # Loki: adversarial review (--docs is required)
python scripts/run_heimdall.py --drop 1 --checkpoint 1   # Heimdall: events -> facts, alerts, task board
streamlit run app/Home.py               # upload + "See the contract" (/Contracts), task board (/Heimdall)

# Local backend (STATE_BACKEND=sqlite, the default): no migrate step, same commands otherwise
python scripts/run_thor.py --no-llm     # ingest + segment only, no API calls
python -m pytest -q                     # mocked LLM; Postgres/Storage tests run only if Supabase is configured
```

`run_thor.py` prints a per-document table and writes `outputs/thor/<doc_id>.json`,
`outputs/thor/_run_summary.json` and `outputs/state_export.json`. Re-running is
idempotent: a document whose sha256 is unchanged and whose last extraction completed is
skipped. Identical LLM calls are served from `.cache/llm/`, so `--force` re-runs are
free. A document added to `contracts/` later (e.g. by an event drop) is picked up and
only that document is extracted. Flags: `--docs A1,A3`, `--force`, `--workers N`
(parallel LLM calls, default 4), `--config path`.

Written with Python 3.11 features only; tested on 3.14 (the interpreter on the dev box).

## Environment (.env)

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER` | `anthropic` (Anthropic SDK) or `openai_compat` (OpenAI SDK: OpenAI, Gemini, Groq, OpenRouter, ...) |
| `LLM_MODEL` | model id; anthropic defaults to `claude-opus-5-5`, openai_compat requires it |
| `LLM_BASE_URL` | openai_compat endpoint (empty = api.openai.com). Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/`; Groq: `https://api.groq.com/openai/v1`; OpenRouter: `https://openrouter.ai/api/v1` |
| `LLM_API_KEY` (alias `ODIN_LLM_API_KEY`) | key for the chosen provider; falls back to `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |
| `LLM_EFFORT` | anthropic `output_config.effort` (default `high`) |
| `LLM_FALLBACKS` | anthropic server-side refusal fallback `fallbacks: "default"` (default on) |
| `LLM_JSON_MODE` | openai_compat `response_format=json_object` (default on, auto-disabled if rejected) |
| `ODIN_MAX_LLM_CALLS`, `ODIN_MAX_TOKENS_BUDGET` | override the run budget |
| `ODIN_CHUNK_MAX_CHARS` | Thor chunk size (default 9000; raise to ~14000 for large-context, high-limit providers) |
| `ODIN_BUNDLE_DIR`, `ODIN_DB_PATH`, `ODIN_OUTPUTS_DIR` | override paths |
| `STATE_BACKEND` | `sqlite` (default: `state/odin.db` + `state/files/`) or `supabase` (Postgres + Storage) |
| `SUPABASE_DB_URL` | Postgres connection string, **session pooler** (port 5432). Paste it as Supabase shows it: a password containing `@`, `/`, `#` ... is percent-encoded automatically |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_SECRET_KEY` | a secret key (`sb_secret_...`), used server-side only for Storage; never logged, never sent to the browser |
| `SUPABASE_BUCKET` | Storage bucket (default `contracts`, created private by `seed_bundle.py`) |
| `ODIN_MAX_UPLOAD_MB` | upload size limit (default 20) |
| `ODIN_FILES_DIR` | file store folder for the sqlite backend (default `state/files`) |

Everything else lives in `config.yaml`: limits (`max_llm_calls`, `max_tokens_budget`,
`max_retries`, `validation_retries`), loop limits for the later agents (`loops.*`) and
Thor's chunk size.

**temperature.** `temperature=0` is sent wherever the provider accepts it (all
openai_compat providers, older Claude models). Current Claude models (Opus 4.7+, Sonnet
5.x, Haiku 5.5, Fable) reject sampling parameters with a 400, so for them
reproducibility comes from the disk cache. The first answer is cached and replayed on
every re-run.

## Layout

```
odin/
  config.py            defaults < config.yaml < env; limits for every agent
  llm.py               LLMClient.call_json(prompt, Schema) -> validated object; retries, cache, budget
  citations.py         code-side quote verification (shared by Thor, Loki, Tyr)
  runtime.py           one (config, store, file store) per process
  viewer.py            get_contract_view(doc_id, clause_id, quote) + clause HTML, deep links
  state/models.py      pydantic row + value schemas
  state/store.py       StateStore interface + SQLite backend (state/odin.db) + JSON export
  state/postgres.py    Supabase Postgres backend (psycopg 3): retries, atomic transactions
  state/migrate.py     applies supabase/migrations in order, recorded in schema_migrations
  state/files.py       file stores: Supabase Storage (private bucket, signed URLs) / local folder
  state/backend.py     open_store(cfg), open_file_store(cfg) from STATE_BACKEND
  ingest/upload.py     ingest_file(file_bytes, filename): validate, dedup, store, PDF text, segment, Thor
  ingest/pdf.py        pdfplumber extraction (never raises) + text similarity
  ingest/bundle.py     seed the dev pack (contract pairs, context, ledger, holidays, clock, event files)
  ingest/loader.py     shared helpers + parsers for events/ledger/holidays/clock
  ingest/segmenter.py  deterministic clause segmentation with exact offsets
  agents/base.py       Agent: name, prompt files, trace logging, LLM hook
  agents/thor.py       extraction, verification, versioning, reextract, message handling
app/Home.py, app/pages/1_Contracts.py, app/ui.py   Streamlit: upload, document table, viewer
supabase/migrations/001_init.sql                   Postgres schema (all tables, RLS on)
prompts/thor_extract.md, prompts/thor_reextract.md, prompts/thor_crossref.md   (=== SYSTEM === / === USER === sections)
scripts/db_migrate.py, scripts/seed_bundle.py, scripts/run_thor.py, scripts/clock.py, scripts/worst_case.py
odin/effective.py      effective_clause(doc, clause, as_of): the clause version in force, following `amends` edges
odin/norns/            calendar.py, rules.py, engine.py (compute), clock.py, worst_case.py, writeup.py, report.py
supabase/migrations/002_norns.sql                  Norns tables
odin/agents/loki.py    review context, one LLM call per part, code checks, findings + workstream status
prompts/loki_review.md, scripts/run_loki.py, supabase/migrations/003_loki.sql   Loki prompt, CLI, table
odin/agents/heimdall.py  drop model, code-first + batched LLM mapping, Norns before/after, alerts, task board
prompts/heimdall_map.md, scripts/run_heimdall.py, supabase/migrations/004_heimdall.sql   Heimdall prompt, CLI, tables
app/pages/2_Heimdall.py, app/heimdall_tracker.py   alert strip, Kanban, progress tracker (no LLM)
docs/DATA_NOTES.md     numbering schemes, references, formats, day counting, traps
tests/
```

## Storage backends

`STATE_BACKEND` picks one of two implementations of the same `StateStore` interface
(`odin/state/store.py`). Every agent goes through its methods; no SQL lives outside
`odin/state`. The SQL is written once, in the subset both engines accept.

| | `supabase` | `sqlite` |
|---|---|---|
| state | Supabase Postgres via `SUPABASE_DB_URL` (psycopg 3, session pooler, autocommit + explicit transactions) | `state/odin.db` |
| schema | `supabase/migrations/*.sql`, applied by `scripts/db_migrate.py` | created / upgraded in place on open |
| files | private Storage bucket `contracts` (supabase-py, `SUPABASE_SECRET_KEY`) | `state/files/contracts/` |
| original in the viewer | signed URL, expires after 1 hour | bytes read by the server |

- **Retries.** Every Supabase call (SQL and Storage) is retried on connection errors with
  exponential backoff and a fresh connection. A connection lost inside a transaction is
  not retried piecemeal. The transaction rolls back and the error says so, so a document
  is never half-written. Each upload stores the file first and then writes all its rows in
  one transaction.
- **Unreachable Supabase** fails with a message naming the host (never the password) and
  telling you to set `STATE_BACKEND=sqlite`. Exit code 3 from the scripts.
- **Security.** Every table has row level security enabled with no policies, so the
  tables are not reachable through Supabase's public Data API. Odin connects
  server-side as the owner. The bucket is private. The browser only receives signed URLs.
- **Migrations.** `db_migrate.py` takes an advisory lock, runs each pending
  `NNN_name.sql` in its own transaction and records it (with a checksum) in
  `schema_migrations`. `--status` lists applied and pending migrations.
  `tests/test_migrations.py` checks that the SQLite schema and the migrations define the
  same tables and columns.

## Uploads (`odin/ingest/upload.py`)

`ingest_file(file_bytes, filename)` accepts `.pdf` and `.txt` up to `upload.max_upload_mb`:

1. **Dedup.** A file whose sha256 is already stored returns the existing document. No
   new row, no second upload, no re-extraction.
2. **Text.** A `.txt` is used as-is. A `.pdf` is read with pdfplumber. A PDF without a
   text layer (a scan) or one that cannot be opened is stored with
   `parse_status=unparseable`, `status=failed` and an `unparseable` flag. It never crashes,
   and Thor skips it.
3. **One document per contract.** The document ID is the filename stem (format_spec), so
   `A1.txt` + `A1.pdf` are one document. The `.txt` is the text source (canonical per
   format_spec; the dataset PDFs say so in their header) and the `.pdf` is the viewable
   original. A `.txt` arriving after a PDF-only upload takes over as the text source. A
   PDF whose text differs from its `.txt` (word similarity below 0.85) is flagged
   `contradictory`. The dataset pairs score 0.962–0.975.
4. **Storage.** `{doc_id}/{sha256}/{filename}` in the bucket is content-addressed, so a
   re-upload is idempotent and old versions stay. `document_files` lists every stored
   file of a document.
5. **Segment, then Thor.** Thor skips documents it already extracted completely, and its
   LLM cache makes repeated prompts free. The registry of documents in Thor's prompts is
   sorted by `doc_id`, so upload order never changes a prompt (or its cache key).

## Contract viewer and deep links

`odin.viewer.get_contract_view(doc_id, clause_id=None, quote=None)` returns the
document metadata, a signed URL for the original (1 hour), the text split into clauses
(each clause's own text, without its sub-clauses), Thor's current fields attached to the
clauses they cite (status, confidence, verified badge) and, for a deep link, the target.

`streamlit run app/Home.py` → **Contracts** page:

- upload widget (`ingest_file`, with progress per file);
- a document table (title, type, parse status, Thor status, fields, open flags) with
  **See the contract** per row;
- **Original** tab: the PDF embedded from its signed URL; the pdf.js viewer
  (`streamlit-pdf-viewer`) when framing is blocked or the store is local; a download
  button as the last fallback;
- **Clauses** tab: clause-by-clause text, Thor's field cards beside each clause, cited
  quotes underlined. Clicking a quote opens its deep link.

Deep link: `/Contracts?doc=A1&clause=A1:4.2&quote=...` opens the Clauses tab, scrolled to
the clause, with the quote highlighted. `clause` accepts `A1:4.2`, `4.2`, `§4.2` or
`Section B`. The quote is matched with the citation verifier's normalisation, so a
hard line wrap does not matter. Build links with `odin.viewer.contract_link(doc_id,
clause_id, quote)`; reports and the dashboard should link every citation this way.

## Shared state (Supabase Postgres, or state/odin.db)

Designed for all six agents; later agents add rows, not columns. JSON columns (`jsonb`
in Postgres) are noted. `outputs/state_export.json` holds every table.

| Table | Key columns | Notes |
|---|---|---|
| `documents` | `doc_id` (file stem), `title` (manifest), `text_title`, `path`, `sha256` (of the text source file), `kind` (contract / standard_terms / amendment / addendum), `status` (Thor: pending / extracting / complete / partial / failed), `status_reason`, `coverage` (% leaf clauses processed), `external_id` (printed CONTRACT/DOCUMENT ID), `source` (bundle / upload), `extracted_sha256`, **`text`** (full text; clause offsets index into it), **`text_source`** (txt / pdf_extracted), **`parse_status`** (parsed / fallback / unparseable), **`storage_path`**, **`original_filename`**, **`mime_type`** (the viewable original), **`uploaded_at`** | kind is classified from the document's own title/preamble |
| `document_files` | `doc_id`, `role` (text_source / original), `sha256`, `storage_path`, `original_filename`, `mime_type`, `size_bytes`, `similarity` (PDF vs .txt), `uploaded_at` | every stored file; dedup looks up `sha256` here |
| `clauses` | `clause_id` (`A1:4.2`, `B1:3.1`, `A1:I.1`, `D1:ExA.M1`, `A1:signatures`), `doc_id`, `number`, `ref` (as written: `§3.1`, `Section C`), `heading`, `text`, `char_start`, `char_end`, `level`, `parent_id` | `text == file_text[char_start:char_end]`; a section's span covers its sub-clauses |
| `extractions` | `id`, `doc_id`, `field_type`, `field_key`, `value` (JSON), `readings` (JSON), `raw_text`, `confidence`, `status` (extracted / ambiguous / missing / contradictory), `source_kind` (`sourced` = Thor, `analysis` = later agents), `agent`, `version`, `is_current`, `supersedes_id`, `run_id` | never overwritten: a correction is a new version; read `is_current=1` |
| `citations` | `extraction_id`, `doc_id`, `clause_id`, `clause_ref`, `quote` (exact .txt substring when verified), `llm_quote`, `llm_clause_id`, `char_start`, `char_end`, `verified`, `match_method` (exact / normalized / reattributed / none), `source_type` (clause; later: event / ledger / context) | |
| `flags` | `doc_id`, `clause_id`, `type` (ambiguous / missing / contradictory / unparseable / cross_reference / unverified_citation), `description`, `raised_by`, `extraction_id`, `evidence`, `evidence_verified`, `status` (open / resolved / superseded) | |
| `doc_relations` | `from_doc`, `to_doc`, `type` (incorporates / amends / supersedes / references / conflicts), `clause_id` (citing clause), `citation` (JSON: quote, offsets, target_clause, operation), `verified`, `raised_by` | Thor writes incorporates / amends / references; Loki adds supersedes / conflicts |
| `messages` | `id`, `from_agent`, `to_agent`, `type` (clarification_request / clarification_response / claim / verification / ruling / alert), `payload` (JSON), `status` (pending / processing / done / failed), `in_reply_to`, `workstream_id` | empty after step 1 |
| `workstreams` | `id` (`ws:A1`, `ws:cross_contract`), `scope`, `members` (JSON, discovered contract family), `agent_status` (JSON `{agent: status}`, merged per agent), `notes` | |
| `trace` | `ts`, `run_id`, `agent`, `action`, `input_ref`, `output_ref`, `tokens`, `duration_ms`, `error`, `meta` (JSON) | every LLM call (incl. cache hits and failed attempts), step and state transition |
| `resources` | `path` (bundle-relative), `kind` (manifest / company_context / ledger / holidays / events / clock), `sha256`, `storage_path`, `mime_type`, `size_bytes`, `text` (company context only) | |
| `ledger_entries`, `holidays`, `clock_checkpoints` | loaded by `seed_bundle.py` from `payments_ledger.csv`, `holidays.csv`, `clock.json` | inputs for Norns / Heimdall |
| `events` | one row per drop line | **empty until Heimdall**: seeding only stores `events/*.jsonl` in Storage (+ a `resources` row) |
| `schema_migrations` | `version`, `name`, `checksum`, `applied_at` | Postgres only |
| `obligation_rules` | `rule_id`, `contract`, `doc_id`, `kind` (payment / notice / renewal / report / cure / penalty_trigger / credit), `payer`, `payee`, `anchor`, `offset_*`, `day_type`, `recurrence`, `amount`, `formula`, `escalations`, `caps`, `conditions`, `valid_from` / `valid_to`, `citations` (Thor extraction ids + quotes), `flags` | Norns; rebuilt from extractions |
| `obligation_instances` | `as_of`, `instance_key`, `rule_id`, `period`, `due_date` (+ calendar / business variants), `amount`, `status` (paid_on_time / paid_late / partial / unpaid / upcoming / met / missed), `paid_amount`, `ledger_lines`, `days_remaining`, `severity`, `flags` | Norns; one set per stored `as_of` |
| `clock_state`, `clock_history` | the single current `as_of`; every move | `scripts/clock.py` |
| `timeline_snapshots` | `as_of`, `summary` (JSON), `chart_data` (JSON) | for the dashboard |
| `exposure_items` | `as_of`, `scenario` (worst_case / on_time), `contract`, `category`, `amount` (null = unquantified), `formula`, `inputs`, `citations`, `source_kind`='analysis' | `scripts/worst_case.py` |
| `writeups` | `as_of`, `label` ("AI-generated analysis" or template), `text`, `model`, `prompt_hash`, `check_passed` | |
| `loki_findings` | `doc_id`, `as_of`, `type` (ambiguity / one_sided / hidden_liability), `title`, `exploited_by`, `citations` (JSON: doc_id, clause_id, verbatim quote, offsets), `readings` (JSON, ambiguity only), `attack_path` (JSON), `severity` + `severity_reason`, `likelihood` + `likelihood_reason`, `confidence`, `impact` (JSON: Norns exposure item id + amount, or `"unquantified"`), `status` (accepted / rejected), `rejection_reason`, `model`, `source_kind`='analysis' | Loki; one set per (doc_id, as_of), a re-run replaces it |
| `heimdall_events` | `as_of`, `drop_name`, `line_no`, `event_id`, `raw`, `event_date`, `status` (mapped / unmapped / noise / unparseable) + `status_reason`, `type`, `doc_ids`, `clause_ids` (JSON), `fact` (JSON Norns fact), `is_noise` + `noise_reason`, `mapped_by` (code / llm), `confidence`, `potential_breach` + `breach_reason`, `exposure` (JSON: worst case before / after its fact, delta, delta per contract, changes) | Heimdall; one set per (as_of, drop), a re-run replaces it |
| `heimdall_alerts` | `as_of`, `alert_key` (contract\|clause\|kind\|due date), `severity`, `kind`, `contract`, `clause_id`, `due_date`, `message`, `citation` (JSON), `source` (norns / event) | rewritten by every reassessment |
| `heimdall_tasks` | `as_of`, `task_id` (Norns instance key), `title`, `contract`, `kind`, `due_date`, `amount`, `citation`, `status` (Not Complete / In Progress / Completed), `status_source` (norns / user), `norns_status`, `fact` (the user's payment_made fact) | the task board; status tags are the team's |

### Extraction values (`extractions.value` per `field_type`)

All keys are optional; an absent fact is omitted, never guessed. The models are in
`odin/state/models.py` (`FIELD_VALUE_MODELS`).

| field_type | value keys |
|---|---|
| party | name, role, address, notice_address, notice_email, contact, entity_type, jurisdiction |
| effective_date | raw, iso (absolute dates only), rule |
| term | duration_raw, duration_months, start_raw/iso, end_raw/iso, rule |
| renewal | auto_renew, renewal_term_raw/months, notice_period_raw/days, day_type, notice_method, notice_recipient, rule |
| payment | item, amount, currency, frequency, due_rule, payment_period_days, day_type, invoice_rule, late_fee_raw, interest_rate_raw, adjustment_raw |
| obligation | obligor, obligee, action, trigger, deadline_raw/amount/unit, day_type, recurring, condition |
| penalty | kind, trigger, amount_raw, formula, cap_raw, payer, beneficiary, claim_window_raw/days, day_type, sole_remedy |
| compliance | category, requirement, obligor, beneficiary, standard, window_raw/amount/unit, day_type |
| termination | kind, who_may_terminate, trigger, notice_period_raw, notice_days, cure_period_raw, cure_days, day_type, consequences |
| governing_law | law, courts |
| liability_cap | cap_raw, cap_formula, cap_amount, exclusions[], damages_waiver_raw |
| indemnity | indemnitor, indemnitee, scope, conditions |
| cross_reference | ref_type (incorporation / amendment / precedence / notwithstanding / reference), from_doc, to_doc, to_doc_resolved, target_clause, operation (replace / insert / delete / modify), new_text, old_value, new_value, controlling_doc, subordinate_doc, scope, effective_raw/iso |

`day_type` is `business` / `calendar` / `unspecified`, exactly as the text words it.
Relative deadlines stay as rules (`deadline_raw`, `rule`). Computing dates is the
Norns' job.

## Thor's guarantees

- **Citations are verified in code** (`odin/citations.py`): the quote must occur in the
  cited clause after normalising whitespace, quotes, dashes and case. On success the
  stored quote is the exact `.txt` substring with offsets. A quote cited at a section
  is narrowed to the sub-clause that contains it. A quote that is wrong-clause but
  unique in the document is re-attributed (`match_method=reattributed`). Anything else
  gets `verified=false`, confidence capped at 0.3, and an `unverified_citation` flag.
- **Never-infer rules** in `prompts/thor_extract.md`: missing means `status=missing`;
  two readings means `ambiguous` with both; clauses that disagree mean `contradictory`
  with both cited; ISO dates only for absolute dates. The schema enforces them
  (ambiguous needs 2 readings, contradictory needs 2 citations, non-missing needs a
  citation) and a violation is re-prompted.
- **Cross-document links are checked, not trusted.** A deterministic pre-scan marks
  clauses whose wording signals an amendment ("is deleted in its entirety", "is
  amended"), a precedence rule ("conflict … controls") or an incorporation
  ("incorporates by reference"). These clauses are listed in the prompt. If the reply
  has no matching `cross_reference` row for one, a small follow-up call
  (`prompts/thor_crossref.md`) re-sends only those clauses. Anything still uncovered
  becomes a `cross_reference` flag. A failed follow-up never discards the main answer.
- **No assumed edges.** A `doc_relations` row is written only if both documents are
  identified in the citing document's own text, by file name (`STD.txt`), printed ID
  (`QH-STRATO-2026-SLA`) or the target's own name when it has no ID ("Standard Terms").
  A model that maps a generic "DPA" onto B2 gets a `cross_reference` flag instead of an
  edge.
- **Status per document:** `complete` only when every chunk succeeded (coverage 100%);
  otherwise `partial` or `failed`, with `status_reason` naming the failed part.

### Step 2B fixes (after the audit, AUDIT_REPORT.md)

- **Amendments are relations.**
  - Every `cross_reference` row needs `ref_type` (incorporates / amends / references /
    precedence / notwithstanding); a missing one is re-prompted.
  - An `amends` row also needs `operation`, `target_doc`, `target_clause`, `new_text` and
    `effective_date`.
  - The target clause is resolved against the clauses table (`A2:3.2`, `A1:B`). An
    unresolved link is flagged and keeps the document from `complete` (`partial` with the
    reason).
  - `odin.effective.effective_clause(doc, clause, as_of)` returns the original clause
    before an amendment's effective date and the amended version (with the amending
    clause's extractions) from that date on.
  - `run_thor.py --relink` re-types rows stored before `ref_type` was required, using the
    amendment wording of the clause they cite, with no LLM call.
- **Recall check (code only).** After extraction, every amount, percentage, duration and
  frequency in a clause (including "fifteen (15) days"), every cap ("not exceed",
  "subject to the maximum") and every uncited exclusion list must appear in an
  extraction citing that clause. Otherwise the clause is re-extracted once
  (`thor.recall_max_reextracts_per_doc`), and whatever is still missing becomes a
  `missing` flag.
- **Day types.** `business` / `calendar` only when those words qualify the days ("30 days
  after the end of the calendar month" is `unspecified`). The code corrects the model, and
  every unspecified day count gets an `ambiguous` flag.
- **False flags.** A "section not present" or "term not defined" issue is checked against
  the related documents (doc_relations, documents named in the text, "capitalised terms
  have the meanings given in ...") and dropped when the section or definition exists. A
  re-run or re-extract replaces the old flags and edges of what it replaces.
- **Verbatim citations.** A quote that fails verification is re-asked once for an exact
  copy (numbers in words and digits). The verifier is unchanged. A plain
  `sole_remedy: true` keeps a stated carve-out ("except as otherwise provided in the
  Agreement") verbatim, with its citation.

## Norns (timeline agent)

All date and money logic is deterministic Python (`Decimal`, `relativedelta`, numpy
business days over the holidays table). The LLM is used only to normalise a due rule
Thor's fields leave open (validated, otherwise flagged) and for the short writeup.

- **Rules** (`odin/norns/rules.py`) come from Thor's current extractions of each contract
  family: A1 + A2 + A3 + STD, and B1 + B2 + STD.
  - Amended clauses give one rule per version: A1's renewal notice is 90 days until
    2026-12-31 and 60 days from 2027-01-01; A2's claim window is 30 days, then 15; the
    credit tiers gain +5% from 2027-01-01.
  - STD terms (late interest 4.4, suspension 2.2, cure 5.2(a)) apply wherever a contract
    incorporates STD.
  - Every rule cites the extraction ids and quotes it was built from.
- **Instances** run from each effective date to 12 months after the last checkpoint.
  - Monthly fees are invoiced on the first business day, with B1's +3% each anniversary.
  - Renewal-notice deadlines are computed both ways; the earlier date is used.
  - The B1 insurance-lapse notice is anchored on the policy expiry in company/context.txt.
- **`compute(as_of, facts=[])`** recomputes everything from scratch with only the ledger
  rows and facts dated on or before `as_of` (no future leakage), in about 10 ms.
  - Ledger rows are matched by contract ID, parties, billing month and amount. Statuses
    are paid_on_time, paid_late, partial, unpaid or upcoming. Unmatched rows are flagged,
    never dropped.
  - Facts (`payment_made`, `notice_sent`, `insurance_renewed`, `outage`) are the hook for
    Heimdall.
- **Clock** (`scripts/clock.py show | set | checkpoint | advance | play`): every move
  recomputes and stores instances and a snapshot. `play` reports what changed: newly
  overdue items, penalties triggered, deadlines passed, renewals locked in.
- **Worst case** (`scripts/worst_case.py`) assumes no action from `as_of` and compares it
  with acting on time; the gap is the avoidable exposure.
  - Quantified exposures:
    - late interest;
    - the A1 -> B1 cascade (StratoNode may suspend after 30 days unpaid, so Route
      Optimizer goes down, so B1 credits are owed);
    - renewal lock-in cost;
    - credits lost to a missed claim window.
  - Unquantified items, with citations: suspension and termination rights, insurance
    lapse, missed notices.
  - Caps and liability caps are applied. Each amount carries its formula, inputs and
    citations.
  - `chart_data` holds cumulative exposure for both scenarios, a contract × month
    matrix, deadlines, breakdowns and KPIs.
- **Writeup**: 150–250 words from the computed top items only.
  - Code checks every number and date against the computed data, with one retry, then a
    template.
  - It is stored as "AI-generated analysis" with the model name and prompt hash.

### Low-limit providers (Groq on-demand and similar)

Chunks default to 9,000 characters (about 6k input tokens per request) so each request
fits an 8k tokens/minute window. Rate-limit replies are retried after the wait the
provider asks for (`Retry-After`, "try again in Ns", or Groq's "Limit L, Requested R"
per-minute window, which Groq sometimes reports as a 413), up to
`limits.rate_limit_max_wait_s` (240 s). A longer requested wait (a daily cap) fails fast
with the provider's message. Rejected attempts don't count against `max_llm_calls`. Run
with `--workers 1` on such tiers: parallel calls only compete for the same window. A
reasoning model like gpt-oss spends 10–25k output tokens per call, so on an 8k/min tier
expect about 3 minutes per call.

## Loki (adversarial review agent)

Loki reads one contract at a time as the counterparty's lawyer and reports ambiguous
clauses, one-sided terms and hidden liabilities (FR4.1). Every finding has clause
citations, an attack path, and a severity and likelihood on fixed scales (FR4.3).

```bash
python scripts/db_migrate.py                              # Supabase: adds loki_findings (003_loki.sql)
python scripts/run_loki.py --docs A1,A2 --checkpoint 1    # or --as-of 2027-03-15
```

- **Review units.** Contracts and addenda (A1, A2, B1, ...). Amendments (A3) and standard
  terms (STD) are not reviewed on their own: their text is reviewed inside the documents
  they amend or that incorporate them. `--docs` is required; there is no "all" default.
- **Context** (`Loki.build_review_context(doc_id, as_of)`, read-only):
  - title, parties and the counterparty (the party that isn't Quillhub), from Thor's party
    fields;
  - every clause in force on as_of via `effective_clause()`. Amended text appears under the
    amendment's own clause id (A3:1 replaces A2 3.2; A3:3 modifies A1 §B, shown beside it);
  - the Standard Terms: all of them if the document incorporates STD (A1), only the cited
    clauses if it merely references STD (A2: the Force Majeure definition);
  - Thor's open flags and an index of its extractions as hints, one line each. An extraction
    that cites only replaced text is left out;
  - company/context.txt, trimmed to about 600 tokens.
- **Split.** Each call stays under about 6,000 input tokens (`loki.max_input_tokens`,
  estimated at `loki.chars_per_token`; Thor's logged Groq calls measured 4.3 characters per
  token). A larger document is split by top-level section, with incorporated STD in its own
  part(s). `run_loki.py` prints the parts and their estimated sizes.
- **Prompt** (`prompts/loki_review.md`): the definitions, the rules (clause text is the
  authority, Thor's output is only hints, verbatim quotes, exact clause ids, nothing
  invented), at most 8 findings, and the scales. The scales are also code constants
  (`SEVERITY_SCALE`, `LIKELIHOOD_SCALE`), and Loki refuses a prompt file that does not state
  them word for word.
- **Code checks** (no LLM). A finding that fails is stored as `rejected` with the reason,
  never re-prompted:
  - every citation is verified with Thor's verifier, limited to the text in force (a quote
    from a replaced clause fails). Unverified citations are dropped, and a finding left with
    none is rejected;
  - a clause id in the attack path must exist in the store, and the path must name at least
    one;
  - every amount, percentage, duration or date in the title or attack path must appear in
    the cited clauses (or be the as_of date). Clause ids and step numbers are ignored;
  - an ambiguity needs at least 2 readings. Type, severity and likelihood must be on their
    scales, titles have at most 15 words, attack paths have 2–5 steps;
  - findings with the same type and the same set of cited clauses are merged, keeping the
    higher severity. Then at most 8 per document are kept, most severe first;
  - impact is the Norns `exposure_items` row at the same as_of that cites one of the
    finding's clauses (its id and amount), otherwise `"unquantified"`. Loki never computes
    an amount.
- **Bookkeeping.** A re-run for the same document and as_of replaces its findings (when no
  call succeeds, earlier findings are kept). Loki's status per document goes into the
  workstreams that contain it (`agent_status["loki:A1"]`, plus `"loki"` for the family, with
  the reason in `notes`). `complete` means every call succeeded and the checks ran;
  otherwise `partial` or `failed`. Each run writes `outputs/loki/<doc_id>_<as_of>.json`.
  Real LLM calls per process are capped by `loki.max_llm_calls` (default 5).

## Heimdall (event monitoring + task board)

Heimdall reads the event drops, maps each event to the contracts and clauses it affects and
reassesses exposure through Norns (FR5.1). It raises severity-rated alerts and filters out
noise (FR5.3), and keeps a task board with a progress tracker in Streamlit.

```bash
python scripts/db_migrate.py                              # Supabase: adds the heimdall_* tables (004_heimdall.sql)
python scripts/run_heimdall.py --drop 1 --checkpoint 1    # or --as-of 2027-03-15; --no-llm for code mapping only
streamlit run app/Home.py                                 # Heimdall page: /Heimdall
```

- **Drop model.** A drop is processed only once it is released: drop *k* at checkpoint *k*
  (`heimdall.drop_release_checkpoints`). format_spec only calls drop 1 the initial analysis and
  drop 2 the mid-cycle update. Only events dated on or before the clock date are visible. The
  file is read from Storage (the copy `seed_bundle.py` stored), else from `bundle/events`. An
  unparseable line is stored with `status=unparseable` and the parser's reason.
- **Mapping, code first.** Printed contract IDs, counterparty names and e-mail domains (from
  Thor's party fields) name the contract. Code classifies structured messages:
  - a provider's status-page outage becomes an `outage` fact, with clauses from Norns' credit
    rules in force on the incident date;
  - an uptime report where every target is met is noise;
  - an invoice or a payment confirmation is matched to Norns' payment instance by contract,
    amount and billing month;
  - a marketing mail is noise.

  The rest goes to the LLM (`prompts/heimdall_map.md`), up to 10 events per call. Each call
  carries the contracts, the clause ids of the contracts those events name, and the events.
  A document or clause id the reply invents leaves the event `unmapped`, with the reason. So
  does an invalid fact (an unknown contract, a date after the clock date, a non-positive amount).
- **Groq limits** (`config.heimdall`): `max_tokens` 3,000, estimated input + max_tokens at most
  7,000 per call (batches are split to fit), at most 7,500 tokens per rolling minute (Heimdall
  waits before a call that would exceed it), and `reasoning_effort="low"` (`llm.py` sends it to
  openai_compat providers and drops it if rejected). At most 4 real calls per process.
- **Exposure.** Mapped events become Norns facts (`payment_made`, `outage`, `notice_sent`).
  `norns.compute(as_of)` runs without facts, then adds one event's fact at a time in date order.
  Each event stores the worst-case total before and after its fact, the delta, the delta per
  contract and what changed in Norns' instances. A fact that changes no instance and no
  exposure turns its event into noise, and so does a fact that repeats an earlier one. A new
  credit Quillhub owes, a suspension right or an insurance-lapse breach marks the event as a
  potential breach.
- **Alerts** (fixed scale, `SEVERITY_SCALE`):
  - critical: a potential breach, a suspension or termination right that is now open, or an
    overdue payment;
  - high: due within 7 days, or a renewal-notice deadline within 30 days;
  - medium: due within 30 days;
  - low: informational.

  Alerts come from Norns' payments, renewals, credit-claim windows and other deadlines on the
  clock date (within 60 days, and always for renewals), plus events that indicate a potential
  breach. They are de-duplicated by (contract, clause, kind, due date), and each has a
  one-line message and a clause citation. Noise is stored, hidden, with its reason.
- **Task board.** One card per Norns instance that is overdue, due or upcoming within 60 days
  (`task_id` = the instance key). Instances Norns marks paid or met start `Completed`
  (`status_source=norns`) and cannot be changed. When a payment card is set to Completed, the
  board records a `payment_made` fact on the clock date (`source="user"`) and recomputes
  Norns, so the worst-case total updates. Moving the card back removes the fact.
- **Page** (`app/pages/2_Heimdall.py`) shows:
  - the clock date, the live worst-case total and the alert strip, with a "show filtered
    noise" toggle;
  - the Kanban (Not Complete / In Progress / Completed). Each card has its due date and days
    left, amount, severity badge and a "See the contract" deep link. "Set status" saves the
    tag at once;
  - the progress tracker (`st.components.v1.html`): one row per contract, its tasks as dots.

  The page re-reads the database after every change and every 10 seconds
  (`streamlit-autorefresh`). It never calls the LLM: it constructs Heimdall without an LLM
  client.

## For the next agents

```python
from odin.config import load_config
from odin.state.backend import open_store
cfg = load_config(); store = open_store(cfg)    # Supabase or SQLite, per STATE_BACKEND

store.current_extractions("A1")                 # current facts for a document
store.citations_for(extraction_id)              # verified quotes + offsets
store.list_relations()                          # discovered document graph
store.list_flags(status="open")
```

Loki asks Thor about one clause through the messages table:

```python
store.post_message(Message(from_agent="loki", to_agent="thor", type="clarification_request",
    payload={"doc_id": "A1", "clause_id": "A1:B", "question": "Is the 90-day notice still in force?"}))
Thor(store, llm, cfg).handle_messages()   # re-reads only A1:B, writes new versions, replies
store.pending_messages("loki", "clarification_response")
```

New agents subclass `odin.agents.base.Agent` (name, `prompt_files`, `self.log(...)`,
`self.call_json(...)`), write `source_kind="analysis"` extractions, and use
`odin.citations.verify_citation` for any quote they surface.

---

## Project Status & Implemented Features (Current Progress)

### 1. What's Done So Far
- **Core Multi-Agent Architecture**:
  - `odin/agents/base.py`: Extensible base agent architecture with structured logging, prompt rendering (`prompts/`), token-budget accounting, and hookable LLM orchestration.
  - `odin/agents/thor.py`: Production-grade **Thor (Extraction & Grounding Agent)** capable of clause segmentation, field extraction, rigorous citation verification, versioned overwrites, and message-driven query handling.
- **Contract Ingestion & Deterministic Segmentation**:
  - `odin/ingest/loader.py`: Bundle ingestion for contracts, company background, event drops, payment ledgers, holidays, and simulated clocks.
  - `odin/ingest/segmenter.py`: Deterministic parser segmenting contracts into hierarchical clauses/sections with character-exact offsets.
- **Resilient Dual-Engine LLM Wrapper**:
  - `odin/llm.py`: Unified adapter for Anthropic Claude SDK and OpenAI-compatible endpoints (Gemini, Groq, OpenRouter, etc.). Includes disk caching (`.cache/llm/`), retry logic with exponential backoff, rate-limit window handling, and Pydantic schema validation.
- **Shared Relational State Store (SQLite + JSON Export)**:
  - `odin/state/store.py` & `odin/state/models.py`: Enterprise relational schema tracking `documents`, `clauses`, `extractions`, `citations`, `flags`, `doc_relations`, `messages`, `workstreams`, and audit `trace`.
  - Export system: Dumps complete multi-agent relational state into `outputs/state_export.json` (30,000+ lines).
- **Automated Clause Citation Verification**:
  - `odin/citations.py`: Code-level grounding preventing LLM hallucination. Quotes must match clause text with offset mapping; unverified quotes are flagged and confidence-capped.
- **Comprehensive Test Suite**:
  - `tests/`: 66 unit tests validating segmenter accuracy, citation normalization, LLM retry mechanisms, and Thor multi-pass extraction pipelines.

### 2. Thor Execution & Extraction Benchmark

The Thor extraction pipeline was executed over the Quillhub contract bundle with the following results:

| Document | Type / Role | Clauses | Extracted Fields | Citations Verified | Status |
|---|---|:---:|:---:|:---:|:---:|
| **STD** | Standard Terms of Service | 92 | 70 | 67 | **Complete** (100% coverage) |
| **A1** | Primary Service Agreement | 16 | 22 | 22 | **Complete** (100% coverage) |
| **A2** | Service Level Agreement (SLA) | 25 | 19 | 19 | **Complete** (100% coverage) |
| **A3** | SLA Amendment 1 | 7 | 15 | 13 | **Complete** (100% coverage) |
| **B1** | Enterprise Addendum | 29 | 31 | 33 | **Complete** (100% coverage) |
| **B2** | Data Processing Addendum (DPA) | 32 | 48 | 48 | **Complete** (100% coverage) |
| **C1** | Schedule C (Pricing & Billing) | 20 | 19 | 20 | **Complete** (100% coverage) |
| **D1** | Master Professional Services Agreement | 55 | - | - | *Pending rerun (hit provider daily TPD limit)* |

- **Outputs Generated**:
  - Individual document extraction outputs: `outputs/thor/<doc_id>.json`
  - High-level pipeline execution audit: `outputs/thor/_run_summary.json`
  - Complete state database export: `outputs/state_export.json`

### 3. Agent Workflow & Next Phase Roadmap

```
+-----------------------------------------------------------------------------------+
|                                 ODIN ORCHESTRATOR                                 |
+-----------------------------------------------------------------------------------+
       |                                |                             |
       v                                v                             v
+--------------+               +------------------+           +---------------+
|     THOR     | <---msgs--->  |       LOKI       |           |     NORNS     |
| (Extraction) |               |  (Cross-Contract |           |  (Timeline &  |
|   [ACTIVE]   |               | Conflicts/Audit) |           |  Sim Clock)   |
+--------------+               +------------------+           +---------------+
       |                                |                             |
       +--------------------------------+-----------------------------+
                                        |
                                        v
                       +----------------------------------+
                       |    SHARED STATE (odin.db)        |
                       |  - documents    - extractions    |
                       |  - clauses      - citations      |
                       |  - flags        - relations      |
                       +----------------------------------+
                                        |
                       +----------------+----------------+
                       |                                 |
                       v                                 v
               +---------------+                 +---------------+
               |   HEIMDALL    |                 |      TYR      |
               | (Event Drops  |                 | (Arbitration &|
               |  Monitoring)  |                 | Notice Draft) |
               +---------------+                 +---------------+
```

- **Phase 1 (Complete)**: Thor extraction, document segmentation, citation verification, shared state store, LLM caching & rate-limit resilience.
- **Phase 2 (Upcoming)**:
  - **Loki**: Adversarial cross-contract audit to identify superseding terms, conflicting liability caps, and silent amendments.
  - **Norns**: Timeline engine that simulates the contract clock and calculates absolute deadlines from relative rules.
  - **Heimdall**: Dynamic event processor reacting to incoming drops (`events_drop1.jsonl`, `events_drop2.jsonl`).
  - **Tyr**: Automated dispute resolution, arbitration decision engine, and legal notice generation.

