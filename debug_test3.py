import os
os.environ["SUPPLIER_API_URL"] = "http://127.0.0.1:9"
from tests.test_scenarios import _run, PRIMARY
from app import trace

status = _run(PRIMARY, "wf_debug3")
print("Status:", status)
steps = trace.list_steps("wf_debug3")
for s in steps:
    print(s["step_id"], s["tool"])
    print("  Outputs:", s.get("output_json"))
    print("  Error:", s.get("error"))
