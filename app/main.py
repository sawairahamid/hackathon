"""OrchestrAI API + static UI."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx

from app import trace
from app.executor import run_workflow
from app.llm import provider_status
from app.models import ApprovalDecision, CreateWorkflowRequest
from app.parser import parse_request
from app.planner import plan_workflow
from app.tools import load_all, registered
from app import domain_ext  # noqa: F401 — registers UC3/UC4 tools + patches parser/planner

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
GENERATED = ROOT / "generated"
GENERATED.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="OrchestrAI", version="1.0.0")
_tasks: set[asyncio.Task] = set()


def _decode_workflow(row: dict) -> dict:
    out = dict(row)
    for key in ("entities_json", "plan_json", "chaos_json"):
        raw = out.pop(key, None)
        name = key.replace("_json", "")
        if raw:
            try:
                out[name] = json.loads(raw)
            except json.JSONDecodeError:
                out[name] = None
        else:
            out[name] = None
    return out


def _snapshot(wid: str) -> dict:
    row = trace.get_workflow(wid)
    if not row:
        raise HTTPException(404, "workflow not found")
    snap = _decode_workflow(row)
    snap["steps"] = trace.list_steps(wid)
    snap["events"] = trace.list_events(wid)
    snap["tool_calls"] = trace.list_tool_calls(wid)
    snap["approvals"] = [a for a in trace.list_approvals() if a["workflow_id"] == wid]
    return snap


@app.on_event("startup")
async def _startup() -> None:
    trace.init_db()
    trace.set_event_loop(asyncio.get_running_loop())
    load_all()


@app.get("/api/health")
def health() -> dict:
    mock_ok = False
    url = os.getenv("SUPPLIER_API_URL", "http://127.0.0.1:8001")
    try:
        r = httpx.get(f"{url}/health", timeout=1.0)
        mock_ok = r.status_code == 200
    except Exception:
        mock_ok = False
    return {
        "ok": True,
        "mock_supplier_api": mock_ok,
        "llm": provider_status(),
        "tools": list(registered()),
    }


@app.get("/api/tools")
def tools() -> dict:
    return registered()


@app.get("/api/workflows")
def workflows() -> list[dict]:
    return trace.list_workflows()


@app.post("/api/workflows")
async def create_workflow(body: CreateWorkflowRequest) -> dict:
    wid = "wf_" + uuid.uuid4().hex[:12]
    chaos = body.chaos.model_dump()
    trace.create_workflow(wid, body.request, chaos)
    trace.emit(wid, "workflow_created", "Request received", payload={"chaos": chaos})

    entities, parse_tag = parse_request(body.request)
    extra = dict(entities.extra or {})
    extra["workflow_id"] = wid
    extra["chaos"] = chaos
    entities.extra = extra
    trace.set_workflow_fields(
        wid,
        status="planning",
        entities_json=entities.model_dump_json(),
    )
    trace.emit(
        wid,
        "entities_extracted",
        f"Parsed {entities.intent}: {entities.quantity} × {entities.item} under {entities.currency} {entities.budget:,.0f} ({parse_tag})",
        payload=json.loads(entities.model_dump_json()),
    )

    plan, plan_tag = plan_workflow(entities)
    trace.set_workflow_fields(wid, plan_json=plan.model_dump_json())
    trace.emit(
        wid,
        "plan_created",
        f"Plan ready ({plan.source}/{plan_tag}): {len(plan.steps)} steps — execution has not started yet",
        payload=json.loads(plan.model_dump_json()),
    )

    def _runner():
        from app.models import Plan
        current_plan = plan
        while True:
            res = run_workflow(wid, entities, current_plan)
            if res == "REPLAN":
                # Fetch the newly replanned version
                row = trace.get_workflow(wid)
                if row and row.get("plan_json"):
                    current_plan = Plan(**json.loads(row["plan_json"]))
                    continue
            break

    task = asyncio.create_task(asyncio.to_thread(_runner))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    return {
        "id": wid,
        "entities": json.loads(entities.model_dump_json()),
        "plan": json.loads(plan.model_dump_json()),
        "parse_provider": parse_tag,
        "plan_provider": plan_tag,
    }


@app.get("/api/workflows/{wid}")
def get_workflow(wid: str) -> dict:
    return _snapshot(wid)

@app.get("/api/workflows/{wid}/incidents")
def get_incidents(wid: str) -> dict:
    incidents = trace.list_incidents(wid)
    actions = trace.list_recovery_actions(wid)
    return {"incidents": incidents, "actions": actions}

from app.impact import calculate_impact

@app.get("/api/workflows/{wid}/impact")
def get_impact(wid: str) -> dict:
    wf = trace.get_workflow(wid)
    if not wf:
        raise HTTPException(404, "workflow not found")
    return calculate_impact(wid)


@app.get("/api/workflows/{wid}/events")
async def stream_events(wid: str):
    if not trace.get_workflow(wid):
        raise HTTPException(404, "workflow not found")

    async def gen():
        seen: set[int] = set()
        q = trace.subscribe(wid)
        try:
            for ev in trace.list_events(wid):
                eid = ev.get("id")
                if eid is not None:
                    seen.add(eid)
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            while True:
                ev = await q.get()
                eid = ev.get("id")
                if eid in seen:
                    continue
                if eid is not None:
                    seen.add(eid)
                yield f"data: {json.dumps(ev, default=str)}\n\n"
                if ev.get("type") in ("workflow_completed", "workflow_failed"):
                    await asyncio.sleep(0.05)
                    break
        finally:
            trace.unsubscribe(wid, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/approvals")
def approvals(status: str | None = "pending_approval") -> list[dict]:
    return trace.list_approvals(status)


@app.post("/api/workflows/{wid}/approval")
def decide(wid: str, body: ApprovalDecision) -> dict:
    rec = trace.resolve_approval(wid, body.decision, body.note)
    if not rec:
        raise HTTPException(404, "no approval request for this workflow")
    status = "approved" if body.decision == "approve" else "rejected"
    trace.set_workflow_fields(wid, status=status)
    trace.emit(
        wid,
        "approval_resolved",
        f"Human {status} the purchase" + (f" — {body.note}" if body.note else ""),
        payload={"decision": body.decision, "note": body.note},
    )
    row = trace.get_workflow(wid)
    report = (row or {}).get("report") or ""
    stamp = f"\n\n---\n**Human decision:** {status.upper()}" + (f" — {body.note}" if body.note else "") + "\n"
    if report and "**Human decision:**" not in report:
        report = report.rstrip() + stamp
        trace.set_workflow_fields(wid, report=report)
        trace.emit(wid, "report_ready", "Report updated with the human decision")
        
    try:
        if row and row.get("entities_json"):
            entities = json.loads(row["entities_json"])
            steps = trace.list_steps(wid)
            rank_step = next((s for s in steps if s.get("tool") == "rank_suppliers"), None)
            po_step = next((s for s in steps if s.get("tool") == "generate_purchase_order"), None)
            if rank_step and rank_step.get("output") and po_step and po_step.get("output"):
                from app.tools.documents import render_po
                po_data = po_step["output"]
                rank_data = rank_step["output"]
                if "po_number" in po_data and "selected" in rank_data:
                    render_po(
                        po_number=po_data["po_number"],
                        entities=entities,
                        selected=rank_data["selected"],
                        ranking=rank_data,
                        approval_status=status,
                        approval_note=body.note,
                    )
    except Exception as e:
        import logging
        logging.error("Failed to re-render PO on approval: %s", e)

    return {"approval": rec, "status": status}


@app.get("/artifacts/{name}")
def artifact(name: str):
    path = GENERATED / name
    if not path.exists() or path.suffix.lower() != ".pdf":
        raise HTTPException(404, "artifact not found")
    return FileResponse(path, media_type="application/pdf", filename=name)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
