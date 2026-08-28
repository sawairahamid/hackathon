"""
Test script: verify parser extracts correct item/quantity for all 7 test cases.
Run: python test_parser_quick.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.parser import heuristic_parse, parse_request

TESTS = [
    {
        "request": "Purchase 30 desktop computers with a maximum budget of PKR 6 million. Compare at least three suppliers and select the best option.",
        "expected_item": "desktop computers",
        "expected_qty": 30,
        "expected_budget": 6_000_000,
    },
    {
        "request": "Purchase 20 enterprise network switches under PKR 4 million.",
        "expected_item": "enterprise network switches",
        "expected_qty": 20,
        "expected_budget": 4_000_000,
    },
    {
        "request": "Procure 15 high-speed routers under PKR 2 million.",
        "expected_item": "high-speed routers",
        "expected_qty": 15,
        "expected_budget": 2_000_000,
    },
    {
        "request": "Buy 5 office printers under PKR 500,000.",
        "expected_item": "office printers",
        "expected_qty": 5,
        "expected_budget": 500_000,
    },
    {
        "request": "Renew 100 Microsoft 365 licenses under PKR 1 million.",
        "expected_item": "Microsoft 365 licenses",
        "expected_qty": 100,
        "expected_budget": 1_000_000,
    },
    {
        "request": "Purchase 40 ergonomic office chairs under PKR 800,000.",
        "expected_item": "ergonomic office chairs",
        "expected_qty": 40,
        "expected_budget": 800_000,
    },
    {
        "request": "Purchase 10 laptops under PKR 2 million.",
        "expected_item": "laptops",
        "expected_qty": 10,
        "expected_budget": 2_000_000,
    },
]

def normalize(s: str) -> str:
    return s.strip().lower().replace("_", " ").replace("-", " ")

passed = 0
failed = 0

print("=" * 70)
print("PARSER TEST RESULTS (heuristic only)")
print("=" * 70)

for i, t in enumerate(TESTS, 1):
    ent = heuristic_parse(t["request"])
    item_ok = normalize(ent.item) == normalize(t["expected_item"]) or normalize(t["expected_item"]) in normalize(ent.item)
    qty_ok = ent.quantity == t["expected_qty"]
    budget_ok = abs(ent.budget - t["expected_budget"]) < 1.0

    status = "PASS" if (item_ok and qty_ok and budget_ok) else "FAIL"
    if status == "PASS":
        passed += 1
    else:
        failed += 1

    print(f"\nTEST {i}: {status}")
    print(f"  Request   : {t['request'][:80]}")
    print(f"  Item      : got='{ent.item}' expected='{t['expected_item']}' {'OK' if item_ok else 'FAIL'}")
    print(f"  Quantity  : got={ent.quantity} expected={t['expected_qty']} {'OK' if qty_ok else 'FAIL'}")
    print(f"  Budget    : got={ent.budget:,.0f} expected={t['expected_budget']:,.0f} {'OK' if budget_ok else 'FAIL'}")

print("\n" + "=" * 70)
print(f"RESULTS: {passed}/{len(TESTS)} passed, {failed} failed")
print("=" * 70)

if failed:
    sys.exit(1)
