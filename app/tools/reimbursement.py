"""Expense/reimbursement tools — deterministic policy check, no LLM arithmetic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import ToolResult
from app.tools import tool

ROOT = Path(__file__).resolve().parents[2]
_POLICY_FILE = ROOT / "mock_api" / "data" / "expense_policy.json"


def _load_policy() -> dict[str, Any]:
    try:
        return json.loads(_POLICY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "version": "fallback",
            "categories": {
                "meals": {"limit_per_day": 75.0, "currency": "USD"},
                "lodging": {"limit_per_night": 200.0, "currency": "USD"},
                "transport": {"limit_per_trip": 500.0, "currency": "USD"},
                "incidentals": {"limit_per_day": 25.0, "currency": "USD"},
            },
        }


@tool(
    name="fetch_policy_limits",
    description="Return corporate expense policy caps per category (meals, lodging, transport, incidentals). Reads bundled policy file — no HTTP, no LLM.",
)
def fetch_policy_limits(workflow_id: str | None = None) -> ToolResult:
    policy = _load_policy()
    return ToolResult(ok=True, tool="fetch_policy_limits", data=policy, source="local")


def check_expense(
    line_items: list[dict[str, Any]],
    policy_limits: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic check of submitted expense line items against policy caps.

    Each line item: {category, amount, quantity (days/nights/trips), description}.
    Returns a dict matching the validator.py envelope shape.
    """
    categories = (policy_limits or {}).get("categories", {})
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    violations: list[dict[str, Any]] = []

    def _limit(cat: str, qty: int) -> float:
        c = categories.get(cat, {})
        cap = c.get("limit_per_day") or c.get("limit_per_night") or c.get("limit_per_trip") or 0.0
        return float(cap) * int(qty or 1)

    total_submitted = 0.0
    for idx, item in enumerate(line_items or []):
        cat = str(item.get("category", "other")).lower()
        amount = float(item.get("amount", 0))
        qty = int(item.get("quantity", 1))
        desc = item.get("description", f"item {idx + 1}")
        limit = _limit(cat, qty)
        total_submitted += amount
        ok = limit == 0 or amount <= limit + 1e-6
        label = f"{desc} ({cat}x{qty})"
        detail = (
            f"${amount:,.2f} <= ${limit:,.2f}" if ok
            else f"${amount:,.2f} EXCEEDS limit ${limit:,.2f}"
        )
        checks.append({"name": label, "ok": ok, "detail": detail,
                       "category": cat, "amount": amount, "limit": limit})
        if not ok:
            errors.append(f"{label}: {detail}")
            violations.append({
                "category": cat, "description": desc,
                "submitted": amount, "limit": limit,
                "overage": round(amount - limit, 2),
            })

    passed = not violations
    return {
        "passed": passed,
        "checks": checks,
        "errors": errors,
        "violations": violations,
        "total_submitted": round(total_submitted, 2),
        "action": "continue" if passed else "escalate",
    }


@tool(
    name="validate_expense",
    description="Check submitted expense line items against corporate policy caps. Deterministic — no LLM. Flags anything over the per-category limit.",
)
def validate_expense(
    line_items: list | None = None,
    policy_limits: dict | None = None,
) -> ToolResult:
    if policy_limits is None:
        policy_limits = _load_policy()
    data = check_expense(list(line_items or []), policy_limits)
    return ToolResult(
        ok=True,
        tool="validate_expense",
        data=data,
        error=None if data["passed"] else "; ".join(data["errors"]),
        source="local",
    )
