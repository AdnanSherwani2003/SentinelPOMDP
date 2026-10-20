"""Run with `uv run python scripts/demo_multistep.py` after applying patch."""
from sentinel_pomdp.multistep import MultiStepPlanner, PlanningConfig

states = ["supplier_A", "supplier_B", "internal_delay"]
prior = {"supplier_A": .40, "supplier_B": .35, "internal_delay": .25}
observations = {
    "delivery_records": {
        "supplier_A": {"late": .891, "on_time": .109},
        "supplier_B": {"late": .306, "on_time": .694},
        "internal_delay": {"late": .167, "on_time": .833},
    },
    "ticket_summary": {
        "supplier_A": {"delayed": .348, "normal": .652},
        "supplier_B": {"delayed": .408, "normal": .592},
        "internal_delay": {"delayed": .194, "normal": .806},
    },
    "production_schedule": {
        "supplier_A": {"blocked": .070, "clear": .930},
        "supplier_B": {"blocked": .966, "clear": .034},
        "internal_delay": {"blocked": .757, "clear": .243},
    },
}
planner = MultiStepPlanner(
    states, observations,
    {"delivery_records": .028, "ticket_summary": .048, "production_schedule": .144},
    PlanningConfig(horizon=2, gamma=.96, correct_answer_reward=5,
                   incorrect_answer_penalty=5, answer_threshold=.75),
)

print("Illustrative synthetic probabilities; not real supplier records.\n")
for horizon in (1, 2):
    d = planner.decide(prior, horizon=horizon)
    print(f"Horizon {horizon}: {d.kind} {d.action or d.hypothesis or ''}")
    print(f"    expected utility = {d.expected_utility:.4f}")
    print(f"    action scores = {dict(d.action_scores)}")

# Demonstrates one ACTUAL observation arriving from a hypothetical tool.
first = planner.decide(prior, horizon=2)
assert first.action is not None
observed_result = "late" if first.action == "delivery_records" else "normal"
posterior = planner.posterior(prior, first.action, observed_result)
second = planner.decide(posterior, history=((first.action, observed_result),), horizon=1)
print(f"\nObserved {first.action}={observed_result}")
print(f"Posterior: {posterior}")
print(f"Next decision: {second.kind} {second.action or second.hypothesis or ''}")
