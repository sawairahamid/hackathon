from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Intent = Literal["procurement", "vendor_comparison", "other"]
FailAction = Literal["retry", "escalate", "skip", "replan"]
WorkflowStatus = Literal[
    "pending",
    "planning",
    "running",
    "recovering",
    "replanning",
    "pending_approval",
    "approved",
    "rejected",
    "escalated",
    "failed",
    "completed",
]
StepStatus = Literal["pending", "in_progress", "done", "failed", "skipped", "recovering", "replanned"]
ApprovalStatus = Literal["pending_approval", "approved", "rejected"]

IncidentType = Literal[
    "TOOL_TIMEOUT",
    "TOOL_UNAVAILABLE",
    "INVALID_TOOL_RESPONSE",
    "DATA_CHANGED",
    "BUDGET_VIOLATION",
    "VALIDATION_FAILURE",
    "MISSING_REQUIRED_FIELD",
    "SUPPLIER_BECOMES_UNAVAILABLE",
    "UNKNOWN_INCIDENT"
]

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

RecoveryActionType = Literal["RETRY", "FALLBACK", "REPLAN", "ESCALATE", "CONTINUE"]

class IncidentRecord(BaseModel):
    incident_id: str
    type: IncidentType
    severity: Severity
    message: str
    affected_steps: list[str] = Field(default_factory=list)
    recovery_action: RecoveryActionType
    reason: str
    requires_human: bool = False


class ChaosConfig(BaseModel):
    force_timeout: bool = False
    force_malformed: bool = False
    force_over_budget: bool = False
    force_price_shock: bool = False
    force_multi_failure: bool = False
    extra_latency_ms: int = 0


class Entities(BaseModel):
    intent: Intent = "procurement"
    item: str
    quantity: int = 1
    budget: float
    currency: str = "PKR"
    suppliers_to_compare: int = 3
    approval_target: str = "procurement_manager"
    constraints: list[str] = Field(default_factory=list)
    raw_request: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class StepCondition(BaseModel):
    type: str = "always"
    step: str | None = None
    field: str | None = None


class PlanStep(BaseModel):
    id: str
    name: str
    tool: str
    description: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    condition: StepCondition | None = None
    on_fail: FailAction = "retry"
    max_retries: int = 2


class Plan(BaseModel):
    title: str
    summary: str = ""
    source: str = "template"
    steps: list[PlanStep]


class ToolResult(BaseModel):
    ok: bool
    tool: str
    latency_ms: int = 0
    data: Any = None
    error: str | None = None
    error_type: IncidentType | None = None
    source: str = "local"


class CreateWorkflowRequest(BaseModel):
    request: str = Field(min_length=3)
    chaos: ChaosConfig = Field(default_factory=ChaosConfig)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = ""
