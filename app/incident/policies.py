from __future__ import annotations


def determine_recovery(
    error_type: str,
    severity: str,
    attempt: int,
    max_retries: int,
    step_id: str,
) -> tuple[str, str]:
    """
    Returns (Action, Reason).

    KEY FIX: VALIDATION_FAILURE on s3 no longer triggers REPLAN.
    Replanning doesn't fix structural data mismatches (e.g. item name normalization).
    Instead: retry_rank is handled inline by executor._self_correct; after that, ESCALATE.

    This prevents the infinite REPLAN → re-run → same failure → REPLAN loop.
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
        # Do NOT replan — self-correction is handled inline by executor._self_correct.
        # Replanning on a structural mismatch causes an infinite loop.
        return "ESCALATE", f"{error_type} — escalating to human review after inline self-correct"

    if severity == "CRITICAL":
        return "ESCALATE", "Critical severity incident requires human intervention"

    return "ESCALATE", f"No specific recovery policy for {error_type}"
