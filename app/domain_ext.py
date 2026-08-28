"""Domain extension module — adds UC3 (reimbursement) and UC4 (onboarding).

Imported once at startup from app/main.py. Does NOT modify any protected file.
Instead it:
  1. Imports new tool modules so @tool decorators register them in _REGISTRY.
  2. Monkey-patches app.parser.heuristic_parse / parse_request to recognise
     the two new intents and store them in entities.extra["intent_detail"].
  3. Monkey-patches app.planner.template_plan / plan_workflow to route new
     intents to domain-specific step sequences.

All patches are idempotent: re-importing or reloading this module is safe.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# ── Register new tools ────────────────────────────────────────────────────────
from app.tools import reimbursement as _reimb   # noqa: F401 — triggers @tool
from app.tools import onboarding as _onb        # noqa: F401 — triggers @tool

# ── Grab originals once (before any patching) ─────────────────────────────────
import app.parser as _parser
import app.planner as _planner
from app.models import Entities, Plan, PlanStep, StepCondition

# Sentinels so we never double-wrap
_PARSER_PATCHED = "_domain_ext_patched"
_PLANNER_PATCHED = "_domain_ext_patched"

if not getattr(_parser.heuristic_parse, _PARSER_PATCHED, False):
    _orig_heuristic = _parser.heuristic_parse
    _orig_parse     = _parser.parse_request

    # ── Extended heuristic parser ─────────────────────────────────────────────

    def _extended_heuristic(text: str) -> Entities:
        raw = text.strip()
        lower = raw.lower()
        ent = _orig_heuristic(text)

        if any(w in lower for w in ("reimburse", "reimbursement", "expense", "travel expense", "claim")):
            ent.intent = "other"
            ent.extra = dict(ent.extra or {})
            ent.extra["intent_detail"] = "reimbursement"
            import re
            m = re.search(r"(?:for|employee[: ]+)([A-Z][a-z]+(?: [A-Z][a-z]+)?)", text)
            if m:
                ent.extra["employee_name"] = m.group(1)
            items = []
            for cat in ("meals", "lodging", "transport", "incidentals"):
                cat_m = re.search(
                    r"(\d+(?:\.\d+)?)\s*(?:USD|\$)?\s*(?:in )?(?:for )?(?:" + cat + ")",
                    lower,
                )
                if cat_m:
                    items.append({"category": cat, "amount": float(cat_m.group(1)), "quantity": 1})
            if items:
                ent.extra["line_items"] = items

        elif any(w in lower for w in ("onboard", "onboarding", "new hire", "new employee", "start next")):
            ent.intent = "other"
            ent.extra = dict(ent.extra or {})
            ent.extra["intent_detail"] = "onboarding"
            import re
            m = re.search(r"(?:for|hire|employee[: ]+)([A-Z][a-z]+(?: [A-Z][a-z]+)?)", text)
            if m:
                ent.extra["employee_name"] = m.group(1)
            dm = re.search(r"(next (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|\d{4}-\d{2}-\d{2})", lower)
            if dm:
                ent.extra["start_date"] = dm.group(1)
            eq_words = []
            for eq in ("laptop", "monitor", "headset", "phone", "keyboard", "mouse", "docking station"):
                if eq in lower:
                    eq_words.append(eq)
            if eq_words:
                ent.extra["equipment_needed"] = eq_words

        return ent

    setattr(_extended_heuristic, _PARSER_PATCHED, True)

    # ── Extended parse_request ────────────────────────────────────────────────

    def _extended_parse(text: str) -> tuple[Entities, str]:
        ent, tag = _orig_parse(text)
        if ent.intent == "other" and not (ent.extra or {}).get("intent_detail"):
            heur = _extended_heuristic(text)
            if heur.extra.get("intent_detail"):
                ent.extra = dict(ent.extra or {})
                ent.extra.update(heur.extra)
        elif ent.intent != "other":
            heur = _extended_heuristic(text)
            if heur.extra.get("intent_detail"):
                ent.intent = "other"
                ent.extra = dict(ent.extra or {})
                ent.extra.update(heur.extra)
        return ent, tag

    setattr(_extended_parse, _PARSER_PATCHED, True)

    _parser.heuristic_parse = _extended_heuristic
    _parser.parse_request   = _extended_parse
    log.info("[domain_ext] parser patched")

# ── Extended planner ──────────────────────────────────────────────────────────

if not getattr(_planner.template_plan, _PLANNER_PATCHED, False):
    _orig_template      = _planner.template_plan
    _orig_plan_workflow = _planner.plan_workflow

    def _reimbursement_plan(entities: Entities) -> Plan:
        emp = (entities.extra or {}).get("employee_name", "Employee")
        return Plan(
            title=f"Expense Reimbursement: {emp}",
            summary="Fetch policy -> validate expenses -> human approval -> report.",
            source="template",
            steps=[
                PlanStep(
                    id="s1", name="Fetch policy limits", tool="fetch_policy_limits",
                    description="Load corporate expense policy caps for all categories.",
                    inputs={"workflow_id": "$entities.extra.workflow_id"},
                    depends_on=[], condition=StepCondition(type="always"),
                    on_fail="retry", max_retries=2,
                ),
                PlanStep(
                    id="s2", name="Validate expenses against policy", tool="validate_expense",
                    description="Check each submitted line item against the fetched policy caps.",
                    inputs={"line_items": "$entities.extra.line_items", "policy_limits": "$s1.output"},
                    depends_on=["s1"], condition=StepCondition(type="deps_ok"),
                    on_fail="escalate", max_retries=1,
                ),
                PlanStep(
                    id="s3", name="Route for human approval", tool="submit_for_approval",
                    description="Submit validated expense report to the manager approval queue.",
                    inputs={
                        "workflow_id": "$entities.extra.workflow_id",
                        "approver": "$entities.approval_target",
                        "summary": "$s2.output.action",
                        "artifact_url": None,
                    },
                    depends_on=["s2"], condition=StepCondition(type="deps_ok"), on_fail="retry",
                ),
                PlanStep(
                    id="s4", name="Compile stakeholder report", tool="compile_report",
                    description="Plain-language summary of expense validation and approval status.",
                    inputs={
                        "request": "$entities.raw_request", "entities": "$entities",
                        "ranking": {}, "validation": "$s2.output",
                        "po": {}, "approval": "$s3.output", "status": "pending_approval",
                    },
                    depends_on=["s3"], condition=StepCondition(type="deps_ok"), on_fail="skip",
                ),
            ],
        )

    def _onboarding_plan(entities: Entities) -> Plan:
        emp = (entities.extra or {}).get("employee_name", "New Hire")
        return Plan(
            title=f"Employee Onboarding: {emp}",
            summary="Provision accounts -> equipment request -> human approval -> report.",
            source="template",
            steps=[
                PlanStep(
                    id="s1", name="Provision system accounts", tool="provision_accounts",
                    description="Create email, Jira, GitHub, and VPN accounts for the new hire.",
                    inputs={
                        "employee_name": "$entities.extra.employee_name",
                        "start_date": "$entities.extra.start_date",
                        "accounts_needed": "$entities.extra.accounts_needed",
                    },
                    depends_on=[], condition=StepCondition(type="always"),
                    on_fail="retry", max_retries=2,
                ),
                PlanStep(
                    id="s2", name="Generate equipment request", tool="request_equipment",
                    description="Create equipment request PDF for manager approval.",
                    inputs={
                        "employee_name": "$entities.extra.employee_name",
                        "start_date": "$entities.extra.start_date",
                        "equipment_list": "$entities.extra.equipment_needed",
                        "workflow_id": "$entities.extra.workflow_id",
                    },
                    depends_on=["s1"], condition=StepCondition(type="deps_ok"),
                    on_fail="escalate", max_retries=1,
                ),
                PlanStep(
                    id="s3", name="Route for manager approval", tool="submit_for_approval",
                    description="Submit onboarding package to manager approval queue.",
                    inputs={
                        "workflow_id": "$entities.extra.workflow_id",
                        "approver": "$entities.approval_target",
                        "artifact_url": "$s2.output.url",
                        "po_number": "$s2.output.doc_number",
                        "summary": "$s1.output.count",
                    },
                    depends_on=["s2"], condition=StepCondition(type="deps_ok"), on_fail="retry",
                ),
                PlanStep(
                    id="s4", name="Compile onboarding report", tool="compile_report",
                    description="Plain-language summary of accounts provisioned and equipment requested.",
                    inputs={
                        "request": "$entities.raw_request", "entities": "$entities",
                        "ranking": {}, "validation": {},
                        "po": "$s2.output", "approval": "$s3.output", "status": "pending_approval",
                    },
                    depends_on=["s3"], condition=StepCondition(type="deps_ok"), on_fail="skip",
                ),
            ],
        )

    def _extended_template(entities: Entities) -> Plan:
        detail = (entities.extra or {}).get("intent_detail")
        if detail == "reimbursement":
            return _reimbursement_plan(entities)
        if detail == "onboarding":
            return _onboarding_plan(entities)
        return _orig_template(entities)

    setattr(_extended_template, _PLANNER_PATCHED, True)

    def _extended_plan_workflow(entities: Entities) -> tuple[Plan, str]:
        detail = (entities.extra or {}).get("intent_detail")
        if detail in ("reimbursement", "onboarding"):
            return _extended_template(entities), "template:domain_ext"
        return _orig_plan_workflow(entities)

    setattr(_extended_plan_workflow, _PLANNER_PATCHED, True)

    _planner.template_plan   = _extended_template
    _planner.plan_workflow   = _extended_plan_workflow
    log.info("[domain_ext] planner patched")

# Patch parse_request + plan_workflow visible in main.py's module namespace
import app.main as _main_mod
_main_mod.plan_workflow = _planner.plan_workflow
_main_mod.parse_request = _parser.parse_request

log.info("[domain_ext] Domain extension loaded: reimbursement, onboarding")
