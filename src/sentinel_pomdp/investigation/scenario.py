"""Domain configuration and illustrative likelihoods for supplier investigations."""
from __future__ import annotations

from dataclasses import dataclass

from sentinel_pomdp.multistep import MultiStepPlanner, PlanningConfig

from .evidence_policy import EvidencePolicy
from .schemas import GraphInvestigationRequest, InvestigationAction, ObservationToken


@dataclass(frozen=True)
class InvestigationScenario:
    name: str
    prior: dict[str, float]
    requests: dict[str, GraphInvestigationRequest]
    action_targets: dict[str, str]
    evidence_policy: EvidencePolicy
    answer_threshold: float = 0.72
    scenario_id: str = ""
    observation_model: dict | None = None
    action_costs: dict[str, float] | None = None
    model_version: str = "illustrative-v1"
    planning_config: PlanningConfig | None = None


def illustrative_observation_model(states: list[str], action_targets: dict[str, str]) -> dict:
    """Hand-designed normalized assumptions, not empirically calibrated probabilities."""
    model = {}
    for action, target in action_targets.items():
        model[action] = {}
        for state in states:
            if state == target:
                row = (.77, .08, .03, .10, .01, .01)
            else:
                row = (.12, .10, .24, .52, .01, .01)
            model[action][state] = dict(zip((
                ObservationToken.SUPPORTED.value,
                ObservationToken.CONFLICTED.value,
                ObservationToken.CONTRADICTED.value,
                ObservationToken.NOT_FOUND.value,
                ObservationToken.DUPLICATE.value,
                ObservationToken.HASH_MISMATCH.value,
            ), row))
    return model


def build_scenario_planner(scenario: InvestigationScenario, horizon: int = 2) -> MultiStepPlanner:
    states = list(scenario.prior)

    def predicted_support(hypothesis: str, history: tuple[tuple[str, str], ...]) -> bool:
        return any(scenario.action_targets.get(action) == hypothesis and
                   observation == ObservationToken.SUPPORTED.value for action, observation in history)

    return MultiStepPlanner(
        states=states,
        observation_model=(scenario.observation_model or
                           illustrative_observation_model(states, scenario.action_targets)),
        action_costs=(scenario.action_costs or {action: {
            InvestigationAction.FACT_EVIDENCE: .08,
            InvestigationAction.ENTITY_RELATIONSHIPS: .12,
            InvestigationAction.COMPETING_CLAIMS: .15,
        }[request.action_name] for action, request in scenario.requests.items()}),
        config=scenario.planning_config or PlanningConfig(horizon=horizon, gamma=.95, correct_answer_reward=5,
                              incorrect_answer_penalty=7, abstain_reward=0,
                              answer_threshold=scenario.answer_threshold, min_observations=1,
                              information_gain_weight=.15),
        support_predicate=predicted_support,
    )


def supplier_delay_scenario(tenant_id: str = "tenant_alpha") -> InvestigationScenario:
    hypotheses = ["supplier_a", "internal_scheduling", "supplier_b"]
    requests = {
        "inspect_supplier_a_attribution": GraphInvestigationRequest(
            tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
            target_id="fact_incident_attributed_sup_a"),
        "inspect_internal_attribution": GraphInvestigationRequest(
            tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
            target_id="fact_incident_attributed_internal"),
        "inspect_supplier_b_delivery": GraphInvestigationRequest(
            tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
            target_id="fact_sup_b_delivered_ontime"),
    }
    return InvestigationScenario(
        name="supplier production-delay attribution",
        prior={"supplier_a": .45, "internal_scheduling": .30, "supplier_b": .25},
        requests=requests,
        action_targets={
            "inspect_supplier_a_attribution": "supplier_a",
            "inspect_internal_attribution": "internal_scheduling",
            "inspect_supplier_b_delivery": "supplier_b",
        },
        evidence_policy=EvidencePolicy(required_fact_ids={
            "supplier_a": {"fact_incident_attributed_sup_a"},
            "internal_scheduling": {"fact_incident_attributed_internal"},
            # Delivery timing is not itself a causal incident-attribution fact.
            "supplier_b": {"fact_incident_attributed_sup_b"},
        }, required_evidence_ids={
            # The current warehouse record proves lateness, not incident causation.
            # A future causal source must be registered explicitly before answering.
            "supplier_a": {"ev_causal_incident_analysis"},
        }),
        scenario_id="supplier_delay_causal_attribution",
    )


def supplier_shipment_delay_scenario(tenant_id: str = "tenant_alpha") -> InvestigationScenario:
    """Narrow factual question that the current receiving records can support."""
    return InvestigationScenario(
        name="Supplier A shipment-delay verification",
        prior={"shipment_delayed": .55, "shipment_on_time": .45},
        requests={"inspect_supplier_a_delivery": GraphInvestigationRequest(
            tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
            target_id="fact_sup_a_caused_delay")},
        action_targets={"inspect_supplier_a_delivery": "shipment_delayed"},
        evidence_policy=EvidencePolicy(required_fact_ids={
            "shipment_delayed": {"fact_sup_a_caused_delay"},
            "shipment_on_time": {"fact_sup_a_caused_delay"},
        }, minimum_distinct_documents=2),
        answer_threshold=.70,
        scenario_id="supplier_a_shipment_delay",
    )


def multi_investigation_scenario(tenant_id: str = "tenant_alpha") -> InvestigationScenario:
    """Two-action screening fixture whose real graph outcomes require two cycles."""
    return InvestigationScenario(
        name="multi-source production-delay screening",
        prior={"supplier_signal": .55, "internal_signal": .45},
        requests={
            "inspect_supplier_signal": GraphInvestigationRequest(
                tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
                target_id="fact_incident_attributed_sup_a"),
            "inspect_internal_signal": GraphInvestigationRequest(
                tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
                target_id="fact_incident_attributed_internal"),
        },
        action_targets={
            "inspect_supplier_signal": "supplier_signal",
            "inspect_internal_signal": "internal_signal",
        },
        evidence_policy=EvidencePolicy(required_fact_ids={
            "supplier_signal": {"fact_incident_attributed_sup_a"},
            "internal_signal": {"fact_incident_attributed_internal"},
        }),
        answer_threshold=.90,
        scenario_id="multi_investigation_screening",
    )


def conflicting_delivery_scenario(tenant_id: str = "tenant_alpha") -> InvestigationScenario:
    return InvestigationScenario(
        name="conflicting Supplier B delivery claim",
        prior={"supplier_b_on_time": .90, "supplier_b_not_on_time": .10},
        requests={"inspect_supplier_b_delivery": GraphInvestigationRequest(
            tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
            target_id="fact_sup_b_delivered_ontime")},
        action_targets={"inspect_supplier_b_delivery": "supplier_b_on_time"},
        evidence_policy=EvidencePolicy(required_fact_ids={
            "supplier_b_on_time": {"fact_sup_b_delivered_ontime"},
            "supplier_b_not_on_time": {"fact_sup_b_delivered_ontime"},
        }),
        answer_threshold=.70,
        scenario_id="supplier_b_conflicting_delivery",
    )


def missing_evidence_scenario(tenant_id: str = "tenant_alpha") -> InvestigationScenario:
    return InvestigationScenario(
        name="missing component certification evidence",
        prior={"certified": .70, "not_certified": .30},
        requests={"inspect_certification": GraphInvestigationRequest(
            tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
            target_id="fact_comp_a_qa_certified")},
        action_targets={"inspect_certification": "certified"},
        evidence_policy=EvidencePolicy(required_fact_ids={
            "certified": {"fact_comp_a_qa_certified"},
            "not_certified": {"fact_comp_a_qa_certified"},
        }),
        answer_threshold=.70,
        scenario_id="component_certification_missing",
    )
