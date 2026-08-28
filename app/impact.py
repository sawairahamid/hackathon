from __future__ import annotations

import json
from app import trace

def calculate_impact(wid: str) -> dict:
    wf = trace.get_workflow(wid)
    if not wf:
        return {}
    
    entities = json.loads(wf.get("entities_json") or "{}")
    budget = entities.get("budget", 0)
    
    steps = trace.list_steps(wid)
    tool_calls = trace.list_tool_calls(wid)
    incidents = trace.list_incidents(wid)
    actions = trace.list_recovery_actions(wid)
    events = trace.list_events(wid)
    
    duration_ms = sum(s.get("latency_ms", 0) for s in tool_calls)
    # Count unique steps that used a tool and attempted to execute
    automated_steps = len(set(s.get("step_id") for s in steps if s.get("tool") and s.get("attempt", 0) > 0))
    
    po_step = next((s for s in reversed(steps) if s.get("tool") == "generate_purchase_order" and s.get("status") == "done"), None)
    final_cost = 0
    if po_step and po_step.get("output"):
        final_cost = po_step["output"].get("grand_total", 0)
        
    savings = max(0, budget - final_cost) if final_cost > 0 else 0
    savings_percent = round((savings / budget) * 100, 1) if budget > 0 else 0
    
    ranking_steps = [s for s in steps if s.get("tool") == "rank_suppliers" and s.get("status") == "done"]
    eval_count = 0
    reject_count = 0
    
    # We can aggregate all suppliers evaluated if there are multiple versions/retries,
    # or just use the last successful ranking step
    if ranking_steps:
        last_rank = ranking_steps[-1].get("output") or {}
        eval_count = len(last_rank.get("ranked", []))
        reject_count = len(last_rank.get("rejected", []))
        
    replans = len([e for e in events if e.get("type") == "REPLAN_COMPLETED"])
    val_fails = len([e for e in events if e.get("type") == "validation" and "failed" in (e.get("message") or "").lower()])
    human_interventions = len([a for a in actions if a.get("requires_human")])
    
    return {
        "workflow_id": wid,
        "status": wf.get("status"),
        "budget": budget,
        "final_cost": final_cost,
        "savings": savings,
        "savings_percent": savings_percent,
        "suppliers_evaluated": eval_count,
        "suppliers_rejected": reject_count,
        "automated_steps": automated_steps,
        "human_interventions": human_interventions,
        "recovery_events": len(actions),
        "workflow_replans": replans,
        "tool_calls": len(tool_calls),
        "validation_failures": val_fails,
        "duration_ms": duration_ms
    }
