"""Isolate tests on a throwaway SQLite file. No API key required."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="orchestrai-tests-"))
os.environ["DATABASE_PATH"] = str(_TMP / "test.db")
os.environ["GEMINI_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ.setdefault("SUPPLIER_API_URL", "http://127.0.0.1:9")  # force local catalog fallback

import pytest

from app import trace
from app.tools import load_all


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    if getattr(trace._local, "conn", None):
        try:
            trace._local.conn.close()
        except Exception:
            pass
        trace._local.conn = None
    trace.init_db()
    load_all()
    yield
    if getattr(trace._local, "conn", None):
        try:
            trace._local.conn.close()
        except Exception:
            pass
        trace._local.conn = None
