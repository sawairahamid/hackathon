from __future__ import annotations

from typing import Any

from app.llm import complete_json

REPORT_PROMPT = """Rewrite the notes as a short briefing for a non-technical manager.
Do not use markdown, headings, bullets, backticks, or asterisks.
Use labeled paragraphs: each block starts with a short label, a colon, then 1-3 sentences.
Keep every number exactly as given. Do not invent suppliers or totals.
Return JSON {{"report": "plain text"}}.

Notes:
{notes}
"""


def _money(n: float, currency: str) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if (currency or "").upper() == "USD":
        return f"${n:,.0f}"
    return f"{currency} {n:,.0f}"


def build_report(
    *,
    request: str,
    entities: dict,
    ranking: dict,
    validation: dict,
    po: dict,
    approval: dict,
    tools_used: list,
    status: str,
    llm_polish: bool = False,
) -> str:
    currency = entities.get("currency", "PKR")
    selected = ranking.get("selected") or {}
    rejected = ranking.get("rejected") or []
    weights = ranking.get("weights") or {"price": 0.5, "delivery": 0.3, "warranty": 0.2}
    checks = validation.get("checks") or []
    qty = entities.get("quantity")
    item = entities.get("item")
    budget = _money(entities.get("budget") or 0, currency)
    status_label = (status or "").replace("_", " ")

    actual_n = len(ranking.get("ranked") or []) + len(rejected)
    asked_n = entities.get("suppliers_to_compare", 3)
    compared_line = f"{actual_n} suppliers compared"
    if asked_n and actual_n and actual_n != asked_n:
        compared_line += f" (asked for {asked_n})"
    if selected and po:
        workflow = (
            "Workflow: request parsed, suppliers retrieved, budget filter applied, suppliers scored, "
            "best option selected, purchase order generated, validated, and sent for human approval."
        )
    elif selected:
        workflow = (
            "Workflow: request parsed, suppliers retrieved, budget filter applied, and suppliers scored. "
            "Purchase order was not issued."
        )
    else:
        workflow = (
            "Workflow: request parsed, suppliers retrieved, and budget filter applied. "
            "No valid supplier — escalated for human review."
        )
    blocks: list[str] = [
        f"Status: {status_label}.",
        f"Request: {request.strip()}",
        (
            f"What was asked: {qty} × {item} under a {budget} ceiling. "
            f"{compared_line}. "
            f"{entities.get('approval_target', 'procurement_manager')} must approve spend — the agent cannot."
        ),
        workflow,
    ]

    if selected:
        scores = selected.get("scores") or {}
        w_price = weights.get("price", 0.5) * 100
        w_del = weights.get("delivery", 0.3) * 100
        w_war = weights.get("warranty", 0.2) * 100
        compared = [r.get("name") or r.get("id") for r in (ranking.get("ranked") or [])]
        compared += [r.get("name") or r.get("id") for r in rejected]
        seen = []
        for n in compared:
            if n and n not in seen:
                seen.append(n)
        if seen:
            blocks.append("Suppliers compared: " + ", ".join(str(x) for x in seen) + ".")
        decision = (
            f"Decision: {selected.get('name')} was selected at {_money(selected.get('total') or 0, currency)}. "
            f"Unit price {_money(selected.get('unit_price') or 0, currency)}. "
            f"Delivery {selected.get('delivery_days')} days, warranty {selected.get('warranty_months')} months. "
            f"Weighted score {scores.get('weighted', '—')} "
            f"(price {w_price:.0f}% / delivery {w_del:.0f}% / warranty {w_war:.0f}%)."
        )
        if scores.get("breakdown"):
            decision += f" Score math: {scores['breakdown']}."
        just = (ranking.get("justification") or "").strip()
        if just:
            decision += " " + just.rstrip(".") + "."
        blocks.append(decision)
    else:
        blocks.append("Decision: No supplier could be selected under the stated ceiling. The workflow was escalated.")

    if rejected:
        names = []
        for r in rejected:
            name = r.get("name") or r.get("id") or "A supplier"
            reason = (r.get("reason") or "did not meet the ceiling").rstrip(".")
            names.append(f"{name} was dropped because {reason}")
        blocks.append("Rejected: " + " ".join(s + "." for s in names))

    if checks:
        failed = [c for c in checks if not c.get("ok")]
        if failed:
            detail = "; ".join(
                f"{c.get('name')}: {c.get('detail')}" for c in failed
            )
            blocks.append(f"Validation: Checks failed. {detail}")
        else:
            labels = []
            for c in checks:
                name = (c.get("name") or "").replace("_", " ")
                labels.append(("OK " if c.get("ok") else "FAIL ") + name)
            blocks.append("Validation: " + "; ".join(labels) + ".")

    if po:
        po_ref = po.get("po_number", "—")
        url = po.get("url")
        po_line = (
            f"Purchase order: {po_ref} for "
            f"{_money(po.get('grand_total') or selected.get('total') or 0, currency)}"
        )
        if url:
            po_line += f". Artifact: {url}"
        blocks.append(po_line + ".")

    if approval:
        appr_status = (approval.get("status") or status or "").replace("_", " ")
        blocks.append(
            f"Approval: {appr_status}. Owner is {approval.get('approver') or entities.get('approval_target')}."
        )

    if tools_used:
        blocks.append("Tools used: " + ", ".join(str(t) for t in tools_used) + ".")

    blocks.append("Note: Numbers come from deterministic scoring and validation, not from the language model.")

    base = "\n\n".join(blocks).strip() + "\n"

    if not llm_polish:
        return base
    parsed, tag = complete_json(REPORT_PROMPT.format(notes=base))
    if parsed and isinstance(parsed.get("report"), str) and parsed["report"].strip():
        extra = parsed["report"].strip()
        if "fallback" not in tag:
            return extra + "\n"
    return base
