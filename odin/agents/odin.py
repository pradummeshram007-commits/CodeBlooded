"""ODIN: the orchestrator.

    odin = Odin(store, cfg, files=files)
    run = odin.new_run("D1", source="upload")      # planned and stored as queued, on the simulated clock's date
    odin.execute(run)                               # THOR -> NORNS -> LOKI -> HEIMDALL, stored stage by stage

    runner = PipelineRunner(lambda: Odin(store, cfg, files=files))
    runner.submit("D1", source="upload")            # the same, queued on a background thread (the web app)

One run = one document on one clock date (as_of). Odin decides what each agent does for it (FR1.2, FR1.3):
  THOR      extract the document; skipped when its text is unchanged and already extracted completely. Fields the
            run leaves out are filled by the deterministic extractor, as an upload always did.
  NORNS     rebuild the obligation timeline of the followed contracts on as_of (norns.contracts from config.yaml
            plus every contract a pipeline has processed, so the uploaded contract joins them) and store the
            instances, the snapshot and the worst-case exposure items.
  LOKI      review the document as the counterparty's lawyer: a contract or addendum itself, an amendment through
            the contracts it amends; standard terms are not applicable (reviewed inside the contracts that
            incorporate them). Needs THOR's output and an LLM.
  HEIMDALL  process the event drops released on as_of that were never processed then, re-map a processed drop
            whose events name the document's contract but were mapped, elsewhere, before it was uploaded or
            re-extracted, then rebuild the alerts and the task board for as_of (reassess).
Every stage is saved as it starts and ends (pipeline_runs), with its numbers and reason, and traced. A stage that
cannot run (no LLM key, THOR failed, the run's LLM budget used up) is ``skipped`` with the reason, which makes the
run ``partial``: a run is ``complete`` only when every stage is (NFR3). LLM spend is capped per run across all
agents (odin.max_llm_calls, odin.max_tokens_budget), within each agent's own cap (FR7.2). Every agent's client
falls back across the configured API keys (odin.llm.KeyPool).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from odin.agents.base import Agent
from odin.agents.heimdall import SEVERITY_RANK, Heimdall, heimdall_llm
from odin.agents.loki import NOT_REVIEWED_KINDS, Loki
from odin.agents.thor import Thor
from odin.config import OdinConfig
from odin.ingest.loader import document_text, load_clock
from odin.llm import LLMClient, llm_unavailable
from odin.norns.engine import Norns
from odin.norns.worst_case import NOT_IN_TOTAL, worst_case
from odin.state.files import FileStore
from odin.state.models import PipelineRun, PipelineStage, Workstream, utcnow
from odin.state.store import StateStore

AGENT = "odin"
FINISHED = ("complete", "partial", "failed", "interrupted")
DONE = ("complete", "not_applicable")              # stage statuses that leave nothing missing

# (agent, config with the run's remaining limits) -> that agent's LLM client, or None when it has no usable LLM.
LLMFactory = Callable[[str, OdinConfig], "LLMClient | None"]


def default_llm(agent: str, cfg: OdinConfig) -> LLMClient | None:
    """The agent's own client: its model, its key pool (fallback keys), the limits in ``cfg``."""
    if llm_unavailable(cfg, "loki" if agent == "loki" else None):
        return None
    if agent == "heimdall":
        return heimdall_llm(cfg)
    return LLMClient.from_config(cfg, agent="loki" if agent == "loki" else None)


def followed_contracts(store: StateStore, cfg: OdinConfig, extra: list[str] | tuple[str, ...] = ()) -> list[str]:
    """The contracts NORNS follows: norns.contracts from config.yaml, then every contract a pipeline run has
    processed, so an uploaded contract joins the portfolio's timeline, worst case, dashboard and task board."""
    docs = {d.doc_id: d for d in store.list_documents(include_text=False)}
    out = list(cfg.norns.contracts)
    roots = sorted({r.plan.get("root") for r in store.list_pipeline_runs(limit=500)
                    if r.status in ("complete", "partial") and r.plan.get("root")})
    for c in [*roots, *extra]:
        if c and c not in out and c in docs and docs[c].kind == "contract":
            out.append(c)
    return out


def default_as_of(store: StateStore, cfg: OdinConfig) -> str:
    """The clock date a run works on: the simulated clock (scripts/clock.py), else the latest HEIMDALL run date, else
    the checkpoint that releases the first event drop, else today."""
    state = store.get_clock_state()
    if state is not None:
        return str(state.current_as_of)[:10]
    runs = store.heimdall_runs()
    if runs:
        return max(a for a, _d in runs)
    points = store.list_checkpoints() or load_clock(cfg.paths.pack_dir / "clock.json")
    first_drop = min(cfg.heimdall.drop_release_checkpoints.values(), default=1)
    return next((p.date for p in points if p.idx == first_drop), date.today().isoformat())


def _ts(value: Any) -> datetime:
    """A stored timestamp (ISO text or datetime, either backend) as an aware datetime; the epoch when unknown."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _money(value: Decimal | None) -> str:
    return f"${value:,.2f}" if value is not None else "no amount"


class Odin(Agent):
    name = AGENT

    def __init__(self, store: StateStore, cfg: OdinConfig, *, files: FileStore | None = None,
                 llm_factory: LLMFactory | None = None, on_update: Callable[[PipelineRun], None] | None = None,
                 run_id: str | None = None):
        super().__init__(store, None, cfg, run_id)
        self.files = files
        self.llm_factory = llm_factory or default_llm
        self.on_update = on_update          # called after every save (the web API refreshes its caches)
        self.spent = {"llm_calls": 0, "cache_hits": 0, "tokens": 0, "failed_attempts": 0}

    # ================================================================== planning

    def default_as_of(self) -> str:
        return default_as_of(self.store, self.cfg)

    def new_run(self, doc_id: str, *, as_of: str | None = None, source: str = "manual",
                options: dict[str, Any] | None = None) -> PipelineRun:
        """Plan a run for one document and store it as queued."""
        if self.store.get_document(doc_id, include_text=False) is None:
            raise LookupError(f"document {doc_id!r} is not in the store")
        day = date.fromisoformat(str(as_of)[:10]).isoformat() if as_of else self.default_as_of()
        opts = {"force_thor": False, "run_loki": self.cfg.odin.run_loki,
                "heimdall_use_llm": self.cfg.odin.heimdall_use_llm, **(options or {})}
        run = PipelineRun(run_id=self.run_id, doc_id=doc_id, as_of=day, source=source, options=opts,  # type: ignore[arg-type]
                          plan={"stages": "thor -> norns -> loki -> heimdall"})
        self._save(run)
        self.log("run_queued", doc_id, day, source=source, options=opts)
        return run

    def root_of(self, doc_id: str) -> str | None:
        """The contract whose family the document belongs to (itself for a contract), from Thor's workstreams and
        relations; None for standard terms (shared by every family) and documents no contract claims."""
        doc = self.store.get_document(doc_id, include_text=False)
        if doc is None or doc.kind == "standard_terms":
            return None
        if doc.kind == "contract":
            return doc_id
        docs = {d.doc_id: d for d in self.store.list_documents(include_text=False)}
        for ws in self.store.list_workstreams():
            if ws.scope in docs and docs[ws.scope].kind == "contract" and doc_id in ws.members:
                return ws.scope
        for r in self.store.list_relations(doc_id):
            if r.type == "amends" and r.from_doc == doc_id and r.to_doc in docs and docs[r.to_doc].kind == "contract":
                return r.to_doc
            if r.type == "incorporates" and r.to_doc == doc_id and r.from_doc in docs and docs[r.from_doc].kind == "contract":
                return r.from_doc
        return None

    def family(self, root: str | None) -> list[str]:
        if root is None:
            return []
        ws = next((w for w in self.store.list_workstreams() if w.scope == root), None)
        return list(ws.members) if ws else [root]

    def loki_targets(self, doc_id: str) -> tuple[list[str], str | None, bool]:
        """(documents LOKI reviews for this one, why none, whether "none" is fine). An amendment is reviewed inside
        the documents it amends; standard terms inside the contracts that incorporate them."""
        doc = self.store.get_document(doc_id, include_text=False)
        assert doc is not None
        if doc.kind not in NOT_REVIEWED_KINDS:
            return [doc_id], None, True
        if doc.kind == "standard_terms":
            return [], "standard terms are reviewed inside the contracts that incorporate them", True
        docs = {d.doc_id: d for d in self.store.list_documents(include_text=False)}
        hosts = sorted({r.to_doc for r in self.store.list_relations(doc_id) if r.type == "amends" and r.from_doc == doc_id
                        and r.to_doc in docs and docs[r.to_doc].kind not in NOT_REVIEWED_KINDS})
        if not hosts:
            return [], "an amendment is reviewed inside the documents it amends, and THOR linked it to none", False
        return hosts[: self.cfg.odin.loki_max_docs], None, True

    # ================================================================== execution

    def execute(self, run: PipelineRun) -> PipelineRun:
        """THOR -> NORNS -> LOKI -> HEIMDALL for the run's document; the run is saved after every step."""
        run.status, run.started_at = "running", utcnow()
        self._save(run)
        self.log("run_start", run.doc_id, run.as_of, options=run.options)
        try:
            for name, step in (("thor", self._thor), ("norns", self._norns), ("loki", self._loki),
                               ("heimdall", self._heimdall)):
                self._run_stage(run, name, step)
        finally:
            run.current_stage = None
            run.status, run.reason = self._verdict(run)
            run.finished_at = utcnow()
            run.llm = dict(self.spent)
            self._save(run)
            try:
                self._update_workstreams(run)
                self.write_output(run)
            except Exception as exc:  # noqa: BLE001 - bookkeeping must not hide the run's own result
                self.log("bookkeeping_error", run.run_id, None, error=f"{type(exc).__name__}: {exc}")
            self.log("run_end", run.doc_id, run.status, reason=run.reason, stages={s.name: s.status for s in run.stages},
                     **self.spent)
        return run

    def _run_stage(self, run: PipelineRun, name: str, step: Callable[[PipelineRun, PipelineStage], None]) -> None:
        stage = run.stage(name)
        blocked = self._blocked(run, name)
        if blocked:
            stage.status, stage.reason, stage.summary = "skipped", blocked, "skipped"
            self.transition(f"pipeline:{run.run_id}:{name}", "pending", "skipped", blocked)
            self._save(run)
            return
        stage.status, stage.started_at, run.current_stage = "running", utcnow(), name
        self._save(run)
        t0 = time.monotonic()
        try:
            step(run, stage)
        except Exception as exc:  # noqa: BLE001 - recorded as the stage's failure; the next stages still run
            stage.status, stage.reason = "failed", f"{type(exc).__name__}: {exc}"
            stage.summary = stage.summary or f"{name.upper()} failed"
            self.log("stage_error", f"{run.run_id}:{name}", None, error=stage.reason)
        stage.finished_at, stage.seconds = utcnow(), round(time.monotonic() - t0, 1)
        self.transition(f"pipeline:{run.run_id}:{name}", "running", stage.status, stage.reason)
        self._save(run)

    @staticmethod
    def _blocked(run: PipelineRun, name: str) -> str | None:
        """Why a stage cannot run because of an earlier one (LOKI reads THOR's output; NORNS and HEIMDALL are
        deterministic and recompute the followed contracts whatever happened to this document)."""
        thor = run.stage("thor")
        if name == "loki" and thor.status == "failed":
            return f"THOR failed: {thor.reason}"
        return None

    @staticmethod
    def _verdict(run: PipelineRun) -> tuple[str, str | None]:
        missing = [s for s in run.stages if s.status not in DONE]
        if not missing:
            return "complete", None
        reason = "; ".join(f"{s.name.upper()} {s.status}: {s.reason or s.summary or 'no reason recorded'}" for s in missing)
        # The document itself could not be analysed; NORNS and HEIMDALL still refreshed the followed contracts.
        if run.stage("thor").status == "failed":
            return "failed", reason
        return "partial", reason

    # ---------------------------------------------------------------- budget

    def _budget_cfg(self, agent_cap: int) -> OdinConfig | None:
        """The config an agent's LLM client gets: the run's remaining calls and tokens, within the agent's own cap;
        None when the run's budget is used up."""
        calls_left = self.cfg.odin.max_llm_calls - self.spent["llm_calls"]
        tokens_left = self.cfg.odin.max_tokens_budget - self.spent["tokens"]
        if calls_left <= 0 or tokens_left <= 0:
            return None
        limits = self.cfg.limits.model_copy(update={
            "max_llm_calls": min(agent_cap, self.cfg.limits.max_llm_calls, calls_left),
            "max_tokens_budget": min(self.cfg.limits.max_tokens_budget, tokens_left)})
        return self.cfg.model_copy(update={"limits": limits})

    def _llm(self, agent: str, agent_cap: int, wanted: bool = True) -> tuple[LLMClient | None, str | None]:
        """(client, why there is none)."""
        if not wanted:
            return None, "turned off for this run"
        problem = llm_unavailable(self.cfg, "loki" if agent == "loki" else None)
        if problem:
            return None, f"no LLM: {problem}"
        cfg = self._budget_cfg(agent_cap)
        if cfg is None:
            return None, (f"the run's LLM budget is used up (odin.max_llm_calls={self.cfg.odin.max_llm_calls}, "
                          f"odin.max_tokens_budget={self.cfg.odin.max_tokens_budget})")
        client = self.llm_factory(agent, cfg)
        return client, None if client is not None else "no LLM client"

    def _charge(self, stage: PipelineStage, *clients: LLMClient | None) -> None:
        for c in clients:
            if c is None:
                continue
            s = c.stats
            stage.llm_calls += s.calls
            stage.cache_hits += s.cache_hits
            stage.tokens += s.tokens
            self.spent["llm_calls"] += s.calls
            self.spent["cache_hits"] += s.cache_hits
            self.spent["tokens"] += s.tokens
            self.spent["failed_attempts"] += s.failures

    # ---------------------------------------------------------------- THOR

    def _thor(self, run: PipelineRun, stage: PipelineStage) -> None:
        doc_id = run.doc_id
        doc = self.store.get_document(doc_id, include_text=False)
        assert doc is not None
        if doc.parse_status == "unparseable":
            stage.status, stage.summary = "failed", "no readable text"
            stage.reason = doc.status_reason or "no text could be read from the file (a scan without a text layer?)"
            return
        force = bool(run.options.get("force_thor"))
        needs = force or self.store.needs_extraction(doc_id)
        llm, why_not = self._llm("thor", self.cfg.limits.max_llm_calls) if needs else (None, None)
        thor = Thor(self.store, llm, self.cfg)
        stage.details["thor_run_id"] = thor.run_id
        if not needs or llm is not None:
            thor.run([doc_id], force=force)   # unchanged and complete: skipped inside, no LLM call
        else:
            thor.update_workstreams()         # no LLM: the document still gets its workstream
        added: list[int] = []
        if needs and llm is None:
            # Without an LLM, the core fields are read from the clause text by the deterministic extractor (what an
            # upload did before Odin). The document stays not extracted, so a run with a key extracts it properly.
            from odin.extract_deterministic import extract_contract_fields_deterministic

            full = self.store.get_document(doc_id)
            assert full is not None
            added = extract_contract_fields_deterministic(self.store, full, self.store.list_clauses(doc_id),
                                                          document_text(self.cfg, full))
        self._charge(stage, llm)
        report = thor.document_report(doc_id)
        out_dir = self.cfg.paths.outputs_dir / "thor"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{doc_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        doc = self.store.get_document(doc_id, include_text=False)
        assert doc is not None
        exs = report["extractions"]
        cites = [c for e in exs for c in e["citations"]]
        fields = sum(1 for e in exs if e["status"] != "missing")
        stage.details.update({
            "doc_status": doc.status, "coverage": doc.coverage, "clauses": len(report["clauses"]), "fields": fields,
            "missing": sum(1 for e in exs if e["status"] == "missing"),
            "ambiguous": sum(1 for e in exs if e["status"] == "ambiguous"),
            "citations_verified": sum(1 for c in cites if c["verified"]),
            "citations_failed": sum(1 for c in cites if not c["verified"]),
            "open_flags": len(report["flags"]), "deterministic_fields": len(added), "extracted": needs,
        })
        stage.summary = (f"{fields} fields · {stage.details['citations_verified']}/{len(cites)} citations verified · "
                         f"{(doc.coverage or 0):.0f}% coverage") if needs or fields else "nothing extracted"
        if not needs:
            stage.status = "complete" if doc.status == "complete" else ("partial" if doc.status == "partial" else "complete")
            stage.summary = f"already extracted, text unchanged · {stage.summary}"
            if doc.status == "partial":
                stage.reason = doc.status_reason
        elif llm is None:
            stage.status = "partial"
            stage.reason = f"{why_not}; only the deterministic fields were extracted"
        elif doc.status == "complete":
            stage.status = "complete"
        elif doc.status in ("partial", "failed"):
            stage.status = doc.status  # type: ignore[assignment]
            stage.reason = doc.status_reason
        else:
            stage.status, stage.reason = "partial", f"THOR left the document {doc.status}: {doc.status_reason}"

    # ---------------------------------------------------------------- NORNS

    def _norns(self, run: PipelineRun, stage: PipelineStage) -> None:
        root = self.root_of(run.doc_id)
        followed = followed_contracts(self.store, self.cfg, [root] if root else [])
        family = self.family(root)
        run.plan.update(root=root, workstream=f"ws:{root}" if root else None, family=family, followed=followed)
        llm, _why = self._llm("norns", self.cfg.limits.max_llm_calls)   # only for due rules Thor's fields leave open
        norns = Norns(self.store, llm, self.cfg, contracts=followed)
        stage.details["norns_run_id"] = norns.run_id
        try:
            norns.load(persist=True)
            day = date.fromisoformat(run.as_of)
            t = norns.compute(day)
            wc = worst_case(norns, t)
            self.store.replace_exposure_items(run.as_of, wc.items())
            norns.persist(t, chart_data=wc.chart_data())
        finally:
            self._charge(stage, llm)

        total = wc.total("worst_case")
        by: dict[str, Decimal] = {}
        for a in wc.accruals:
            if a.scenario == "worst_case" and a.category not in NOT_IN_TOTAL:
                by[a.contract] = by.get(a.contract, Decimal(0)) + a.amount
        stage.details.update({"followed": followed, "worst_case_total": str(total),
                              "worst_case_by_contract": {c: str(v) for c, v in sorted(by.items())}})
        if root is None:
            stage.status = "complete"
            stage.summary = f"{len(followed)} followed contracts recomputed · worst case {_money(total)}"
            stage.reason = "the document belongs to no single contract family: every followed timeline was recomputed"
            return
        rules = [r for r in norns.rules if r.contract == root]
        mine = [i for i in t.instances if i.contract == root]
        prefixes = tuple(f"{d}{sep}" for d in family for sep in (":", "/"))
        flags = [f for f in t.flags if f.startswith(prefixes)]
        counts: dict[str, int] = {}
        for i in mine:
            counts[i.status] = counts.get(i.status, 0) + 1
        nxt = next((i for i in sorted(mine, key=lambda i: (i.due or date.max)) if i.status == "upcoming" and i.due), None)
        stage.details.update({"root": root, "rules": len(rules), "instances": len(mine), "statuses": counts,
                              "flags": flags[:20], "root_worst_case": str(by.get(root, Decimal(0))),
                              "next_deadline": nxt.view() if nxt else None})
        if mine:
            stage.status = "complete"
            stage.summary = (f"{len(rules)} rules · {len(mine)} dated obligations for {root} · worst case "
                             f"{_money(by.get(root, Decimal(0)))}")
        else:
            stage.status = "partial"
            stage.summary = f"no obligation of {root} could be dated ({len(rules)} rule(s))"
            stage.reason = (f"NORNS could not date any obligation of {root}"
                            + (f": {'; '.join(flags[:2])}" if flags else " (THOR's fields give no dates or periods)"))

    # ---------------------------------------------------------------- LOKI

    def _loki(self, run: PipelineRun, stage: PipelineStage) -> None:
        targets, why_none, fine = self.loki_targets(run.doc_id)
        run.plan["loki_docs"] = targets
        if not targets:
            stage.status = "not_applicable" if fine else "skipped"
            stage.reason, stage.summary = why_none, "nothing to review"
            return
        llm, why_not = self._llm("loki", self.cfg.loki.max_llm_calls, bool(run.options.get("run_loki", True)))
        if llm is None:
            stage.status, stage.reason, stage.summary = "skipped", why_not, f"{', '.join(targets)} not reviewed"
            return
        loki = Loki(self.store, llm, self.cfg)
        stage.details["loki_run_id"] = loki.run_id
        try:
            reviews = loki.run(targets, run.as_of)
        finally:
            self._charge(stage, llm)
        per = {r.doc_id: {"status": r.status, "reason": r.reason, "accepted": len(r.accepted), "rejected": len(r.rejected)}
               for r in reviews}
        top = sorted((f for r in reviews for f in r.accepted),
                     key=lambda f: (-{"critical": 4, "high": 3, "medium": 2, "low": 1}.get(f.severity or "", 0), f.rank))
        stage.details.update({"reviews": per, "top_findings": [
            {"doc_id": f.doc_id, "title": f.title, "type": f.type, "severity": f.severity, "likelihood": f.likelihood}
            for f in top[:5]]})
        accepted = sum(v["accepted"] for v in per.values())
        statuses = {v["status"] for v in per.values()}
        stage.summary = f"{accepted} finding(s) on {', '.join(targets)}" + (
            f" · most severe: {top[0].title} ({top[0].severity})" if top else "")
        if statuses <= {"complete", "skipped"}:
            stage.status = "complete"
        else:
            stage.status = "failed" if statuses == {"failed"} else "partial"
            stage.reason = "; ".join(f"{d}: {v['reason']}" for d, v in per.items() if v["status"] not in ("complete", "skipped"))

    # ---------------------------------------------------------------- HEIMDALL

    def _heimdall(self, run: PipelineRun, stage: PipelineStage) -> None:
        day = run.as_of
        root = run.plan.get("root") if "root" in run.plan else self.root_of(run.doc_id)
        followed = run.plan.get("followed") or followed_contracts(self.store, self.cfg, [root] if root else [])
        family = set(run.plan.get("family") or self.family(root))
        norns = Norns(self.store, None, self.cfg, contracts=followed)
        norns.load(persist=False)
        board = Heimdall(self.store, None, self.cfg, files=self.files, norns=norns)
        released = board.released_drops(day)
        processed = set(self.store.heimdall_runs())
        actions: list[dict[str, Any]] = []
        for drop in released:
            if (day, drop) not in processed:
                actions.append({"drop": drop, "action": "process", "why": f"released, not yet processed on {day}"})
            elif root:
                # Only events mapped before the family's text or extraction last changed can map differently now;
                # the rest (noise naming the contract included) would come out the same, so they cost no re-run.
                stored = {e.event_id: e for e in self.store.list_heimdall_events(day, drop)}
                changed = self._changed_at(family | {root})
                new = [eid for eid in board.events_naming(drop, day, root)
                       if eid not in stored or (_ts(stored[eid].created_at) < changed
                                                and not (set(stored[eid].doc_ids) & family
                                                         or (stored[eid].fact or {}).get("contract") == root))]
                if new:
                    actions.append({"drop": drop, "action": "remap",
                                    "why": f"{', '.join(new)} name {root} but are not mapped to it"})
        run.plan["heimdall"] = actions

        for a in actions:
            llm, why_not = self._llm("heimdall", self.cfg.heimdall.max_llm_calls,
                                     bool(run.options.get("heimdall_use_llm", True)))
            try:
                stored = self.store.list_heimdall_events(day, a["drop"])
                if a["action"] == "remap" and llm is None and any(e.mapped_by == "llm" for e in stored):
                    a["result"] = f"not re-mapped ({why_not}): a code-only run would undo the events the LLM mapped"
                    continue
                result = Heimdall(self.store, llm, self.cfg, files=self.files, norns=norns).run(a["drop"], day)
                a["result"] = result.counts()
                a["llm"] = None if llm else why_not
            finally:
                self._charge(stage, llm)          # per drop, so the next drop's budget sees this one's spend
        live = board.reassess(day)

        events = board.event_rows(day)
        about = [e for e in events if e.status == "mapped" and (set(e.doc_ids) & family
                                                                 or (e.fact or {}).get("contract") == root)]
        waiting = [e for e in events if e.status == "unmapped" and "no LLM client" in (e.status_reason or "")]
        alerts = [a for a in live.alerts if not root or a.contract == root]
        severities = {s: sum(1 for a in live.alerts if a.severity == s) for s in SEVERITY_RANK}
        tasks = [t for t in live.tasks if not root or t.contract == root]
        stage.details.update({
            "released_drops": released, "actions": actions, "events": len(events),
            "events_about_document": [{"event_id": e.event_id, "type": e.type, "clause_ids": e.clause_ids} for e in about],
            "unmapped_waiting_for_llm": [e.event_id for e in waiting],
            "alerts": len(live.alerts), "alerts_by_severity": severities, "alerts_about_document": len(alerts),
            "tasks": len(live.tasks), "tasks_about_document": len(tasks), "worst_case_live": str(live.live),
        })
        if not released:
            first = min(self.cfg.heimdall.drop_release_checkpoints.items(), key=lambda kv: kv[1], default=None)
            when = board.release_date(first[0]) if first else None
            stage.summary = f"no event drop released on {day} yet" + (f" (the first opens {when})" if when else "")
        else:
            stage.summary = (f"{len(events)} events behind {day} · {len(about)} about {root or run.doc_id} · "
                             f"{len(live.alerts)} alerts ({severities['critical']} critical) · {len(live.tasks)} tasks")
        skipped = [a for a in actions if isinstance(a.get("result"), str)]
        if skipped or waiting:
            stage.status = "partial"
            stage.reason = "; ".join([f"{a['drop']} {a['result']}" for a in skipped]
                                     + ([f"{len(waiting)} event(s) wait for an LLM to be mapped "
                                         f"({', '.join(e.event_id or '?' for e in waiting)})"] if waiting else []))
        else:
            stage.status = "complete"

    def _changed_at(self, doc_ids: set[str]) -> datetime:
        """When any of the documents was last ingested or changed status (a THOR extraction)."""
        docs = [d for d in self.store.list_documents(include_text=False) if d.doc_id in doc_ids]
        return max((max(_ts(d.ingested_at), _ts(d.updated_at)) for d in docs), default=_ts(None))

    # ================================================================== bookkeeping

    def _save(self, run: PipelineRun) -> None:
        self.store.save_pipeline_run(run)
        if self.on_update is not None:
            try:
                self.on_update(run)
            except Exception as exc:  # noqa: BLE001 - a listener never breaks the run
                self.log("listener_error", run.run_id, None, error=f"{type(exc).__name__}: {exc}")

    def _update_workstreams(self, run: PipelineRun) -> None:
        """Odin's status for the run's document, in every workstream that has it (FR1.3)."""
        entry = {"run_id": run.run_id, "doc_id": run.doc_id, "as_of": run.as_of, "status": run.status,
                 "stages": {s.name: s.status for s in run.stages}, "finished_at": run.finished_at}
        for ws in self.store.list_workstreams():
            if ws.scope != "cross_contract" and (run.doc_id in ws.members or ws.scope == run.plan.get("root")):
                self.store.upsert_workstream(Workstream(id=ws.id, scope=ws.scope, members=ws.members,
                                                        agent_status={AGENT: run.status},
                                                        notes=json.dumps({AGENT: entry})))

    def write_output(self, run: PipelineRun) -> Path:
        out_dir = self.cfg.paths.outputs_dir / "odin"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{run.run_id}.json"
        path.write_text(json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path


class PipelineRunner:
    """Runs pipeline runs one at a time on a background thread, in the order they were submitted (they share the API
    keys and LLM budgets). The web API holds one runner.

        runner = PipelineRunner(lambda: Odin(store, cfg, files=files))
        run = runner.submit("D1", source="upload")      # returns at once, queued; poll store.get_pipeline_run
    """

    def __init__(self, make_odin: Callable[[], Odin], *, on_finish: Callable[[PipelineRun], None] | None = None,
                 idle_s: float = 30.0):
        self.make_odin = make_odin
        self.on_finish = on_finish
        self.idle_s = idle_s
        self.current: str | None = None            # run id being executed
        self._queue: queue.Queue[tuple[Odin, PipelineRun]] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def submit(self, doc_id: str, *, as_of: str | None = None, source: str = "manual",
               options: dict[str, Any] | None = None) -> PipelineRun:
        odin = self.make_odin()
        run = odin.new_run(doc_id, as_of=as_of, source=source, options=options)
        queued = run.model_copy(deep=True)     # the caller's copy: the worker thread changes ``run`` as it goes
        self._queue.put((odin, run))
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name="odin-pipeline", daemon=True)
                self._thread.start()
        return queued

    @property
    def queued(self) -> int:
        return self._queue.qsize()

    def _work(self) -> None:
        while True:
            try:
                odin, run = self._queue.get(timeout=self.idle_s)
            except queue.Empty:
                with self._lock:
                    if self._queue.empty():
                        self._thread = None      # idle: the next submit starts a new thread
                        return
                continue
            self.current = run.run_id
            try:
                odin.execute(run)
            except Exception as exc:  # noqa: BLE001 - execute() records stage failures; this is a last resort
                odin.log("run_crashed", run.run_id, None, error=f"{type(exc).__name__}: {exc}")
            finally:
                self.current = None
                self._queue.task_done()
                if self.on_finish is not None:
                    try:
                        self.on_finish(run)
                    except Exception:  # noqa: BLE001 - a listener never stops the queue
                        pass
