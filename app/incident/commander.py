from __future__ import annotations

import uuid
from typing import Any

from app import trace
from app.models import IncidentRecord, ToolResult
from app.incident.policies import determine_recovery
from app.incident.replanner import replan_workflow


def handle_incident(wid: str, step_id: str, result: ToolResult, attempt: int, max_retries: int) -> str | None:
    """
    Classifies a failure and selects a recovery action.
    Returns a string instruction: "RETRY", "ESCALATE", "SKIP", "REPLAN", "CONTINUE", or None.
    """
    iid = "inc_" + uuid.uuid4().hex[:12]
    error = result.error or "Unknown failure"
    error_type = result.error_type or _classify_error(error)
    severity = _determine_severity(error_type)
    
    trace.emit(wid, "INCIDENT_DETECTED", f"Incident detected: {error_type}", step_id=step_id, payload={"incident_id": iid, "severity": severity, "message": error})
    trace.record_incident(iid, wid, step_id, error_type, severity, error, [step_id])

    action, reason = determine_recovery(error_type, severity, attempt, max_retries, step_id)

    trace.record_recovery_action(iid, wid, action, reason, action == "ESCALATE")
    trace.emit(wid, "RECOVERY_ACTION_SELECTED", f"Action selected: {action}", step_id=step_id, payload={"action": action, "reason": reason})

    if action == "REPLAN":
        trace.emit(wid, "REPLAN_STARTED", "Dynamically replanning workflow to recover", step_id=step_id)
        # Perform the actual replan
        new_wid = replan_workflow(wid, step_id, iid, error_type)
        trace.emit(wid, "REPLAN_COMPLETED", f"Replanned to new version: {new_wid}", step_id=step_id)
        return "REPLAN"

    return action

def _classify_error(error: str) -> str:
    err_lower = error.lower()
    if "timeout" in err_lower or "504" in err_lower:
        return "TOOL_TIMEOUT"
    if "unavailable" in err_lower or "503" in err_lower or "connection" in err_lower:
        return "TOOL_UNAVAILABLE"
    if "invalid response" in err_lower or "json" in err_lower or "malformed" in err_lower:
        return "INVALID_TOOL_RESPONSE"
    if "budget" in err_lower or "policy" in err_lower or "validation" in err_lower:
        if "budget" in err_lower:
            return "BUDGET_VIOLATION"
        return "VALIDATION_FAILURE"
    return "UNKNOWN_INCIDENT"

def _determine_severity(error_type: str) -> str:
    if error_type in ("TOOL_TIMEOUT", "INVALID_TOOL_RESPONSE"):
        return "MEDIUM"
    if error_type in ("TOOL_UNAVAILABLE", "DATA_CHANGED"):
        return "HIGH"
    if error_type in ("BUDGET_VIOLATION", "VALIDATION_FAILURE"):
        return "HIGH"
    return "LOW"
