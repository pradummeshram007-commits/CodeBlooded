"""ODIN Backend Server Entrypoint.

Exposes the FastAPI application and allows starting the server directly:
    python backend/main.py
or via uvicorn:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
"""
import os
import sys
from pathlib import Path

# Ensure the project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

# Import the FastAPI application from odin.api
from odin.api import app

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Starting ODIN Backend on http://{host}:{port} ...")
    uvicorn.run("backend.main:app", host=host, port=port, reload=True, log_level="info")
