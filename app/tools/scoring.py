"""Transparent weighted ranking. The LLM never picks the supplier.

KEY FIX: quantity is always taken from the ranking call's `quantity` parameter
(which comes from entities), never from the supplier quote's quantity field.
This prevents a supplier returning qty=1 from corrupting the total.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models import ToolResult
from app.tools import tool
from app.policies import default_policy_engine

log = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {"price": 0.5, "delivery": 0.3, "warranty": 0.2}


def _normalize_item(s: str) -> str:
    """Lowercase + replace underscores/hyphens with spaces for item comparison."""
    return (s or "").strip().lower().replace("_", " ").replace("-", " ")


def _money(n: float, currency: str) -> str:
    if currency.upper() == "USD":
        return f"${n:,.0f}"
    return f"{currency} {n:,.0f}"


def rank(
    quotes: list[dict[str, Any]],
    budget: float,
    currency: str = "PKR",
    quantity: int = 1,
    weights: dict[str, float] | None = None,
    exclude_ids: list[str] | None = None,
    requested_item: str | None = None,
) -> dict[str, Any]:
    weights = dict(weights or DEFAULT_WEIGHTS)
    exclude = set(exclude_ids or [])
    usable = []
    for q in quotes:
        rec = dict(q)
        # ── Data integrity: enforce requested quantity on every quote ─────────
        rec["quantity"] = int(quantity)
        unit = float(rec.get("unit_price") or 0)
        rec["total"] = round(unit * quantity, 2)

        # ── Data integrity: enforce requested item on every quote ─────────────
        if requested_item:
            rec["item"] = requested_item

        pol_budget_ok, pol_budget_msg = default_policy_engine.evaluate_budget(currency, rec["total"])
        local_budget_ok = rec["total"] <= budget
        rec["meets_budget"] = pol_budget_ok and local_budget_ok

        pol_sup_ok, pol_sup_msg = default_policy_engine.evaluate_supplier(rec)
        rec["meets_policy"] = pol_sup_ok
        rec["policy_reason"] = pol_sup_msg

        if rec["id"] in exclude:
            rec["excluded"] = True
        usable.append(rec)

    totals = [q["total"] for q in usable if q["total"] > 0] or [1]
    days = [q.get("delivery_days") or 1 for q in usable] or [1]
    warr = [q.get("warranty_months") or 0 for q in usable] or [0]
    min_total, min_days, max_warr = min(totals), min(days), max(warr) or 1

    rejected = []
    scored = []
    for q in usable:
        price_s = 100.0 * (min_total / q["total"]) if q["total"] else 0
        del_s = 100.0 * (min_days / (q.get("delivery_days") or min_days))
        war_s = 100.0 * ((q.get("warranty_months") or 0) / max_warr)
        weighted = (
            weights["price"] * price_s
            + weights["delivery"] * del_s
            + weights["warranty"] * war_s
        )
        q["scores"] = {
            "price": round(price_s, 1),
            "delivery": round(del_s, 1),
            "warranty": round(war_s, 1),
            "weighted": round(weighted, 1),
        }
        if q.get("excluded"):
            rejected.append({"id": q["id"], "name": q.get("name"), "reason": "Excluded after validation self-correct", "total": q["total"], "scores": q["scores"]})
            continue
        if not q["meets_budget"]:
            rejected.append(
                {
                    "id": q["id"],
                    "name": q.get("name"),
                    "reason": f"Total {_money(q['total'], currency)} exceeds budget {_money(budget, currency)} or policy maximum",
                    "total": q["total"],
                    "scores": q["scores"],
                }
            )
            continue
        if not q.get("meets_policy", True):
            rejected.append(
                {
                    "id": q["id"],
                    "name": q.get("name"),
                    "reason": q.get("policy_reason", "Failed business policy"),
                    "total": q["total"],
                    "scores": q["scores"],
                }
            )
            continue
        scored.append(q)

    scored.sort(key=lambda r: (-r["scores"]["weighted"], r["total"]))
    selected = scored[0] if scored else None

    if selected:
        justification = (
            f"{selected['name']} ranked highest on the disclosed model "
            f"(price {weights['price']*100:.0f}% / delivery {weights['delivery']*100:.0f}% / "
            f"warranty {weights['warranty']*100:.0f}%) with a weighted score of "
            f"{selected['scores']['weighted']}. "
            f"Unit price {_money(selected['unit_price'], currency)}, "
            f"total {_money(selected['total'], currency)} for {quantity} units, "
            f"{selected.get('delivery_days')} day delivery, "
            f"{selected.get('warranty_months')} month warranty."
        )
        if rejected:
            justification += " Rejected: " + "; ".join(f"{r['name']} ({r['reason']})" for r in rejected) + "."
    else:
        justification = (
            f"No supplier met the {_money(budget, currency)} ceiling after applying constraints."
        )

    return {
        "weights": weights,
        "rejected": rejected,
        "ranked": scored,
        "selected": selected,
        "justification": justification,
        "currency": currency,
        "budget": budget,
        "quantity": quantity,
    }


@tool(
    name="rank_suppliers",
    description="Filter quotes against the budget ceiling and rank remaining suppliers with disclosed weights (price 50 / delivery 30 / warranty 20). Deterministic — no LLM. Always enforces requested quantity.",
)
def rank_suppliers(
    quotes: list[dict] | dict | None = None,
    budget: float = 0,
    currency: str = "PKR",
    quantity: int = 1,
    weights: dict | None = None,
    exclude_ids: list[str] | None = None,
    requested_item: str | None = None,
) -> ToolResult:
    if isinstance(quotes, dict):
        # Extract the original item for enforcement
        if not requested_item:
            requested_item = quotes.get("item")
        quotes = quotes.get("quotes") or quotes.get("ranked") or []
    quotes = list(quotes or [])

    log.info(
        "[RANKING_INPUT] item='%s' quantity=%d budget=%s quotes=%d",
        requested_item, quantity, budget, len(quotes),
    )

    data = rank(quotes, float(budget), currency, int(quantity), weights, exclude_ids, requested_item)
    ok = data["selected"] is not None

    if ok:
        sel = data["selected"]
        log.info(
            "[SELECTED_SUPPLIER] name='%s' item='%s' qty=%d unit_price=%s total=%s",
            sel.get("name"), sel.get("item"), sel.get("quantity"), sel.get("unit_price"), sel.get("total"),
        )
    else:
        log.warning("[RANKING] No supplier selected — all rejected")

    return ToolResult(
        ok=ok,
        tool="rank_suppliers",
        data=data,
        error=None if ok else "No supplier met the budget ceiling",
        source="local",
    )
