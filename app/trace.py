from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_DB = DATA_DIR / "orchestrai.db"

_local = threading.local()
_lock = threading.Lock()
_subscribers: dict[str, list[asyncio.Queue]] = {}
_loop: asyncio.AbstractEventLoop | None = None


def db_path() -> Path:
    raw = os.getenv("DATABASE_PATH", str(DEFAULT_DB))
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(db_path(), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


@contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    conn = _connect()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with cursor() as cur:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                request TEXT NOT NULL,
                entities_json TEXT,
                plan_json TEXT,
                report TEXT,
                chaos_json TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS steps (
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                name TEXT,
                tool TEXT,
                status TEXT NOT NULL,
                attempt INTEGER DEFAULT 0,
                output_json TEXT,
                error TEXT,
                started_at TEXT,
                finished_at TEXT,
                PRIMARY KEY (workflow_id, step_id)
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                step_id TEXT,
                tool TEXT NOT NULL,
                inputs_json TEXT,
                outputs_json TEXT,
                ok INTEGER NOT NULL,
                latency_ms INTEGER,
                ts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                step_id TEXT,
                message TEXT NOT NULL,
                payload_json TEXT
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                approver TEXT,
                note TEXT,
                artifact_url TEXT,
                summary TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS llm_cache (
                prompt_hash TEXT PRIMARY KEY,
                provider TEXT,
                model TEXT,
                response TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_wf ON events(workflow_id, id);
            CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
            """
        )


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def create_workflow(wid: str, request: str, chaos: dict[str, Any] | None = None) -> None:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO workflows (id, created_at, status, request, chaos_json) VALUES (?,?,?,?,?)",
            (wid, utcnow(), "pending", request, json.dumps(chaos or {})),
        )


def set_workflow_fields(wid: str, **fields: Any) -> None:
    if not fields:
        return
    cols = []
    vals = []
    for k, v in fields.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(wid)
    with cursor() as cur:
        cur.execute(f"UPDATE workflows SET {', '.join(cols)} WHERE id = ?", vals)


def get_workflow(wid: str) -> dict[str, Any] | None:
    with cursor() as cur:
        row = cur.execute("SELECT * FROM workflows WHERE id = ?", (wid,)).fetchone()
    return dict(row) if row else None


def list_workflows(limit: int = 30) -> list[dict[str, Any]]:
    with cursor() as cur:
        rows = cur.execute(
            "SELECT id, created_at, status, request FROM workflows ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_step(
    wid: str,
    step_id: str,
    *,
    name: str | None = None,
    tool: str | None = None,
    status: str | None = None,
    attempt: int | None = None,
    output: Any = None,
    error: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    now = utcnow()
    with cursor() as cur:
        existing = cur.execute(
            "SELECT step_id FROM steps WHERE workflow_id = ? AND step_id = ?",
            (wid, step_id),
        ).fetchone()
        if not existing:
            cur.execute(
                """INSERT INTO steps (workflow_id, step_id, name, tool, status, attempt, started_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (wid, step_id, name or step_id, tool or "", status or "pending", attempt or 0, now if started else None),
            )
            existing = True
            if status is None and not started:
                return
        sets = []
        vals: list[Any] = []
        if name is not None:
            sets.append("name = ?")
            vals.append(name)
        if tool is not None:
            sets.append("tool = ?")
            vals.append(tool)
        if status is not None:
            sets.append("status = ?")
            vals.append(status)
        if attempt is not None:
            sets.append("attempt = ?")
            vals.append(attempt)
        if output is not None:
            sets.append("output_json = ?")
            vals.append(json.dumps(output, default=str))
        if error is not None:
            sets.append("error = ?")
            vals.append(error)
        if started:
            sets.append("started_at = ?")
            vals.append(now)
        if finished:
            sets.append("finished_at = ?")
            vals.append(now)
        if sets:
            vals.extend([wid, step_id])
            cur.execute(
                f"UPDATE steps SET {', '.join(sets)} WHERE workflow_id = ? AND step_id = ?",
                vals,
            )


def list_steps(wid: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        rows = cur.execute(
            "SELECT * FROM steps WHERE workflow_id = ? ORDER BY started_at, step_id",
            (wid,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("output_json"):
            try:
                d["output"] = json.loads(d["output_json"])
            except json.JSONDecodeError:
                d["output"] = None
        out.append(d)
    return out


def record_tool_call(
    wid: str,
    step_id: str | None,
    tool: str,
    inputs: Any,
    outputs: Any,
    ok: bool,
    latency_ms: int,
) -> None:
    with cursor() as cur:
        cur.execute(
            """INSERT INTO tool_calls (workflow_id, step_id, tool, inputs_json, outputs_json, ok, latency_ms, ts)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                wid,
                step_id,
                tool,
                json.dumps(inputs, default=str),
                json.dumps(outputs, default=str),
                1 if ok else 0,
                latency_ms,
                utcnow(),
            ),
        )


def list_tool_calls(wid: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        rows = cur.execute(
            "SELECT * FROM tool_calls WHERE workflow_id = ? ORDER BY id",
            (wid,),
        ).fetchall()
    return [dict(r) for r in rows]


def emit(
    wid: str,
    etype: str,
    message: str,
    *,
    step_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ts = utcnow()
    payload_json = json.dumps(payload or {}, default=str)
    with cursor() as cur:
        cur.execute(
            "INSERT INTO events (workflow_id, ts, type, step_id, message, payload_json) VALUES (?,?,?,?,?,?)",
            (wid, ts, etype, step_id, message, payload_json),
        )
        eid = cur.lastrowid
    event = {
        "id": eid,
        "workflow_id": wid,
        "ts": ts,
        "type": etype,
        "step_id": step_id,
        "message": message,
        "payload": payload or {},
    }
    _broadcast(wid, event)
    return event


def list_events(wid: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        rows = cur.execute(
            "SELECT * FROM events WHERE workflow_id = ? ORDER BY id",
            (wid,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            d["payload"] = {}
        out.append(d)
    return out


def create_approval(
    aid: str,
    wid: str,
    approver: str,
    summary: str,
    artifact_url: str | None = None,
) -> dict[str, Any]:
    ts = utcnow()
    with cursor() as cur:
        cur.execute(
            """INSERT INTO approvals (id, workflow_id, status, approver, note, artifact_url, summary, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (aid, wid, "pending_approval", approver, "", artifact_url, summary, ts),
        )
    return {
        "id": aid,
        "workflow_id": wid,
        "status": "pending_approval",
        "approver": approver,
        "artifact_url": artifact_url,
        "summary": summary,
        "created_at": ts,
    }


def resolve_approval(wid: str, decision: str, note: str = "") -> dict[str, Any] | None:
    status = "approved" if decision == "approve" else "rejected"
    ts = utcnow()
    with cursor() as cur:
        row = cur.execute(
            "SELECT * FROM approvals WHERE workflow_id = ? ORDER BY created_at DESC LIMIT 1",
            (wid,),
        ).fetchone()
        if not row:
            return None
        cur.execute(
            "UPDATE approvals SET status = ?, note = ?, resolved_at = ? WHERE id = ?",
            (status, note, ts, row["id"]),
        )
    d = dict(row)
    d["status"] = status
    d["note"] = note
    d["resolved_at"] = ts
    return d


def list_approvals(status: str | None = None) -> list[dict[str, Any]]:
    with cursor() as cur:
        if status:
            rows = cur.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = cur.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def cache_get(prompt_hash: str) -> str | None:
    with cursor() as cur:
        row = cur.execute("SELECT response FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,)).fetchone()
    return row["response"] if row else None


def cache_put(prompt_hash: str, provider: str, model: str, response: str) -> None:
    with cursor() as cur:
        cur.execute(
            """INSERT OR REPLACE INTO llm_cache (prompt_hash, provider, model, response, ts)
               VALUES (?,?,?,?,?)""",
            (prompt_hash, provider, model, response, utcnow()),
        )


def subscribe(wid: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _subscribers.setdefault(wid, []).append(q)
    return q


def unsubscribe(wid: str, q: asyncio.Queue) -> None:
    with _lock:
        subs = _subscribers.get(wid, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            _subscribers.pop(wid, None)


def _broadcast(wid: str, event: dict[str, Any]) -> None:
    with _lock:
        queues = list(_subscribers.get(wid, []))
    loop = _loop
    for q in queues:
        if loop and loop.is_running():
            loop.call_soon_threadsafe(q.put_nowait, event)
        else:
            try:
                q.put_nowait(event)
            except Exception:
                pass
