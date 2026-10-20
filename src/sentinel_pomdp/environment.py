import random

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import initial_belief
from sentinel_pomdp.model import OBSERVATION_MODEL
from sentinel_pomdp.observations import Observation
from sentinel_pomdp.states import SecurityState


class SecurityInvestigationEnv:
    """
    Synthetic security investigation environment.

    The environment knows the true incident state.
    The agent must infer it from observations.
    """

    def __init__(
        self,
        true_state: SecurityState | None = None,
        seed: int | None = None,
        observation_model: dict | None = None,
        initial_belief_state: dict | None = None,
    ) -> None:
        self.rng = random.Random(seed)
        self.observation_model = (
            OBSERVATION_MODEL if observation_model is None else observation_model
        )
        self.initial_belief_state = initial_belief_state

        if true_state is None:
            self.true_state = self._sample_initial_state()
        else:
            self.true_state = true_state

    def _sample_initial_state(self) -> SecurityState:
        belief = self.initial_belief_state or initial_belief()

        states = list(belief.keys())
        probabilities = list(belief.values())

        return self.rng.choices(
            states,
            weights=probabilities,
            k=1,
        )[0]

    def observe(
        self,
        action: InvestigationAction,
    ) -> Observation:
        distribution = self.observation_model[
            action
        ][self.true_state]

        observations = list(distribution.keys())
        probabilities = list(distribution.values())

        return self.rng.choices(
            observations,
            weights=probabilities,
            k=1,
        )[0]
