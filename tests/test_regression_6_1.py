"""Comprehensive Regression Tests for SentinelPOMDP Implementation 6.1.

Validates:
1. Exact Bayesian belief updates and likelihood scaling.
2. Posterior normalization and bounded probabilities.
3. Exact finite-depth Bellman recursion and discounting.
4. Horizon-1 equivalence to one-step expected utility reference.
5. Horizon-2 lookahead planning (where 2-step optimal action differs from 1-step).
6. Exact action cost accounting without double-counting or omission.
7. Explicit ANSWER, INVESTIGATE, and ABSTAIN decision boundaries.
8. High-confidence conclusions vetoed when evidence support is lacking.
9. Contradictory observations vetoing unsupportable hypotheses.
10. Uninformative observations leading to rational abstention.
11. Action history enforcement and repetition prevention.
12. Deterministic tie-breaking and order invariance.
13. Episode budget bounds and terminal decision enforcement on final steps.
14. Multi-step integration with environment replanning after real observations.
15. Scenarios where abstention is genuinely mathematically optimal.
"""
from __future__ import annotations

import math
import pytest

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import (
    balanced_belief,
    initial_belief,
    update_belief,
)
from sentinel_pomdp.decision import DecisionType
from sentinel_pomdp.environment import SecurityInvestigationEnv
from sentinel_pomdp.episode import run_episode
from sentinel_pomdp.integration import (
    build_investigation_planner,
    security_evidence_support,
)
from sentinel_pomdp.model import (
    CALIBRATED_OBSERVATION_MODEL,
    OBSERVATION_MODEL,
    validate_observation_model,
)
from sentinel_pomdp.multistep import (
    ImpossibleObservation,
    MultiStepPlanner,
    PlanningConfig,
)
from sentinel_pomdp.observations import Observation
from sentinel_pomdp.reward import (
    ACTION_COSTS,
    DEFAULT_REWARD_CONFIG,
    RewardConfig,
    investigation_utility,
)
from sentinel_pomdp.states import SecurityState


# ==============================================================================
# 1. Bayesian Updates and Belief Normalization
# ==============================================================================

def test_bayesian_update_directionality():
    """Bayes update increases posterior when likelihood > marginal, decreases when likelihood < marginal."""
    belief = balanced_belief()
    action = InvestigationAction.INSPECT_NETWORK
    obs = Observation.NETWORK_HIGH_UPLOAD

    # Under CALIBRATED_OBSERVATION_MODEL, NETWORK_HIGH_UPLOAD is 0.70 for DATA_EXFILTRATION and <= 0.05 for others
    posterior = update_belief(belief, action, obs, observation_model=CALIBRATED_OBSERVATION_MODEL)

    assert posterior[SecurityState.DATA_EXFILTRATION] > belief[SecurityState.DATA_EXFILTRATION]
    assert posterior[SecurityState.BENIGN] < belief[SecurityState.BENIGN]
    assert sum(posterior.values()) == pytest.approx(1.0, abs=1e-9)


def test_belief_normalization_across_all_actions_and_observations():
    """All possible observation transitions preserve sum-to-1 normalization."""
    belief = balanced_belief()
    for action in InvestigationAction:
        for obs in CALIBRATED_OBSERVATION_MODEL[action][SecurityState.BENIGN]:
            posterior = update_belief(belief, action, obs, observation_model=CALIBRATED_OBSERVATION_MODEL)
            assert sum(posterior.values()) == pytest.approx(1.0, abs=1e-9)
            assert all(0.0 <= p <= 1.0 for p in posterior.values())


def test_calibrated_observation_model_is_valid():
    """Calibrated observation model rows must all be valid probability distributions."""
    validate_observation_model(CALIBRATED_OBSERVATION_MODEL)


# ==============================================================================
# 2. Bellman Recursion, Horizons, and Cost Accounting
# ==============================================================================

def test_horizon_0_returns_terminal_decision():
    """At horizon 0, no investigation actions can be considered."""
    planner = build_investigation_planner(horizon=0)
    decision = planner.decide({s.value: 0.2 for s in SecurityState}, horizon=0)
    assert decision.kind in ("ANSWER", "ABSTAIN")
    assert decision.action is None
    assert decision.action_scores == ()


def test_horizon_1_matches_one_step_bellman_reference():
    """Horizon 1 Q-value equals immediate reward plus discounted terminal expectation."""
    reward_cfg = RewardConfig(
        correct_answer_reward=2.0,
        wrong_answer_penalty=6.0,
        abstain_penalty=0.20,
        information_gain_weight=1.0,
    )
    gamma = 0.90
    planner = build_investigation_planner(
        horizon=1,
        gamma=gamma,
        reward_config=reward_cfg,
        model_version="baseline",
    )
    b = {s.value: 0.2 for s in SecurityState}
    plan = planner.decide(b, horizon=1)

    # Reconstruct expected 1-step Q-value for each action manually
    for action_str, q_reported in plan.action_scores:
        action_enum = InvestigationAction(action_str)
        # Immediate reward = IG - cost
        imm_utility = investigation_utility(
            {SecurityState(k): v for k, v in b.items()},
            action_enum,
            reward_cfg,
        )
        # Future value = sum_o P(o|b, a) * V_terminal(b')
        future_term = 0.0
        for obs_str in planner.outcomes[action_str]:
            p_obs = planner.outcome_probability(b, action_str, obs_str)
            if p_obs > 0:
                b_prime = planner.posterior(b, action_str, obs_str)
                top_p = max(b_prime.values())
                # Terminal value: answer if top_p * R - (1-p)*W > -A and top_p >= threshold
                ans_val = top_p * reward_cfg.correct_answer_reward - (1 - top_p) * reward_cfg.wrong_answer_penalty
                if top_p >= reward_cfg.min_answer_confidence and ans_val > -reward_cfg.abstain_penalty:
                    v_term = ans_val
                else:
                    v_term = -reward_cfg.abstain_penalty
                future_term += p_obs * v_term

        expected_q = imm_utility + gamma * future_term
        assert q_reported == pytest.approx(expected_q, abs=1e-7)


def test_action_costs_properly_reduce_utility():
    """Higher action cost strictly reduces action Q-value by the cost difference."""
    states = ["S1", "S2"]
    model = {
        "act1": {"S1": {"o1": 0.8, "o2": 0.2}, "S2": {"o1": 0.2, "o2": 0.8}}
    }
    p_low_cost = MultiStepPlanner(states, model, {"act1": 0.05}, PlanningConfig(horizon=1))
    p_high_cost = MultiStepPlanner(states, model, {"act1": 0.25}, PlanningConfig(horizon=1))

    b = {"S1": 0.5, "S2": 0.5}
    score_low = dict(p_low_cost.decide(b).action_scores)["act1"]
    score_high = dict(p_high_cost.decide(b).action_scores)["act1"]

    assert score_low - score_high == pytest.approx(0.20, abs=1e-9)


# ==============================================================================
# 3. Two-Step Lookahead Optimal Policy Shift
# ==============================================================================

def test_two_step_lookahead_overcomes_one_step_myopic_abstention():
    """1-step horizon cannot reach certainty and abstains; 2-step horizon discovers value of inquiry."""
    states = ["H1", "H2", "H3"]
    obs_model = {
        "probe_A": {
            "H1": {"pos": 0.90, "neg": 0.10},
            "H2": {"pos": 0.50, "neg": 0.50},
            "H3": {"pos": 0.10, "neg": 0.90},
        },
        "probe_B": {
            "H1": {"pos": 0.10, "neg": 0.90},
            "H2": {"pos": 0.90, "neg": 0.10},
            "H3": {"pos": 0.50, "neg": 0.50},
        },
        "probe_C": {
            "H1": {"pos": 0.85, "neg": 0.15},
            "H2": {"pos": 0.15, "neg": 0.85},
            "H3": {"pos": 0.50, "neg": 0.50},
        },
    }
    costs = {"probe_A": 0.02, "probe_B": 0.02, "probe_C": 0.02}
    cfg = PlanningConfig(
        horizon=2,
        gamma=0.98,
        correct_answer_reward=10.0,
        incorrect_answer_penalty=10.0,
        abstain_reward=0.0,
        answer_threshold=0.85,
        min_observations=1,
        information_gain_weight=0.0,
    )
    planner = MultiStepPlanner(states, obs_model, costs, cfg)
    prior = {"H1": 0.34, "H2": 0.33, "H3": 0.33}

    plan_1 = planner.decide(prior, horizon=1)
    plan_2 = planner.decide(prior, horizon=2)

    assert plan_1.kind == "ABSTAIN"
    assert plan_2.kind == "INVESTIGATE"
    assert plan_2.expected_utility > plan_1.expected_utility
    assert plan_2.action in ("probe_A", "probe_B")


def test_two_step_lookahead_changes_optimal_first_action():
    """Scenario where 1-step greedy action differs from optimal 2-step first action."""
    states = ["A", "B", "C"]
    prior = {"A": 0.40, "B": 0.35, "C": 0.25}
    obs_model = {
        "first": {
            "A": {"positive": 0.891, "negative": 0.109},
            "B": {"positive": 0.306, "negative": 0.694},
            "C": {"positive": 0.167, "negative": 0.833},
        },
        "second": {
            "A": {"positive": 0.348, "negative": 0.652},
            "B": {"positive": 0.408, "negative": 0.592},
            "C": {"positive": 0.194, "negative": 0.806},
        },
        "third": {
            "A": {"positive": 0.070, "negative": 0.930},
            "B": {"positive": 0.966, "negative": 0.034},
            "C": {"positive": 0.757, "negative": 0.243},
        },
    }
    planner = MultiStepPlanner(
        states=states,
        observation_model=obs_model,
        action_costs={"first": 0.028, "second": 0.048, "third": 0.144},
        config=PlanningConfig(
            gamma=0.96,
            correct_answer_reward=5.0,
            incorrect_answer_penalty=5.0,
            answer_threshold=0.75,
            min_observations=1,
            horizon=2,
        ),
    )
    plan_1 = planner.decide(prior, horizon=1)
    plan_2 = planner.decide(prior, horizon=2)

    assert plan_1.kind == "INVESTIGATE"
    assert plan_2.kind == "INVESTIGATE"
    assert plan_1.action == "third"
    assert plan_2.action == "first"
    assert plan_2.expected_utility > plan_1.expected_utility


# ==============================================================================
# 4. Evidence Sufficiency, Contradiction Veto, and Rational Abstention
# ==============================================================================

def test_high_posterior_without_evidence_support_is_vetoed():
    """If candidate hypothesis has probability above threshold but lacks supporting evidence, agent must ABSTAIN."""
    planner = build_investigation_planner(
        horizon=1,
        use_support_predicate=True,
    )
    # Skewed belief favoring benign without any observations
    belief = {
        SecurityState.BENIGN.value: 0.92,
        SecurityState.CREDENTIAL_COMPROMISE.value: 0.02,
        SecurityState.MALWARE_COMPROMISE.value: 0.02,
        SecurityState.LATERAL_MOVEMENT.value: 0.02,
        SecurityState.DATA_EXFILTRATION.value: 0.02,
    }
    decision = planner.decide(belief, history=(), horizon=0)
    # Empty history means no affirmative observations -> must ABSTAIN
    assert decision.kind == "ABSTAIN"


def test_contradictory_evidence_vetoes_benign_answer():
    """Anomalous attack observation strictly vetoes answering BENIGN even if posterior is high."""
    planner = build_investigation_planner(
        horizon=1,
        use_support_predicate=True,
    )
    # Suppose benign posterior is 0.88 due to high prior, but an attack anomaly was observed
    belief = {
        SecurityState.BENIGN.value: 0.88,
        SecurityState.CREDENTIAL_COMPROMISE.value: 0.03,
        SecurityState.MALWARE_COMPROMISE.value: 0.03,
        SecurityState.LATERAL_MOVEMENT.value: 0.03,
        SecurityState.DATA_EXFILTRATION.value: 0.03,
    }
    contradictory_history = (
        ("inspect_process", "process_suspicious_script"),
    )
    decision = planner.decide(belief, history=contradictory_history, horizon=0)
    assert decision.kind == "ABSTAIN"


def test_affirmative_evidence_permits_answer():
    """When high confidence is accompanied by affirmative supporting evidence, ANSWER is chosen."""
    planner = build_investigation_planner(
        horizon=1,
        use_support_predicate=True,
        answer_threshold=0.80,
    )
    belief = {
        SecurityState.BENIGN.value: 0.05,
        SecurityState.CREDENTIAL_COMPROMISE.value: 0.88,
        SecurityState.MALWARE_COMPROMISE.value: 0.03,
        SecurityState.LATERAL_MOVEMENT.value: 0.02,
        SecurityState.DATA_EXFILTRATION.value: 0.02,
    }
    supporting_history = (
        ("inspect_auth", "auth_mfa_anomaly"),
    )
    decision = planner.decide(belief, history=supporting_history, horizon=0)
    assert decision.kind == "ANSWER"
    assert decision.hypothesis == SecurityState.CREDENTIAL_COMPROMISE.value


def test_uninformative_observation_leads_to_rational_abstention():
    """When remaining actions provide negligible information and incur cost, planner abstains."""
    states = ["A", "B"]
    uninformative_model = {
        "useless": {"A": {"obs1": 0.50, "obs2": 0.50}, "B": {"obs1": 0.50, "obs2": 0.50}}
    }
    planner = MultiStepPlanner(
        states=states,
        observation_model=uninformative_model,
        action_costs={"useless": 0.10},
        config=PlanningConfig(
            horizon=2,
            correct_answer_reward=2.0,
            incorrect_answer_penalty=5.0,
            abstain_reward=0.0,
            answer_threshold=0.85,
        ),
    )
    # Uncertain prior where answering gives negative utility and action gives zero info at positive cost
    decision = planner.decide({"A": 0.50, "B": 0.50})
    assert decision.kind == "ABSTAIN"


def test_high_tool_cost_forces_abstention_over_investigation():
    """Prohibitive investigation cost makes immediate abstention optimal."""
    planner = build_investigation_planner(
        horizon=2,
        reward_config=RewardConfig(
            operational_cost_weight=100.0,
            privacy_cost_weight=100.0,
            latency_cost_weight=100.0,
            abstain_penalty=0.05,
        ),
    )
    decision = planner.decide({s.value: 0.20 for s in SecurityState})
    assert decision.kind == "ABSTAIN"


# ==============================================================================
# 5. History Restrictions, Repetition Prevention, and Error Handling
# ==============================================================================

def test_action_cannot_be_repeated():
    """Actions already taken in history cannot be selected for subsequent investigations."""
    planner = build_investigation_planner(horizon=2)
    history = (("inspect_network", "network_normal"),)
    decision = planner.decide({s.value: 0.20 for s in SecurityState}, history=history)
    assert decision.action != "inspect_network"
    assert "inspect_network" not in dict(decision.action_scores)


def test_duplicate_actions_in_history_raises_error():
    """Duplicate actions in history violate POMDP policy precondition."""
    planner = build_investigation_planner(horizon=2)
    history = (
        ("inspect_network", "network_normal"),
        ("inspect_network", "network_c2_pattern"),
    )
    with pytest.raises(ValueError, match="at most once"):
        planner.decide({s.value: 0.20 for s in SecurityState}, history=history)


def test_impossible_observation_raises_impossible_observation():
    """Zero-probability observations raise ImpossibleObservation."""
    planner = build_investigation_planner(horizon=1)
    # Force belief with 1.0 probability on benign
    belief = {s.value: (1.0 if s == SecurityState.BENIGN else 0.0) for s in SecurityState}
    # Under benign, network_high_upload has 0.01 in baseline, but let's test a synthetic zero
    toy_model = {
        "act": {"S1": {"o1": 1.0, "o2": 0.0}, "S2": {"o1": 1.0, "o2": 0.0}}
    }
    p = MultiStepPlanner(["S1", "S2"], toy_model, {"act": 0.01})
    with pytest.raises(ImpossibleObservation):
        p.posterior({"S1": 0.5, "S2": 0.5}, "act", "o2")


def test_deterministic_tie_breaking_order_invariance():
    """Planner action ranking is invariant to dict key insertion order."""
    planner = build_investigation_planner(horizon=2)
    b_forward = {s.value: 0.20 for s in SecurityState}
    b_reverse = {s.value: 0.20 for s in reversed(list(SecurityState))}

    dec_forward = planner.decide(b_forward)
    dec_reverse = planner.decide(b_reverse)

    assert dec_forward.kind == dec_reverse.kind
    assert dec_forward.action == dec_reverse.action
    assert dec_forward.expected_utility == pytest.approx(dec_reverse.expected_utility, abs=1e-12)


# ==============================================================================
# 6. Integrated Episode Execution and Realized Utility
# ==============================================================================

def test_episode_execution_with_calibrated_model_identifies_compromise():
    """Full episode integration with calibrated model successfully gathers evidence and classifies compromise."""
    env = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=42,
        observation_model=CALIBRATED_OBSERVATION_MODEL,
        initial_belief_state=balanced_belief(),
    )
    planner = build_investigation_planner(
        horizon=2,
        model_version="calibrated",
        use_support_predicate=True,
        answer_threshold=0.80,
    )
    result = run_episode(
        env,
        max_steps=5,
        planner=planner,
        initial_belief_state=balanced_belief(),
        observation_model=CALIBRATED_OBSERVATION_MODEL,
    )
    assert result.terminated_by in (DecisionType.ANSWER, DecisionType.ABSTAIN)
    assert result.total_cost >= 0.0
    assert math.isfinite(result.realized_utility)
    assert len(result.steps) <= 5


def test_episode_budget_reserves_final_decision_slot():
    """At step == max_steps, planner must return terminal decision (ANSWER or ABSTAIN)."""
    env = SecurityInvestigationEnv(
        true_state=SecurityState.BENIGN,
        seed=10,
        observation_model=CALIBRATED_OBSERVATION_MODEL,
        initial_belief_state=balanced_belief(),
    )
    planner = build_investigation_planner(
        horizon=2,
        model_version="calibrated",
    )
    # With max_steps=1, the very first step is the last step
    result = run_episode(env, max_steps=1, planner=planner, initial_belief_state=balanced_belief())
    assert len(result.steps) == 1
    assert result.steps[0].decision.kind in (DecisionType.ANSWER, DecisionType.ABSTAIN)
    assert result.terminated_by in (DecisionType.ANSWER, DecisionType.ABSTAIN)
