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
        # Ranking/validation recovery is handled in-executor (self-correct / skip PO).
        # Replanning here would re-run the failed step and can loop.
        return "ESCALATE", f"Cannot recover from {error_type} at this stage — flagged for human review"

    if severity == "CRITICAL":
        return "ESCALATE", "Critical severity incident requires human intervention"

    return "ESCALATE", f"No specific recovery policy for {error_type}"
