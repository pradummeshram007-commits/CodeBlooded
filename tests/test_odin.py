"""ODIN, the orchestrator: THOR -> NORNS -> LOKI -> HEIMDALL on one document (scripted LLM: no real call)."""
from __future__ import annotations

import json
import time

import pytest

from odin.agents.heimdall import heimdall_llm
from odin.agents.odin import Odin, PipelineRunner, default_llm, followed_contracts
from odin.agents.thor import Thor
from odin.config import load_config
from odin.state.models import PipelineRun

from .conftest import make_llm
from .test_heimdall import AS_OF, ScriptedProvider, thor_state  # noqa: F401  (thor_state is a fixture)
from .test_thor import a1_responder

REAL = "overdue amounts accrue interest at 1.5% per month"   # A1 §C, verbatim
FINDING = {"type": "hidden_liability", "title": "Late interest runs from the due date",
           "citations": [{"clause_id": "A1:C", "quote": REAL}],
           "attack_path": ["StratoNode invoices under A1:C", "Late amounts accrue 1.5% per month under A1:C"],
           "severity": "high", "severity_reason": "recurring", "likelihood": "medium", "likelihood_reason": "plausible",
           "confidence": 0.8}
STAGES = ["thor", "norns", "loki", "heimdall"]


def loki_responder(system, messages):
    return json.dumps({"findings": [FINDING]})


def scripted(thor=None, loki=None, heimdall=False):
    """An llm_factory for Odin: each agent gets a scripted client built with the limits Odin hands it (the run's
    remaining budget); ``providers`` collects the fake providers, so a test sees which agents were given a client."""
    providers: dict[str, list] = {}

    def factory(agent, c):
        if agent == "heimdall":
            if not heimdall:
                return None
            provider = ScriptedProvider()
            providers.setdefault(agent, []).append(provider)
            return heimdall_llm(c, provider=provider, sleep=lambda s: None)
        responder = {"thor": thor, "loki": loki}.get(agent)
        if responder is None:
            return None
        client, provider = make_llm(c, responder)
        providers.setdefault(agent, []).append(provider)
        return client

    return factory, providers


@pytest.fixture
def keyed(cfg):
    cfg.llm.api_key = "test-key"          # passes llm_unavailable(); every client in these tests is scripted
    return cfg


def run_pipeline(store, cfg, doc_id, **kw):
    factory = kw.pop("llm_factory", None)
    odin = Odin(store, cfg, llm_factory=factory)
    return odin.execute(odin.new_run(doc_id, **kw))


def test_one_run_takes_a_contract_through_the_four_agents(thor_state, keyed) -> None:  # noqa: F811
    factory, providers = scripted(loki=loki_responder, heimdall=True)
    saved: list[tuple[str, str | None]] = []
    odin = Odin(thor_state, keyed, llm_factory=factory, on_update=lambda r: saved.append((r.status, r.current_stage)))
    run = odin.new_run("A1", source="upload")
    assert run.status == "queued" and run.as_of == AS_OF                  # the checkpoint that releases drop 1
    run = odin.execute(run)

    st = {s.name: s for s in run.stages}
    assert [s.name for s in run.stages] == STAGES
    assert list(dict.fromkeys(stage for _status, stage in saved if stage)) == STAGES   # in order, saved as they ran
    assert run.status == "complete" and run.reason is None, run.reason
    assert st["thor"].status == "complete" and st["thor"].llm_calls == 0     # extracted before, text unchanged
    assert st["thor"].summary.startswith("already extracted")
    assert st["norns"].status == "complete" and st["norns"].details["root"] == "A1" and st["norns"].details["instances"]
    assert st["loki"].status == "complete" and st["loki"].llm_calls == 1
    assert st["loki"].details["reviews"]["A1"]["accepted"] == 1
    assert st["heimdall"].status == "complete" and st["heimdall"].llm_calls == 1
    assert [(a["drop"], a["action"]) for a in run.plan["heimdall"]] == [("drop1", "process")]
    assert [e["event_id"] for e in st["heimdall"].details["events_about_document"]] == ["E-04"]
    assert run.plan["workstream"] == "ws:A1" and run.plan["family"] == ["A1", "A2", "A3", "STD"]   # A3 amends A1
    assert run.plan["loki_docs"] == ["A1"] and run.llm["llm_calls"] == 2
    assert len(providers["loki"][0].calls) == len(providers["heimdall"][0].calls) == 1

    stored = thor_state.get_pipeline_run(run.run_id)
    assert stored.status == "complete" and [s.status for s in stored.stages] == ["complete"] * 4
    assert (keyed.paths.outputs_dir / "odin" / f"{run.run_id}.json").exists()
    assert thor_state.list_loki_findings("A1", AS_OF) and thor_state.list_heimdall_events(AS_OF, "drop1")

    ws = {w.id: w for w in thor_state.list_workstreams()}
    assert ws["ws:A1"].agent_status["odin"] == "complete" and "odin" not in ws["ws:cross_contract"].agent_status
    Thor(thor_state, None, keyed).update_workstreams()                     # Thor's notes no longer wipe Odin's
    notes = json.loads({w.id: w for w in thor_state.list_workstreams()}["ws:A1"].notes)
    assert notes["odin"]["run_id"] == run.run_id and notes["odin"]["stages"]["loki"] == "complete"

    again = run_pipeline(thor_state, keyed, "A1", as_of=AS_OF, llm_factory=factory)
    assert again.status == "complete" and again.llm["llm_calls"] == 0      # nothing new: a re-run costs no call
    assert again.stage("loki").cache_hits == 1 and again.plan["heimdall"] == []


def test_the_run_budget_is_shared_by_the_agents(thor_state, keyed) -> None:  # noqa: F811
    keyed.odin.max_llm_calls = 1
    factory, providers = scripted(loki=loki_responder, heimdall=True)
    run = run_pipeline(thor_state, keyed, "A1", as_of=AS_OF, llm_factory=factory)
    assert run.stage("loki").status == "complete" and run.stage("loki").llm_calls == 1
    assert "heimdall" not in providers                                     # LOKI spent the run's only call
    [action] = run.plan["heimdall"]
    assert action["action"] == "process" and "budget is used up" in action["llm"]
    heimdall = run.stage("heimdall")
    assert heimdall.status == "partial" and "wait for an LLM to be mapped" in heimdall.reason
    assert run.status == "partial" and run.reason.startswith("HEIMDALL partial")


def test_without_an_api_key_every_stage_says_what_it_could_not_do(ingested, cfg) -> None:
    run = run_pipeline(ingested, cfg, "D1", source="upload")             # default_llm: the test config has no key
    st = {s.name: s for s in run.stages}
    assert run.as_of == AS_OF and run.status == "partial"
    assert st["thor"].status == "partial"
    assert st["thor"].reason == "no LLM: no API key set (LLM_API_KEY in .env); only the deterministic fields were extracted"
    assert st["thor"].details["deterministic_fields"] > 0
    assert ingested.needs_extraction("D1")                 # still not extracted: a run with a key uses the LLM on it
    assert st["loki"].status == "skipped" and st["loki"].reason == "no LLM: no API key set (LLM_API_KEY in .env)"
    assert st["heimdall"].status == "partial" and "wait for an LLM" in st["heimdall"].reason
    assert all(f"{s.upper()} " in run.reason for s in ("thor", "loki", "heimdall"))
    assert "D1" in followed_contracts(ingested, cfg)      # the processed contract joins NORNS' portfolio


def test_thor_extracts_new_text_once_and_loki_can_be_turned_off(ingested, keyed) -> None:
    factory, providers = scripted(thor=a1_responder)
    off = {"run_loki": False, "heimdall_use_llm": False}
    run = run_pipeline(ingested, keyed, "A1", as_of=AS_OF, llm_factory=factory, options=off)
    thor = run.stage("thor")
    assert thor.status == "complete" and thor.llm_calls == len(providers["thor"][0].calls) > 0
    assert thor.details["citations_failed"] == 1 and thor.details["citations_verified"] > 0   # the invented quote
    assert run.stage("loki").status == "skipped" and run.stage("loki").reason == "turned off for this run"

    again = run_pipeline(ingested, keyed, "A1", as_of=AS_OF, llm_factory=factory, options=off)
    assert again.stage("thor").llm_calls == 0 and again.stage("thor").summary.startswith("already extracted")
    assert len(providers["thor"]) == 1                                     # no client was even built


def test_the_plan_follows_contract_families(thor_state, keyed) -> None:  # noqa: F811
    odin = Odin(thor_state, keyed)
    assert [odin.root_of(d) for d in ("A1", "A2", "A3", "B2", "STD")] == ["A1", "A1", "A1", "B1", None]
    assert odin.family("B1") == ["B1", "B2", "STD"]
    assert odin.loki_targets("A3") == (["A1", "A2"], None, True)          # an amendment, inside what it amends
    assert odin.loki_targets("B2") == (["B2"], None, True)                # an addendum is reviewed itself
    targets, why, fine = odin.loki_targets("STD")
    assert targets == [] and fine and why.startswith("standard terms are reviewed inside")
    with pytest.raises(LookupError):
        odin.new_run("NOPE")


def test_the_runner_runs_submissions_one_at_a_time_in_order(ingested, cfg) -> None:
    finished: list[PipelineRun] = []
    runner = PipelineRunner(lambda: Odin(ingested, cfg, llm_factory=lambda agent, c: None), on_finish=finished.append,
                            idle_s=0.2)
    first, second = runner.submit("D1", source="upload"), runner.submit("C1")
    assert first.status == second.status == "queued"
    deadline = time.monotonic() + 120
    while len(finished) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [r.run_id for r in finished] == [first.run_id, second.run_id]
    a, b = (ingested.get_pipeline_run(r.run_id) for r in (first, second))
    assert a.status == b.status == "partial" and a.finished_at <= b.started_at


def test_pipeline_runs_are_stored_and_unfinished_ones_interrupted(any_store) -> None:
    run = PipelineRun(run_id="odin-1", doc_id="A1", as_of=AS_OF, status="running", current_stage="norns")
    run.stage("thor").status = "complete"
    any_store.save_pipeline_run(run)
    any_store.save_pipeline_run(PipelineRun(run_id="odin-2", doc_id="B1", as_of=AS_OF, status="complete"))
    run.stage("norns").details = {"rules": 3}
    any_store.save_pipeline_run(run)                                       # saved again: updated, not duplicated
    got = any_store.get_pipeline_run("odin-1")
    assert got.stage("thor").status == "complete" and got.stage("norns").details == {"rules": 3}
    assert [r.run_id for r in any_store.list_pipeline_runs("A1")] == ["odin-1"]
    assert {r.run_id for r in any_store.list_pipeline_runs()} == {"odin-1", "odin-2"}

    assert any_store.interrupt_pipeline_runs("the server stopped") == 1
    got = any_store.get_pipeline_run("odin-1")
    assert got.status == "interrupted" and got.reason == "the server stopped" and got.current_stage is None
    assert any_store.get_pipeline_run("odin-2").status == "complete" and any_store.get_pipeline_run("nope") is None


def test_every_agent_gets_all_the_api_keys(tmp_path) -> None:
    env = {"ODIN_DB_PATH": str(tmp_path / "odin.db"), "LLM_API_KEY": "k1", "LLM_API_KEY_2": "k2", "LLM_API_KEY_3": "k3"}
    c = load_config(env=env)
    assert {a: default_llm(a, c).key_count for a in STAGES} == dict.fromkeys(STAGES, 3)
    assert default_llm("thor", load_config(env={"ODIN_DB_PATH": env["ODIN_DB_PATH"]})) is None


def test_upload_starts_the_pipeline_and_the_api_follows_it(thor_state, cfg, monkeypatch) -> None:  # noqa: F811
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import odin.api as api

    monkeypatch.setattr(api, "cfg", cfg)
    monkeypatch.setattr(api, "_store", thor_state)
    monkeypatch.setattr(api, "_heimdall_board", None)
    monkeypatch.setattr(api, "_runner", None)
    api._norns_cache.clear()
    client = TestClient(api.app)
    text = ("HOSTING SERVICES AGREEMENT\n\nThis Agreement is entered into as of February 1, 2027 by Quillhub Inc. "
            "(\"Customer\") and Orbit Cloud Ltd. (\"Provider\").\n\n1. FEES\n1.1 Customer will pay a monthly fee of "
            "$7,500.00, payable within thirty (30) days of the invoice date.\n\n2. TERM\n2.1 This Agreement ends on "
            "January 31, 2029.\n")

    def upload():
        r = client.post("/api/upload", params={"as_of": AS_OF}, files={"file": ("orbit.txt", text.encode(), "text/plain")})
        assert r.status_code == 200, r.text
        return r.json()

    def finished(run_id):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            run = client.get(f"/api/odin/runs/{run_id}").json()
            if run["status"] not in ("queued", "running"):
                return run
            time.sleep(0.1)
        raise AssertionError(f"{run_id} did not finish")

    try:
        body = upload()
        assert body["status"] == "success" and body["doc_id"] == "orbit" and body["pipeline"]["status"] == "queued"
        run = finished(body["pipeline"]["run_id"])
        assert run["source"] == "upload" and run["as_of"] == AS_OF and run["status"] == "partial"
        assert [s["name"] for s in run["stages"]] == STAGES and all(s["finished_at"] for s in run["stages"])
        assert run["stages"][0]["reason"].startswith("no LLM: no API key set")

        overview = client.get("/api/odin/overview").json()
        assert "orbit" in overview["followed_contracts"]
        docs = {d["doc_id"]: d for d in overview["documents"]}
        assert docs["orbit"]["last_run"]["run_id"] == run["run_id"]
        assert overview["llm"]["thor"]["keys"] == 0 and overview["queue"] == {"current": None, "queued": 0}

        again = upload()                                                   # same text: no copy, the pipeline re-runs
        assert again["status"] == "duplicate" and again["doc_id"] == "orbit"
        finished(again["pipeline"]["run_id"])
        assert len(client.get("/api/odin/runs", params={"doc_id": "orbit"}).json()["runs"]) == 2
        assert client.get("/api/odin/runs/nope").status_code == 404
        assert client.post("/api/odin/run", json={"doc_id": "nope"}).status_code == 404
        r = client.post("/api/odin/run", json={"doc_id": "orbit", "as_of": AS_OF, "run_loki": False})
        assert r.status_code == 202 and r.json()["options"]["run_loki"] is False
        assert finished(r.json()["run_id"])["stages"][2]["reason"] == "turned off for this run"
    finally:
        api._norns_cache.clear()
