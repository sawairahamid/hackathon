"""HTTP client for the mock vendor API, with a local catalog fallback.

KEY FIX: The original item string (e.g. "desktop computers") is preserved
throughout. Only the BUNDLED static catalogs ("laptops" / "software_subscription")
are looked up via a normalized key — all other items get dynamically generated
quotes using the ORIGINAL item name, not the snake_case key.
"""

from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Any

import httpx

from app.models import ChaosConfig, ToolResult
from app.tools import tool

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = {
    "laptops": ROOT / "mock_api" / "data" / "laptops.json",
    "software_subscription": ROOT / "mock_api" / "data" / "software_vendors.json",
}

# Items that map to the laptop static catalog
_LAPTOP_ALIASES = {"laptops", "laptop", "notebook", "notebooks"}
# Items that map to the software subscription static catalog
_SOFTWARE_ALIASES = {"software_subscription", "software", "saas", "subscription"}


def _normalize_key(item: str) -> str:
    """Return a lowercase, underscore-joined key for catalog lookup only."""
    return (item or "").strip().lower().replace(" ", "_")


def _should_use_bundled(item: str) -> str | None:
    """
    Return the BUNDLED key if the requested item maps to a static catalog,
    otherwise return None so we use dynamic generation.
    """
    key = _normalize_key(item)
    if key in _LAPTOP_ALIASES or key in BUNDLED and "laptop" in key:
        return "laptops"
    if key in _SOFTWARE_ALIASES or key in BUNDLED and "software" in key:
        return "software_subscription"
    # Direct key match
    if key in BUNDLED:
        return key
    return None


def _local_quotes(item: str, quantity: int, budget: float | None = None) -> list[dict[str, Any]]:
    """
    Generate supplier quotes for the given item.
    Uses static catalog ONLY when the item actually IS laptops/software.
    For all other items, generates dynamic quotes preserving the original item name.
    """
    bundled_key = _should_use_bundled(item)

    if bundled_key:
        log.debug("[SUPPLIER_FALLBACK] Using bundled catalog '%s' for item='%s'", bundled_key, item)
        path = BUNDLED[bundled_key]
        rows = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for raw in rows:
            rec = dict(raw)
            # Overwrite item with what the user actually requested
            rec["item"] = item
            rec["quantity"] = quantity
            rec["total"] = rec["unit_price"] * quantity
            rec["meets_budget"] = True
            out.append(rec)
        return out

    # Dynamic generation — preserve the ORIGINAL item name
    log.debug("[SUPPLIER_FALLBACK] Generating dynamic quotes for item='%s' qty=%d budget=%s", item, quantity, budget)
    base_price = (budget / quantity) * 0.9 if (budget and quantity) else 100_000.0
    supplier_names = [
        f"Global {item.title()} Supplies",
        f"Tech {item.title()} Distributors",
        f"Mega {item.title()} Corp",
        f"Prime {item.title()} Solutions",
    ]
    delivery_options = [5, 7, 10, 14]
    warranty_options = [12, 24, 36]
    out = []
    for i, name in enumerate(supplier_names[:4]):
        unit_price = round(base_price * random.uniform(0.80, 1.15), 2)
        rec = {
            "id": f"dyn_{i}",
            "name": name,
            "sku": f"DYN-{_normalize_key(item)[:6].upper()}-{i:02d}",
            "item": item,           # ← ORIGINAL item name, not normalized
            "unit_price": unit_price,
            "currency": "PKR",
            "delivery_days": delivery_options[i % len(delivery_options)],
            "warranty_months": warranty_options[i % len(warranty_options)],
            "rating": round(random.uniform(4.0, 5.0), 1),
            "notes": f"Dynamic quote for {item} — {quantity} units",
            "quantity": quantity,
            "total": round(unit_price * quantity, 2),
            "meets_budget": True,
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
    description="Query the vendor data source for quotes. Real HTTP call to the mock supplier API; falls back to dynamically generated quotes if the API is down. The original item name is always preserved.",
)
def fetch_suppliers(
    item: str,
    quantity: int = 1,
    currency: str = "PKR",
    limit: int = 3,
    chaos: dict | None = None,
    budget: float | None = None,
) -> ToolResult:
    # ── Debug entry log ──────────────────────────────────────────────────────
    log.info(
        "[SUPPLIER_INPUT] item='%s' quantity=%d currency=%s budget=%s limit=%d",
        item, quantity, currency, budget, limit,
    )

    # Validate inputs
    if not item or not item.strip():
        return ToolResult(
            ok=False,
            tool="fetch_suppliers",
            error="item is required and cannot be empty",
            error_type="INVALID_TOOL_RESPONSE",
        )
    item = item.strip()
    quantity = max(int(quantity or 1), 1)

    url = os.getenv("SUPPLIER_API_URL", "http://127.0.0.1:8001").rstrip("/")
    fail = _chaos_fail(chaos)
    extra = 0
    if isinstance(chaos, dict):
        extra = int(chaos.get("extra_latency_ms") or 0)

    params: dict[str, Any] = {
        "item": item,          # ← Send ORIGINAL item name to the API
        "quantity": quantity,
        "limit": max(int(limit or 3), 3),
        "extra_latency_ms": extra,
    }
    if budget is not None:
        params["budget"] = budget
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
                # ── Data integrity: enforce original item/quantity ────────────
                rec["item"] = item          # ← original item name, not whatever API returned
                rec["quantity"] = quantity  # ← original requested quantity
                rec["total"] = round(float(rec.get("unit_price", 0)) * quantity, 2)
                rec["currency"] = rec.get("currency") or currency
                if budget is not None:
                    rec["meets_budget"] = rec["total"] <= budget
                enriched.append(rec)

            log.info(
                "[SUPPLIER_OUTPUT] source=live item='%s' quantity=%d quotes=%d",
                item, quantity, len(enriched),
            )
            return ToolResult(
                ok=True,
                tool="fetch_suppliers",
                data={
                    "item": item,
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

    # ── API unavailable — use local fallback ─────────────────────────────────
    log.warning("[SUPPLIER_FALLBACK] API unreachable (%s). Using local fallback for item='%s'", last_err, item)
    quotes = _local_quotes(item, quantity, budget=budget)
    if budget is not None:
        for q in quotes:
            q["meets_budget"] = q["total"] <= budget

    log.info(
        "[SUPPLIER_OUTPUT] source=fallback item='%s' quantity=%d quotes=%d",
        item, quantity, len(quotes),
    )

    # If use_fallback is explicitly set by incident commander, return ok=True
    use_fallback = isinstance(chaos, dict) and chaos.get("use_fallback")

    if last_err and not use_fallback:
        # Don't silently fall back — incident commander must handle it
        return ToolResult(
            ok=False,
            tool="fetch_suppliers",
            error=f"All retries failed. Last error: {last_err}",
            error_type="TOOL_UNAVAILABLE",
            source="live",
        )

    return ToolResult(
        ok=True,
        tool="fetch_suppliers",
        data={
            "item": item,
            "quantity": quantity,
            "currency": currency,
            "quotes": quotes,
            "fallback_reason": last_err,
        },
        source="fallback",
        error=None,
    )
