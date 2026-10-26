"""The web app's LOKI and HEIMDALL endpoints (odin/api.py) over Thor's committed export. Scripted LLM: no real call."""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import odin.api as api  # noqa: E402

from .conftest import make_llm  # noqa: E402
from .test_heimdall import AS_OF, thor_state  # noqa: E402, F401  (thor_state is a fixture)

REAL = "overdue amounts accrue interest at 1.5% per month"   # A1 §C, verbatim


@pytest.fixture
def client(thor_state, cfg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api, "cfg", cfg)
    monkeypatch.setattr(api, "_store", thor_state)
    monkeypatch.setattr(api, "_heimdall_board", None)
    api._norns_cache.clear()
    yield TestClient(api.app)
    api._norns_cache.clear()


def test_loki_review_needs_an_llm_then_stores_checked_findings(client, thor_state, cfg, monkeypatch) -> None:  # noqa: F811
    docs = {d["doc_id"]: d for d in client.get("/api/loki/documents").json()["documents"]}
    assert docs["A1"]["reviewable"] and docs["A1"]["last_review"] is None
    assert not docs["A3"]["reviewable"] and docs["A3"]["reviewed_inside"] == ["A1", "A2"]
    assert not docs["STD"]["reviewable"]
    assert client.get("/api/loki/findings", params={"doc_id": "A1", "as_of": "15/03/2027"}).status_code == 400

    r = client.post("/api/loki/review", json={"doc_ids": ["A1"], "as_of": AS_OF})
    assert r.status_code == 503 and r.json()["detail"].startswith("Loki needs an LLM")     # no key in the test config

    reply = {"findings": [
        {"type": "hidden_liability", "title": "Late interest runs from the due date",
         "citations": [{"clause_id": "A1:C", "quote": REAL}],
         "attack_path": ["StratoNode invoices under A1:C", "Late amounts accrue 1.5% per month under A1:C"],
         "severity": "high", "severity_reason": "recurring", "likelihood": "medium", "likelihood_reason": "plausible",
         "confidence": 0.8},
        {"type": "one_sided", "title": "Weekly fee", "citations": [{"clause_id": "A1:C", "quote": "payable weekly"}],
         "attack_path": ["StratoNode bills weekly under A1:C", "Quillhub overpays"], "severity": "high",
         "likelihood": "high", "confidence": 0.5},
    ]}
    llm, provider = make_llm(cfg, lambda system, messages: json.dumps(reply))
    monkeypatch.setattr(api, "llm_status", lambda agent=None: {"configured": True, "provider": "fake",
                                                               "model": "fake-model", "problem": None})
    monkeypatch.setattr(api, "LLMClient", type("ScriptedClient", (), {"from_config": staticmethod(lambda *a, **k: llm)}))
    r = client.post("/api/loki/review", json={"doc_ids": ["A1"], "as_of": AS_OF})
    assert r.status_code == 200, r.text
    [review] = r.json()["reviews"]
    assert review["status"] == "complete" and len(provider.calls) == 1
    assert thor_state.list_exposure_items(AS_OF)                     # stored first, so impacts can cite Norns

    body = client.get("/api/loki/findings", params={"doc_id": "A1"}).json()
    assert body["as_of"] == AS_OF and body["available_as_of"] == [AS_OF]
    assert body["summary"]["accepted"] == 1 and body["summary"]["rejected"] == 1
    good, bad = body["findings"]
    assert good["status"] == "accepted" and good["citations"][0]["verified"] and good["citations"][0]["quote"] == REAL
    assert bad["status"] == "rejected" and bad["rejection_reason"].startswith("no verified citation")
    assert body["last_review"]["status"] == "complete"
    step = client.get("/api/dashboard").json()["agent_activity"]["steps"][0]
    assert step["agent"] == "LOKI" and "Late interest runs from the due date" in step["summary"] and step["link"] == "/loki?doc=A1"


def test_heimdall_run_board_task_tags_and_reassess(client) -> None:
    over = client.get("/api/heimdall/overview").json()
    assert [(d["name"], d["release_date"]) for d in over["drops"]] == [("drop1", "2027-03-15"), ("drop2", "2027-06-01")]
    assert client.post("/api/heimdall/run", json={"drop": "2", "as_of": AS_OF, "use_llm": False}).status_code == 400
    assert client.post("/api/heimdall/run", json={"drop": "1", "as_of": AS_OF, "use_llm": True}).status_code == 503
    run = client.post("/api/heimdall/run", json={"drop": "1", "as_of": AS_OF, "use_llm": False}).json()
    assert run["counts"]["total"] == 7 and run["counts"]["unmapped"] == 4 and run["llm"]["llm_calls"] == 0

    board = client.get("/api/heimdall/board").json()                  # defaults to the latest run date
    assert board["as_of"] == AS_OF and board["counts"]["total"] == 7 and board["alerts"]
    april = next(t for t in board["tasks"] if t["contract"] == "A1" and t["title"] == "Monthly Fee April 2027")
    assert april["severity"] == "low" and april["days_left"] == 47
    locked = next(t for t in board["tasks"] if t["status_source"] == "norns")
    assert locked["severity"] == "done"
    r = client.post("/api/heimdall/tasks/status", json={"as_of": AS_OF, "task_id": locked["task_id"], "status": "Not Complete"})
    assert r.status_code == 409 and "cannot be changed" in r.json()["detail"]
    r = client.post("/api/heimdall/tasks/status", json={"as_of": AS_OF, "task_id": april["task_id"], "status": "Completed"})
    assert r.status_code == 200 and "worst case now" in r.json()["message"]
    after = client.get("/api/heimdall/board", params={"as_of": AS_OF}).json()
    assert Decimal(after["worst_case"]["live"]) < Decimal(board["worst_case"]["live"])

    r = client.post("/api/heimdall/reassess", json={"as_of": "2027-06-01"})
    assert r.status_code == 200 and r.json()["tasks"] > 0
    step = client.get("/api/dashboard").json()["agent_activity"]["steps"][1]
    assert step["agent"] == "HEIMDALL" and step["link"] == f"/heimdall?as_of={AS_OF}"
