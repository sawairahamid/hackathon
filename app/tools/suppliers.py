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
    if any(w in key for w in ("laptop", "notebook", "computer")):
        return "laptops"
    return key.replace(" ", "_") or "laptops"


def _quote_limit(limit: Any) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 3
    if n <= 0:
        n = 3
    return min(n, 50)


def _local_quotes(item: str, quantity: int, limit: int | None = None) -> list[dict[str, Any]]:
    key = _normalize_item(item)
    path = BUNDLED.get(key, BUNDLED["laptops"])
    rows = json.loads(path.read_text(encoding="utf-8"))
    n = _quote_limit(limit if limit is not None else len(rows))
    out = []
    seen: set[str] = set()
    for raw in rows:
        rec = dict(raw)
        vid = str(rec.get("id") or "")
        if vid in seen:
            continue
        seen.add(vid)
        rec["quantity"] = quantity
        rec["total"] = rec["unit_price"] * quantity
        rec["meets_budget"] = True
        out.append(rec)
        if len(out) >= n:
            break
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
    description="Query the vendor data source for quotes. Returns exactly `limit` unique suppliers when that many exist in the catalog; never pads with duplicates.",
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
    n = _quote_limit(limit)
    extra = 0
    if isinstance(chaos, dict):
        extra = int(chaos.get("extra_latency_ms") or 0)
    params: dict[str, Any] = {
        "item": item_key,
        "quantity": quantity,
        "limit": n,
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
            seen: set[str] = set()
            for q in quotes:
                rec = dict(q)
                vid = str(rec.get("id") or "")
                if vid in seen:
                    continue
                seen.add(vid)
                rec["quantity"] = quantity
                rec["total"] = rec.get("total") or rec["unit_price"] * quantity
                rec["currency"] = rec.get("currency") or currency
                if budget is not None:
                    rec["meets_budget"] = rec["total"] <= budget
                enriched.append(rec)
                if len(enriched) >= n:
                    break
            return ToolResult(
                ok=True,
                tool="fetch_suppliers",
                data={
                    "item": item_key,
                    "quantity": quantity,
                    "currency": currency,
                    "quotes": enriched,
                    "limit": n,
                    "available": len(enriched),
                    "attempt": attempt + 1,
                },
                source="live",
            )
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue

    quotes = _local_quotes(item_key, quantity, n)
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
            "limit": n,
            "available": len(quotes),
            "fallback_reason": last_err,
        },
        source="fallback",
        error=None,
    )
