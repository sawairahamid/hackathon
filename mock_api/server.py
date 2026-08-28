"""OrchestrAI Mock Vendor API.

KEY FIX: Dynamic catalog generation preserves the ORIGINAL item name passed
by the client. The item field in returned quotes is always the requested item,
not a normalized snake_case key.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

DATA = Path(__file__).parent / "data"
_fail_once: dict[str, int] = {}

app = FastAPI(title="OrchestrAI Mock Vendor API", version="1.0.0")


def _load(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8") as f:
        return json.load(f)


CATALOGS = {
    "laptops": _load("laptops.json"),
    "laptop": _load("laptops.json"),
    "software_subscription": _load("software_vendors.json"),
    "software": _load("software_vendors.json"),
    "vendor": _load("software_vendors.json"),
}


def _catalog_for(item: str, budget: float | None = None, quantity: int = 1) -> list[dict]:
    """
    Return a list of supplier records for `item`.
    Static catalogs are used ONLY for laptops/software. Everything else gets
    dynamically generated quotes that preserve the original item name.
    """
    # Normalize for catalog lookup only
    key = (item or "").strip().lower().replace(" ", "_")

    if key in CATALOGS:
        # Use static catalog, but overwrite item with original name
        records = []
        for raw in CATALOGS[key]:
            rec = dict(raw)
            rec["item"] = item  # ← preserve original item name
            records.append(rec)
        return records

    # Dynamic generation — use the ORIGINAL item name (not key)
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
    for i, name in enumerate(supplier_names):
        unit_price = round(base_price * random.uniform(0.80, 1.15), 2)
        rec = {
            "id": f"dyn_{i}",
            "name": name,
            "sku": f"DYN-{key[:6].upper()}-{i:02d}",
            "item": item,           # ← ORIGINAL item name
            "unit_price": unit_price,
            "currency": "PKR",
            "delivery_days": delivery_options[i % len(delivery_options)],
            "warranty_months": warranty_options[i % len(warranty_options)],
            "rating": round(random.uniform(4.0, 5.0), 1),
            "notes": f"Dynamic quote for {item}",
        }
        out.append(rec)
    return out


@app.get("/health")
def health() -> dict:
    return {"ok": True, "catalogs": list(CATALOGS.keys())}


@app.get("/catalog")
def catalog() -> dict:
    return {k: [r["id"] for r in v] for k, v in CATALOGS.items()}


@app.get("/quotes")
def quotes(
    item: str = Query(..., min_length=1),
    quantity: int = Query(1, ge=1),
    limit: int = Query(4, ge=1, le=12),
    fail: str | None = Query(None),
    extra_latency_ms: int = Query(0, ge=0, le=5000),
    budget: float | None = Query(None),
):
    token = f"{item}:{fail}"
    latency = random.randint(80, 220) + extra_latency_ms
    time.sleep(latency / 1000)

    if fail == "timeout":
        n = _fail_once.get(token, 0)
        _fail_once[token] = n + 1
        if n == 0:
            time.sleep(1.4)
            return JSONResponse({"ok": False, "error": "vendor gateway timeout"}, status_code=503)

    if fail == "malformed":
        n = _fail_once.get(token, 0)
        _fail_once[token] = n + 1
        if n == 0:
            return JSONResponse({"unexpected": True, "payload": "<<<not-json-quotes>>>"}, status_code=200)

    if fail == "multi_failure":
        n = _fail_once.get(token, 0)
        _fail_once[token] = n + 1
        if n == 0:
            time.sleep(1.4)
            return JSONResponse({"ok": False, "error": "vendor gateway timeout (multi 1)"}, status_code=503)
        if n == 1:
            return JSONResponse({"unexpected": True, "payload": "<<<not-json-quotes>>> (multi 2)"}, status_code=200)

    catalog_rows = _catalog_for(item, budget=budget, quantity=quantity)
    rows = []
    for i, raw in enumerate(catalog_rows[: max(limit, 3)]):
        rec = dict(raw)
        # ── Data integrity: always use the requested quantity and item ────────
        rec["item"] = item          # ← ORIGINAL item name
        rec["quantity"] = quantity  # ← requested quantity
        rec["total"] = round(float(rec["unit_price"]) * quantity, 2)
        if fail == "over_budget":
            rec["unit_price"] = rec["unit_price"] * 5
            rec["total"] = round(float(rec["unit_price"]) * quantity, 2)
            rec["notes"] = (rec.get("notes") or "") + " [CHAOS] prices inflated 5x"
        if fail == "price_shock" and i % 2 == 0:
            rec["unit_price"] = rec["unit_price"] * 3
            rec["total"] = round(float(rec["unit_price"]) * quantity, 2)
            rec["notes"] = (rec.get("notes") or "") + " [CHAOS] price shock applied"
        rows.append(rec)

    return {"ok": True, "item": item, "quantity": quantity, "latency_ms": latency, "quotes": rows}
