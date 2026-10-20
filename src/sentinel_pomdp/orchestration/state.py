"""Serializable state contracts for LangGraph orchestration."""
from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel, Field, field_validator


class WorkflowTraceEvent(BaseModel):
    sequence: int = Field(ge=1)
    node_name: str
    route: str | None = None
    planner_action: str | None = None
    planner_horizon: int | None = None
    expected_utility: float | None = None
    tool_name: str | None = None
    tool_status: str | None = None
    observation: str | None = None
    belief_before: dict[str, float] | None = None
    belief_after: dict[str, float] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    evidence_gate_verdict: str | None = None
    investigation_cost: float = 0.0
    node_runtime_ms: float = Field(default=0.0, ge=0)
    termination_reason: str | None = None
    error: str | None = None


class InitialWorkflowInput(BaseModel):
    tenant_id: str
    scenario_id: str
    planning_horizon: int = Field(default=2, ge=0)
    max_tool_calls: int = Field(default=3, ge=0)
    initial_budget: float = Field(default=1.0, ge=0)
    model_version: str = Field(default="illustrative-v1", min_length=1, max_length=200)

    @field_validator("tenant_id", "scenario_id")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workflow identifiers must be non-empty")
        return value.strip()


class InvestigationGraphState(TypedDict, total=False):
    tenant_id: str
    scenario_id: str
    model_version: str
    hypotheses: list[str]
    current_belief: dict[str, float]
    planning_horizon: int
    max_tool_calls: int
    initial_budget: float
    investigation_count: int
    remaining_budget: float
    total_cost: float
    pending_action: str | None
    planner_decision: dict[str, Any] | None
    proposed_hypothesis: str | None
    latest_tool_result: dict[str, Any] | None
    latest_observation: dict[str, Any] | None
    action_history: list[list[str]]
    observations: list[dict[str, Any]]
    seen_evidence_ids: list[str]
    seen_document_ids: list[str]
    investigation_steps: list[dict[str, Any]]
    workflow_trace: list[dict[str, Any]]
    evidence_status: str | None
    evidence_verdict: dict[str, Any] | None
    terminal_decision: str | None
    final_hypothesis: str | None
    termination_reason: str | None
    error: str | None
    planning_runtime_ms: float
    tool_runtime_ms: float
    final_outcome: dict[str, Any] | None
