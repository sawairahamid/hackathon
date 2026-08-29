from __future__ import annotations

import json
import re
from typing import Any

from app.llm import complete_json
from app.models import Entities

PARSER_PROMPT = """You extract structured procurement entities from a business request.
Return JSON with keys:
  intent: "procurement" | "vendor_comparison" | "other"
  item: short catalog name (use "laptops" or "software_subscription" when those fit)
  quantity: integer (units to buy — NOT the number of suppliers). "Show me 5 laptops" = quantity 5. "50 laptops" = 50.
  budget: number (the ceiling, expanded — "10 million" = 10000000, "12M" = 12000000)
  currency: "PKR" or "USD"
  suppliers_to_compare: integer. Number of suppliers/vendors to retrieve. "Compare 5 suppliers" / "Show me 10 suppliers" / "Get me 6 vendors" = that number. "Show me 5 laptops" does NOT set this. Default 3 ONLY if they did not specify a supplier/vendor count. Never clamp a specified count down to 3.
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


_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
_NUM = r"(?:\d+|" + "|".join(_WORD_NUM) + r")"


def _to_count(raw: str) -> int:
    s = (raw or "").strip().lower()
    if s in _WORD_NUM:
        return _WORD_NUM[s]
    return int(s)


def _requested_result_count(lower: str) -> int | None:
    """How many unique suppliers to retrieve. Default is applied by the caller, not here."""
    patterns = (
        rf"compare\s+({_NUM})",
        rf"(?:from|among)\s+({_NUM})\s+(?:suppliers?|vendors?)",
        rf"(?:show(?:\s+me)?|find|give(?:\s+me)?|list|get(?:\s+me)?)\s+({_NUM})\s+(?:[\w'-]+\s+){{0,4}}(?:suppliers?|vendors?)",
        rf"({_NUM})\s+(?:suppliers?|vendors?)",
    )
    for pat in patterns:
        m = re.search(pat, lower)
        if not m:
            continue
        n = _to_count(m.group(1))
        if 1 <= n <= 50:
            return n
    return None


def _approval_target(lower: str) -> str:
    m = re.search(
        r"(?:to|for)\s+(?:the\s+)?(procurement(?:\s+manager)?|cfo|finance(?:\s+director)?|manager)",
        lower,
    )
    if not m:
        return "procurement_manager"
    token = re.sub(r"\s+", "_", m.group(1).strip())
    if token == "procurement":
        return "procurement_manager"
    return token


def heuristic_parse(text: str) -> Entities:
    raw = text.strip()
    lower = raw.lower()

    intent: str = "procurement"
    item = "item"
    if any(w in lower for w in ("renew", "vendor", "software", "license", "saas", "subscription", "contract")):
        intent = "vendor_comparison"
        item = "software_subscription"
    if any(w in lower for w in ("laptop", "notebook")):
        item = "laptops"
        if intent == "vendor_comparison" and "laptop" in lower:
            intent = "procurement"

    qty = 1
    for m in re.finditer(r"(\d+)\s*(?:x\s*)?(laptops?|units?|seats?|licenses?|notebooks?)", lower):
        rest = lower[m.end():]
        if re.match(r"\s*(?:suppliers?|vendors?)", rest):
            continue
        qty = int(m.group(1))
    if qty == 1 and intent == "vendor_comparison":
        qty = 1

    budget = 0.0
    currency = "PKR"
    pkr = re.search(
        r"(?:pkr|rs\.?)\s*([\d,]+(?:\.\d+)?)\s*(million|m|mn|lakh|k|thousand)?",
        lower,
    )
    usd = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(k|thousand)?", lower)
    under = re.search(
        r"(?:under|below|within(?:\s+a)?|ceiling(?:\s+of)?|budget(?:\s+of)?|price\s+range\s+of|up\s*to|max(?:imum)?)\s*(?:pkr|rs\.?|\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|m|mn|lakh|k|thousand)?",
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

    n_sup = _requested_result_count(lower)
    if n_sup is None:
        n_sup = 3

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
        approval_target=_approval_target(lower),
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
        explicit = _requested_result_count((fallback.raw_request or "").lower())
        if explicit is not None:
            data["suppliers_to_compare"] = max(1, min(int(explicit), 50))
        else:
            data["suppliers_to_compare"] = 3
        if fallback.quantity and int(fallback.quantity) != 1:
            data["quantity"] = int(fallback.quantity)
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
