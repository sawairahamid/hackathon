from __future__ import annotations

import logging
import time
from typing import Any

from app import trace
from app.models import Entities, Plan, PlanStep, ToolResult
from app.tools import invoke, load_all
from app.incident.commander import handle_incident

log = logging.getLogger(__name__)

# Maximum times a validation failure can trigger self-correct before we escalate
MAX_VALIDATION_SELF_CORRECTS = 2


def _dig(obj: Any, parts: list[str]) -> Any:
    for p in parts:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(p)
        elif isinstance(obj, list):
            if p.isdigit() and int(p) < len(obj):
                obj = obj[int(p)]
            else:
                return None
        else:
            obj = getattr(obj, p, None)
    return obj


def resolve(value: Any, entities: dict[str, Any], outputs: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        parts = value[1:].split(".")
        if parts[0] == "entities":
            return _dig(entities, parts[1:])
        blob = outputs.get(parts[0])
        rest = parts[1:]
        if rest[:1] == ["output"]:
            rest = rest[1:]
        return _dig(blob, rest) if rest else blob
    if isinstance(value, dict):
        return {k: resolve(v, entities, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, entities, outputs) for v in value]
    return value


def _truthy_nonempty(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, (list, dict, str)):
        return len(val) > 0
    return True


def condition_holds(step: PlanStep, statuses: dict[str, str], outputs: dict[str, Any]) -> bool:
    cond = step.condition
    if not cond or cond.type in ("always", None, ""):
        return True
    if cond.type == "deps_ok":
        return all(statuses.get(d) == "done" for d in step.depends_on)
    if cond.type == "output_nonempty":
        target = cond.step or (step.depends_on[0] if step.depends_on else None)
        return _truthy_nonempty(outputs.get(target))
    if cond.type == "field_true":
        target = cond.step
        blob = outputs.get(target) if target else None
        if not cond.field:
            return bool(blob)
        return bool(_dig(blob, cond.field.split(".")))
    return True


def _self_correct(wid: str, entities: dict, outputs: dict, validation: dict) -> dict:
    """Re-rank excluding the bad supplier, then re-validate. Returns new validation dict."""
    exclude = list(validation.get("suggested_exclude_ids") or [])
    if not exclude:
        return validation
    trace.emit(
        wid,
        "self_correct",
        f"Validation failed — re-ranking with excluded suppliers {exclude}",
        step_id="s3",
        payload={"exclude_ids": exclude, "errors": validation.get("errors")},
    )
    log.info("[SELF_CORRECT] excluding suppliers %s", exclude)
    quotes = outputs.get("s1") or {}
    result = invoke(
        "rank_suppliers",
        {
            "quotes": quotes,
            "budget": entities.get("budget"),
            "currency": entities.get("currency"),
            "quantity": entities.get("quantity"),
            "requested_item": entities.get("item"),
            "exclude_ids": exclude,
        },
    )
    trace.record_tool_call(wid, "s2", "rank_suppliers", {"exclude_ids": exclude}, result.model_dump(), result.ok, result.latency_ms)
    if result.ok and result.data:
        outputs["s2"] = result.data
        trace.upsert_step(wid, "s2", status="done", output=result.data)
        trace.emit(wid, "tool_result", "Re-rank complete after self-correct", step_id="s2", payload=result.data if isinstance(result.data, dict) else {})
    reval = invoke(
        "validate_selection",
        {"entities": entities, "quotes": quotes, "ranking": outputs.get("s2")},
    )
    trace.record_tool_call(wid, "s3", "validate_selection", {"after": "self_correct"}, reval.model_dump(), reval.ok, reval.latency_ms)
    data = reval.data if isinstance(reval.data, dict) else validation
    outputs["s3"] = data
    trace.upsert_step(wid, "s3", status="done" if data.get("passed") else "failed", output=data)
    trace.emit(
        wid,
        "validation",
        "Re-validation " + ("passed" if data.get("passed") else "failed"),
        step_id="s3",
        payload=data,
    )
    return data


def run_workflow(wid: str, entities: Entities, plan: Plan) -> str:
    load_all()
    ent = entities.model_dump()
    ent.setdefault("extra", {})
    ent["extra"]["workflow_id"] = wid

    log.info(
        "[REQUEST] wid=%s item='%s' qty=%d budget=%s currency=%s",
        wid, ent.get("item"), ent.get("quantity"), ent.get("budget"), ent.get("currency"),
    )

    outputs: dict[str, Any] = {}
    statuses: dict[str, str] = {s.id: "pending" for s in plan.steps}
    tools_used: list[str] = []
    # Track how many times we've called handle_incident for validation on this run
    _validation_incident_count = 0

    for step in plan.steps:
        trace.upsert_step(wid, step.id, name=step.name, tool=step.tool, status="pending")

    trace.set_workflow_fields(wid, status="running")

    def fail_workflow(msg: str) -> str:
        trace.set_workflow_fields(wid, status="failed", error=msg)
        trace.emit(wid, "workflow_failed", msg)
        return "failed"

    for step in plan.steps:
        if any(statuses.get(d) == "failed" for d in step.depends_on):
            statuses[step.id] = "skipped"
            trace.upsert_step(wid, step.id, status="skipped", finished=True)
            trace.emit(wid, "log", f"Skipping {step.id} because a dependency failed", step_id=step.id)
            continue
        if any(statuses.get(d) not in ("done", "skipped") for d in step.depends_on):
            statuses[step.id] = "skipped"
            trace.upsert_step(wid, step.id, status="skipped", finished=True)
            continue
        if not condition_holds(step, statuses, outputs):
            statuses[step.id] = "skipped"
            trace.upsert_step(wid, step.id, status="skipped", finished=True)
            trace.emit(
                wid,
                "log",
                f"Condition blocked {step.id} ({step.condition.type if step.condition else 'n/a'})",
                step_id=step.id,
            )
            continue

        statuses[step.id] = "in_progress"
        trace.upsert_step(wid, step.id, name=step.name, tool=step.tool, status="in_progress", started=True)
        trace.emit(wid, "step_started", f"{step.name} · {step.tool}", step_id=step.id)

        inputs = resolve(step.inputs, ent, outputs)
        if step.tool == "compile_report":
            inputs["tools_used"] = tools_used
            inputs.setdefault("status", "pending_approval")

        # ── Inject requested_item into rank_suppliers calls ───────────────────
        if step.tool == "rank_suppliers" and isinstance(inputs, dict):
            if "requested_item" not in inputs:
                inputs["requested_item"] = ent.get("item")

        result = ToolResult(ok=False, tool=step.tool, error="not invoked")
        attempts = max(int(step.max_retries or 0), 0) + 1
        for attempt in range(1, attempts + 1):
            trace.upsert_step(wid, step.id, attempt=attempt)
            trace.emit(
                wid,
                "tool_called",
                f"Invoking {step.tool} (attempt {attempt}/{attempts})",
                step_id=step.id,
                payload={"inputs": _safe(inputs)},
            )
            result = invoke(step.tool, inputs if isinstance(inputs, dict) else {})
            trace.record_tool_call(
                wid, step.id, step.tool, inputs, result.model_dump(), result.ok, result.latency_ms
            )
            trace.emit(
                wid,
                "tool_result",
                f"{step.tool} {'ok' if result.ok else 'error'} in {result.latency_ms} ms"
                + (f" · {result.error}" if result.error else ""),
                step_id=step.id,
                payload={"ok": result.ok, "source": result.source, "error": result.error},
            )
            if result.ok:
                break

            # ── Incident handling — bounded to prevent infinite loops ──────────
            action = handle_incident(wid, step.id, result, attempt, attempts)

            if action == "REPLAN":
                # No longer triggered by validation failures (fixed in policies.py)
                # But handle it if it ever fires for other reasons
                return "REPLAN"
            elif action == "RETRY":
                if attempt < attempts:
                    trace.emit(wid, "step_retry", f"{step.tool} failed, retrying ({result.error})", step_id=step.id)
                    time.sleep(0.35 * attempt)
            elif action == "ESCALATE":
                break
            elif action == "FALLBACK":
                if isinstance(inputs, dict):
                    if "chaos" not in inputs or not isinstance(inputs.get("chaos"), dict):
                        inputs["chaos"] = {}
                    inputs["chaos"]["use_fallback"] = True
                trace.emit(wid, "FALLBACK_ACTIVATED", "Falling back to bundled catalog", step_id=step.id)
                step_result = invoke(step.tool, inputs if isinstance(inputs, dict) else {})
                trace.record_tool_call(wid, step.id, step.tool, inputs, step_result.model_dump(), step_result.ok, step_result.latency_ms)
                if step_result.ok:
                    result = step_result
                    trace.upsert_step(wid, step.id, status="done", output=step_result.data, finished=True)
                    break

        if step.tool not in tools_used:
            tools_used.append(step.tool)

        data = result.data if result.ok else None
        if isinstance(data, dict):
            outputs[step.id] = data
        elif result.ok:
            outputs[step.id] = data

        # ── Validation step special handling ──────────────────────────────────
        if step.tool == "validate_selection" and isinstance(data, dict):
            trace.emit(wid, "validation", "Selection validation " + ("passed" if data.get("passed") else "failed"), step_id=step.id, payload=data)
            if not data.get("passed") and data.get("action") == "retry_rank":
                # Inline self-correct — bounded by MAX_VALIDATION_SELF_CORRECTS
                if _validation_incident_count < MAX_VALIDATION_SELF_CORRECTS:
                    _validation_incident_count += 1
                    log.info("[SELF_CORRECT] attempt %d/%d", _validation_incident_count, MAX_VALIDATION_SELF_CORRECTS)
                    data = _self_correct(wid, ent, outputs, data)
                    outputs[step.id] = data
                else:
                    log.warning("[SELF_CORRECT] Max attempts reached (%d). Escalating.", MAX_VALIDATION_SELF_CORRECTS)
                    trace.emit(wid, "log", f"Self-correct limit reached ({MAX_VALIDATION_SELF_CORRECTS}) — escalating", step_id=step.id)

        if not result.ok or (step.tool == "validate_selection" and isinstance(data, dict) and not data.get("passed")):
            if step.tool == "validate_selection" and isinstance(data, dict) and not data.get("passed"):
                # ── Bounded: do NOT call handle_incident again for validation ────
                # This prevents the incident count explosion
                statuses[step.id] = "failed"
                trace.upsert_step(wid, step.id, status="failed", output=data, error="; ".join(data.get("errors") or []), finished=True)
                trace.emit(wid, "escalated", "Validation could not be satisfied — escalating to a human", step_id=step.id, payload=data)
                trace.set_workflow_fields(wid, status="escalated")
                _compile_best_effort(wid, ent, outputs, tools_used, status="escalated")
                trace.emit(wid, "workflow_completed", "Workflow escalated after validation failure")
                from app.impact import calculate_impact
                trace.emit(wid, "impact_ready", "Impact analytics ready", payload=calculate_impact(wid))
                return "escalated"

            if step.on_fail == "skip":
                statuses[step.id] = "skipped"
                trace.upsert_step(wid, step.id, status="skipped", error=result.error, finished=True)
                continue

            statuses[step.id] = "failed"
            trace.upsert_step(wid, step.id, status="failed", error=result.error, finished=True)
            trace.set_workflow_fields(wid, status="escalated", error=result.error)
            trace.emit(wid, "escalated", f"{step.name} failed: {result.error}", step_id=step.id)
            _compile_best_effort(wid, ent, outputs, tools_used, status="escalated")
            trace.emit(wid, "workflow_completed", "Workflow escalated")
            from app.impact import calculate_impact
            trace.emit(wid, "impact_ready", "Impact analytics ready", payload=calculate_impact(wid))
            return "escalated"

        statuses[step.id] = "done"
        trace.upsert_step(wid, step.id, status="done", output=data, finished=True)
        trace.emit(wid, "step_done", f"{step.name} complete", step_id=step.id, payload=_safe(data) if isinstance(data, dict) else {})
        time.sleep(0.12)

    report = None
    s6 = outputs.get("s6")
    if isinstance(s6, dict):
        report = s6.get("report")
    if report:
        trace.set_workflow_fields(wid, report=report, status="pending_approval")
        trace.emit(wid, "report_ready", "Stakeholder report ready", payload={"chars": len(report)})
    else:
        trace.set_workflow_fields(wid, status="pending_approval")
    trace.emit(wid, "approval_requested", "Waiting for human approval — agent will not auto-approve spend")
    trace.emit(wid, "workflow_completed", "Execution finished; approval gate is open")
    from app.impact import calculate_impact
    trace.emit(wid, "impact_ready", "Impact analytics ready", payload=calculate_impact(wid))
    return "pending_approval"


def _compile_best_effort(wid: str, ent: dict, outputs: dict, tools_used: list[str], status: str) -> None:
    result = invoke(
        "compile_report",
        {
            "request": ent.get("raw_request"),
            "entities": ent,
            "ranking": outputs.get("s2") or {},
            "validation": outputs.get("s3") or {},
            "po": outputs.get("s4") or {},
            "approval": outputs.get("s5") or {},
            "tools_used": tools_used,
            "status": status,
        },
    )
    if result.ok and isinstance(result.data, dict) and result.data.get("report"):
        trace.set_workflow_fields(wid, report=result.data["report"], status=status)
        trace.emit(wid, "report_ready", "Escalation report ready")


def _safe(obj: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "…"
    if isinstance(obj, dict):
        if len(obj) > 12:
            return {k: _safe(obj[k], depth + 1) for k in list(obj)[:12]}
        return {k: _safe(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(x, depth + 1) for x in obj[:8]]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        if isinstance(obj, str) and len(obj) > 400:
            return obj[:400] + "…"
        return obj
    return str(obj)
