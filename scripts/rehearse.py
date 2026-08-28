"""Live rehearsal against a running OrchestrAI instance."""

from __future__ import annotations

import json
import time
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PRIMARY = (
    "Create a purchase request for 50 laptops under PKR 10 million, compare three suppliers, "
    "identify the best option, prepare the purchase order, and send it for approval."
)
SECONDARY = (
    "Our software vendor contract is expiring. Compare 3 renewal/alternative options "
    "and recommend one within a $20,000 budget."
)


def wait(wid: str) -> dict:
    for _ in range(50):
        snap = httpx.get(f"{BASE}/api/workflows/{wid}", timeout=10).json()
        if snap["status"] in {"pending_approval", "escalated", "failed", "completed", "approved"}:
            return snap
        time.sleep(0.35)
    return httpx.get(f"{BASE}/api/workflows/{wid}", timeout=10).json()


def run(label: str, request: str, chaos: dict | None = None) -> dict:
    created = httpx.post(f"{BASE}/api/workflows", json={"request": request, "chaos": chaos or {}}, timeout=30).json()
    snap = wait(created["id"])
    ranking = next((s for s in snap["steps"] if s.get("tool") == "rank_suppliers"), None)
    selected = (ranking or {}).get("output") or {}
    print(
        f"{label}: status={snap['status']} selected={(selected.get('selected') or {}).get('name')} "
        f"rejected={[r.get('name') for r in selected.get('rejected') or []]}"
    )
    return snap


def main() -> None:
    print("health", json.dumps(httpx.get(f"{BASE}/api/health", timeout=5).json()))
    snap = run("primary", PRIMARY)
    if snap["status"] == "pending_approval":
        r = httpx.post(
            f"{BASE}/api/workflows/{snap['id']}/approval",
            json={"decision": "approve", "note": "rehearsal"},
            timeout=10,
        )
        print("approved", r.json().get("status"))
    run("secondary", SECONDARY)
    run("chaos-timeout", PRIMARY, {"force_timeout": True})


if __name__ == "__main__":
    main()
