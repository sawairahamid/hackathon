from __future__ import annotations

def determine_recovery(error_type: str, severity: str, attempt: int, max_retries: int, step_id: str) -> tuple[str, str]:
    """
    Returns (Action, Reason)
    """
    if error_type in ("TOOL_TIMEOUT", "INVALID_TOOL_RESPONSE"):
        if attempt < max_retries:
            return "RETRY", f"Transient error '{error_type}', retrying ({attempt}/{max_retries})"
        return "ESCALATE", f"Max retries reached for {error_type}"

    if error_type == "TOOL_UNAVAILABLE":
        if attempt < max_retries:
            return "RETRY", "Service unavailable, retrying"
        return "FALLBACK", "Falling back to bundled catalog after HTTP failure"

    if error_type in ("BUDGET_VIOLATION", "VALIDATION_FAILURE"):
        # For validation failures, we should REPLAN if possible
        if step_id.startswith("s3"):  # validation step
            return "REPLAN", f"{error_type} detected at validation; replanning workflow"
        return "ESCALATE", f"Cannot recover from {error_type} at this stage"

    if severity == "CRITICAL":
        return "ESCALATE", "Critical severity incident requires human intervention"

    return "ESCALATE", f"No specific recovery policy for {error_type}"
