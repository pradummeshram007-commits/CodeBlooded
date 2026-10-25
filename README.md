# Odin: contract intelligence war room

Multi-agent system over the Quillhub contract bundle. **Step 1 (this commit):** shared
state, schemas, LLM wrapper, config/limits, ingestion and **Thor** (extraction). Norns,
Loki, Heimdall, Tyr and the dashboard plug into the same state store.

| Agent | Role | Status |
|---|---|---|
| Odin | orchestrator | later |
| **Thor** | clause-cited extraction, cross-document references | **done** |
| Norns | timeline + simulated clock | later |
| Loki | adversarial review, cross-contract conflicts; asks Thor via `messages` | later |
| Heimdall | event monitoring per drop | later |
| Tyr | arbitration, drafted notices | later |

## Run it

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env              # then fill in provider, model, key

python scripts/run_thor.py --no-llm     # ingest + segment only, no API calls
python scripts/run_thor.py --details    # extract all 8 documents, print flags/relations
python -m pytest -q                     # tests use a mocked LLM, no network
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
  state/models.py      pydantic row + value schemas
  state/store.py       SQLite StateStore (state/odin.db) + JSON export
  ingest/loader.py     manifest, company context, contracts; loaders for events/ledger/holidays/clock
  ingest/segmenter.py  deterministic clause segmentation with exact offsets
  agents/base.py       Agent: name, prompt files, trace logging, LLM hook
  agents/thor.py       extraction, verification, versioning, reextract, message handling
prompts/thor_extract.md, prompts/thor_reextract.md, prompts/thor_crossref.md   (=== SYSTEM === / === USER === sections)
scripts/run_thor.py
docs/DATA_NOTES.md     numbering schemes, references, formats, day counting, traps
tests/
```

## Shared state (state/odin.db)

Designed for all six agents; later agents add rows, not columns. JSON columns are
noted. `outputs/state_export.json` holds every table.

| Table | Key columns | Notes |
|---|---|---|
| `documents` | `doc_id` (file stem), `title` (manifest), `text_title`, `path`, `sha256`, `kind` (contract / standard_terms / amendment / addendum), `status` (pending / extracting / complete / partial / failed), `status_reason`, `coverage` (% leaf clauses processed), `external_id` (printed CONTRACT/DOCUMENT ID), `source`, `extracted_sha256` | kind is classified from the document's own title/preamble |
| `clauses` | `clause_id` (`A1:4.2`, `B1:3.1`, `A1:I.1`, `D1:ExA.M1`, `A1:signatures`), `doc_id`, `number`, `ref` (as written: `§3.1`, `Section C`), `heading`, `text`, `char_start`, `char_end`, `level`, `parent_id` | `text == file_text[char_start:char_end]`; a section's span covers its sub-clauses |
| `extractions` | `id`, `doc_id`, `field_type`, `field_key`, `value` (JSON), `readings` (JSON), `raw_text`, `confidence`, `status` (extracted / ambiguous / missing / contradictory), `source_kind` (`sourced` = Thor, `analysis` = later agents), `agent`, `version`, `is_current`, `supersedes_id`, `run_id` | never overwritten: a correction is a new version; read `is_current=1` |
| `citations` | `extraction_id`, `doc_id`, `clause_id`, `clause_ref`, `quote` (exact .txt substring when verified), `llm_quote`, `llm_clause_id`, `char_start`, `char_end`, `verified`, `match_method` (exact / normalized / reattributed / none), `source_type` (clause; later: event / ledger / context) | |
| `flags` | `doc_id`, `clause_id`, `type` (ambiguous / missing / contradictory / unparseable / cross_reference / unverified_citation), `description`, `raised_by`, `extraction_id`, `evidence`, `evidence_verified`, `status` (open / resolved / superseded) | |
| `doc_relations` | `from_doc`, `to_doc`, `type` (incorporates / amends / supersedes / references / conflicts), `clause_id` (citing clause), `citation` (JSON: quote, offsets, target_clause, operation), `verified`, `raised_by` | Thor writes incorporates / amends / references; Loki adds supersedes / conflicts |
| `messages` | `id`, `from_agent`, `to_agent`, `type` (clarification_request / clarification_response / claim / verification / ruling / alert), `payload` (JSON), `status` (pending / processing / done / failed), `in_reply_to`, `workstream_id` | empty after step 1 |
| `workstreams` | `id` (`ws:A1`, `ws:cross_contract`), `scope`, `members` (JSON, discovered contract family), `agent_status` (JSON `{agent: status}`, merged per agent), `notes` | |
| `trace` | `ts`, `run_id`, `agent`, `action`, `input_ref`, `output_ref`, `tokens`, `duration_ms`, `error`, `meta` (JSON) | every LLM call (incl. cache hits and failed attempts), step and state transition |
| `resources`, `events`, `ledger`, `holidays`, `checkpoints` | inputs for Norns/Heimdall | loader functions exist in `ingest/loader.py`; step 1 only registers the files |

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

## For the next agents

```python
from odin.config import load_config
from odin.state.store import StateStore
cfg = load_config(); store = StateStore(cfg.paths.db_path)

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
