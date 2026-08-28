"""Human-in-the-loop approval queue. The agent must never auto-approve spend."""

from __future__ import annotations

import uuid

from app import trace
from app.models import ToolResult
from app.tools import tool


@tool(
    name="submit_for_approval",
    description="Route the generated PO into the human approval inbox. Never auto-approves.",
)
def submit_for_approval(
    workflow_id: str,
    summary: str,
    approver: str = "procurement_manager",
    artifact_url: str | None = None,
    po_number: str | None = None,
) -> ToolResult:
    aid = "appr_" + uuid.uuid4().hex[:10]
    rec = trace.create_approval(
        aid,
        workflow_id,
        approver,
        summary=summary if not po_number else f"{po_number}: {summary}",
        artifact_url=artifact_url,
    )
    rec["po_number"] = po_number
    return ToolResult(ok=True, tool="submit_for_approval", data=rec, source="local")


@tool(
    name="compile_report",
    description="Assemble a structured, non-technical completion report from the workflow trace.",
)
def compile_report(
    request: str = "",
    entities: dict | None = None,
    ranking: dict | None = None,
    validation: dict | None = None,
    po: dict | None = None,
    approval: dict | None = None,
    tools_used: list | None = None,
    status: str = "pending_approval",
) -> ToolResult:
    from app.reporter import build_report

    text = build_report(
        request=request,
        entities=entities or {},
        ranking=ranking or {},
        validation=validation or {},
        po=po or {},
        approval=approval or {},
        tools_used=tools_used or [],
        status=status,
        llm_polish=True,
    )
    return ToolResult(ok=True, tool="compile_report", data={"report": text, "status": status}, source="local")
