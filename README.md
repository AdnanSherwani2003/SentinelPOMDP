# Sentinel POMDP (`sentinel-pomdp`)

A modular Python library for Partially Observable Markov Decision Process (POMDP) modeling, state estimation, and exact Bayesian belief updating tailored for sentinel surveillance and target tracking domains.

---

## 📁 Repository Architecture

```
sentinel-pomdp/
│
├── src/
│   └── sentinel_pomdp/
│       ├── __init__.py          # Package exports and public API
│       ├── states.py            # State abstractions & GridState dataclass
│       ├── actions.py           # Action enums & movement deltas
│       ├── observations.py      # Sensory observations & detection models
│       ├── model.py             # POMDPModel base & SentinelPOMDP environment
│       └── belief.py            # BeliefDistribution & Bayesian update engine
│
├── tests/
│   └── test_belief.py           # Pytest suite for belief updates & math checks
│
├── scripts/
│   └── demo_belief_update.py    # Interactive demo with ASCII heatmap visualization
│
├── README.md                    # Project documentation
└── requirements.txt             # Python dependencies
```

---

## 🎯 POMDP Formulation Overview

In a Partially Observable Markov Decision Process (POMDP), the agent cannot directly observe the true world state $s \in S$. Instead, it maintains a **belief distribution** $b(s) = P(s_t = s \mid h_t)$ over all possible states given history $h_t$.

### Exact Bayesian Belief Update Formula

When the sentinel executes action $a$ and receives observation $o$, the updated belief distribution $b'(s')$ for state $s'$ is calculated via Bayes' filter:

$$b'(s') = \frac{O(o \mid s', a) \sum_{s \in S} T(s' \mid s, a) \, b(s)}{\sum_{s'' \in S} O(o \mid s'', a) \sum_{s \in S} T(s'' \mid s, a) \, b(s)}$$

Where:
- $T(s' \mid s, a) = P(s_{t+1} = s' \mid s_t = s, a_t = a)$ is the **state transition model**.
- $O(o \mid s', a) = P(o_{t+1} = o \mid s_{t+1} = s', a_t = a)$ is the **observation model**.
- The denominator is the normalization factor $P(o \mid b, a)$.

---

## ⚡ Quickstart & Installation

### Requirements
- Python 3.9+
- NumPy >= 1.20.0
- pytest >= 7.0.0

### Installation

```bash
git clone https://github.com/your-username/sentinel-pomdp.git
cd sentinel-pomdp

# Install dependencies
pip install -r requirements.txt
```

---

## 🚀 Running the Demo

To run the interactive belief update demo with target location heatmap visualization:

```bash
python scripts/demo_belief_update.py
```

### Sample Output Visualization

```text
=============================================
 Target Location Belief Heatmap (Sentinel at (1, 1))
=============================================
     x=0    x=1    x=2    x=3  
   +------+------+------+------+
y=3 | 0.2%| 1.4%| 84.5%| 1.1%|
   +------+------+------+------+
y=2 | 0.1%| 0.8%| 8.2%| 0.9%|
   +------+------+------+------+
y=1 | 0.0%| S:0.3%| 1.2%| 0.2%|
   +------+------+------+------+
y=0 | 0.0%| 0.1%| 0.8%| 0.2%|
   +------+------+------+------+
```

---

## 🧪 Running Unit Tests

Run the full pytest suite:

```bash
pytest tests/
```

---

## 💻 Python Usage Example

```python
from sentinel_pomdp import (
    SentinelPOMDP,
    SentinelAction,
    SentinelObservation,
    BeliefDistribution,
)

# 1. Initialize 5x5 Sentinel POMDP environment
model = SentinelPOMDP(grid_width=5, grid_height=5)

# 2. Set up initial uniform belief distribution
states = model.get_states()
belief = BeliefDistribution.uniform(states)
print(f"Initial Entropy: {belief.entropy():.3f} bits")

# 3. Sentinel takes a SCAN action and gets observation
action = SentinelAction.SCAN
observation = SentinelObservation(
    target_detected=True,
    observed_pos=(2, 3),
    signal_quality=0.9
)

# 4. Perform Bayesian belief update
updated_belief = belief.update(model, action, observation)

# 5. Retrieve most likely target state
most_likely, probability = updated_belief.most_likely_state()
print(f"Most likely state: {most_likely}")
print(f"Probability: {probability * 100:.2f}%")
print(f"New Entropy: {updated_belief.entropy():.3f} bits")
```

---

## 📄 License

MIT License. Free for research, education, and commercial use.
