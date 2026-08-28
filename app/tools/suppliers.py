"""HTTP client for the mock vendor API, with a local catalog fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from app.models import ChaosConfig, ToolResult
from app.tools import tool

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = {
    "laptops": ROOT / "mock_api" / "data" / "laptops.json",
    "software_subscription": ROOT / "mock_api" / "data" / "software_vendors.json",
}


def _normalize_item(item: str) -> str:
    key = (item or "").strip().lower()
    if any(w in key for w in ("software", "vendor", "license", "saas", "renewal", "subscription")):
        return "software_subscription"
    if any(w in key for w in ("laptop", "notebook")):
        return "laptops"
    return key.replace(" ", "_")


def _local_quotes(item: str, quantity: int, budget: float | None = None) -> list[dict[str, Any]]:
    key = _normalize_item(item)
    if key in BUNDLED:
        path = BUNDLED[key]
        rows = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for raw in rows:
            rec = dict(raw)
            rec["quantity"] = quantity
            rec["total"] = rec["unit_price"] * quantity
            rec["meets_budget"] = True
            out.append(rec)
        return out
    
    import random
    out = []
    base_price = (budget / quantity) * 0.9 if budget else 100000.0
    for i, name in enumerate(["Global Supplies", "Tech Distributors", "Mega Distributors"]):
        unit_price = base_price * random.uniform(0.8, 1.1)
        rec = {
            "id": f"mock_{i}",
            "name": name,
            "sku": f"MOCK-{key[:3].upper()}-{i}",
            "item": item,
            "unit_price": unit_price,
            "currency": "PKR",
            "delivery_days": random.randint(3, 14),
            "warranty_months": random.choice([12, 24, 36]),
            "rating": round(random.uniform(4.0, 5.0), 1),
            "notes": f"Generated mock quote for {item}",
            "quantity": quantity,
            "total": unit_price * quantity,
            "meets_budget": True
        }
        out.append(rec)
    return out


def _chaos_fail(chaos: ChaosConfig | dict | None) -> str | None:
    if not chaos:
        return None
    c = chaos if isinstance(chaos, ChaosConfig) else ChaosConfig.model_validate(chaos)
    if c.force_timeout:
        return "timeout"
    if c.force_malformed:
        return "malformed"
    if c.force_over_budget:
        return "over_budget"
    if c.force_price_shock:
        return "price_shock"
    if c.force_multi_failure:
        return "multi_failure"
    return None


@tool(
    name="fetch_suppliers",
    description="Query the vendor data source for quotes. Real HTTP call to the mock supplier API; falls back to bundled catalog if the API is down.",
)
def fetch_suppliers(
    item: str,
    quantity: int = 1,
    currency: str = "PKR",
    limit: int = 3,
    chaos: dict | None = None,
    budget: float | None = None,
) -> ToolResult:
    item_key = _normalize_item(item)
    url = os.getenv("SUPPLIER_API_URL", "http://127.0.0.1:8001").rstrip("/")
    fail = _chaos_fail(chaos)
    extra = 0
    if isinstance(chaos, dict):
        extra = int(chaos.get("extra_latency_ms") or 0)
    params: dict[str, Any] = {
        "item": item_key,
        "quantity": quantity,
        "limit": max(int(limit or 3), 3),
        "extra_latency_ms": extra,
    }
    if fail:
        params["fail"] = fail

    last_err = None
    for attempt in range(3):
        try:
            resp = httpx.get(f"{url}/quotes", params=params, timeout=httpx.Timeout(2.5, connect=0.4))
            if resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue
            body = resp.json()
            quotes = body.get("quotes")
            if not isinstance(quotes, list) or not quotes:
                last_err = "malformed vendor payload (no quotes array)"
                continue
            enriched = []
            for q in quotes:
                rec = dict(q)
                rec["quantity"] = quantity
                rec["total"] = rec.get("total") or rec["unit_price"] * quantity
                rec["currency"] = rec.get("currency") or currency
                if budget is not None:
                    rec["meets_budget"] = rec["total"] <= budget
                enriched.append(rec)
            return ToolResult(
                ok=True,
                tool="fetch_suppliers",
                data={
                    "item": item_key,
                    "quantity": quantity,
                    "currency": currency,
                    "quotes": enriched,
                    "attempt": attempt + 1,
                },
                source="live",
            )
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue

    quotes = _local_quotes(item_key, quantity)
    if budget is not None:
        for q in quotes:
            q["meets_budget"] = q["total"] <= budget
    
    # If use_fallback is explicitly set by incident commander, we don't return error
    use_fallback = isinstance(chaos, dict) and chaos.get("use_fallback")
    
    if last_err and not use_fallback:
        # Don't silently fallback! The incident commander MUST handle it.
        # We return the error, so incident commander can trigger Fallback action or Escalate.
        return ToolResult(
            ok=False,
            tool="fetch_suppliers",
            error=f"All retries failed. Last error: {last_err}",
            error_type="TOOL_UNAVAILABLE",
            source="live"
        )
            
    return ToolResult(
        ok=True,
        tool="fetch_suppliers",
        data={
            "item": item_key,
            "quantity": quantity,
            "currency": currency,
            "quotes": quotes,
            "fallback_reason": last_err,
        },
        source="fallback",
        error=None,
    )
