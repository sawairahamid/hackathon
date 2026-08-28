import sys
import json
import uuid
from app import trace
trace.init_db()
from app.parser import parse_request
from app.planner import plan_workflow
from app.executor import run_workflow

# A prompt designed to fail validation 
# Requesting 100 laptops for a tiny budget (PKR 1,000)
p = "Purchase 10 laptops with a maximum budget of PKR 2,000,000"

print(f"--- TRIGGERING VALIDATION FAILURE ---")
ent, tag = parse_request(p)
wid = f"wf_test_{uuid.uuid4().hex[:6]}"
ent.extra = {"workflow_id": wid}
plan, _ = plan_workflow(ent)
trace.create_workflow(wid, p, {})
trace.set_workflow_fields(wid, plan_json=plan.model_dump_json())

current_plan = plan
workflow_retries = 0
MAX_WORKFLOW_RETRIES = 2

while True:
    res = run_workflow(wid, ent, current_plan)
    if res == "REPLAN":
        workflow_retries += 1
        print(f"Recovery attempt {workflow_retries}/{MAX_WORKFLOW_RETRIES}")
        if workflow_retries > MAX_WORKFLOW_RETRIES:
            print("Retry limit reached. Stopping workflow.")
            trace.set_workflow_fields(wid, status="failed", error="MAX_WORKFLOW_RETRIES exceeded")
            break
        row = trace.get_workflow(wid)
        from app.models import Plan
        current_plan = Plan(**json.loads(row["plan_json"]))
        continue
    break

steps = trace.list_steps(wid)
print("\nFINAL EXECUTION TRACE:")
for s in steps:
    print(f"Step {s.get('step_id')}: {s.get('tool')} -> {s.get('status')} (error: {s.get('error')})")

row = trace.get_workflow(wid)
print(f"\nWorkflow Status: {row.get('status')}")
print(f"Workflow Error: {row.get('error')}")

incidents = trace.list_incidents(wid)
print(f"\nTotal DB Incidents created: {len(incidents)}")
for inc in incidents:
    print(f" - {inc.get('id')}: {inc.get('type')}")
