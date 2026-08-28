import os
os.environ["SUPPLIER_API_URL"] = "http://127.0.0.1:9"
os.environ["DATABASE_PATH"] = "test5.db"
from app import trace
trace.init_db()
from tests.test_scenarios import _run, PRIMARY

status = _run(PRIMARY, "wf_debug5")
print("Status:", status)
tcs = trace.list_tool_calls("wf_debug5")
for tc in tcs:
    print(tc["step_id"], tc["tool"], tc["ok"])
    print("  Outputs:", tc["outputs_json"])

steps = trace.list_steps("wf_debug5")
for s in steps:
    print(s["step_id"], s["tool"])
    print("  Outputs:", s.get("output_json"))
    print("  Error:", s.get("error"))
