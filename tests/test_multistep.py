"""Implementation 6 regression tests; independent of the episode environment."""

from __future__ import annotations

import pytest

from sentinel_pomdp.multistep import (
    ImpossibleObservation,
    MultiStepPlanner,
    PlanningConfig,
)


PRIOR = {"A": 0.40, "B": 0.35, "C": 0.25}

# Deliberately chosen three-hypothesis experiment: myopic action choice
# differs from the two-action lookahead choice under the same costs/rewards.
OBSERVATION_MODEL = {
    "first": {
        "A": {"positive": .891, "negative": .109},
        "B": {"positive": .306, "negative": .694},
        "C": {"positive": .167, "negative": .833},
    },
    "second": {
        "A": {"positive": .348, "negative": .652},
        "B": {"positive": .408, "negative": .592},
        "C": {"positive": .194, "negative": .806},
    },
    "third": {
        "A": {"positive": .070, "negative": .930},
        "B": {"positive": .966, "negative": .034},
        "C": {"positive": .757, "negative": .243},
    },
}


def build_planner(**overrides):
    options = dict(gamma=.96, correct_answer_reward=5,
                   incorrect_answer_penalty=5, answer_threshold=.75,
                   min_observations=1, horizon=2)
    options.update(overrides)
    return MultiStepPlanner(
        states=["A", "B", "C"],
        observation_model=OBSERVATION_MODEL,
        action_costs={"first": .028, "second": .048, "third": .144},
        config=PlanningConfig(**options),
    )


def test_two_step_planning_changes_the_optimal_first_action():
    planner = build_planner()
    greedy = planner.decide(PRIOR, horizon=1)
    lookahead = planner.decide(PRIOR, horizon=2)
    assert greedy.kind == lookahead.kind == "INVESTIGATE"
    assert greedy.action == "third"
    assert lookahead.action == "first"
    assert lookahead.expected_utility > greedy.expected_utility
    assert len(lookahead.action_scores) == 3


def test_horizon_zero_must_abstain_without_evidence():
    decision = build_planner().decide(PRIOR, horizon=0)
    assert decision.kind == "ABSTAIN"
    assert decision.action is None
    assert decision.hypothesis is None


def test_real_observation_updates_belief_by_bayes():
    planner = build_planner()
    posterior = planner.posterior(PRIOR, "first", "positive")
    assert sum(posterior.values()) == pytest.approx(1)
    assert posterior["A"] > PRIOR["A"]
    prob = planner.outcome_probability(PRIOR, "first", "positive")
    assert posterior["A"] == pytest.approx(PRIOR["A"] * .891 / prob)


def test_action_is_not_repeated_after_observation():
    planner = build_planner()
    b = planner.posterior(PRIOR, "first", "negative")
    chosen = planner.decide(b, history=(("first", "negative"),), horizon=2)
    assert "first" not in dict(chosen.action_scores)
    assert chosen.action != "first"


def test_answer_allowed_after_strong_evidence():
    planner = MultiStepPlanner(
        ["A", "B"],
        {"check": {"A": {"yes": .99, "no": .01},
                   "B": {"yes": .01, "no": .99}}},
        {"check": .01},
        PlanningConfig(answer_threshold=.9, min_observations=1),
    )
    posterior = planner.posterior({"A": .5, "B": .5}, "check", "yes")
    decision = planner.decide(posterior, history=(("check", "yes"),))
    assert decision.kind == "ANSWER"
    assert decision.hypothesis == "A"


def test_policy_can_veto_answer_even_with_high_probability():
    planner = MultiStepPlanner(
        ["A", "B"],
        {"check": {"A": {"yes": 1.0}, "B": {"yes": 1.0}}},
        {"check": .01},
        PlanningConfig(answer_threshold=.9, min_observations=1),
        support_predicate=lambda history: False,
    )
    result = planner.decide({"A": .99, "B": .01}, history=(("check", "yes"),))
    assert result.kind == "ABSTAIN"


def test_high_tool_cost_makes_abstention_optimal():
    planner = MultiStepPlanner(
        ["A", "B"],
        {"expensive": {"A": {"yes": 1.0, "no": 0.0},
                       "B": {"yes": 0.0, "no": 1.0}}},
        {"expensive": 100.0},
    )
    result = planner.decide({"A": .5, "B": .5})
    assert result.kind == "ABSTAIN"


def test_impossible_observation_explicitly_rejected():
    planner = MultiStepPlanner(
        ["A", "B"],
        {"check": {"A": {"yes": 1.0, "no": 0.0},
                   "B": {"yes": 1.0, "no": 0.0}}},
        {"check": .01},
    )
    with pytest.raises(ImpossibleObservation):
        planner.posterior({"A": .5, "B": .5}, "check", "no")


def test_invalid_observation_matrix_rejected():
    with pytest.raises(ValueError, match="sum to 1"):
        MultiStepPlanner(["A"], {"check": {"A": {"yes": .8}}}, {"check": .1})


def test_invalid_belief_rejected():
    with pytest.raises(ValueError, match="sum to 1"):
        build_planner().decide({"A": .9, "B": .9, "C": .1})


def test_duplicate_actions_in_history_rejected():
    with pytest.raises(ValueError, match="at most once"):
        build_planner().decide(PRIOR, history=(("first", "positive"), ("first", "negative")))


def test_order_of_dict_keys_cannot_change_selection():
    original = build_planner().decide(PRIOR)
    reversed_model = dict(reversed(list(OBSERVATION_MODEL.items())))
    other = MultiStepPlanner(["C", "A", "B"], reversed_model,
                             {"third": .144, "first": .028, "second": .048},
                             build_planner().config)
    changed = other.decide({"C": .25, "B": .35, "A": .40})
    assert (original.kind, original.action) == (changed.kind, changed.action)
    assert original.expected_utility == pytest.approx(changed.expected_utility)


def test_predictive_observation_distribution_sums_to_one():
    planner = build_planner()
    for action in planner.actions:
        assert sum(planner.outcome_probability(PRIOR, action, o) for o in planner.outcomes[action]) == pytest.approx(1)
