"""
FINAL RUNTIME AUDIT — OrchestrAI Procurement Workflow
Traces every stage of the pipeline for each test case and validates data integrity.

Run with both servers already started:
  python runtime_audit.py
"""
import sys
import time
import json
import httpx

BASE_APP  = "http://127.0.0.1:8000"
BASE_MOCK = "http://127.0.0.1:8001"

TESTS = [
    {
        "id": "A",
        "request": "Purchase 30 desktop computers with a maximum budget of PKR 6 million.",
        "expected_item": "desktop computers",
        "expected_qty": 30,
        "expected_budget": 6_000_000,
        "expected_currency": "PKR",
    },
    {
        "id": "B",
        "request": "Purchase 20 enterprise network switches under PKR 4 million.",
        "expected_item": "enterprise network switches",
        "expected_qty": 20,
        "expected_budget": 4_000_000,
        "expected_currency": "PKR",
    },
    {
        "id": "C",
        "request": "Purchase 40 ergonomic office chairs under PKR 800,000.",
        "expected_item": "ergonomic office chairs",
        "expected_qty": 40,
        "expected_budget": 800_000,
        "expected_currency": "PKR",
    },
    {
        "id": "D",
        "request": "Renew 100 Microsoft 365 licenses under PKR 1 million.",
        "expected_item": "Microsoft 365 licenses",
        "expected_qty": 100,
        "expected_budget": 1_000_000,
        "expected_currency": "PKR",
    },
    {
        "id": "E",
        "request": "Purchase 10 laptops under PKR 2 million.",
        "expected_item": "laptops",
        "expected_qty": 10,
        "expected_budget": 2_000_000,
        "expected_currency": "PKR",
    },
]

LAPTOP_SUPPLIERS = {"bytehub", "techmart", "megaoffice", "pakcompute"}
LAPTOP_SKUS = {"BH-PRO-15", "TM-LAP-14-i5", "MO-ULTRA-16", "PC-WORK-14"}


def norm(s: str) -> str:
    return (s or "").strip().lower().replace("_", " ").replace("-", " ")


def ok_fail(b: bool) -> str:
    return "PASS" if b else "FAIL"


def poll(wid: str, timeout: int = 90) -> dict | None:
    terminal = {"pending_approval", "approved", "rejected", "escalated", "failed"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_APP}/api/workflows/{wid}", timeout=10)
            wf = r.json()
            if wf.get("status") in terminal:
                return wf
        except Exception:
            pass
        time.sleep(1.5)
    return None


def audit_test(t: dict) -> dict:
    """Run one test and return a result dict with all checks."""
    print(f"\n{'='*72}")
    print(f"  TEST {t['id']}: {t['request']}")
    print(f"{'='*72}")
    result = {
        "id": t["id"],
        "requested_item": t["expected_item"],
        "requested_qty": t["expected_qty"],
        "parsed_item": None,
        "parsed_qty": None,
        "po_item": None,
        "po_qty": None,
        "final_status": None,
        "checks": {},
        "all_pass": False,
    }
    failures = []

    # ── 1. POST to /api/workflows ────────────────────────────────────────────
    print(f"\n[STEP 1] Submitting request to {BASE_APP}/api/workflows")
    try:
        r = httpx.post(
            f"{BASE_APP}/api/workflows",
            json={"request": t["request"], "chaos": {}},
            timeout=20,
        )
        if r.status_code != 200:
            failures.append(f"API returned {r.status_code}")
            result["all_pass"] = False
            return result
        resp = r.json()
    except Exception as e:
        failures.append(f"POST failed: {e}")
        result["all_pass"] = False
        return result

    wid = resp["id"]
    ent = resp.get("entities", {})
    plan = resp.get("plan", {})

    # ── 2. Parser output ─────────────────────────────────────────────────────
    print(f"\n[PARSER OUTPUT]")
    print(f"  item      = '{ent.get('item')}'")
    print(f"  quantity  = {ent.get('quantity')}")
    print(f"  budget    = {ent.get('budget'):,.0f}")
    print(f"  currency  = {ent.get('currency')}")
    print(f"  intent    = {ent.get('intent')}")

    result["parsed_item"] = ent.get("item")
    result["parsed_qty"] = ent.get("quantity")

    c_item = norm(ent.get("item", "")) == norm(t["expected_item"])
    c_qty  = int(ent.get("quantity", 0)) == t["expected_qty"]
    c_budget = abs(float(ent.get("budget", 0)) - t["expected_budget"]) < 1.0
    c_not_item_placeholder = norm(ent.get("item", "")) not in ("item", "unknown", "")
    c_not_qty_1 = not (t["expected_qty"] != 1 and int(ent.get("quantity", 1)) == 1)

    result["checks"]["parser_item"]        = c_item
    result["checks"]["parser_qty"]         = c_qty
    result["checks"]["parser_budget"]      = c_budget
    result["checks"]["no_item_placeholder"]= c_not_item_placeholder
    result["checks"]["no_qty_silenced_1"]  = c_not_qty_1

    print(f"\n  parser_item        : {ok_fail(c_item)}  (got '{ent.get('item')}' expected '{t['expected_item']}')")
    print(f"  parser_qty         : {ok_fail(c_qty)}  (got {ent.get('quantity')} expected {t['expected_qty']})")
    print(f"  parser_budget      : {ok_fail(c_budget)}  (got {ent.get('budget',0):,.0f} expected {t['expected_budget']:,.0f})")
    print(f"  no_item_placeholder: {ok_fail(c_not_item_placeholder)}")
    print(f"  no_qty_silenced_1  : {ok_fail(c_not_qty_1)}")

    if not c_item:   failures.append(f"parser_item: got '{ent.get('item')}' expected '{t['expected_item']}'")
    if not c_qty:    failures.append(f"parser_qty: got {ent.get('quantity')} expected {t['expected_qty']}")
    if not c_budget: failures.append(f"parser_budget mismatch")

    # ── 3. Plan steps sanity ─────────────────────────────────────────────────
    print(f"\n[PLAN] {plan.get('title')}")
    print(f"  steps: {[s['tool'] for s in plan.get('steps', [])]}")

    # ── 4. Poll until terminal ───────────────────────────────────────────────
    print(f"\n[POLLING] workflow {wid} ...")
    wf = poll(wid, timeout=90)
    if wf is None:
        failures.append("workflow timed out")
        result["all_pass"] = False
        return result

    result["final_status"] = wf.get("status")
    print(f"  Final status: {result['final_status']}")

    steps = wf.get("steps") or []

    # ── 5. Supplier fetch output ─────────────────────────────────────────────
    fetch_step = next((s for s in steps if s.get("tool") == "fetch_suppliers"), None)
    if fetch_step and fetch_step.get("output"):
        fo = fetch_step["output"]
        quotes = fo.get("quotes") or []
        print(f"\n[SUPPLIER OUTPUT]")
        print(f"  source   : {fetch_step.get('source', 'unknown')}")
        print(f"  item key : '{fo.get('item')}'")
        print(f"  quantity : {fo.get('quantity')}")
        print(f"  quotes   : {len(quotes)}")
        for i, q in enumerate(quotes[:4]):
            print(f"    [{i}] name='{q.get('name')}' item='{q.get('item')}' sku='{q.get('sku')}' qty={q.get('quantity')} unit={q.get('unit_price'):,.0f} total={q.get('total'):,.0f}")

        # Check: no laptop supplier IDs for non-laptop items
        if norm(t["expected_item"]) not in ("laptops", "laptop", "notebooks"):
            c_no_laptop_suppliers = not any(q.get("id") in LAPTOP_SUPPLIERS for q in quotes)
            c_no_laptop_skus      = not any(q.get("sku") in LAPTOP_SKUS for q in quotes)
            result["checks"]["no_laptop_suppliers"] = c_no_laptop_suppliers
            result["checks"]["no_laptop_skus"]      = c_no_laptop_skus
            print(f"\n  no_laptop_suppliers: {ok_fail(c_no_laptop_suppliers)}")
            print(f"  no_laptop_skus     : {ok_fail(c_no_laptop_skus)}")
            if not c_no_laptop_suppliers: failures.append("laptop supplier IDs appeared for non-laptop item")
            if not c_no_laptop_skus:      failures.append("laptop SKUs appeared for non-laptop item")

        # Check: all quotes have correct item and quantity
        quote_item_ok = all(
            norm(q.get("item", "")) == norm(t["expected_item"])
            or norm(t["expected_item"]) in norm(q.get("item", ""))
            for q in quotes
        )
        quote_qty_ok = all(int(q.get("quantity", 0)) == t["expected_qty"] for q in quotes)
        quote_total_ok = all(
            abs(float(q.get("total", 0)) - float(q.get("unit_price", 0)) * t["expected_qty"]) < 1.0
            for q in quotes
        )
        result["checks"]["quote_items_correct"]  = quote_item_ok
        result["checks"]["quote_qty_correct"]    = quote_qty_ok
        result["checks"]["quote_total_correct"]  = quote_total_ok
        print(f"  quote_items_correct : {ok_fail(quote_item_ok)}")
        print(f"  quote_qty_correct   : {ok_fail(quote_qty_ok)}")
        print(f"  quote_total_correct : {ok_fail(quote_total_ok)}")
        if not quote_item_ok:  failures.append("some quotes have wrong item name")
        if not quote_qty_ok:   failures.append("some quotes have wrong quantity")
        if not quote_total_ok: failures.append("some quotes have wrong total (unit_price × qty)")

    # ── 6. Ranking output ────────────────────────────────────────────────────
    rank_step = next((s for s in steps if s.get("tool") == "rank_suppliers"), None)
    if rank_step and rank_step.get("output"):
        ro = rank_step["output"]
        sel = ro.get("selected")
        print(f"\n[RANKING OUTPUT]")
        print(f"  quantity : {ro.get('quantity')}")
        print(f"  selected : '{sel.get('name') if sel else None}'")
        if sel:
            print(f"    item   = '{sel.get('item')}'")
            print(f"    qty    = {sel.get('quantity')}")
            print(f"    unit   = {sel.get('unit_price'):,.2f}")
            print(f"    total  = {sel.get('total'):,.2f}")

        if sel:
            rank_qty_ok  = int(sel.get("quantity", 0)) == t["expected_qty"]
            rank_item_ok = norm(sel.get("item", "")) == norm(t["expected_item"]) \
                or norm(t["expected_item"]) in norm(sel.get("item", ""))
            rank_total_ok = abs(float(sel.get("total", 0)) - float(sel.get("unit_price", 0)) * t["expected_qty"]) < 1.0
            result["checks"]["rank_qty_ok"]   = rank_qty_ok
            result["checks"]["rank_item_ok"]  = rank_item_ok
            result["checks"]["rank_total_ok"] = rank_total_ok
            print(f"\n  rank_qty_ok  : {ok_fail(rank_qty_ok)}")
            print(f"  rank_item_ok : {ok_fail(rank_item_ok)}")
            print(f"  rank_total_ok: {ok_fail(rank_total_ok)}")
            if not rank_qty_ok:   failures.append(f"ranking selected qty={sel.get('quantity')} expected {t['expected_qty']}")
            if not rank_item_ok:  failures.append(f"ranking selected item='{sel.get('item')}' expected '{t['expected_item']}'")
            if not rank_total_ok: failures.append(f"ranking selected total incorrect")

    # ── 7. Validation output ─────────────────────────────────────────────────
    val_step = next((s for s in steps if s.get("tool") == "validate_selection"), None)
    if val_step and val_step.get("output"):
        vo = val_step["output"]
        print(f"\n[VALIDATION OUTPUT]")
        print(f"  passed  : {vo.get('passed')}")
        print(f"  action  : {vo.get('action')}")
        for chk in vo.get("checks") or []:
            print(f"  [{ok_fail(chk['ok'])}] {chk['name']}: {chk['detail']}")
        result["checks"]["validation_passed"] = bool(vo.get("passed"))
        if not vo.get("passed"):
            failures.append(f"validation failed: {vo.get('errors')}")

    # ── 8. Purchase Order ────────────────────────────────────────────────────
    po_step = next((s for s in steps if s.get("tool") == "generate_purchase_order"), None)
    if po_step and po_step.get("output"):
        po = po_step["output"]
        line_items = po.get("line_items") or []
        grand_total = float(po.get("grand_total", 0))
        print(f"\n[PURCHASE ORDER]")
        print(f"  po_number  : {po.get('po_number')}")
        print(f"  supplier   : '{po.get('supplier_name')}'")
        for li in line_items:
            print(f"  description: '{li.get('description')}'")
            print(f"  qty        : {li.get('qty')}")
            print(f"  unit_price : {li.get('unit_price'):,.2f}")
            print(f"  line_total : {li.get('total'):,.2f}")
        print(f"  grand_total: {grand_total:,.2f}")

        result["po_item"] = line_items[0].get("description") if line_items else None
        result["po_qty"]  = line_items[0].get("qty") if line_items else None

        if line_items:
            li = line_items[0]
            po_item_ok  = norm(li.get("description", "")) == norm(t["expected_item"])
            po_qty_ok   = int(li.get("qty", 0)) == t["expected_qty"]
            po_math_ok  = abs(float(li.get("total", 0)) - float(li.get("unit_price", 0)) * t["expected_qty"]) < 1.0
            po_grand_ok = abs(grand_total - float(li.get("total", 0))) < 1.0
            po_not_item_placeholder = norm(li.get("description", "")) not in ("item", "unknown", "")
            po_not_qty_1 = not (t["expected_qty"] != 1 and int(li.get("qty", 1)) == 1)

            result["checks"]["po_item_ok"]           = po_item_ok
            result["checks"]["po_qty_ok"]            = po_qty_ok
            result["checks"]["po_math_ok"]           = po_math_ok
            result["checks"]["po_grand_ok"]          = po_grand_ok
            result["checks"]["po_not_item_placeholder"] = po_not_item_placeholder
            result["checks"]["po_not_qty_1"]         = po_not_qty_1

            print(f"\n  po_item_ok             : {ok_fail(po_item_ok)}")
            print(f"  po_qty_ok              : {ok_fail(po_qty_ok)}")
            print(f"  po_math_ok (unit×qty)  : {ok_fail(po_math_ok)}")
            print(f"  po_grand_ok            : {ok_fail(po_grand_ok)}")
            print(f"  po_not_item_placeholder: {ok_fail(po_not_item_placeholder)}")
            print(f"  po_not_qty_1           : {ok_fail(po_not_qty_1)}")

            if not po_item_ok:  failures.append(f"PO description='{li.get('description')}' expected '{t['expected_item']}'")
            if not po_qty_ok:   failures.append(f"PO qty={li.get('qty')} expected {t['expected_qty']}")
            if not po_math_ok:  failures.append("PO line_total != unit_price × qty")
            if not po_grand_ok: failures.append("PO grand_total != line_total")
            if not po_not_item_placeholder: failures.append("PO description is a placeholder")
            if not po_not_qty_1: failures.append("PO qty silently became 1")

    # ── 9. Incident loop check ───────────────────────────────────────────────
    print(f"\n[INCIDENT CHECK]")
    try:
        inc_r = httpx.get(f"{BASE_APP}/api/workflows/{wid}/incidents", timeout=5)
        inc_data = inc_r.json()
        incidents  = inc_data.get("incidents") or []
        actions    = inc_data.get("actions") or []
        print(f"  incidents recorded : {len(incidents)}")
        print(f"  actions recorded   : {len(actions)}")
        c_no_loop = len(incidents) < 10  # >10 is a sign of runaway looping
        result["checks"]["no_incident_loop"] = c_no_loop
        print(f"  no_incident_loop   : {ok_fail(c_no_loop)}  ({'OK' if c_no_loop else f'WARNING: {len(incidents)} incidents'})")
        if not c_no_loop:
            failures.append(f"incident loop detected: {len(incidents)} incidents")
    except Exception as e:
        print(f"  (incident check skipped: {e})")

    # ── 10. Terminal state ───────────────────────────────────────────────────
    terminal_states = {"pending_approval", "approved", "rejected", "escalated", "failed"}
    c_terminal = result["final_status"] in terminal_states
    result["checks"]["reached_terminal"] = c_terminal
    print(f"\n[TERMINAL STATE] {result['final_status']}: {ok_fail(c_terminal)}")
    if not c_terminal:
        failures.append(f"workflow did not reach terminal state: {result['final_status']}")

    # ── Summary ──────────────────────────────────────────────────────────────
    result["failures"] = failures
    result["all_pass"] = len(failures) == 0
    print(f"\n  OVERALL TEST {t['id']}: {'PASS' if result['all_pass'] else 'FAIL'}")
    if failures:
        for f in failures:
            print(f"    FAIL: {f}")
    return result


def main():
    print(f"\n{'#'*72}")
    print(f"  FINAL RUNTIME AUDIT — OrchestrAI Procurement Workflow")
    print(f"  App: {BASE_APP}  |  Mock API: {BASE_MOCK}")
    print(f"{'#'*72}")

    # Verify servers
    print("\n[SERVER CHECK]")
    try:
        h1 = httpx.get(f"{BASE_APP}/api/health", timeout=5).json()
        print(f"  App OK  — mock_supplier_api={h1.get('mock_supplier_api')} llm={h1.get('llm')}")
    except Exception as e:
        print(f"  App UNREACHABLE: {e}")
        sys.exit(1)
    try:
        h2 = httpx.get(f"{BASE_MOCK}/health", timeout=5).json()
        print(f"  Mock OK — catalogs={h2.get('catalogs')}")
    except Exception as e:
        print(f"  Mock API UNREACHABLE: {e}")
        sys.exit(1)

    # Run all tests
    results = []
    for t in TESTS:
        res = audit_test(t)
        results.append(res)
        time.sleep(0.5)

    # ── Final Summary Table ──────────────────────────────────────────────────
    print(f"\n\n{'='*72}")
    print(f"  FINAL AUDIT TABLE")
    print(f"{'='*72}")
    header = f"{'Test':<5} {'Req Item':<30} {'Parsed Item':<30} {'Req Qty':>7} {'Parsed Qty':>10} {'PO Item':<30} {'PO Qty':>6} {'Status':<18} {'Result'}"
    print(header)
    print("-" * len(header))
    all_passed = True
    for r in results:
        overall = "PASS" if r["all_pass"] else "FAIL"
        if not r["all_pass"]:
            all_passed = False
        print(
            f"  {r['id']:<3}  "
            f"{str(r['requested_item']):<30} "
            f"{str(r['parsed_item'] or 'N/A'):<30} "
            f"{r['requested_qty']:>7}  "
            f"{str(r['parsed_qty'] or 'N/A'):>10}  "
            f"{str(r['po_item'] or 'N/A'):<30} "
            f"{str(r['po_qty'] or 'N/A'):>6}  "
            f"{str(r['final_status'] or 'N/A'):<18} "
            f"{overall}"
        )

    print(f"\n{'='*72}")
    if all_passed:
        print(f"  ALL TESTS PASSED — workflow is fully dynamic and data-integrity compliant")
    else:
        print(f"  SOME TESTS FAILED — see individual failures above")
    print(f"{'='*72}\n")

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
