"""Chronological, leakage-safe Olist prediction evaluation."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, asdict
from math import log
from statistics import mean
from sentinel_pomdp.multistep import MultiStepPlanner, PlanningConfig
from .dataset import OlistDataset, OlistOrder, Outcome, Snapshot

@dataclass(frozen=True)
class Split:
    train: tuple[OlistOrder,...]; validation: tuple[OlistOrder,...]; test: tuple[OlistOrder,...]

def chronological_split(orders: list[OlistOrder], train_fraction: float=.6, validation_fraction: float=.2) -> Split:
    eligible=sorted((o for o in orders if o.outcome in {Outcome.LATE,Outcome.ON_TIME}),key=lambda o:(o.purchase_at,o.order_id))
    if len(eligible)<10: raise ValueError("at least 10 eligible completed orders are required")
    a=int(len(eligible)*train_fraction); b=int(len(eligible)*(train_fraction+validation_fraction))
    return Split(tuple(eligible[:a]),tuple(eligible[a:b]),tuple(eligible[b:]))

def _bucket(order: OlistOrder, snapshot: Snapshot) -> str:
    if not order.estimated_at: return "missing"
    origin=order.purchase_at
    if snapshot is Snapshot.CARRIER_HANDOFF:
        if not order.carrier_at: return "missing"
        origin=order.carrier_at
    days=(order.estimated_at.date()-origin.date()).days
    return "short" if days<8 else "medium" if days<16 else "long"

def _fit(train: tuple[OlistOrder,...], snapshot: Snapshot) -> tuple[float,dict[str,float],dict[str,dict[str,int]]]:
    late=sum(o.outcome is Outcome.LATE for o in train); prior=(late+1)/(len(train)+2)
    counts={b:Counter() for b in ("short","medium","long","missing")}
    for o in train: counts[_bucket(o,snapshot)][o.outcome.value]+=1
    probs={b:(c[Outcome.LATE.value]+1)/(sum(c.values())+2) for b,c in counts.items()}
    return prior,probs,{b:dict(c) for b,c in counts.items()}

def _likelihoods(train: tuple[OlistOrder,...], snapshot: Snapshot) -> dict[str,dict[str,float]]:
    """P(observed margin bucket | eventual outcome), fitted on training only."""
    buckets=("short","medium","long","missing")
    result={}
    for state in (Outcome.LATE,Outcome.ON_TIME):
        cases=[o for o in train if o.outcome is state]
        counts=Counter(_bucket(o,snapshot) for o in cases)
        result[state.value]={bucket:(counts[bucket]+1)/(len(cases)+len(buckets)) for bucket in buckets}
    return result

def _posterior(prior: float, likelihoods: dict[str,dict[str,float]], bucket: str) -> float:
    late=prior*likelihoods[Outcome.LATE.value][bucket]
    on_time=(1-prior)*likelihoods[Outcome.ON_TIME.value][bucket]
    return late/(late+on_time)

def _metrics(rows: list[dict]) -> dict:
    if not rows: return {}
    brier=mean((r["probability_late"]-r["actual_late"])**2 for r in rows)
    logloss=-mean(r["actual_late"]*log(max(r["probability_late"],1e-12))+(1-r["actual_late"])*log(max(1-r["probability_late"],1e-12)) for r in rows)
    answered=[r for r in rows if r["decision"]!="ABSTAIN"]; correct=sum(r["correct"] for r in answered)
    return {"cases":len(rows),"coverage":len(answered)/len(rows),"selective_accuracy":correct/len(answered) if answered else None,
        "wrong_answer_rate":(len(answered)-correct)/len(rows),"abstention_rate":1-len(answered)/len(rows),
        "brier_score":brier,"log_loss":logloss}

def evaluate_olist(dataset: OlistDataset, *, snapshot: Snapshot=Snapshot.CARRIER_HANDOFF, limit: int|None=None) -> dict:
    if snapshot is Snapshot.DELIVERY_COMPLETED: raise ValueError("future outcome snapshot is forbidden for prediction")
    split=chronological_split(list(dataset.orders(limit)))
    prior,_,counts=_fit(split.train,snapshot)
    likelihoods=_likelihoods(split.train,snapshot)
    probs={bucket:_posterior(prior,likelihoods,bucket) for bucket in ("short","medium","long","missing")}
    thresholds=[.6,.7,.8,.9]
    def score(cases,threshold):
        rows=[]
        for o in cases:
            p=_posterior(prior,likelihoods,_bucket(o,snapshot)); prediction=1 if p>=.5 else 0
            decision="ANSWER" if max(p,1-p)>=threshold else "ABSTAIN"; actual=int(o.outcome is Outcome.LATE)
            rows.append({"order_ref":__import__("hashlib").sha256(o.order_id.encode()).hexdigest()[:12],"probability_late":p,"actual_late":actual,"decision":decision,
                         "correct":decision=="ANSWER" and prediction==actual,"snapshot":snapshot.value})
        return rows
    selected=max(thresholds,key=lambda t: ((_metrics(score(split.validation,t)).get("selective_accuracy") or 0),_metrics(score(split.validation,t))["coverage"]))
    test_rows=score(split.test,selected)
    prior_rows=[]
    for order in split.test:
        actual=int(order.outcome is Outcome.LATE)
        predicted=int(prior>=.5)
        prior_rows.append({"probability_late":prior,"actual_late":actual,"decision":"ANSWER",
                           "correct":predicted==actual})
    # The only historical observation channel is the published schedule margin.
    # It cannot independently verify the eventual delivery outcome.
    planner=MultiStepPlanner(states=(Outcome.LATE.value,Outcome.ON_TIME.value),
        observation_model={"inspect_schedule_margin":likelihoods},
        action_costs={"inspect_schedule_margin":.01},
        config=PlanningConfig(horizon=1,answer_threshold=selected,min_observations=1),
        support_predicate=lambda _hypothesis,_history: False)
    pomdp_initial=planner.decide({Outcome.LATE.value:prior,Outcome.ON_TIME.value:1-prior})
    return {"method":"purchase/carrier margin categorical empirical baseline; Laplace smoothing",
        "snapshot":snapshot.value,"outcome_hidden_during_prediction":True,"prior_late":prior,
        "likelihood_by_outcome":likelihoods,"posterior_by_margin_bucket":probs,
        "training_counts":counts,"selected_threshold":selected,
        "split":{"train":len(split.train),"validation":len(split.validation),"test":len(split.test),
                 "train_end":split.train[-1].purchase_at.isoformat(),"validation_end":split.validation[-1].purchase_at.isoformat()},
        "metrics":_metrics(test_rows),"prior_only_metrics":_metrics(prior_rows),
        "pomdp_with_evidence_gate":{"initial_decision":pomdp_initial.kind,"coverage":0.0,
            "reason":"Schedule margin is not independent evidence of the eventual delivery outcome."},
        "rows":test_rows,
        "limitations":["Olist outcome is an operational proxy, not independently audited ground truth.",
            "The margin bucket is an observed feature channel, not a counterfactual tool action.",
            "No multi-step advantage is claimed because the dataset lacks counterfactual action outcomes."]}
