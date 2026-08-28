from __future__ import annotations

import json
from copy import deepcopy

from app import trace
from app.models import Plan


def replan_workflow(wid: str, step_id: str, incident_id: str, error_type: str) -> Plan:
    """
    Mutates the current workflow plan to insert recovery steps.
    Returns the new Plan object.
    """
    row = trace.get_workflow(wid)
    if not row or not row.get("plan_json"):
        raise RuntimeError("Workflow or plan not found")
        
    plan_dict = json.loads(row["plan_json"])
    plan = Plan(**plan_dict)
    
    # Bump version
    current_version = row.get("workflow_version", 1)
    new_version = current_version + 1
    
    # Example logic for budget violation / validation failure:
    # Original: s1 -> s2 -> s3 (fails) -> s4 -> s5
    # New: s1 -> s2 -> s3 -> s3_replan -> s4_replan -> s5_replan
    
    if error_type in ("BUDGET_VIOLATION", "VALIDATION_FAILURE"):
        # Find where we failed
        # Usually s3 is validate_selection.
        
        # We will add new steps for re-ranking and re-validating
        steps_db = trace.list_steps(wid)
        failed_out = {}
        for s in steps_db:
            if s.get("step_id") == step_id:
                failed_out = s.get("output") or {}
                break
        exclude_ids = failed_out.get("suggested_exclude_ids") or []

        s2_replan = {
            "id": f"s2_v{new_version}",
            "name": f"Re-rank suppliers (v{new_version})",
            "tool": "rank_suppliers",
            "description": "Recalculate ranking excluding the budget violator.",
            "inputs": {
                "quotes": "$s1.output",
                "budget": "$entities.budget",
                "currency": "$entities.currency",
                "quantity": "$entities.quantity",
                "exclude_ids": exclude_ids
            },
            "depends_on": [],
            "condition": {"type": "always"},
            "on_fail": "escalate",
            "max_retries": 1
        }
        
        s3_replan = {
            "id": f"s3_v{new_version}",
            "name": f"Re-validate selection (v{new_version})",
            "tool": "validate_selection",
            "inputs": {
                "entities": "$entities",
                "quotes": "$s1.output",
                "ranking": f"${s2_replan['id']}.output"
            },
            "depends_on": [s2_replan["id"]],
            "condition": {"type": "always"},
            "on_fail": "escalate",
            "max_retries": 1
        }
        
        s4_replan = {
            "id": f"s4_v{new_version}",
            "name": f"Generate new PO (v{new_version})",
            "tool": "generate_purchase_order",
            "inputs": {
                "entities": "$entities",
                "ranking": f"${s2_replan['id']}.output"
            },
            "depends_on": [s3_replan["id"]],
            "condition": {"type": "always"},
            "on_fail": "retry",
            "max_retries": 2
        }
        
        s5_replan = {
            "id": f"s5_v{new_version}",
            "name": f"Request Approval (v{new_version})",
            "tool": "submit_for_approval",
            "inputs": {
                "approver": "$entities.approval_target",
                "po": f"${s4_replan['id']}.output"
            },
            "depends_on": [s4_replan["id"]],
            "condition": {"type": "always"},
            "on_fail": "retry",
            "max_retries": 2
        }
        
        # We append these to the plan.
        # But we also need to skip the original s4/s5 if they haven't run yet.
        # So we filter out the old un-run downstream steps.
        
        # Keep steps up to the failure point (including the failed step itself to show it)
        # Assuming the failure was on s3 (or something that produces a validation error)
        
        idx = 0
        for i, s in enumerate(plan.steps):
            if s.id == step_id:
                idx = i
                break
                
        new_steps = plan.steps[:idx]
        
        from app.models import PlanStep
        new_steps.append(PlanStep(**s2_replan))
        new_steps.append(PlanStep(**s3_replan))
        new_steps.append(PlanStep(**s4_replan))
        new_steps.append(PlanStep(**s5_replan))
        
        # If there's a compile_report step (like s6), append a new version of it too
        s6 = next((s for s in plan.steps if s.tool == "compile_report"), None)
        if s6:
            s6_replan = deepcopy(s6.model_dump())
            s6_replan["id"] = f"{s6.id}_v{new_version}"
            s6_replan["name"] = f"{s6.name} (v{new_version})"
            s6_replan["depends_on"] = [s5_replan["id"]]
            # Need to update inputs to point to new versions if they use them
            inputs = s6_replan["inputs"]
            if isinstance(inputs, dict):
                for k, v in inputs.items():
                    if isinstance(v, str) and v.startswith("$"):
                        # Replace old refs like $s2 with $s2_vX
                        if "s2.output" in v: inputs[k] = v.replace("s2.output", f"{s2_replan['id']}.output")
                        if "s3.output" in v: inputs[k] = v.replace("s3.output", f"{s3_replan['id']}.output")
                        if "s4.output" in v: inputs[k] = v.replace("s4.output", f"{s4_replan['id']}.output")
                        if "s5.output" in v: inputs[k] = v.replace("s5.output", f"{s5_replan['id']}.output")
            new_steps.append(PlanStep(**s6_replan))
            
        plan.steps = new_steps
        plan.title = f"{plan.title} (v{new_version})"
        plan.summary = f"{plan.summary} - Replanned after incident {error_type}"
        
        # Update database
        trace.set_workflow_fields(wid, plan_json=plan.model_dump_json(), workflow_version=new_version)
        
        # Emit event so UI redraws the DAG
        trace.emit(wid, "plan_created", f"Dynamic Replan (v{new_version}) created", payload=json.loads(plan.model_dump_json()))
        
        return plan

    # Default fallback: don't replan
    return plan
