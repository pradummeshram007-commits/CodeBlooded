"""ODIN / THOR HTTP API Server.

Exposes REST endpoints for:
- Document listing & inspection
- Contract uploading & segmentation (TXT / PDF)
- Clause-level evidence retrieval
- Targeted re-extraction via Thor.reextract
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from odin.agents.thor import Thor
from odin.config import load_config
from odin.ingest.loader import ingest_document
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

    # Ingest & segment
    ingest_res = ingest_document(store, dest_path, f"contracts/{doc_id}.txt", title=Path(name).stem, source="upload")

    llm = get_llm()
    thor = Thor(store, llm, cfg)
    
    # Run extraction: if LLM configured, try Thor; otherwise execute deterministic verbatim extraction
    extraction_status = "complete"
    doc_obj = store.get_document(doc_id)
    clauses = store.list_clauses(doc_id)

    if llm is not None:
        try:
            thor.run([doc_id], force=True)
            extraction_status = "complete"
        except Exception as exc:
            logger.warning("LLM extraction failed, falling back to deterministic extraction: %s", exc)
            from odin.extract_deterministic import extract_contract_fields_deterministic
            extract_contract_fields_deterministic(store, doc_obj, clauses, text)
    else:
        from odin.extract_deterministic import extract_contract_fields_deterministic
        extract_contract_fields_deterministic(store, doc_obj, clauses, text)

    # Export document report JSON so the frontend static and API queries can load it immediately
    out_dir = Path(cfg.paths.outputs_dir) / "thor"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_data = thor.document_report(doc_id)
    (out_dir / f"{doc_id}.json").write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "success",
        "doc_id": doc_id,
        "filename": name,
        "clauses": ingest_res.clauses,
        "extractions": len(report_data.get("extractions", [])),
        "extraction_status": extraction_status,
        "warnings": ingest_res.warnings,
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
