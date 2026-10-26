"""Heimdall on drop 1 at checkpoint 1, over Thor's committed export (scripted LLM: no real call)."""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from odin.agents.heimdall import Heimdall, heimdall_llm
from odin.config import ROOT
from odin.ingest.loader import read_text_exact
from odin.llm import ProviderResponse
from odin.state.models import DocRelation

AS_OF = "2027-03-15"
TABLES = ("documents", "document_files", "clauses", "extractions", "citations", "flags", "doc_relations",
          "workstreams", "resources", "ledger_entries", "holidays", "clock_checkpoints")
# What Thor's step-2B code stores for A3 (the committed export predates it).
AMENDS = (("A3:1", "A2", "A2:3.2", "replace"), ("A3:2", "A2", "A2:3.1", "replace"), ("A3:3", "A1", "A1:B", "modify"))

REPLIES = {
    "E-01": {"noise": True, "noise_reason": "advance maintenance notice; no downtime reported", "type": "maintenance_notice",
             "doc_ids": ["A2"], "clause_ids": ["A2:1.3"]},
    "E-02": {"type": "outage_inquiry", "doc_ids": ["B1"], "clause_ids": ["B1:3.1"], "confidence": 0.7,
             "fact": {"type": "outage", "contract": "B1", "date": "2027-02-03", "minutes": 10, "single_incident_minutes": 5}},
    "E-03": {"type": "deliverable_submitted", "doc_ids": ["D1"], "clause_ids": ["D1:9.9"],
             "fact": {"type": "other", "description": "M3 submitted"}},
    "E-05": {"type": "incident_notice", "doc_ids": ["B1"], "clause_ids": ["B1:3.1"], "potential_breach": True,
             "breach_reason": "uptime below target", "confidence": 0.85,
             "fact": {"type": "outage", "contract": "B1", "date": "2027-03-03", "minutes": 190, "single_incident_minutes": 190}},
}


class ScriptedProvider:
    name, model = "fake", "fake-model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def settings_fingerprint(self) -> dict:
        return {}

    def complete(self, system, messages, max_tokens) -> ProviderResponse:
        user = messages[0]["content"]
        self.calls.append((system, user, max_tokens))
        ids = [line[1:].split("]")[0] for line in user.splitlines() if line.startswith("[E-")]
        events = [{"event_id": i, **REPLIES[i]} for i in ids if i in REPLIES]
        return ProviderResponse(json.dumps({"events": events}), 2500, 400, "end_turn", self.model)


@pytest.fixture
def thor_state(store, cfg):
    """Thor's committed output (outputs/state_export.json) restored into the test store."""
    data = json.loads((ROOT / "outputs" / "state_export.json").read_text(encoding="utf-8"))
    for doc in data["documents"]:
        doc["text"] = read_text_exact(cfg.paths.bundle_dir / doc["path"])
    for table in TABLES:
        store._insert_many(table, data[table])   # test setup only: the export's rows as they are
    clauses = {c["clause_id"]: c for c in data["clauses"]}
    for cid, to_doc, target, op in AMENDS:
        store.add_relation(DocRelation(from_doc="A3", to_doc=to_doc, type="amends", clause_id=cid, verified=True,
                                       citation={"clause_id": cid, "quote": clauses[cid]["text"][:60], "verified": True,
                                                 "target_clause_id": target, "operation": op,
                                                 "effective_date": "2027-01-01"}))
    return store


def run_drop1(store, cfg) -> tuple[Heimdall, ScriptedProvider, object]:
    provider = ScriptedProvider()
    heimdall = Heimdall(store, heimdall_llm(cfg, provider=provider, sleep=lambda s: None), cfg, sleep=lambda s: None)
    return heimdall, provider, heimdall.run("drop1", AS_OF)


def test_drop_model_code_first_then_one_llm_batch(thor_state, cfg) -> None:
    heimdall, provider, result = run_drop1(thor_state, cfg)
    with pytest.raises(ValueError, match="not released"):
        heimdall.run("drop2", AS_OF)                                   # drop 2 opens at checkpoint 2
    ev = {e.event_id: e for e in result.events}
    assert sorted(ev) == [f"E-0{n}" for n in range(1, 8)] and result.counts()["not_yet_visible"] == 3
    assert ev["E-04"].mapped_by == "code" and ev["E-04"].fact["type"] == "outage" and ev["E-04"].fact["minutes"] == 190
    assert ev["E-04"].clause_ids and all(thor_state.get_clause(c) for c in ev["E-04"].clause_ids)
    assert ev["E-06"].status == ev["E-07"].status == "noise" and ev["E-06"].mapped_by == "code"

    [(system, user, max_tokens)] = provider.calls                       # one batch for what code could not map
    assert [ln[1:5] for ln in user.splitlines() if ln.startswith("[E-")] == ["E-01", "E-02", "E-03", "E-05"]
    assert max_tokens == cfg.heimdall.max_tokens == 3000
    assert len(system + user) / cfg.heimdall.chars_per_token + max_tokens <= cfg.heimdall.max_request_tokens
    assert ev["E-03"].status == "unmapped" and "D1:9.9" in ev["E-03"].status_reason       # invented clause id
    assert ev["E-01"].status == "noise" and ev["E-01"].noise_reason.startswith("advance maintenance")
    assert ev["E-02"].status == "noise" and "changes no obligation" in ev["E-02"].noise_reason

    later, _future, _src = heimdall.load_events("drop2", "2027-09-15")
    bad = [e for e in later if e.parse_error]
    assert len(bad) == 1 and bad[0].line_no == 8 and "Expecting value" in bad[0].parse_error


def test_exposure_delta_and_alerts(thor_state, cfg) -> None:
    _heimdall, _provider, result = run_drop1(thor_state, cfg)
    ev = {e.event_id: e for e in result.events}
    assert ev["E-04"].exposure["delta"] == "400.00" and ev["E-04"].exposure["by_contract"] == {"A1": "400.00"}
    assert Decimal(ev["E-04"].exposure["after"]) - Decimal(ev["E-04"].exposure["before"]) == Decimal("400.00")
    assert ev["E-05"].potential_breach and "may claim $6,000.00" in ev["E-05"].breach_reason
    live = result.live
    assert live.after_events - live.baseline == Decimal("400.00")

    alerts = thor_state.list_heimdall_alerts(AS_OF)
    assert len({a.alert_key for a in alerts}) == len(alerts)          # one per (contract, clause, kind, due date)
    breach = [a for a in alerts if a.kind == "potential_breach"]
    assert len(breach) == 1 and breach[0].severity == "critical" and breach[0].contract == "B1"
    assert all(a.message and "\n" not in a.message and a.citation.get("clause_id") for a in alerts)
    fee = next(a for a in alerts if a.kind == "payment_due")
    assert fee.severity == "low" and fee.due_date == "2027-05-01"      # 47 days away: informational


def test_task_board_tags_record_user_payment_facts(thor_state, cfg) -> None:
    run_drop1(thor_state, cfg)
    board = Heimdall(thor_state, None, cfg)                             # the page's Heimdall: no LLM client
    tasks = {t.title: t for t in thor_state.list_heimdall_tasks(AS_OF) if t.contract == "A1"}
    assert tasks["Monthly Fee March 2027"].status == "Completed" and tasks["Monthly Fee March 2027"].status_source == "norns"
    ok, why = board.set_task_status(AS_OF, tasks["Monthly Fee March 2027"].task_id, "Not Complete")
    assert not ok and "cannot be changed" in why

    april = tasks["Monthly Fee April 2027"]
    before = board.totals(AS_OF).live
    assert board.set_task_status(AS_OF, april.task_id, "Completed")[0]
    stored = next(t for t in thor_state.list_heimdall_tasks(AS_OF) if t.task_id == april.task_id)
    assert stored.fact["type"] == "payment_made" and stored.fact["source"] == "user" and stored.fact["date"] == AS_OF
    assert board.totals(AS_OF).live < before
    assert not [a for a in thor_state.list_heimdall_alerts(AS_OF) if a.instance_key == april.task_id]

    assert board.set_task_status(AS_OF, april.task_id, "In Progress")[0]
    assert next(t for t in thor_state.list_heimdall_tasks(AS_OF) if t.task_id == april.task_id).fact is None
    assert board.totals(AS_OF).live == before
