from tests.test_scenarios import _run, PRIMARY
from app import trace

status = _run(PRIMARY, "wf_debug2")
print("Status:", status)

steps = trace.list_steps("wf_debug2")
for s in steps:
    print(s["step_id"], s["tool"])
    print("  Inputs:", s.get("inputs_json"))
    print("  Outputs:", s.get("output_json"))
    print("  Error:", s.get("error"))
