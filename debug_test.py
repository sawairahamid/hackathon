from tests.test_scenarios import _run, PRIMARY
from app import trace
import json

status = _run(PRIMARY, "wf_debug")
print("Status:", status)

steps = trace.list_steps("wf_debug")
for s in steps:
    print(s["step_id"], s["status"], s.get("error"))

events = trace.list_events("wf_debug")
for e in events:
    print(e["type"], e["message"])
