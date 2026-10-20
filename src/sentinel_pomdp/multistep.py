"""Finite-horizon, exact belief-space lookahead for a small static-state POMDP.

Independent of LLMs, LangGraph, or the simulation environment's hidden truth.
This module is deliberately additive: it does not replace the existing planner,
reward, decision, or episode modules.

Assumptions:
* The latent hypothesis stays fixed during evidence gathering (identity T).
* Observation likelihoods are specified for each action and hidden state.
* Given the hidden state, observations of DISTINCT tools are conditionally
  independent. Each tool can be called at most once per episode.
* The finite horizon counts future evidence-gathering actions; final ANSWER or
  ABSTAIN is available at every depth, including depth zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite, log2
from typing import Callable, Mapping, Sequence


EvidenceHistory = tuple[tuple[str, str], ...]
SupportPredicate = Callable[[EvidenceHistory], bool]


@dataclass(frozen=True)
class PlanningConfig:
    """All decision parameters are explicit and should be logged with runs."""

    horizon: int = 2
    gamma: float = 0.95
    correct_answer_reward: float = 4.0
    incorrect_answer_penalty: float = 8.0
    abstain_reward: float = 0.0
    answer_threshold: float = 0.85
    min_observations: int = 1
    information_gain_weight: float = 0.0  # Zero preserves the original patch's objective.

    def __post_init__(self) -> None:
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int) or self.horizon < 0:
            raise ValueError("horizon must be a nonnegative integer")
        if not (isfinite(self.gamma) and 0 < self.gamma <= 1):
            raise ValueError("gamma must be finite and in (0, 1]")
        if not (isfinite(self.answer_threshold) and 0 <= self.answer_threshold <= 1):
            raise ValueError("answer_threshold must be finite and in [0, 1]")
        if (isinstance(self.min_observations, bool) or
                not isinstance(self.min_observations, int) or self.min_observations < 0):
            raise ValueError("min_observations must be a nonnegative integer")
        for name in ("correct_answer_reward", "incorrect_answer_penalty", "abstain_reward", "information_gain_weight"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.information_gain_weight < 0:
            raise ValueError("information_gain_weight must be nonnegative")
        if self.incorrect_answer_penalty < 0:
            raise ValueError("incorrect_answer_penalty must be nonnegative")


@dataclass(frozen=True)
class PlanDecision:
    """Selected decision plus comparable utility scores for reproducible traces."""

    kind: str  # INVESTIGATE, ANSWER, or ABSTAIN
    action: str | None
    hypothesis: str | None
    expected_utility: float
    action_scores: tuple[tuple[str, float], ...]


class ImpossibleObservation(ValueError):
    """This outcome has zero predictive probability for the given belief."""


class MultiStepPlanner:
    """Exact finite-depth Bellman lookahead for enumerated evidence actions.

    observation_model[action][state][observation] = P(observation | state, action)
    Unknown observation labels are treated as having probability 0.

    `support_predicate` is an OPTIONAL deterministic policy for evidence support
    expressible from (tool, observed-result) histories. It is evaluated on
    *hypothetical* histories during planning: do not put network calls, LLMs,
    actual graph lookups, or external state changes inside it. A later, separate
    provenance verifier must still check real records before final synthesis.
    """

    def __init__(
        self,
        states: Sequence[str],
        observation_model: Mapping[str, Mapping[str, Mapping[str, float]]],
        action_costs: Mapping[str, float],
        config: PlanningConfig | None = None,
        support_predicate: SupportPredicate | None = None,
    ) -> None:
        self.config = config or PlanningConfig()
        self.states = tuple(sorted(states))
        if not self.states or any(not isinstance(s, str) or not s for s in self.states):
            raise ValueError("states must contain nonempty names")
        if len(set(self.states)) != len(self.states):
            raise ValueError("state names must be unique")
        if not observation_model:
            raise ValueError("At least one investigation action is required")
        self.actions = tuple(sorted(observation_model))
        if set(action_costs) != set(self.actions):
            raise ValueError("action_costs must specify exactly the modeled actions")
        self.costs = {}
        self.likelihoods: dict[str, dict[str, dict[str, float]]] = {}
        self.outcomes: dict[str, tuple[str, ...]] = {}
        for action in self.actions:
            cost = float(action_costs[action])
            if not isfinite(cost) or cost < 0:
                raise ValueError(f"Invalid cost for {action}")
            self.costs[action] = cost
            rows = observation_model[action]
            if set(rows) != set(self.states):
                raise ValueError(f"Observation model for {action} must cover all states")
            all_outcomes: set[str] = set()
            clean_rows = {}
            for state in self.states:
                row = rows[state]
                if not row:
                    raise ValueError(f"Empty observation row for {action}/{state}")
                if any(not isinstance(k, str) or not k for k in row):
                    raise ValueError("Observation names must be nonempty strings")
                converted = {o: float(p) for o, p in row.items()}
                if any(not isfinite(v) or v < 0 or v > 1 for v in converted.values()):
                    raise ValueError(f"Invalid observation probability for {action}/{state}")
                if abs(sum(converted.values()) - 1) > 1e-9:
                    raise ValueError(f"Probabilities for {action}/{state} must sum to 1")
                all_outcomes.update(converted)
                clean_rows[state] = converted
            self.likelihoods[action] = clean_rows
            self.outcomes[action] = tuple(sorted(all_outcomes))
        self.support_predicate = support_predicate

    def _belief_tuple(self, belief: Mapping[str, float]) -> tuple[float, ...]:
        if set(belief) != set(self.states):
            raise ValueError("Belief must specify exactly the modeled states")
        values = tuple(float(belief[s]) for s in self.states)
        if any(not isfinite(x) or x < 0 or x > 1 for x in values):
            raise ValueError("Belief probabilities must be finite and in [0, 1]")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("Belief must sum to 1")
        return values

    def outcome_probability(self, belief: Mapping[str, float], action: str, outcome: str) -> float:
        b = self._belief_tuple(belief)
        return self._outcome_probability(b, action, outcome)

    def _outcome_probability(self, b: tuple[float, ...], action: str, outcome: str) -> float:
        if action not in self.likelihoods:
            raise KeyError(action)
        return sum(b[i] * self.likelihoods[action][s].get(outcome, 0.0)
                   for i, s in enumerate(self.states))

    def _posterior(self, b: tuple[float, ...], action: str, outcome: str) -> tuple[float, ...]:
        mass = self._outcome_probability(b, action, outcome)
        if mass <= 0:
            raise ImpossibleObservation(f"Impossible observation {outcome!r} for {action!r}")
        return tuple(b[i] * self.likelihoods[action][s].get(outcome, 0.0) / mass
                     for i, s in enumerate(self.states))

    def posterior(self, belief: Mapping[str, float], action: str, outcome: str) -> dict[str, float]:
        updated = self._posterior(self._belief_tuple(belief), action, outcome)
        return dict(zip(self.states, updated))

    def _eval_support_predicate(self, hypothesis: str, evidence: EvidenceHistory) -> bool:
        if self.support_predicate is None:
            return True
        import inspect
        try:
            sig = inspect.signature(self.support_predicate)
            params = list(sig.parameters.values())
            if len(params) >= 2 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
                return bool(self.support_predicate(hypothesis, evidence))
            return bool(self.support_predicate(evidence))
        except (ValueError, TypeError):
            try:
                return bool(self.support_predicate(hypothesis, evidence))
            except TypeError:
                return bool(self.support_predicate(evidence))

    def decide(
        self,
        belief: Mapping[str, float],
        history: Sequence[tuple[str, str]] = (),
        horizon: int | None = None,
    ) -> PlanDecision:
        """Plan from current evidence, never from the environment's hidden state.

        Replan after every real observation using posterior(...) and an extended
        history. Do not feed simulated observations into the live episode trace.
        """
        b = self._belief_tuple(belief)
        path: EvidenceHistory = tuple(history)
        if any(a not in self.actions or o not in self.outcomes[a] for a, o in path):
            raise ValueError("History contains unknown action/observation")
        used = [a for a, _ in path]
        if len(used) != len(set(used)):
            raise ValueError("Each evidence action may be used at most once")
        remaining = tuple(a for a in self.actions if a not in used)
        depth = self.config.horizon if horizon is None else horizon
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise ValueError("horizon must be a nonnegative integer")
        depth = min(depth, len(remaining))
        cfg = self.config
        epsilon = 1e-12

        def terminal(belief_vector: tuple[float, ...], evidence: EvidenceHistory) -> tuple[str, str | None, float]:
            # Abstention always remains possible. Ties favor abstention.
            kind: str = "ABSTAIN"
            hypothesis = None
            utility = cfg.abstain_reward
            top_index = max(range(len(belief_vector)), key=lambda i: (belief_vector[i], -i))
            top_probability = belief_vector[top_index]
            if len(evidence) >= cfg.min_observations and top_probability + epsilon >= cfg.answer_threshold:
                candidate = self.states[top_index]
                supported = True
                if self.support_predicate is not None:
                    supported = self._eval_support_predicate(candidate, evidence)
                if supported:
                    answer_value = (top_probability * cfg.correct_answer_reward
                                    - (1 - top_probability) * cfg.incorrect_answer_penalty)
                    if answer_value > utility + epsilon:
                        kind = "ANSWER"
                        hypothesis = candidate
                        utility = answer_value
            return kind, hypothesis, utility

        @lru_cache(maxsize=None)
        def entropy(vector: tuple[float, ...]) -> float:
            return -sum(p * log2(p) for p in vector if p > 0.0)

        @lru_cache(maxsize=None)
        def best(
            belief_vector: tuple[float, ...],
            remaining_actions: tuple[str, ...],
            steps_left: int,
            evidence: EvidenceHistory,
        ) -> tuple[str, str | None, str | None, float]:
            kind, hypothesis, value = terminal(belief_vector, evidence)
            selected_action = None
            if steps_left:
                for action in remaining_actions:  # sorted deterministic tie break
                    score = q_value(belief_vector, remaining_actions, steps_left, evidence, action)
                    if score > value + epsilon:
                        kind, hypothesis, selected_action, value = "INVESTIGATE", None, action, score
            return kind, hypothesis, selected_action, value

        @lru_cache(maxsize=None)
        def q_value(
            belief_vector: tuple[float, ...],
            remaining_actions: tuple[str, ...],
            steps_left: int,
            evidence: EvidenceHistory,
            action: str,
        ) -> float:
            later_actions = tuple(x for x in remaining_actions if x != action)
            future_value = 0.0
            expected_post_entropy = 0.0
            for outcome in self.outcomes[action]:
                p = self._outcome_probability(belief_vector, action, outcome)
                if p <= 0:
                    continue  # Impossible observation: it cannot affect expected value
                posterior = self._posterior(belief_vector, action, outcome)
                _, _, _, value = best(posterior, later_actions, steps_left - 1,
                                      evidence + ((action, outcome),))
                future_value += p * value
                if cfg.information_gain_weight:
                    expected_post_entropy += p * entropy(posterior)
            gain = (entropy(belief_vector) - expected_post_entropy
                    if cfg.information_gain_weight else 0.0)
            return (cfg.information_gain_weight * max(0.0, gain)
                    - self.costs[action] + cfg.gamma * future_value)

        kind, hypothesis, action, utility = best(b, remaining, depth, path)
        scores = tuple((a, q_value(b, remaining, depth, path, a)) for a in remaining) if depth else ()
        return PlanDecision(kind=kind, action=action, hypothesis=hypothesis,
                            expected_utility=utility, action_scores=scores)
