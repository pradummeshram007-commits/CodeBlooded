from __future__ import annotations

import json

from odin.agents.thor import CONFIDENCE_CAP_UNVERIFIED, Thor
from odin.llm import LLMError, RetryableError
from odin.state.models import FIELD_TYPES, Message

from .conftest import A3_ALL, A3_RELATIONS_ONLY_SLA, doc_id_of, field, make_llm, reply

GOOD = "Monthly Fee:     $8,000.00 (Eight Thousand U.S. Dollars)"
FAKE = "Monthly Fee: $9,500.00 payable weekly"


def a1_responder(system, messages):
    assert doc_id_of(messages) == "A1"
    return reply(
        [
            field("payment", "monthly_fee", {"item": "Monthly Fee", "amount": 8000, "currency": "USD"},
                  [("A1:C", GOOD)]),
            field("payment", "weekly_fee", {"item": "Weekly Fee", "amount": 9500}, [("A1:C", FAKE)], confidence=0.95),
            field("cross_reference", "incorporates_standard_terms",
                  {"ref_type": "incorporates", "from_doc": "A1", "to_doc": "STD.txt", "to_doc_resolved": True},
                  [("A1:preamble", "This Cover Page incorporates by reference the Common Paper Cloud Service Agreement")]),
            field("cross_reference", "incorporates_sla",
                  {"ref_type": "incorporates", "from_doc": "A1", "to_doc": "QH-STRATO-2026-SLA"},
                  [("A1:E", "which is incorporated into this Agreement by reference")]),
            field("renewal", "renewal", None, [("A1:B", "Non-Renewal Notice Period: 90 days before the end")],
                  status="ambiguous",
                  readings=[{"interpretation": "90 calendar days", "value": {"notice_period_days": 90, "day_type": "calendar"}},
                            {"interpretation": "90 business days", "value": {"notice_period_days": 90, "day_type": "business"}}]),
            field("governing_law", "governing_law", None, [], status="missing", confidence=0.4),
        ],
        issues=[{"type": "cross_reference", "clause_id": "A1:E", "quote": "document QH-STRATO-2026-SLA",
                 "description": "SLA is a separate document"}],
    )


def test_citations_are_verified_in_code_and_failures_capped(ingested, cfg) -> None:
    llm, _ = make_llm(cfg, a1_responder)
    [res] = Thor(ingested, llm, cfg).run(["A1"], workers=1)
    assert res.status == "complete" and res.coverage == 100.0

    exs = {e.field_key: e for e in ingested.current_extractions("A1")}
    good = ingested.citations_for(exs["monthly_fee"].id)[0]
    assert good.verified and good.match_method == "exact"
    assert good.quote == GOOD and good.char_start is not None
    assert exs["monthly_fee"].confidence == 0.9

    bad = ingested.citations_for(exs["weekly_fee"].id)[0]
    assert not bad.verified and bad.char_start is None
    assert exs["weekly_fee"].confidence == CONFIDENCE_CAP_UNVERIFIED

    flags = ingested.list_flags("A1")
    unverified = [f for f in flags if f.type == "unverified_citation"]
    assert len(unverified) == 1 and unverified[0].extraction_id == exs["weekly_fee"].id
    assert any(f.type == "ambiguous" and f.extraction_id == exs["renewal"].id for f in flags)
    assert any(f.type == "missing" and "governing law" in f.description for f in flags)  # core field on a contract
    assert any(f.type == "cross_reference" and f.evidence_verified for f in flags)        # LLM issue, verified quote


def test_every_field_type_is_represented_and_missing_is_recorded(ingested, cfg) -> None:
    llm, _ = make_llm(cfg, a1_responder)
    Thor(ingested, llm, cfg).run(["A1"], workers=1)
    exs = ingested.current_extractions("A1")
    assert {e.field_type for e in exs} == set(FIELD_TYPES)
    gl = [e for e in exs if e.field_type == "governing_law"]
    assert len(gl) == 1 and gl[0].status == "missing" and not ingested.citations_for(gl[0].id)


def test_relations_are_resolved_from_the_documents_own_ids(ingested, cfg) -> None:
    llm, _ = make_llm(cfg, a1_responder)
    Thor(ingested, llm, cfg).run(["A1"], workers=1)
    rels = {(r.from_doc, r.type, r.to_doc): r for r in ingested.list_relations()}
    assert ("A1", "incorporates", "STD") in rels         # resolved from "STD.txt"
    assert ("A1", "incorporates", "A2") in rels          # resolved from the printed ID QH-STRATO-2026-SLA
    assert all(r.verified for r in rels.values())


def test_links_the_text_never_identifies_are_not_recorded(ingested, cfg) -> None:
    # STD only mentions a generic "DPA"; mapping it to B2 would be an assumption.
    bad = reply([field("cross_reference", "dpa_reference", {"ref_type": "references", "from_doc": "STD", "to_doc": "B2"},
                       [("STD:3.1", "If the parties have a DPA, each party will comply with its obligations in the DPA")])])
    llm, _ = make_llm(cfg, lambda s, m: bad)
    Thor(ingested, llm, cfg).run(["STD"], workers=1)
    assert not [r for r in ingested.list_relations() if r.to_doc == "B2"]
    assert any("never identified in STD" in f.description for f in ingested.list_flags("STD"))


def test_incorporation_direction_follows_the_quoted_grammar(ingested, cfg) -> None:
    # "This Addendum is incorporated into ... the Agreement": B1 incorporates B2, whatever the model wrote.
    flipped = reply([field("cross_reference", "addendum_part_of_agreement",
                           {"ref_type": "incorporates", "from_doc": "B2", "to_doc": "QH-HARBOR-2026-001"},
                           [("B2:preamble", "This Addendum is incorporated into and forms part of the Agreement.")])])
    llm, _ = make_llm(cfg, lambda s, m: flipped)
    Thor(ingested, llm, cfg).run(["B2"], workers=1)
    [rel] = [r for r in ingested.list_relations() if r.type == "incorporates"]
    assert (rel.from_doc, rel.to_doc) == ("B1", "B2") and rel.citation["direction_corrected"]


def test_target_clause_must_exist_in_the_target(ingested, cfg) -> None:
    wrong = reply([field("cross_reference", "unlimited_claims_ref",
                         {"ref_type": "references", "from_doc": "B2", "to_doc": "STD", "target_clause": "Section J"},
                         [("B2:8.1", "Unlimited Claims as specified in Section J of the Cover Page")]),
                   field("cross_reference", "breach_definition",
                         {"ref_type": "references", "from_doc": "B2", "to_doc": "B1", "target_clause": "Section 5.1"},
                         [("B2:3.1", "as defined in Section 5.1 of the Agreement")])])
    llm, _ = make_llm(cfg, lambda s, m: wrong)
    Thor(ingested, llm, cfg).run(["B2"], workers=1)
    rels = {r.to_doc: r for r in ingested.list_relations() if r.type == "references"}
    assert rels["STD"].citation["target_clause"] is None and rels["STD"].citation["target_clause_raw"] == "Section J"
    assert rels["B1"].citation["target_clause_id"] == "B1:5.1" and rels["B1"].citation["target_clause"] == "§5.1"
    assert any("'Section J' is not a clause of STD" in f.description for f in ingested.list_flags("B2"))


def test_target_clause_must_be_named_by_the_citing_clause(ingested, cfg) -> None:
    # B2 §5.1 talks about termination of "the Agreement" but never names B1 §5.1.
    confused = reply([field("cross_reference", "retention_ref",
                            {"ref_type": "references", "from_doc": "B2", "to_doc": "B1", "target_clause": "Section 5.1"},
                            [("B2:5.1", "Upon termination or expiration of the Agreement")])])
    llm, _ = make_llm(cfg, lambda s, m: confused)
    Thor(ingested, llm, cfg).run(["B2"], workers=1)
    [rel] = [r for r in ingested.list_relations() if r.type == "references"]
    assert rel.to_doc == "B1" and rel.citation["target_clause"] is None


def test_unrelated_issue_does_not_excuse_a_missed_amendment(ingested, cfg) -> None:
    main = reply(A3_RELATIONS_ONLY_SLA, issues=[
        {"type": "missing", "clause_id": "A3:3", "quote": "Notice Address", "description": "term defined elsewhere"}])
    llm, provider = make_llm(cfg, lambda s, m: main if len(provider.calls) == 1 else reply(A3_ALL))
    Thor(ingested, llm, cfg).run(["A3"], workers=1)
    assert "[[A3:3]]" in provider.calls[1][0]["content"]          # A3:3 still sent to the follow-up
    assert ("A3", "amends", "A1") in {(r.from_doc, r.type, r.to_doc) for r in ingested.list_relations()}


def test_invalid_model_output_is_reprompted(ingested, cfg) -> None:
    links = [field("cross_reference", "incorporates_std", {"ref_type": "incorporates", "to_doc": "STD.txt"},
                   [("A1:preamble", "This Cover Page incorporates by reference the Common Paper Cloud Service Agreement")]),
             field("cross_reference", "incorporates_sla", {"ref_type": "incorporates", "to_doc": "QH-STRATO-2026-SLA"},
                   [("A1:E", "which is incorporated into this Agreement by reference")])]
    replies = [
        # 'extracted' without citations violates the schema rules -> re-prompt
        reply([field("payment", "monthly_fee", {"amount": 8000}, [])]),
        reply([field("payment", "monthly_fee", {"amount": 8000}, [("A1:C", GOOD)])] + links),
    ]
    llm, provider = make_llm(cfg, lambda s, m: replies[min(len(provider.calls) - 1, 1)])
    [res] = Thor(ingested, llm, cfg).run(["A1"], workers=1)
    assert res.status == "complete"
    assert "no citations" in provider.calls[1][-1]["content"]
    assert ingested.citations_for(next(e for e in ingested.current_extractions("A1")
                                       if e.field_key == "monthly_fee").id)[0].verified


def test_cue_check_reprompts_for_missed_links(ingested, cfg) -> None:
    replies = [reply(A3_RELATIONS_ONLY_SLA), reply(A3_ALL)]
    llm, provider = make_llm(cfg, lambda s, m: replies[min(len(provider.calls) - 1, 1)])
    Thor(ingested, llm, cfg).run(["A3"], workers=1)
    first_prompt = provider.calls[0][0]["content"]
    assert "A3:3: amendment" in first_prompt                      # pre-scan listed in the prompt
    followup = provider.calls[1]
    assert len(followup) == 1                                      # a fresh small request, not the whole conversation
    assert "A3:3: amendment wording" in followup[0]["content"] and "[[A3:3]]" in followup[0]["content"]
    assert "[[A3:1]]" not in followup[0]["content"]                # already covered by the first reply
    rels = {(r.from_doc, r.type, r.to_doc) for r in ingested.list_relations()}
    # A link stated by A3 between two other documents keeps its real direction.
    assert {("A3", "amends", "A2"), ("A3", "amends", "A1"), ("A1", "incorporates", "A2")} <= rels
    assert not [f for f in ingested.list_flags("A3") if "even after a re-check" in f.description]


def test_cues_still_missing_after_recheck_become_flags(ingested, cfg) -> None:
    llm, provider = make_llm(cfg, lambda s, m: reply(A3_RELATIONS_ONLY_SLA))
    Thor(ingested, llm, cfg).run(["A3"], workers=1)
    assert len(provider.calls) == 2                               # one re-check only, then accept
    leftover = [f for f in ingested.list_flags("A3") if "even after a re-check" in f.description]
    assert {f.clause_id for f in leftover} >= {"A3:2", "A3:3"}
    # A stated amendment that never became an edge keeps the document from "complete".
    doc = ingested.get_document("A3")
    assert doc.status == "partial" and "unresolved cross-reference" in doc.status_reason and "A3:3" in doc.status_reason


def test_failed_followup_keeps_the_main_answer(ingested, cfg) -> None:
    cfg.limits.max_retries = 0

    def responder(system, messages):
        if "# Follow-up" in messages[0]["content"]:
            raise LLMError("openai_compat status 413: request too large")
        return reply(A3_RELATIONS_ONLY_SLA)

    llm, _ = make_llm(cfg, responder)
    [res] = Thor(ingested, llm, cfg).run(["A3"], workers=1)
    assert res.status == "partial" and res.citations_verified >= 1       # main answer kept, links still missing
    assert any("even after a re-check" in f.description for f in ingested.list_flags("A3"))


def test_failed_chunk_marks_document_partial(ingested, cfg) -> None:
    cfg.limits.max_retries = 0

    def responder(system, messages):
        if "This is part 2 of " in messages[0]["content"]:
            raise RetryableError("upstream overloaded")
        return reply([field("party", "party_provider", {"name": "Provider"},
                            [("STD:using-this-agreement", "the Cover Page controls")])])

    llm, _ = make_llm(cfg, responder)
    [res] = Thor(ingested, llm, cfg).run(["STD"], workers=2)
    doc = ingested.get_document("STD")
    assert res.status == "partial" and doc.status == "partial"
    assert 0 < doc.coverage < 100 and "part 2/" in doc.status_reason and "failed" in doc.status_reason
    assert ingested.needs_extraction("STD")


def test_reextract_reads_one_clause_and_keeps_history(ingested, cfg) -> None:
    llm, provider = make_llm(cfg, a1_responder)
    thor = Thor(ingested, llm, cfg)
    thor.run(["A1"], workers=1)
    old = next(e for e in ingested.current_extractions("A1") if e.field_key == "weekly_fee")

    def re_responder(system, messages):
        prompt = messages[0]["content"]
        assert "[[A1:C]]" in prompt and "[[A1:B]]" not in prompt  # only the questioned clause is sent
        return json.dumps({"answer": "The fee is monthly, $8,000.00.", "fields": [
            {**field("payment", "weekly_fee", {"item": "Monthly Fee", "amount": 8000, "frequency": "monthly"},
                     [("A1:C", GOOD)]), "replaces_extraction_id": old.id}]})

    provider.responder = re_responder
    ingested.post_message(Message(from_agent="loki", to_agent="thor", type="clarification_request",
                                  payload={"doc_id": "A1", "clause_id": "A1:C", "question": "Is there a weekly fee?"}))
    [msg_id] = thor.handle_messages()

    history = ingested.extraction_history("A1", "weekly_fee")
    assert [e.version for e in history] == [1, 2]
    assert not history[0].is_current and history[1].is_current
    assert history[1].supersedes_id == old.id and history[1].value["amount"] == 8000
    assert ingested.citations_for(history[1].id)[0].verified
    assert ingested.get_message(msg_id).status == "done"
    response = ingested.pending_messages("loki", "clarification_response")[0]
    assert response.in_reply_to == msg_id and response.payload["superseded_extraction_ids"] == [old.id]


def test_trace_records_llm_calls_and_transitions(ingested, cfg) -> None:
    llm, _ = make_llm(cfg, a1_responder)
    thor = Thor(ingested, llm, cfg)
    thor.run(["A1"], workers=1)
    actions = [t.action for t in ingested.trace(run_id=thor.run_id)]
    assert actions[0] == "run_start" and actions[-1] == "run_end"
    assert "llm_call" in actions and "persist_extractions" in actions
    transitions = [(t.input_ref, t.output_ref) for t in ingested.trace(run_id=thor.run_id) if t.action == "state_transition"]
    assert ("document:A1", "extracting") in transitions and ("document:A1", "complete") in transitions
    ws = {w.id: w for w in ingested.list_workstreams()}
    # The family is discovered from A1's own cross-references, not from the manifest.
    assert ws["ws:A1"].members == ["A1", "A2", "STD"]
    assert ws["ws:A1"].agent_status["thor"] == "in_progress"      # A2 and STD not extracted in this test
    assert ws["ws:B1"].members == ["B1"]
    assert "ws:cross_contract" in ws
