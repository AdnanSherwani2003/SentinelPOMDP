"""End-to-end natural-language facade around the existing deterministic workflow."""
from __future__ import annotations

from uuid import uuid4

from pydantic import ValidationError

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.investigation.scenario import build_scenario_planner
from sentinel_pomdp.orchestration.workflow import run_langgraph_investigation

from .clients import LLMClient, LLMClientError
from .grounding import (collect_evidence_references, deterministic_explanation,
                        explanation_payload, validate_explanation)
from .prompts import EXPLAIN_SYSTEM_PROMPT, INTERPRET_SYSTEM_PROMPT
from .registry import (IntentAmbiguityError, IntentValidationError, ScenarioRegistry,
                       default_scenario_registry)
from .schemas import (GroundedExplanationDraft, InvestigationResponse, IntentType,
                      ParsedInvestigationIntent, ResponseStatus, ClaimType)


class InvestigationIntelligenceService:
    """LLM assistance with deterministic validation before and after orchestration."""

    def __init__(self, repository: BaseGraphRepository, llm_client: LLMClient, *,
                 registry: ScenarioRegistry | None = None, generation_attempts: int = 2) -> None:
        self.repository = repository
        self.llm = llm_client
        self.registry = registry or default_scenario_registry()
        self.generation_attempts = max(1, min(generation_attempts, 3))

    def investigate(self, question: str, tenant_id: str, *, horizon: int = 2,
                    max_tool_calls: int = 3, budget: float = 1.0) -> InvestigationResponse:
        trace_id = str(uuid4())
        question = question.strip()
        if not question:
            return self._non_run(ResponseStatus.CLARIFICATION_REQUIRED, question, trace_id,
                                 "Please provide an investigation question.")
        intent, usages = self._interpret(question)
        if intent is None:
            return self._non_run(ResponseStatus.INTERPRETATION_FAILED, question, trace_id,
                                 "The question could not be safely mapped to a registered investigation.", usages)
        if intent.intent_type == IntentType.CLARIFY:
            return self._non_run(ResponseStatus.CLARIFICATION_REQUIRED, question, trace_id,
                                 intent.clarification_question or "Please clarify the investigation.", usages)
        if intent.intent_type == IntentType.UNSUPPORTED:
            return self._non_run(ResponseStatus.UNSUPPORTED, question, trace_id,
                                 "That request is outside the registered investigation catalog.", usages)
        try:
            scenario = self.registry.validate(intent, tenant_id, question=question)
        except IntentAmbiguityError as exc:
            return self._non_run(ResponseStatus.CLARIFICATION_REQUIRED, question, trace_id,
                                 f"Please clarify the investigation: {exc}.", usages)
        except IntentValidationError as exc:
            return self._non_run(ResponseStatus.INTERPRETATION_FAILED, question, trace_id,
                                 f"Rejected untrusted interpretation: {exc}.", usages)

        planner = build_scenario_planner(scenario, horizon=horizon)
        outcome = run_langgraph_investigation(
            self.repository, scenario, planner, tenant_id,
            max_tool_calls=max_tool_calls, budget=budget, thread_id=trace_id)
        refs = collect_evidence_references(self.repository, outcome, tenant_id)
        draft = None
        for _ in range(self.generation_attempts):
            try:
                result = self.llm.generate_structured(
                    system_prompt=EXPLAIN_SYSTEM_PROMPT,
                    payload={"question": question,
                             "scope": {"scenario_id": scenario.scenario_id,
                                       "subject_id": intent.subject_id,
                                       "claim_type": intent.claim_type.value},
                             "outcome": explanation_payload(outcome, refs)},
                    response_model=GroundedExplanationDraft)
                usages.append(result.usage)
                candidate = GroundedExplanationDraft.model_validate(result.parsed)
                if not validate_explanation(candidate, outcome, refs):
                    draft = candidate
                    break
            except (LLMClientError, ValidationError, TypeError, ValueError):
                continue
        fallback = draft is None
        if fallback:
            draft = deterministic_explanation(outcome, refs)
        return InvestigationResponse(
            status=ResponseStatus.COMPLETED, question=question,
            scenario_id=scenario.scenario_id, subject_id=intent.subject_id,
            claim_type=intent.claim_type, decision=outcome.decision,
            selected_hypothesis=outcome.selected_hypothesis,
            final_belief=outcome.final_belief, explanation=draft.summary,
            fact_ids=draft.fact_ids,
            supporting_evidence_ids=draft.supporting_evidence_ids,
            contradicting_evidence_ids=draft.contradicting_evidence_ids,
            document_ids=draft.document_ids, provenance_status=draft.provenance_status,
            limitation=draft.limitation or None, explanation_fallback_used=fallback,
            grounding_valid=True, trace_id=trace_id,
            investigation=outcome.model_dump(mode="json"), llm_usage=usages)

    def investigate_scenario(self, question: str, tenant_id: str, scenario, *,
                             horizon: int = 2, max_tool_calls: int = 3,
                             budget: float = 1.0) -> InvestigationResponse:
        """Run a reviewer-approved domain pack without giving an LLM control."""
        trace_id = str(uuid4())
        planner = build_scenario_planner(scenario, horizon=horizon)
        outcome = run_langgraph_investigation(
            self.repository, scenario, planner, tenant_id,
            max_tool_calls=max_tool_calls, budget=budget, thread_id=trace_id)
        outcome.metadata["domain_model_version"] = scenario.model_version
        refs = collect_evidence_references(self.repository, outcome, tenant_id)
        draft = deterministic_explanation(outcome, refs)
        return InvestigationResponse(
            status=ResponseStatus.COMPLETED, question=question,
            scenario_id=scenario.scenario_id, claim_type=ClaimType.SHIPMENT_TIMELINESS,
            decision=outcome.decision, selected_hypothesis=outcome.selected_hypothesis,
            final_belief=outcome.final_belief, explanation=draft.summary,
            fact_ids=draft.fact_ids,
            supporting_evidence_ids=draft.supporting_evidence_ids,
            contradicting_evidence_ids=draft.contradicting_evidence_ids,
            document_ids=draft.document_ids, provenance_status=draft.provenance_status,
            limitation=draft.limitation or None, explanation_fallback_used=True,
            grounding_valid=True, trace_id=trace_id,
            investigation=outcome.model_dump(mode="json"))

    def _interpret(self, question: str):
        usages = []
        for _ in range(self.generation_attempts):
            try:
                result = self.llm.generate_structured(
                    system_prompt=INTERPRET_SYSTEM_PROMPT,
                    payload={"question": question, "registered_scenarios": self.registry.prompt_catalog()},
                    response_model=ParsedInvestigationIntent)
                usages.append(result.usage)
                return ParsedInvestigationIntent.model_validate(result.parsed), usages
            except (LLMClientError, ValidationError, TypeError, ValueError):
                continue
        return None, usages

    @staticmethod
    def _non_run(status, question, trace_id, explanation, usages=None):
        return InvestigationResponse(status=status, question=question, explanation=explanation,
                                     trace_id=trace_id, llm_usage=usages or [])
