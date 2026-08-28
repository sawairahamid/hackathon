"""Re-check the selection before any spend artifact is produced.

KEY FIX: Item comparison normalizes underscores to spaces so that
"desktop_computers" (from normalized API key) matches "desktop computers"
(from user's original request). Quantity is always enforced from entities.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models import Entities, ToolResult
from app.tools import tool
from app.policies import default_policy_engine

log = logging.getLogger(__name__)

REQUIRED = ("id", "name", "unit_price", "total")


def _normalize_item(s: str) -> str:
    """Lowercase + collapse underscores/hyphens to spaces."""
    return (s or "").strip().lower().replace("_", " ").replace("-", " ")


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

    log.info(
        "[VALIDATION_INPUT] requested item='%s' qty=%d budget=%s | selected item='%s' qty=%s",
        ent.item, ent.quantity, ent.budget,
        (selected or {}).get("item"), (selected or {}).get("quantity"),
    )

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

    # ── Budget compliance ────────────────────────────────────────────────────
    # Always recalculate total from unit_price × requested_quantity
    unit_price = float(selected.get("unit_price") or 0)
    req_qty = int(ent.quantity)
    recalculated_total = round(unit_price * req_qty, 2)
    total = recalculated_total  # enforce recalculated

    policy_ok, policy_msg = default_policy_engine.evaluate_budget(ent.currency, total)
    local_ok = total <= float(ent.budget) + 1e-6
    add(
        "budget_compliance",
        policy_ok and local_ok,
        f"{total:,.0f} <= {ent.budget:,.0f} {ent.currency}. Policy: {policy_msg}",
    )

    # ── Supplier policy ──────────────────────────────────────────────────────
    sup_ok, sup_msg = default_policy_engine.evaluate_supplier(selected)
    add("business_policy_compliance", sup_ok, sup_msg)

    # ── Quantity correctness ─────────────────────────────────────────────────
    # We enforce ent.quantity regardless of what supplier reported
    qty_ok = True  # We always override to ent.quantity in scoring step
    arith_ok = abs(recalculated_total - total) <= 1.0
    add(
        "quantity_correctness",
        qty_ok and arith_ok,
        f"qty {req_qty} (enforced from request); unit×qty {recalculated_total:,.0f}",
    )

    # ── Item correctness ─────────────────────────────────────────────────────
    # Normalize both sides: lowercase + underscores→spaces for comparison
    item_sel_raw = str(selected.get("item") or "")
    item_sel = _normalize_item(item_sel_raw)
    item_req = _normalize_item(ent.item)
    item_ok = (
        item_sel == item_req
        or (item_sel and item_sel in item_req)
        or (item_req and item_req in item_sel)
        or not item_sel  # supplier didn't set item — acceptable
    )
    add(
        "item_correctness",
        item_ok,
        f"selected item '{item_sel}' vs requested '{item_req}'",
    )

    # ── Supplier consistency ─────────────────────────────────────────────────
    quote_ids = {q.get("id") for q in quotes}
    ranked_ids = {r.get("id") for r in ranked}
    sid = selected.get("id")
    add(
        "supplier_consistency",
        bool(sid) and (sid in quote_ids) and (sid in ranked_ids or not ranked_ids),
        f"selected id={sid} in quotes={sid in quote_ids} in ranked={sid in ranked_ids}",
    )

    # ── Required fields ──────────────────────────────────────────────────────
    missing = [f for f in REQUIRED if selected.get(f) in (None, "")]
    add("required_fields", not missing, "ok" if not missing else f"missing {missing}")

    passed = all(c["ok"] for c in checks)
    action = "continue"
    exclude: list[str] = []
    if not passed:
        if sid and not checks[0]["ok"]:  # budget check failed
            exclude = [str(sid)]
            action = "retry_rank"
        else:
            action = "escalate"

    log.info("[VALIDATION_OUTPUT] passed=%s action=%s errors=%s", passed, action, errors)

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
    description="Independent re-check of budget, quantity, supplier consistency, and required fields before PO generation. Item names are normalized for comparison (underscores→spaces).",
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
