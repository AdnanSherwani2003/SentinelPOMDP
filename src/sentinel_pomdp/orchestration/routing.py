"""Pure routing functions used by StateGraph conditional edges."""
from __future__ import annotations

from typing import Literal

from .state import InvestigationGraphState


def route_planner_decision(state: InvestigationGraphState) -> Literal["investigate", "evidence_gate", "finalize"]:
    if state.get("error"):
        return "finalize"
    decision = (state.get("planner_decision") or {}).get("kind")
    if decision == "INVESTIGATE":
        return "investigate"
    if decision == "ANSWER":
        return "evidence_gate"
    if decision == "ABSTAIN":
        return "finalize"
    return "finalize"


def route_observation(state: InvestigationGraphState) -> Literal["bayesian_update", "finalize"]:
    return "finalize" if state.get("error") else "bayesian_update"


def route_after_update(state: InvestigationGraphState) -> Literal["plan", "finalize"]:
    return "finalize" if state.get("error") else "plan"
