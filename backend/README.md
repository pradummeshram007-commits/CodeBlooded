# ODIN Backend

This directory encapsulates all backend controls, server execution scripts, and API runners for the ODIN Autonomous Multi-Agent Contract Intelligence Platform.

---

## Quick Start (How to Run the Backend)

### Option 1 — Using Python Runner (Recommended, auto-frees port 8000)
```bash
python backend/run.py
```
*Automatically detects and frees port 8000 if another process was left hanging, preventing `[Errno 10048]` socket errors.*

### Option 2 — Double-click Windows Batch Script
```bash
backend\start_server.bat
```

### Option 3 — Using Uvicorn Directly
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
or from the project root:
```bash
uvicorn odin.api:app --host 127.0.0.1 --port 8000 --reload
```

---

## API Endpoints

Once running, interactive OpenAPI documentation is available at:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Core Endpoints:
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check & system version status |
| `GET` | `/api/documents` | List all ingested contracts with counts & metadata |
| `GET` | `/api/documents/{doc_id}` | Retrieve deep report, clauses, extractions & flags |
| `POST` | `/api/upload` | Upload & segment contract PDF/TXT; runs extraction pipeline |
| `POST` | `/api/reextract` | Targeted clause-level re-extraction with custom query |
| `GET` | `/api/norns/timeline` | Global or document-specific chronological obligations timeline |
| `GET` | `/api/norns/obligations` | Structured obligations ledger with categories & frequencies |
| `GET` | `/api/norns/worst-case` | Worst-case liability simulation & financial exposure calculation |
| `GET` | `/api/norns/summary` | Executive contract intelligence summary |
