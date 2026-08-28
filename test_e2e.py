"""
End-to-end workflow test — submits requests to the live server and checks results.
Run AFTER starting both servers:
  python -m uvicorn mock_api.server:app --host 127.0.0.1 --port 8001
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

Usage: python test_e2e.py
"""
import sys
import time
import httpx

BASE = "http://127.0.0.1:8000"

TESTS = [
    {
        "name": "TEST 1 – 30 desktop computers PKR 6M",
        "request": "Purchase 30 desktop computers with a maximum budget of PKR 6 million. Compare at least three suppliers and select the best option.",
        "expected_item": "desktop computers",
        "expected_qty": 30,
        "expected_budget": 6_000_000,
    },
    {
        "name": "TEST 2 – 20 enterprise network switches PKR 4M",
        "request": "Purchase 20 enterprise network switches under PKR 4 million.",
        "expected_item": "enterprise network switches",
        "expected_qty": 20,
        "expected_budget": 4_000_000,
    },
    {
        "name": "TEST 3 – 15 high-speed routers PKR 2M",
        "request": "Procure 15 high-speed routers under PKR 2 million.",
        "expected_item": "high-speed routers",
        "expected_qty": 15,
        "expected_budget": 2_000_000,
    },
    {
        "name": "TEST 4 – 5 office printers PKR 500K",
        "request": "Buy 5 office printers under PKR 500,000.",
        "expected_item": "office printers",
        "expected_qty": 5,
        "expected_budget": 500_000,
    },
    {
        "name": "TEST 5 – 100 Microsoft 365 licenses PKR 1M",
        "request": "Renew 100 Microsoft 365 licenses under PKR 1 million.",
        "expected_item": "Microsoft 365 licenses",
        "expected_qty": 100,
        "expected_budget": 1_000_000,
    },
    {
        "name": "TEST 6 – 40 ergonomic office chairs PKR 800K",
        "request": "Purchase 40 ergonomic office chairs under PKR 800,000.",
        "expected_item": "ergonomic office chairs",
        "expected_qty": 40,
        "expected_budget": 800_000,
    },
    {
        "name": "TEST 7 – 10 laptops PKR 2M",
        "request": "Purchase 10 laptops under PKR 2 million.",
        "expected_item": "laptops",
        "expected_qty": 10,
        "expected_budget": 2_000_000,
    },
]


def normalize(s):
    return (s or "").strip().lower().replace("_", " ").replace("-", " ")


def poll_workflow(wid, timeout=60):
    """Poll until workflow reaches a terminal state."""
    terminal = {"pending_approval", "approved", "rejected", "escalated", "failed"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = httpx.get(f"{BASE}/api/workflows/{wid}", timeout=10)
        wf = r.json()
        status = wf.get("status")
        if status in terminal:
            return wf
        time.sleep(1)
    return None


def run_test(t):
    print(f"\n{'='*70}")
    print(f"  {t['name']}")
    print(f"  Request: {t['request'][:80]}")
    print(f"{'='*70}")

    # Create workflow
    r = httpx.post(f"{BASE}/api/workflows", json={"request": t["request"]}, timeout=15)
    if r.status_code != 200:
        print(f"  [FAIL] Could not create workflow: {r.status_code} {r.text[:200]}")
        return False
    resp = r.json()
    wid = resp["id"]
    ent = resp.get("entities", {})

    print(f"  Parsed entities:")
    print(f"    item     = '{ent.get('item')}'")
    print(f"    quantity = {ent.get('quantity')}")
    print(f"    budget   = {ent.get('budget'):,.0f}")
    print(f"    currency = {ent.get('currency')}")

    # Check parsed entities
    item_ok = normalize(ent.get("item", "")) == normalize(t["expected_item"])
    qty_ok = int(ent.get("quantity", 0)) == t["expected_qty"]
    budget_ok = abs(float(ent.get("budget", 0)) - t["expected_budget"]) < 1.0

    print(f"\n  Parser checks:")
    print(f"    item     : {'PASS' if item_ok else 'FAIL'} (got '{ent.get('item')}' expected '{t['expected_item']}')")
    print(f"    quantity : {'PASS' if qty_ok else 'FAIL'} (got {ent.get('quantity')} expected {t['expected_qty']})")
    print(f"    budget   : {'PASS' if budget_ok else 'FAIL'} (got {ent.get('budget', 0):,.0f} expected {t['expected_budget']:,.0f})")

    # Poll for completion
    print(f"\n  Polling workflow {wid}...")
    wf = poll_workflow(wid, timeout=90)
    if not wf:
        print(f"  [FAIL] Workflow timed out")
        return False

    status = wf.get("status")
    print(f"  Final status: {status}")

    # Check PO
    steps = wf.get("steps") or []
    po_step = next((s for s in steps if s.get("tool") == "generate_purchase_order"), None)
    rank_step = next((s for s in steps if s.get("tool") == "rank_suppliers"), None)

    po_ok = False
    if po_step and po_step.get("output"):
        po_data = po_step["output"]
        line_items = po_data.get("line_items") or []
        grand_total = po_data.get("grand_total", 0)

        print(f"\n  PO data:")
        for li in line_items:
            print(f"    description : '{li.get('description')}'")
            print(f"    qty         : {li.get('qty')}")
            print(f"    unit_price  : {li.get('unit_price'):,.2f}")
            print(f"    line_total  : {li.get('total'):,.2f}")
        print(f"    grand_total : {grand_total:,.2f}")

        po_item_ok = False
        po_qty_ok = False
        if line_items:
            li = line_items[0]
            po_item_ok = normalize(li.get("description", "")) == normalize(t["expected_item"])
            po_qty_ok = int(li.get("qty", 0)) == t["expected_qty"]

        print(f"\n  PO checks:")
        print(f"    description : {'PASS' if po_item_ok else 'FAIL'} (got '{line_items[0].get('description') if line_items else None}')")
        print(f"    qty         : {'PASS' if po_qty_ok else 'FAIL'} (got {line_items[0].get('qty') if line_items else None} expected {t['expected_qty']})")

        po_ok = po_item_ok and po_qty_ok
    else:
        print(f"  [INFO] No PO generated (status={status}) — checking if within expected behavior")
        po_ok = status in ("pending_approval", "escalated")  # acceptable if no PO but workflow completed

    overall = (item_ok and qty_ok and budget_ok and po_ok) or (item_ok and qty_ok and budget_ok and status in ("pending_approval",))
    print(f"\n  OVERALL: {'PASS' if overall else 'FAIL'}")
    return overall


def main():
    # Wait for server to be ready
    print("Waiting for server...")
    for _ in range(20):
        try:
            r = httpx.get(f"{BASE}/api/health", timeout=2)
            if r.status_code == 200:
                print("Server ready.")
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        print("Server not available!")
        sys.exit(1)

    results = []
    for t in TESTS:
        results.append(run_test(t))
        time.sleep(0.5)  # brief pause between tests

    passed = sum(1 for r in results if r)
    failed = len(results) - passed
    print(f"\n{'='*70}")
    print(f"FINAL RESULTS: {passed}/{len(TESTS)} passed, {failed} failed")
    print(f"{'='*70}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
