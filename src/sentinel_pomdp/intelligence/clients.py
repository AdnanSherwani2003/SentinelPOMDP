"""Provider-neutral client contract plus an explicitly fake deterministic client."""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from .schemas import GroundedExplanationDraft, LLMUsage, ParsedInvestigationIntent

T = TypeVar("T", bound=BaseModel)


class LLMClientError(RuntimeError):
    """A bounded, safe provider failure."""


@dataclass(frozen=True)
class LLMResult:
    parsed: BaseModel
    usage: LLMUsage


class LLMClient(Protocol):
    def generate_structured(self, *, system_prompt: str, payload: dict[str, Any],
                            response_model: type[T]) -> LLMResult: ...


class DeterministicFakeLLM:
    """Offline test double; it is not a language model and is labeled accordingly."""

    provider = "deterministic-fake"
    model = "rules-v1"

    def __init__(self, scripted: list[BaseModel | Exception | dict[str, Any]] | None = None) -> None:
        self.scripted = deque(scripted or [])
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, *, system_prompt: str, payload: dict[str, Any],
                            response_model: type[T]) -> LLMResult:
        started = perf_counter()
        self.calls.append({"system_prompt": system_prompt, "payload": payload,
                           "response_model": response_model})
        if self.scripted:
            value = self.scripted.popleft()
            if isinstance(value, Exception):
                raise value
            parsed = value if isinstance(value, BaseModel) else response_model.model_validate(value)
        elif response_model is ParsedInvestigationIntent:
            parsed = self._interpret(str(payload.get("question", "")))
        elif response_model is GroundedExplanationDraft:
            values = dict(payload["outcome"])
            posterior = ", ".join(
                f"{entry['hypothesis']}={entry['probability']:.3f}"
                for entry in values["final_belief"])
            supporting = ", ".join(values["supporting_evidence_ids"]) or "none"
            contradicting = ", ".join(values["contradicting_evidence_ids"]) or "none"
            facts = ", ".join(values["fact_ids"]) or "none"
            documents = ", ".join(values["document_ids"]) or "none"
            prefix = (f"Answer: {values['selected_hypothesis']}." if values["decision"] == "ANSWER"
                      else "Abstained.")
            values["summary"] = (
                f"{prefix} Posterior: {posterior}. Facts: {facts}. Supporting evidence: {supporting}; "
                f"contradicting evidence: {contradicting}. Source documents: {documents}. "
                f"Provenance: {values['provenance_status']}."
                + (f" Limitation: {values['limitation']}" if values.get("limitation") else ""))
            parsed = GroundedExplanationDraft.model_validate(values)
        else:
            raise LLMClientError(f"fake client has no rule for {response_model.__name__}")
        elapsed = (perf_counter() - started) * 1000
        return LLMResult(parsed=parsed, usage=LLMUsage(
            provider=self.provider, model=self.model, input_tokens=0, output_tokens=0,
            total_tokens=0, estimated_cost_usd=0, latency_ms=elapsed))

    @staticmethod
    def _interpret(question: str) -> ParsedInvestigationIntent:
        q = re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()
        subject = "sup_a" if ("supplier a" in q or "sup a" in q) else (
            "sup_b" if ("supplier b" in q or "sup b" in q) else (
            "comp_a" if ("component a" in q or "comp a" in q) else None))
        if ("certif" in q or "qa" in q) and subject == "comp_a":
            return ParsedInvestigationIntent(intent_type="INVESTIGATE",
                scenario_id="component_certification_missing", subject_id=subject,
                claim_type="CERTIFICATION_STATUS")
        if subject == "sup_b" and any(word in q for word in ("delivery", "delivered", "on time")):
            return ParsedInvestigationIntent(intent_type="INVESTIGATE",
                scenario_id="supplier_b_conflicting_delivery", subject_id=subject,
                claim_type="DELIVERY_TIMELINESS")
        if subject == "sup_a" and any(word in q for word in ("caused", "cause", "responsible", "attribut")):
            return ParsedInvestigationIntent(intent_type="INVESTIGATE",
                scenario_id="supplier_delay_causal_attribution", subject_id=subject,
                claim_type="CAUSAL_ATTRIBUTION")
        if subject == "sup_a" and any(word in q for word in ("shipment", "late", "delay", "arriv")):
            return ParsedInvestigationIntent(intent_type="INVESTIGATE",
                scenario_id="supplier_a_shipment_delay", subject_id=subject,
                claim_type="SHIPMENT_TIMELINESS")
        if any(word in q for word in ("screen", "signal", "which source")) and "delay" in q:
            return ParsedInvestigationIntent(intent_type="INVESTIGATE",
                scenario_id="multi_investigation_screening", subject_id="inc_delay_001",
                claim_type="DELAY_SIGNAL_SCREENING")
        if any(word in q for word in ("weather", "poem", "recipe", "stock price")):
            return ParsedInvestigationIntent(intent_type="UNSUPPORTED")
        return ParsedInvestigationIntent(intent_type="CLARIFY",
            clarification_question="Which registered supplier, component, and claim should be investigated?")
