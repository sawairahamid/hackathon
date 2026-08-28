"""Re-check the selection before any spend artifact is produced."""

from __future__ import annotations

from typing import Any

from app.models import Entities, ToolResult
from app.tools import tool

REQUIRED = ("id", "name", "unit_price", "total")


def validate(
    entities: Entities | dict,
    quotes: list[dict] | dict | None,
    ranking: dict | None,
    selected: dict | None = None,
) -> dict[str, Any]:
    if isinstance(entities, dict):
        ent = Entities.model_validate(entities)
    else:
        ent = entities
    if isinstance(quotes, dict):
        quotes = quotes.get("quotes") or []
    quotes = list(quotes or [])
    ranking = ranking or {}
    selected = selected or ranking.get("selected")
    ranked = ranking.get("ranked") or []

    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    if not selected:
        add("selection_present", False, "No supplier was selected")
        return {
            "passed": False,
            "checks": checks,
            "errors": errors,
            "suggested_exclude_ids": [],
            "action": "escalate",
        }

    total = float(selected.get("total") or 0)
    add(
        "budget_compliance",
        total <= float(ent.budget) + 1e-6,
        f"{total:,.0f} <= {ent.budget:,.0f} {ent.currency}",
    )

    qty_sel = int(selected.get("quantity") or ent.quantity)
    expected_total = float(selected.get("unit_price") or 0) * int(ent.quantity)
    qty_ok = qty_sel == int(ent.quantity)
    arith_ok = abs(total - expected_total) <= 1.0
    add(
        "quantity_correctness",
        qty_ok and arith_ok,
        f"qty {qty_sel} vs requested {ent.quantity}; total {total:,.0f} vs unit×qty {expected_total:,.0f}",
    )

    quote_ids = {q.get("id") for q in quotes}
    ranked_ids = {r.get("id") for r in ranked}
    sid = selected.get("id")
    add(
        "supplier_consistency",
        bool(sid) and (sid in quote_ids) and (sid in ranked_ids or not ranked_ids),
        f"selected id={sid} in quotes={sid in quote_ids} in ranked={sid in ranked_ids}",
    )

    missing = [f for f in REQUIRED if selected.get(f) in (None, "")]
    add("required_fields", not missing, "ok" if not missing else f"missing {missing}")

    passed = all(c["ok"] for c in checks)
    action = "continue"
    exclude: list[str] = []
    if not passed:
        if sid and not checks[0]["ok"]:
            exclude = [str(sid)]
            action = "retry_rank"
        else:
            action = "escalate"
    return {
        "passed": passed,
        "checks": checks,
        "errors": errors,
        "suggested_exclude_ids": exclude,
        "action": action,
        "selected_id": sid,
    }


@tool(
    name="validate_selection",
    description="Independent re-check of budget, quantity, supplier consistency, and required fields before PO generation.",
)
def validate_selection(
    entities: dict | None = None,
    quotes: list | dict | None = None,
    ranking: dict | None = None,
    selected: dict | None = None,
) -> ToolResult:
    data = validate(entities or {}, quotes, ranking, selected)
    return ToolResult(
        ok=True,
        tool="validate_selection",
        data=data,
        error=None if data["passed"] else "; ".join(data["errors"]),
        source="local",
    )
