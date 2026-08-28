"""Transparent weighted ranking. The LLM never picks the supplier."""

from __future__ import annotations

from typing import Any

from app.models import ToolResult
from app.tools import tool
from app.policies import default_policy_engine

DEFAULT_WEIGHTS = {"price": 0.5, "delivery": 0.3, "warranty": 0.2}


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
) -> dict[str, Any]:
    weights = dict(weights or DEFAULT_WEIGHTS)
    exclude = set(exclude_ids or [])
    usable = []
    for q in quotes:
        rec = dict(q)
        rec["total"] = rec.get("total") or rec.get("unit_price", 0) * quantity
        
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
                    "scores": q["scores"]
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
                    "scores": q["scores"]
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
    description="Filter quotes against the budget ceiling and rank remaining suppliers with disclosed weights (price 50 / delivery 30 / warranty 20). Deterministic — no LLM.",
)
def rank_suppliers(
    quotes: list[dict] | dict | None = None,
    budget: float = 0,
    currency: str = "PKR",
    quantity: int = 1,
    weights: dict | None = None,
    exclude_ids: list[str] | None = None,
) -> ToolResult:
    if isinstance(quotes, dict):
        quotes = quotes.get("quotes") or quotes.get("ranked") or []
    quotes = list(quotes or [])
    data = rank(quotes, float(budget), currency, int(quantity), weights, exclude_ids)
    ok = data["selected"] is not None
    return ToolResult(
        ok=ok,
        tool="rank_suppliers",
        data=data,
        error=None if ok else "No supplier met the budget ceiling",
        source="local",
    )
