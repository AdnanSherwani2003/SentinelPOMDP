"""Trusted allow-list connecting language labels to deterministic scenario factories."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sentinel_pomdp.investigation.scenario import (
    InvestigationScenario, conflicting_delivery_scenario, missing_evidence_scenario,
    multi_investigation_scenario, supplier_delay_scenario, supplier_shipment_delay_scenario,
)

from .schemas import ClaimType, ParsedInvestigationIntent


class IntentValidationError(ValueError):
    pass


class IntentAmbiguityError(IntentValidationError):
    pass


@dataclass(frozen=True)
class ScenarioRegistration:
    scenario_id: str
    subject_id: str
    claim_type: ClaimType
    description: str
    factory: Callable[[str], InvestigationScenario]
    question_aliases: tuple[str, ...]


class ScenarioRegistry:
    def __init__(self, registrations: list[ScenarioRegistration]) -> None:
        self._items = {item.scenario_id: item for item in registrations}
        if len(self._items) != len(registrations):
            raise ValueError("scenario IDs must be unique")

    def prompt_catalog(self) -> list[dict[str, str]]:
        return [{"scenario_id": x.scenario_id, "subject_id": x.subject_id,
                 "claim_type": x.claim_type.value, "description": x.description}
                for x in self._items.values()]

    def resolve(self, scenario_id: str, tenant_id: str) -> InvestigationScenario:
        """Resolve an explicit trusted ID without natural-language interpretation."""
        item = self._items.get(scenario_id)
        if item is None:
            raise IntentValidationError("scenario is not registered")
        scenario = item.factory(tenant_id)
        if scenario.scenario_id != item.scenario_id:
            raise IntentValidationError("scenario factory identity mismatch")
        if any(request.tenant_id != tenant_id for request in scenario.requests.values()):
            raise IntentValidationError("scenario factory violated tenant scope")
        return scenario

    def validate(self, intent: ParsedInvestigationIntent, tenant_id: str, *,
                 question: str | None = None) -> InvestigationScenario:
        item = self._items.get(intent.scenario_id)
        if item is None:
            raise IntentValidationError("scenario is not registered")
        if intent.subject_id != item.subject_id or intent.claim_type != item.claim_type:
            raise IntentValidationError("subject or claim type does not match the registered scenario")
        if question is not None:
            normalized = " ".join(question.casefold().split())
            if not any(alias in normalized for alias in item.question_aliases):
                raise IntentAmbiguityError(
                    "the question does not explicitly identify the registered subject or scope")
        scenario = item.factory(tenant_id)
        if scenario.scenario_id != item.scenario_id:
            raise IntentValidationError("scenario factory identity mismatch")
        if any(request.tenant_id != tenant_id for request in scenario.requests.values()):
            raise IntentValidationError("scenario factory violated tenant scope")
        return scenario


def default_scenario_registry() -> ScenarioRegistry:
    return ScenarioRegistry([
        ScenarioRegistration("supplier_a_shipment_delay", "sup_a", ClaimType.SHIPMENT_TIMELINESS,
                             "Whether Supplier A's shipment arrived late.", supplier_shipment_delay_scenario,
                             ("supplier a", "sup a")),
        ScenarioRegistration("supplier_delay_causal_attribution", "sup_a", ClaimType.CAUSAL_ATTRIBUTION,
                             "Whether Supplier A caused the production-delay incident.", supplier_delay_scenario,
                             ("supplier a", "sup a")),
        ScenarioRegistration("supplier_b_conflicting_delivery", "sup_b", ClaimType.DELIVERY_TIMELINESS,
                             "Whether Supplier B delivered on time when sources conflict.", conflicting_delivery_scenario,
                             ("supplier b", "sup b")),
        ScenarioRegistration("component_certification_missing", "comp_a", ClaimType.CERTIFICATION_STATUS,
                             "Whether Component A has QA certification evidence.", missing_evidence_scenario,
                             ("component a", "comp a")),
        ScenarioRegistration("multi_investigation_screening", "inc_delay_001", ClaimType.DELAY_SIGNAL_SCREENING,
                             "Screen supplier and internal signals for a production delay.", multi_investigation_scenario,
                             ("screen", "signal", "which source")),
    ])
