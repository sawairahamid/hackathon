"""Launch mock vendor API (8001) and OrchestrAI (8000) together."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    py = sys.executable
    mock = subprocess.Popen(
        [py, "-m", "uvicorn", "mock_api.server:app", "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
        cwd=ROOT,
    )
    time.sleep(0.7)
    try:
        print("\n  OrchestrAI  http://127.0.0.1:8000")
        print("  Vendor API  http://127.0.0.1:8001/health\n")
        subprocess.run(
            [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=ROOT,
            check=False,
        )
    finally:
        mock.terminate()
        try:
            mock.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock.kill()


if __name__ == "__main__":
    main()
