"""Request parser — extracts structured procurement entities from free text.

KEY FIXES:
- item default is "" (empty) not "item" — if extraction fails, item stays empty and
  we can detect the failure instead of silently corrupting downstream data.
- Quantity default is 1 only as a safe last-resort after all extraction attempts.
- Intent detection no longer biases toward "vendor_comparison" just because the
  word "license" appears — only unambiguous SaaS/subscription keywords trigger it.
- Debug logging added.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.llm import complete_json
from app.models import Entities

log = logging.getLogger(__name__)

PARSER_PROMPT = """You extract structured procurement entities from a business request.
Return JSON with keys:
  intent: "procurement" | "vendor_comparison" | "other"
  item: the exact product/service the user wants to procure (e.g. "desktop computers", "enterprise network switches", "Microsoft 365 licenses")
  quantity: integer — the number of units requested
  budget: number (the ceiling, expanded — "6 million" = 6000000, "4 million" = 4000000)
  currency: "PKR" or "USD"
  suppliers_to_compare: integer (default 3)
  approval_target: string (default "procurement_manager")
  constraints: string array

Rules:
- Extract EXACTLY what the user asked for — do NOT replace with "laptops", "item", or any placeholder.
- If the user says "30 desktop computers", item="desktop computers" and quantity=30.
- If the user says "100 Microsoft 365 licenses", item="Microsoft 365 licenses" and quantity=100.
- Do not invent a budget of 0. If a million/lakh/thousand suffix is present, expand it.
- intent is "vendor_comparison" ONLY for pure SaaS/subscription renewals; "procurement" for hardware/physical goods even if they have licenses.

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

    # ── Intent detection ─────────────────────────────────────────────────────
    # Only use vendor_comparison for unambiguous SaaS/subscription/renewal requests.
    # "license" alone does NOT imply vendor_comparison if it's hardware-associated.
    intent: str = "procurement"
    _saas_words = {"saas", "subscription", "renew", "renewal", "software license", "software subscription"}
    if any(w in lower for w in _saas_words):
        intent = "vendor_comparison"
    # Also check for "vendor" without "procurement" context
    elif "vendor comparison" in lower or "compare vendors" in lower:
        intent = "vendor_comparison"

    # ── Quantity and item extraction ──────────────────────────────────────────
    # Strategy: find the first integer in the text (likely the quantity),
    # then capture everything after it up to a stop-word as the item name.
    qty = 1
    item = ""

    # Pattern: <quantity> <item words...> stopping at budget/price context words
    _stop = {"with", "for", "under", "within", "below", "at", "budget", "pkr", "usd", "rs",
              "ceiling", "maximum", "max", "compare", "get", "and", "a", "an", "the",
              "least", "suppliers", "options"}

    m = re.search(
        r"(?:purchase|procure|buy|order|renew|get|acquire)\s+(\d+)\s+(.+?)(?:\s+(?:with|for|under|within|below|at|budget|pkr|usd|rs\b|ceiling|maximum|max|compare|and\b|$))",
        lower,
        re.IGNORECASE,
    )
    if m:
        qty = int(m.group(1))
        raw_item = m.group(2).strip()
        # Strip trailing stop-words from item
        words = raw_item.split()
        clean = []
        for w in words:
            if w.rstrip(".,;:") in _stop:
                break
            clean.append(w)
        if clean:
            item = " ".join(clean).strip().rstrip(".,;:")
    else:
        # Fallback: find first standalone integer and grab following words
        m2 = re.search(r"\b(\d+)\s+([a-zA-Z][a-zA-Z0-9\s\-]+)", lower)
        if m2:
            qty = int(m2.group(1))
            raw_item = m2.group(2).strip()
            words = raw_item.split()
            clean = []
            for w in words:
                if w.rstrip(".,;:") in _stop:
                    break
                clean.append(w)
            if clean:
                item = " ".join(clean).strip().rstrip(".,;:")

    # Preserve original casing for item by re-extracting from original text
    if item:
        # Try to find the item in original-cased text
        pattern = re.compile(re.escape(item), re.IGNORECASE)
        cm = pattern.search(raw)
        if cm:
            item = cm.group(0)

    if intent == "vendor_comparison":
        qty = 1

    log.debug("[PARSER_HEURISTIC] qty=%d item='%s' intent=%s", qty, item, intent)

    # ── Budget extraction ─────────────────────────────────────────────────────
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

    # ── Suppliers count ───────────────────────────────────────────────────────
    n_sup = 3
    sm = re.search(r"compare\s+(?:at\s+least\s+)?(\d+)", lower)
    if sm:
        n_sup = int(sm.group(1))

    constraints = []
    if budget:
        constraints.append(f"total_cost <= {currency} {budget:,.0f}")

    log.info(
        "[PARSER] item='%s' qty=%d budget=%s currency=%s intent=%s",
        item, qty, budget, currency, intent,
    )

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
        v = llm.get(k)
        if v not in (None, "", 0, [], {}):
            data[k] = v

    # Guard against the model dropping the million expansion.
    if fallback.budget and (not data.get("budget") or float(data["budget"]) < fallback.budget * 0.5):
        if fallback.budget >= 1_000_000 and float(data.get("budget") or 0) <= 100:
            data["budget"] = fallback.budget
        elif fallback.budget > float(data.get("budget") or 0) * 100:
            data["budget"] = fallback.budget

    # Guard: LLM must not replace a known item with a placeholder
    llm_item = str(llm.get("item") or "").strip()
    if llm_item.lower() in ("item", "unknown", "product", "goods", ""):
        data["item"] = fallback.item  # keep heuristic's extraction
    # Guard: LLM must not replace a known quantity with 0 or 1 when fallback found >1
    if fallback.quantity > 1 and int(llm.get("quantity") or 1) <= 1:
        data["quantity"] = fallback.quantity

    if data.get("intent") not in ("procurement", "vendor_comparison", "other"):
        data["intent"] = fallback.intent
    data["raw_request"] = fallback.raw_request
    try:
        data["quantity"] = int(data["quantity"])
        data["budget"] = float(data["budget"])
        data["suppliers_to_compare"] = int(data.get("suppliers_to_compare") or 3)
    except (TypeError, ValueError):
        pass

    log.info(
        "[PARSER_MERGE] item='%s' qty=%d budget=%s (llm_item='%s' llm_qty=%s)",
        data.get("item"), data.get("quantity"), data.get("budget"),
        llm.get("item"), llm.get("quantity"),
    )
    return Entities.model_validate(data)


def parse_request(text: str) -> tuple[Entities, str]:
    log.info("[REQUEST] raw='%s'", text[:200])
    fallback = heuristic_parse(text)
    parsed, tag = complete_json(PARSER_PROMPT.format(request=text))
    if not parsed:
        log.info("[PARSER_OUTPUT] source=heuristic item='%s' qty=%d", fallback.item, fallback.quantity)
        return fallback, f"heuristic:{tag}"
    try:
        result = _merge(parsed, fallback)
        log.info("[PARSER_OUTPUT] source=%s item='%s' qty=%d budget=%s", tag, result.item, result.quantity, result.budget)
        return result, tag
    except Exception:
        log.info("[PARSER_OUTPUT] source=heuristic:fallback item='%s' qty=%d", fallback.item, fallback.quantity)
        return fallback, f"heuristic:{tag}:invalid_llm"


def parse_to_json(text: str) -> dict[str, Any]:
    ent, _ = parse_request(text)
    return json.loads(ent.model_dump_json())
