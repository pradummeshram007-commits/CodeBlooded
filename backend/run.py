"""ODIN Backend Server Runner with automatic port conflict resolution.

Usage:
    python backend/run.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "127.0.0.1")

def free_port(port: int):
    """Detect and terminate any existing process listening on the given port."""
    try:
        if sys.platform == "win32":
            res = subprocess.run(
                f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
                shell=True,
                capture_output=True,
                text=True,
            )
            for line in res.stdout.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}"):
                    pid = parts[-1]
                    try:
                        my_pid = str(os.getpid())
                        if pid != my_pid and int(pid) > 0:
                            print(f"[backend] Freeing port {port} (killing PID {pid})...")
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                            time.sleep(0.5)
                    except Exception as e:
                        print(f"[backend] Warning: could not kill PID {pid}: {e}")
    except Exception as exc:
        print(f"[backend] Port check note: {exc}")

if __name__ == "__main__":
    free_port(PORT)
    import uvicorn
    print(f"\n========================================================")
    print(f"  ODIN Autonomous Contract Intelligence API Server")
    print(f"  URL:  http://{HOST}:{PORT}")
    print(f"  Docs: http://{HOST}:{PORT}/docs")
    print(f"========================================================\n")
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=True, log_level="info")
