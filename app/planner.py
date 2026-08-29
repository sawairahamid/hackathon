from __future__ import annotations

from typing import Any

from app.llm import complete_json
from app.models import Entities, Plan, PlanStep, StepCondition
from app.tools import registered

PLANNER_PROMPT = """You are a workflow planner for an agentic procurement system.
Return JSON: {{"title": str, "summary": str, "steps": [{{
  "id": "s1", "name": str, "tool": str, "description": str,
  "inputs": object, "depends_on": [str],
  "condition": {{"type": "always"|"deps_ok"|"field_true"|"output_nonempty", "step": str|null, "field": str|null}},
  "on_fail": "retry"|"escalate"|"skip", "max_retries": 2
}}]}}

Rules:
- Use ONLY these tools: {tools}
- Prefer this canonical sequence: fetch_suppliers -> rank_suppliers -> validate_selection -> generate_purchase_order -> submit_for_approval -> compile_report
- Inputs may reference $entities.field or $sN.output or $sN.output.path
- Always include workflow_id: "$entities.extra.workflow_id" on submit_for_approval and generate_purchase_order
- Do not invent tools. Do not skip validation or the human approval gate.

Entities:
{entities}
"""


def template_plan(entities: Entities) -> Plan:
    intent_label = "Vendor comparison" if entities.intent == "vendor_comparison" else "Procurement"
    title = f"{intent_label}: {entities.quantity} × {entities.item} · {entities.currency} {entities.budget:,.0f} ceiling"
    steps = [
        PlanStep(
            id="s1",
            name="Fetch supplier quotes",
            tool="fetch_suppliers",
            description="Fetch exactly the requested number of unique supplier quotes (default 3).",
            inputs={
                "item": "$entities.item",
                "quantity": "$entities.quantity",
                "currency": "$entities.currency",
                "limit": "$entities.suppliers_to_compare",
                "budget": "$entities.budget",
                "chaos": "$entities.extra.chaos",
            },
            depends_on=[],
            condition=StepCondition(type="always"),
            on_fail="retry",
            max_retries=2,
        ),
        PlanStep(
            id="s2",
            name="Score & rank under budget",
            tool="rank_suppliers",
            description="Reject over-budget quotes, rank the rest on price 50 / delivery 30 / warranty 20.",
            inputs={
                "quotes": "$s1.output",
                "budget": "$entities.budget",
                "currency": "$entities.currency",
                "quantity": "$entities.quantity",
            },
            depends_on=["s1"],
            condition=StepCondition(type="output_nonempty", step="s1"),
            on_fail="escalate",
            max_retries=1,
        ),
        PlanStep(
            id="s3",
            name="Validate selection",
            tool="validate_selection",
            description="Re-check budget, quantity, supplier consistency, and required fields.",
            inputs={
                "entities": "$entities",
                "quotes": "$s1.output",
                "ranking": "$s2.output",
            },
            depends_on=["s2"],
            condition=StepCondition(type="deps_ok"),
            on_fail="retry",
            max_retries=1,
        ),
        PlanStep(
            id="s4",
            name="Generate purchase order",
            tool="generate_purchase_order",
            description="Render a PO PDF with line items, totals, and the chosen supplier.",
            inputs={
                "entities": "$entities",
                "selected": "$s2.output.selected",
                "ranking": "$s2.output",
                "workflow_id": "$entities.extra.workflow_id",
            },
            depends_on=["s3"],
            condition=StepCondition(type="field_true", step="s3", field="passed"),
            on_fail="escalate",
        ),
        PlanStep(
            id="s5",
            name="Route for human approval",
            tool="submit_for_approval",
            description="Park the PO in the approval inbox. The agent cannot approve its own spend.",
            inputs={
                "workflow_id": "$entities.extra.workflow_id",
                "approver": "$entities.approval_target",
                "artifact_url": "$s4.output.url",
                "po_number": "$s4.output.po_number",
                "summary": "$s2.output.justification",
            },
            depends_on=["s4"],
            condition=StepCondition(type="deps_ok"),
            on_fail="retry",
        ),
        PlanStep(
            id="s6",
            name="Compile stakeholder report",
            tool="compile_report",
            description="Plain-language summary of request, decision, tools, artifact, and status.",
            inputs={
                "request": "$entities.raw_request",
                "entities": "$entities",
                "ranking": "$s2.output",
                "validation": "$s3.output",
                "po": "$s4.output",
                "approval": "$s5.output",
                "status": "pending_approval",
            },
            depends_on=["s5"],
            condition=StepCondition(type="deps_ok"),
            on_fail="skip",
        ),
    ]
    return Plan(title=title, summary="Plan → tool execution → validation → human approval → report.", source="template", steps=steps)


def _coerce_plan(raw: dict[str, Any], fallback: Plan) -> Plan | None:
    tools = set(registered())
    steps_in = raw.get("steps") or []
    if len(steps_in) < 4:
        return None
    steps: list[PlanStep] = []
    for i, s in enumerate(steps_in, start=1):
        tool = s.get("tool")
        if tool not in tools:
            return None
        cond = s.get("condition") or {"type": "always"}
        if isinstance(cond, str):
            cond = {"type": cond}
        steps.append(
            PlanStep(
                id=str(s.get("id") or f"s{i}"),
                name=s.get("name") or tool,
                tool=tool,
                description=s.get("description") or "",
                inputs=s.get("inputs") or {},
                depends_on=list(s.get("depends_on") or []),
                condition=StepCondition.model_validate(cond),
                on_fail=s.get("on_fail") or "retry",
                max_retries=int(s.get("max_retries") or 2),
            )
        )
    names = {s.tool for s in steps}
    required = {"fetch_suppliers", "rank_suppliers", "validate_selection", "generate_purchase_order", "submit_for_approval"}
    if not required.issubset(names):
        return None
    return Plan(
        title=raw.get("title") or fallback.title,
        summary=raw.get("summary") or fallback.summary,
        source="llm",
        steps=steps,
    )


def plan_workflow(entities: Entities) -> tuple[Plan, str]:
    fallback = template_plan(entities)
    tools = ", ".join(sorted(registered()))
    parsed, tag = complete_json(
        PLANNER_PROMPT.format(tools=tools, entities=entities.model_dump_json(indent=2))
    )
    if not parsed:
        return fallback, f"template:{tag}"
    coerced = _coerce_plan(parsed, fallback)
    if not coerced:
        return fallback, f"template:{tag}:invalid_llm"
    return coerced, tag
