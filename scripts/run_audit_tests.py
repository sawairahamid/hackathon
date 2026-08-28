import os
import sys
import json
import uuid
from app import trace
trace.init_db()
from app.parser import parse_request
from app.planner import plan_workflow
from app.executor import run_workflow

PROMPTS = [
    "Purchase 30 desktop computers with a maximum budget of PKR 6 million.",
    "Purchase 20 enterprise network switches with a maximum budget of PKR 4 million.",
    "Purchase 15 high-speed routers under PKR 2 million.",
    "Buy 5 office printers with a PKR 100,000 budget.",
    "Procure 2 database servers under PKR 8 million.",
    "Purchase 50 4K monitors for PKR 2.5 million.",
    "Renew 100 Microsoft 365 licenses for PKR 1 million.",
    "Purchase 10 laptops for PKR 1.5 million."
]

print("Starting audit tests...\n")
for i, p in enumerate(PROMPTS):
    print(f"--- TEST {i+1} ---")
    print(f"USER REQUEST: {p}")
    ent, _ = parse_request(p)
    print(f"PARSED ENTITIES: intent={ent.intent}, item={ent.item}, qty={ent.quantity}, budget={ent.budget}")
    
    wid = f"wf_test_{uuid.uuid4().hex[:6]}"
    ent.extra = {"workflow_id": wid}
    plan, _ = plan_workflow(ent)
    trace.create_workflow(wid, p, {})
    trace.set_workflow_fields(wid, plan_json=plan.model_dump_json())
    
    # Run synchronously
    current_plan = plan
    res = None
    for _ in range(5):  # limit replan loops
        res = run_workflow(wid, ent, current_plan)
        if res == "REPLAN":
            row = trace.get_workflow(wid)
            from app.models import Plan
            current_plan = Plan(**json.loads(row["plan_json"]))
            continue
        break
        
    steps = trace.list_steps(wid)
    sup_input = None
    selected_sup = None
    unit_price = None
    line_total = None
    po_desc = None
    po_qty = None
    grand_tot = None
    
    for s in steps:
        if s.get("tool") == "fetch_suppliers":
            sup_input = s.get("inputs")
        elif s.get("tool") == "rank_suppliers":
            out = s.get("output") or {}
            sel = out.get("selected") or {}
            selected_sup = sel.get("name")
            unit_price = sel.get("unit_price")
            line_total = sel.get("total")
        elif s.get("tool") == "generate_purchase_order":
            out = s.get("output") or {}
            items = out.get("line_items") or [{}]
            po_desc = items[0].get("description")
            po_qty = items[0].get("qty")
            grand_tot = out.get("grand_total")
            
    print(f"SUPPLIER INPUT: {sup_input}")
    print(f"SELECTED SUPPLIER: {selected_sup}")
    print(f"QUANTITY: {ent.quantity}")
    print(f"UNIT PRICE: {unit_price}")
    print(f"LINE TOTAL: {line_total}")
    print(f"GRAND TOTAL: {grand_tot}")
    print(f"PO DESCRIPTION: {po_desc}")
    print(f"PO QUANTITY: {po_qty}\n")

