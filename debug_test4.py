import os
os.environ["SUPPLIER_API_URL"] = "http://127.0.0.1:9"
from tests.test_scenarios import _run, PRIMARY
from app import trace

status = _run(PRIMARY, "wf_debug4")
print("Status:", status)
tcs = trace.list_tool_calls("wf_debug4")
for tc in tcs:
    print(tc["step_id"], tc["tool"], tc["ok"])
    print("  Inputs:", tc["inputs_json"])
    print("  Outputs:", tc["outputs_json"])
