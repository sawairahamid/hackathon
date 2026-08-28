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
    "software_subscription": _load("software_vendors.json"),
    "software": _load("software_vendors.json"),
    "vendor": _load("software_vendors.json"),
}


def _catalog_for(item: str, budget: float | None = None, quantity: int = 1) -> list[dict]:
    key = (item or "").strip().lower().replace(" ", "_")
    if key in CATALOGS:
        return CATALOGS[key]
    
    # Generate dynamic catalog on the fly
    import random
    out = []
    base_price = (budget / quantity) * 0.9 if budget else 100000.0
    names = [f"Global {str(item).title()} Supplies", f"Tech {str(item).title()} Distributors", f"Mega {str(item).title()}"]
    for i, name in enumerate(names):
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
            "notes": f"Generated mock quote for {item}"
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

    rows = []
    for i, raw in enumerate(_catalog_for(item, budget=budget, quantity=quantity)[: max(limit, 3)]):
        rec = dict(raw)
        rec["quantity"] = quantity
        rec["total"] = rec["unit_price"] * quantity
        if fail == "over_budget":
            rec["unit_price"] = rec["unit_price"] * 5
            rec["total"] = rec["unit_price"] * quantity
            rec["notes"] = (rec.get("notes") or "") + " [CHAOS] prices inflated 5x"
        if fail == "price_shock" and i % 2 == 0:
            # Inject a price shock on every other item to violate budget/policies for some but not all
            rec["unit_price"] = rec["unit_price"] * 3
            rec["total"] = rec["unit_price"] * quantity
            rec["notes"] = (rec.get("notes") or "") + " [CHAOS] price shock applied"
        rows.append(rec)

    return {"ok": True, "item": item, "quantity": quantity, "latency_ms": latency, "quotes": rows}
