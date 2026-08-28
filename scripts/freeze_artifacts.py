"""Headless runs that freeze sample PO PDFs and reports for the submission zip."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app import trace
from app.executor import run_workflow
from app.parser import parse_request
from app.planner import template_plan
from app.tools import load_all

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

SCENARIOS = {
    "procurement": (
        "wf_sample_primary",
        "Create a purchase request for 50 laptops under PKR 10 million, compare three suppliers, "
        "identify the best option, prepare the purchase order, and send it for approval.",
    ),
    "renewal": (
        "wf_sample_renewal",
        "Our software vendor contract is expiring. Compare 3 renewal/alternative options "
        "and recommend one within a $20,000 budget.",
    ),
}


def _run(wid: str, text: str) -> None:
    if not trace.get_workflow(wid):
        ent, _ = parse_request(text)
        ent.extra = {"workflow_id": wid, "chaos": {}}
        trace.create_workflow(wid, text, {})
        run_workflow(wid, ent, template_plan(ent))


def main() -> None:
    load_all()
    trace.init_db()
    SAMPLES.mkdir(exist_ok=True)
    for name, (wid, text) in SCENARIOS.items():
        _run(wid, text)
        row = trace.get_workflow(wid)
        if row and row.get("report"):
            path = SAMPLES / f"sample-execution-report-{name}.md"
            path.write_text(row["report"], encoding="utf-8")
            print("wrote", path)
        steps = {s["step_id"]: s for s in trace.list_steps(wid)}
        po = steps.get("s4", {}).get("output_json")
        if po:
            data = json.loads(po)
            src = Path(data["path"])
            dest = SAMPLES / f"sample-{name}-po.pdf"
            if src.exists():
                shutil.copy2(src, dest)
                print("copied", dest)
        events = trace.list_events(wid)
        (SAMPLES / f"sample-trace-{name}.json").write_text(
            json.dumps(events, indent=2, default=str), encoding="utf-8"
        )
        print(name, "status", row["status"] if row else None)


if __name__ == "__main__":
    main()
