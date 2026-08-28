from __future__ import annotations

import json
import re
from typing import Any

from app.llm import complete_json
from app.models import Entities

PARSER_PROMPT = """You extract structured procurement entities from a business request.
Return JSON with keys:
  intent: "procurement" | "vendor_comparison" | "other"
  item: short catalog name (extract exactly what the user requested, e.g., "desktop computers")
  quantity: integer
  budget: number (the ceiling, expanded — "10 million" = 10000000)
  currency: "PKR" or "USD"
  suppliers_to_compare: integer (default 3)
  approval_target: string (default "procurement_manager")
  constraints: string array
Do not invent a budget of 0. If a million/lakh/thousand suffix is present, expand it.
Request:
{request}
"""


def _expand(num: float, suffix: str | None) -> float:
    s = (suffix or "").lower().strip()
    if s in {"m", "mn", "million"}:
        return num * 1_000_000
    if s in {"l", "lakh"}:
        return num * 100_000
    if s in {"k", "thousand"}:
        return num * 1_000
    return num


def heuristic_parse(text: str) -> Entities:
    raw = text.strip()
    lower = raw.lower()

    intent: str = "procurement"
    if any(w in lower for w in ("renew", "vendor", "software", "license", "saas", "subscription", "contract")):
        intent = "vendor_comparison"

    qty = 1
    item = "item"
    m = re.search(r"(\d+)\s*(?:x\s*)?([a-zA-Z0-9\s-]+)?", lower)
    if m:
        qty = int(m.group(1))
        if m.group(2):
            words = m.group(2).strip().split()
            clean = []
            for w in words:
                if w in ("with", "for", "under", "budget", "pkr", "usd", "rs", "ceiling", "at", "max", "maximum", "compare", "get"):
                    break
                clean.append(w)
            if clean:
                item = " ".join(clean)

    budget = 0.0
    currency = "PKR"
    pkr = re.search(
        r"(?:pkr|rs\.?)\s*([\d,]+(?:\.\d+)?)\s*(million|m|mn|lakh|k|thousand)?",
        lower,
    )
    usd = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(k|thousand)?", lower)
    under = re.search(
        r"(?:under|below|within|ceiling(?:\s+of)?|budget(?:\s+of)?)\s*(?:pkr|rs\.?|\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|m|mn|lakh|k|thousand)?",
        lower,
    )
    if pkr:
        budget = _expand(float(pkr.group(1).replace(",", "")), pkr.group(2))
        currency = "PKR"
    elif usd:
        budget = _expand(float(usd.group(1).replace(",", "")), usd.group(2))
        currency = "USD"
    elif under:
        budget = _expand(float(under.group(1).replace(",", "")), under.group(2))
        currency = "USD" if "$" in lower and "pkr" not in lower else "PKR"

    n_sup = 3
    sm = re.search(r"compare\s+(\d+)", lower)
    if sm:
        n_sup = int(sm.group(1))

    constraints = []
    if budget:
        constraints.append(f"total_cost <= {currency} {budget:,.0f}")

    return Entities(
        intent=intent if intent in ("procurement", "vendor_comparison", "other") else "other",
        item=item,
        quantity=qty,
        budget=budget,
        currency=currency,
        suppliers_to_compare=n_sup,
        approval_target="procurement_manager",
        constraints=constraints,
        raw_request=raw,
    )


def _merge(llm: dict[str, Any], fallback: Entities) -> Entities:
    data = fallback.model_dump()
    for k in (
        "intent",
        "item",
        "quantity",
        "budget",
        "currency",
        "suppliers_to_compare",
        "approval_target",
        "constraints",
    ):
        if k in llm and llm[k] not in (None, "", 0, [], {}):
            data[k] = llm[k]
    # Guard against the model dropping the million expansion.
    if fallback.budget and (not data.get("budget") or float(data["budget"]) < fallback.budget * 0.5):
        if fallback.budget >= 1_000_000 and float(data.get("budget") or 0) <= 100:
            data["budget"] = fallback.budget
        elif fallback.budget > float(data.get("budget") or 0) * 100:
            data["budget"] = fallback.budget
    if data.get("intent") not in ("procurement", "vendor_comparison", "other"):
        data["intent"] = fallback.intent
    data["raw_request"] = fallback.raw_request
    try:
        data["quantity"] = int(data["quantity"])
        data["budget"] = float(data["budget"])
        data["suppliers_to_compare"] = int(data.get("suppliers_to_compare") or 3)
    except (TypeError, ValueError):
        pass
    return Entities.model_validate(data)


def parse_request(text: str) -> tuple[Entities, str]:
    fallback = heuristic_parse(text)
    parsed, tag = complete_json(PARSER_PROMPT.format(request=text))
    if not parsed:
        return fallback, f"heuristic:{tag}"
    try:
        return _merge(parsed, fallback), tag
    except Exception:
        return fallback, f"heuristic:{tag}:invalid_llm"


def parse_to_json(text: str) -> dict[str, Any]:
    ent, _ = parse_request(text)
    return json.loads(ent.model_dump_json())
