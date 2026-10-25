"""ODIN / THOR / NORNS HTTP API Server.

Exposes REST endpoints for:
- Document listing & inspection
- Contract uploading & segmentation (TXT / PDF)
- Clause-level evidence retrieval
- Targeted re-extraction via Thor.reextract
- NORNS timeline, obligations ledger, and worst-case projection
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from odin.agents.thor import Thor
from odin.config import load_config
from odin.ingest.upload import ingest_file
from odin.llm import LLMClient
from odin.state.store import StateStore

app = FastAPI(title="ODIN / THOR API", version="2.4.0")

# Enable CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("odin.api")
logging.basicConfig(level=logging.INFO)

cfg = load_config()

def get_store() -> StateStore:
    return StateStore(cfg.paths.db_path)

def get_llm():
    try:
        if not cfg.llm.model or not cfg.llm.api_key:
            return None
        return LLMClient(cfg.llm, cfg.limits, cache_dir=cfg.paths.llm_cache_dir)
    except Exception as exc:
        logger.warning("LLM client could not be initialized: %s", exc)
        return None

class ReextractRequest(BaseModel):
    doc_id: str
    clause_id: str
    question: str

@app.get("/api/health")
def health():
    return {"status": "ok", "agent": "thor", "version": "v2.4-CORP"}

@app.get("/api/summary")
def get_summary():
    summary_path = Path(cfg.paths.outputs_dir) / "thor" / "_run_summary.json"
    if summary_path.exists():
        try:
            return json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to parse run summary: %s", e)
    
    store = get_store()
    docs = store.list_documents()
    return {
        "run_id": "live",
        "provider": cfg.llm.provider,
        "model": cfg.llm.model,
        "documents": [
            {
                "doc_id": d.doc_id,
                "status": d.status,
                "clauses": len(store.list_clauses(d.doc_id)),
                "coverage": d.coverage or 0.0,
            }
            for d in docs
        ]
    }

@app.get("/api/documents")
def list_documents():
    store = get_store()
    docs = store.list_documents()
    return [
        {
            **d.model_dump(),
            "clause_count": len(store.list_clauses(d.doc_id)),
            "extraction_count": len(store.current_extractions(d.doc_id, "thor")),
            "flag_count": len(store.list_flags(d.doc_id)),
        }
        for d in docs
    ]

@app.get("/api/documents/{doc_id}")
def get_document_report(doc_id: str):
    store = get_store()
    doc = store.get_document(doc_id)
    out_file = Path(cfg.paths.outputs_dir) / "thor" / f"{doc_id}.json"
    
    exs = store.current_extractions(doc_id, "thor") if doc else []
    if not exs and out_file.exists():
        try:
            data = json.loads(out_file.read_text(encoding="utf-8"))
            if doc is not None:
                data["document"] = {**doc.model_dump(), **data.get("document", {})}
            return data
        except Exception as e:
            logger.warning("Error reading %s: %s", out_file, e)

    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    return {
        "document": doc.model_dump(),
        "clauses": [c.model_dump() for c in store.list_clauses(doc_id)],
        "extractions": [
            {
                **e.model_dump(),
                "citations": [c.model_dump() for c in store.citations_for(e.id)],
            }
            for e in exs
        ],
        "flags": [f.model_dump() for f in store.list_flags(doc_id)],
        "doc_relations": [r.model_dump() for r in store.list_relations(doc_id)],
    }

@app.post("/api/upload")
async def upload_contract(file: UploadFile = File(...)):
    store = get_store()
    name = file.filename or "contract.txt"
    content = await file.read()
    
    # Extract text from PDF or decode plain text
    if name.lower().endswith(".pdf"):
        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:
            try:
                import pypdfium2
                pdf = pypdfium2.PdfDocument(content)
                text = "\n\n".join(page.get_textpage().get_text_range() for page in pdf)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Could not extract text from PDF: {exc}")
    else:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

    if not text.strip():
        raise HTTPException(status_code=400, detail="Document text is empty or could not be read.")

    # Determine unique doc_id
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", Path(name).stem) or "DOC"
    doc_id = stem
    counter = 1
    while store.get_document(doc_id) is not None:
        doc_id = f"{stem}_{counter}"
        counter += 1

    # Save to contracts directory
    dest_path = cfg.paths.bundle_dir / "contracts" / f"{doc_id}.txt"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(text, encoding="utf-8")

    # Ingest & segment using upload pipeline
    upload_res = ingest_file(
        content if name.lower().endswith(".txt") else text.encode("utf-8"),
        f"{doc_id}.txt",
        store=store,
        cfg=cfg,
        extract=False,
        title=Path(name).stem,
    )

    llm = get_llm()
    thor = Thor(store, llm, cfg)
    
    # Run extraction: if LLM configured, try Thor; always ensure deterministic extraction if needed
    doc_obj = store.get_document(doc_id)
    clauses = store.list_clauses(doc_id)
    extraction_status = "complete"

    if llm is not None:
        try:
            thor.run([doc_id], force=True)
        except Exception as exc:
            logger.warning("Thor LLM run failed: %s", exc)

    # Check if extractions were produced. If not (or if LLM hit rate limits / failed), run deterministic extractor
    current_exs = store.current_extractions(doc_id, "thor")
    if not current_exs:
        from odin.extract_deterministic import extract_contract_fields_deterministic
        extract_contract_fields_deterministic(store, doc_obj, clauses, text)

    # Export document report JSON so the frontend static and API queries can load it immediately
    out_dir = Path(cfg.paths.outputs_dir) / "thor"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_data = thor.document_report(doc_id)
    (out_dir / f"{doc_id}.json").write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also copy to frontend public directory so any static fallback loads it seamlessly
    frontend_data_dir = Path("frontend/public/data/thor")
    if frontend_data_dir.exists():
        (frontend_data_dir / f"{doc_id}.json").write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "success",
        "doc_id": doc_id,
        "filename": name,
        "clauses": upload_res.clauses,
        "extractions": len(report_data.get("extractions", [])),
        "extraction_status": extraction_status,
        "report": report_data,
        "warnings": upload_res.warnings,
    }

@app.post("/api/reextract")
def run_reextract(req: ReextractRequest):
    store = get_store()
    clause = store.get_clause(req.clause_id)
    if clause is None:
        raise HTTPException(status_code=404, detail=f"Clause {req.clause_id} not found in store")

    llm = get_llm()
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="LLM client not available or API key not set in environment (set LLM_API_KEY in .env)"
        )

    thor = Thor(store, llm, cfg)
    try:
        res = thor.reextract(req.doc_id, req.clause_id, req.question)
        
        # Fetch updated extractions
        exs = store.current_extractions(req.doc_id, "thor")
        updated_extractions = [
            {
                **e.model_dump(),
                "citations": [c.model_dump() for c in store.citations_for(e.id)],
            }
            for e in exs
            if e.id in res.new_ids
        ]
        
        return {
            "status": "success",
            "doc_id": req.doc_id,
            "clause_id": req.clause_id,
            "answer": res.answer,
            "new_ids": res.new_ids,
            "superseded_ids": res.superseded_ids,
            "unchanged_ids": res.unchanged_ids,
            "unverified": res.unverified,
            "updated_extractions": updated_extractions,
        }
    except Exception as exc:
        logger.exception("Re-extraction failed")
        raise HTTPException(status_code=500, detail=f"Re-extraction error: {exc}")


# ============================================================
# NORNS — Timeline & Obligations API
# ============================================================

def get_norns(contracts: list[str] | None = None):
    """Build a Norns agent instance for the given contracts (or all configured)."""
    try:
        from odin.norns.engine import Norns
        store = get_store()
        llm = get_llm()
        return Norns(store, llm, cfg, contracts=contracts)
    except Exception as exc:
        logger.error("Could not instantiate NORNS: %s", exc)
        raise HTTPException(status_code=503, detail=f"NORNS engine unavailable: {exc}")


@app.get("/api/norns/documents")
def norns_documents():
    """List all documents that NORNS can process (have THOR extractions)."""
    store = get_store()
    docs = store.list_documents()
    result = []
    for d in docs:
        exs = store.current_extractions(d.doc_id, "thor")
        if exs or d.status in ("complete", "done"):
            result.append({
                "doc_id": d.doc_id,
                "title": d.title or f"Contract {d.doc_id}",
                "status": d.status,
                "coverage": d.coverage or 0.0,
                "extraction_count": len(exs),
                "clause_count": len(store.list_clauses(d.doc_id)),
            })
    return result


@app.get("/api/norns/timeline")
def norns_timeline(
    as_of: Optional[str] = Query(None, description="ISO date YYYY-MM-DD; defaults to today"),
    doc_id: Optional[str] = Query(None, description="Restrict to a single document"),
):
    """Compute the NORNS timeline for the given date and optional document filter."""
    try:
        target_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {as_of}")

    contracts = [doc_id] if doc_id else None
    norns = get_norns(contracts)
    try:
        norns.load()
        timeline = norns.compute(target_date)
        summary = timeline.summary(due_soon_days=7)
        # Enrich with all instances serialized
        summary["all_instances"] = [i.view() for i in timeline.instances]
        summary["penalty_triggers"] = timeline.penalty_triggers
        return summary
    except Exception as exc:
        logger.warning("NORNS timeline failed, returning empty: %s", exc)
        return {
            "as_of": str(target_date),
            "contracts": contracts or [],
            "status_counts": {},
            "overdue": [],
            "due_now": [],
            "next_deadlines": [],
            "renewal_deadlines": {},
            "penalty_triggers": [],
            "unmatched_ledger": [],
            "out_of_scope_ledger": [],
            "flags": ["NORNS engine could not load. Ensure THOR extractions exist for configured contracts."],
            "all_instances": [],
            "_error": str(exc),
        }


@app.get("/api/norns/obligations")
def norns_obligations(
    as_of: Optional[str] = Query(None),
    doc_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, description="overdue|upcoming|paid|all"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return paginated obligation instances, optionally filtered by status."""
    try:
        target_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {as_of}")

    contracts = [doc_id] if doc_id else None
    norns = get_norns(contracts)
    try:
        norns.load()
        timeline = norns.compute(target_date)
        instances = [i.view() for i in timeline.instances]
        # Filter by status
        if status_filter and status_filter != "all":
            if status_filter == "overdue":
                instances = [i for i in instances if i["status"] in ("unpaid", "partial", "missed") and i["due"] and i["due"] < str(target_date)]
            elif status_filter == "upcoming":
                instances = [i for i in instances if i["status"] == "upcoming"]
            elif status_filter == "paid":
                instances = [i for i in instances if i["status"] in ("paid_on_time", "paid_late")]
        total = len(instances)
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "as_of": str(target_date),
            "obligations": instances[offset:offset + limit],
        }
    except Exception as exc:
        logger.warning("NORNS obligations failed: %s", exc)
        return {"total": 0, "offset": offset, "limit": limit, "as_of": str(target_date), "obligations": [], "_error": str(exc)}


@app.get("/api/norns/worst-case")
def norns_worst_case(
    as_of: Optional[str] = Query(None),
    doc_id: Optional[str] = Query(None),
    projection_months: int = Query(12, ge=1, le=60),
):
    """Compute worst-case financial exposure projection."""
    try:
        target_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {as_of}")

    contracts = [doc_id] if doc_id else None
    norns = get_norns(contracts)
    try:
        norns.load()
        from odin.norns.worst_case import WorstCaseEngine
        engine = WorstCaseEngine(norns)
        wc = engine.compute(target_date, projection_months=projection_months)
        return {
            "as_of": str(target_date),
            "projection_end": str(wc.projection_end),
            "worst_case_total": str(wc.total("worst_case")),
            "on_time_total": str(wc.total("on_time")),
            "avoidable_exposure": str(wc.avoidable),
            "accruals": [
                {
                    "scenario": a.scenario,
                    "contract": a.contract,
                    "category": a.category,
                    "description": a.description,
                    "formula": a.formula,
                    "amount": str(a.amount),
                    "at": str(a.at),
                    "end": str(a.end) if a.end else None,
                    "citations": a.citations,
                }
                for a in wc.accruals
            ],
            "unquantified": wc.unquantified,
            "deadlines": wc.deadlines,
            "flags": wc.flags,
        }
    except Exception as exc:
        logger.warning("Worst-case engine failed: %s", exc)
        return {
            "as_of": str(target_date),
            "projection_end": str(target_date + timedelta(days=30 * projection_months)),
            "worst_case_total": "0.00",
            "on_time_total": "0.00",
            "avoidable_exposure": "0.00",
            "accruals": [],
            "unquantified": [],
            "deadlines": [],
            "flags": [f"Worst-case engine unavailable: {exc}"],
            "_error": str(exc),
        }
