from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import initial_belief
from sentinel_pomdp.decision import (
    DecisionType,
    select_decision,
)
from sentinel_pomdp.information import expected_information_gain
from sentinel_pomdp.reward import (
    DEFAULT_REWARD_CONFIG,
    answer_utility,
    investigation_utility,
)
from sentinel_pomdp.states import SecurityState


def test_initial_decision_is_investigation():
    belief = initial_belief()

    decision = select_decision(
        belief,
        list(InvestigationAction),
    )

    assert decision.kind == DecisionType.INVESTIGATE


def test_initial_decision_is_network_investigation():
    belief = initial_belief()

    decision = select_decision(
        belief,
        list(InvestigationAction),
    )

    assert (
        decision.action
        == InvestigationAction.INSPECT_NETWORK
    )


def test_high_confidence_belief_answers():
    belief = {
        SecurityState.BENIGN: 0.01,
        SecurityState.CREDENTIAL_COMPROMISE: 0.02,
        SecurityState.MALWARE_COMPROMISE: 0.92,
        SecurityState.LATERAL_MOVEMENT: 0.03,
        SecurityState.DATA_EXFILTRATION: 0.02,
    }

    decision = select_decision(
        belief,
        list(InvestigationAction),
    )

    assert decision.kind == DecisionType.ANSWER

    assert (
        decision.hypothesis
        == SecurityState.MALWARE_COMPROMISE
    )


def test_uncertain_belief_with_no_actions_abstains():
    belief = initial_belief()

    decision = select_decision(
        belief,
        [],
    )

    assert decision.kind == DecisionType.ABSTAIN


def test_answer_utility_improves_with_confidence():
    lower_confidence = {
        SecurityState.BENIGN: 0.10,
        SecurityState.CREDENTIAL_COMPROMISE: 0.05,
        SecurityState.MALWARE_COMPROMISE: 0.75,
        SecurityState.LATERAL_MOVEMENT: 0.05,
        SecurityState.DATA_EXFILTRATION: 0.05,
    }

    higher_confidence = {
        SecurityState.BENIGN: 0.02,
        SecurityState.CREDENTIAL_COMPROMISE: 0.02,
        SecurityState.MALWARE_COMPROMISE: 0.92,
        SecurityState.LATERAL_MOVEMENT: 0.02,
        SecurityState.DATA_EXFILTRATION: 0.02,
    }

    _, low_utility = answer_utility(
        lower_confidence
    )

    _, high_utility = answer_utility(
        higher_confidence
    )

    assert high_utility > low_utility


def test_costs_reduce_investigation_utility():
    belief = initial_belief()

    information_gain = expected_information_gain(
        belief,
        InvestigationAction.INSPECT_NETWORK,
    )

    utility = investigation_utility(
        belief,
        InvestigationAction.INSPECT_NETWORK,
    )

    assert utility < information_gain

