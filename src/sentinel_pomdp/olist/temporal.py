"""Leakage-safe Olist decision-time feature construction."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from heapq import heappop, heappush
from math import log1p

from .dataset import OlistDataset, OlistOrder, Outcome, Snapshot


class TemporalFeatureError(ValueError):
    pass


class PredictionStage(str, Enum):
    PURCHASE = "PURCHASE"
    APPROVAL = "APPROVAL"
    CARRIER_HANDOFF = "CARRIER_HANDOFF"


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    earliest_stage: PredictionStage
    source_file: str
    source_fields: tuple[str, ...]
    availability_assumption: str
    missing_semantics: str


FEATURE_REGISTRY = (
    FeatureDefinition("estimated_lead_days", PredictionStage.PURCHASE,
        "olist_orders_dataset.csv", ("order_purchase_timestamp", "order_estimated_delivery_date"),
        "The published estimate is conservatively assumed available when the order is created.",
        "Missing means the source export has no valid estimate."),
    FeatureDefinition("purchase_weekday", PredictionStage.PURCHASE,
        "olist_orders_dataset.csv", ("order_purchase_timestamp",),
        "Purchase time is the decision timestamp.", "Missing purchase times are ineligible."),
    FeatureDefinition("item_count", PredictionStage.PURCHASE,
        "olist_order_items_dataset.csv", ("order_id", "order_item_id"),
        "Order-line membership is assumed available at purchase; the archive has no access log.",
        "Zero means no valid matching item row was present."),
    FeatureDefinition("seller_history_rate", PredictionStage.PURCHASE,
        "olist_order_items_dataset.csv + olist_orders_dataset.csv",
        ("seller_id", "order_delivered_customer_date", "order_estimated_delivery_date"),
        "Only earlier orders delivered strictly before the prediction timestamp contribute.",
        "Missing means none of the order's sellers has a prior knowable eligible outcome."),
    FeatureDefinition("seller_history_count_log", PredictionStage.PURCHASE,
        "derived temporal history", ("seller_id",),
        "Count uses the same strictly earlier completed outcomes as seller_history_rate.",
        "Zero means no prior knowable seller outcome."),
    FeatureDefinition("approval_elapsed_days", PredictionStage.APPROVAL,
        "olist_orders_dataset.csv", ("order_approved_at", "order_purchase_timestamp"),
        "Approval timestamp is used only at or after approval.",
        "Missing approval makes an approval-time prediction unavailable."),
    FeatureDefinition("handoff_elapsed_days", PredictionStage.CARRIER_HANDOFF,
        "olist_orders_dataset.csv", ("order_delivered_carrier_date", "order_purchase_timestamp"),
        "Carrier handoff timestamp is used only at or after handoff.",
        "Missing handoff makes a carrier-time prediction unavailable."),
    FeatureDefinition("days_remaining_at_handoff", PredictionStage.CARRIER_HANDOFF,
        "olist_orders_dataset.csv", ("order_delivered_carrier_date", "order_estimated_delivery_date"),
        "Both values must be available at carrier handoff.",
        "Missing handoff or estimate makes the feature unavailable."),
)

PROHIBITED_PRE_OUTCOME_FIELDS = frozenset({
    "order_delivered_customer_date", "final_status", "outcome", "review_score",
    "post_delivery_review", "future_seller_delay_rate",
})

_STAGE_ORDER = {stage: index for index, stage in enumerate(PredictionStage)}


@dataclass(frozen=True)
class TemporalExample:
    order_id: str
    stage: PredictionStage
    decision_time: datetime
    label_available_at: datetime
    label: str
    values: dict[str, float | None]
    provenance: dict[str, dict[str, object]]
    seller_history_available: bool

    def require_no_future_fields(self) -> None:
        leaked = PROHIBITED_PRE_OUTCOME_FIELDS & set(self.values)
        if leaked:
            raise TemporalFeatureError("future fields are prohibited: " + ", ".join(sorted(leaked)))


def feature_registry(stage: PredictionStage) -> list[dict[str, object]]:
    return [definition.__dict__ for definition in FEATURE_REGISTRY
            if _STAGE_ORDER[definition.earliest_stage] <= _STAGE_ORDER[stage]]


def validate_feature_payload(stage: PredictionStage, values: dict[str, object]) -> None:
    if PROHIBITED_PRE_OUTCOME_FIELDS & set(values):
        raise TemporalFeatureError("future outcome or post-delivery fields are not allowed")
    allowed = {item["name"] for item in feature_registry(stage)}
    unknown = set(values) - allowed
    if unknown:
        raise TemporalFeatureError("feature is unavailable at decision time: " + ", ".join(sorted(unknown)))


def _decision_time(order: OlistOrder, stage: PredictionStage) -> datetime | None:
    if stage is PredictionStage.PURCHASE:
        return order.purchase_at
    if stage is PredictionStage.APPROVAL:
        return order.approved_at
    return order.carrier_at


def _order_items(dataset: OlistDataset) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    counts: dict[str, int] = defaultdict(int)
    sellers: dict[str, set[str]] = defaultdict(set)
    for _, row in dataset.rows("olist_order_items_dataset.csv"):
        order_id = row["order_id"]
        if not order_id or not row["order_item_id"]:
            continue
        counts[order_id] += 1
        if row["seller_id"]:
            sellers[order_id].add(row["seller_id"])
    return dict(counts), {key: tuple(sorted(value)) for key, value in sellers.items()}


def build_temporal_examples(dataset: OlistDataset, stage: PredictionStage) -> list[TemporalExample]:
    """Build examples in event order; seller outcomes enter history only after delivery."""
    orders = [order for order in dataset.orders()
              if order.outcome in {Outcome.LATE, Outcome.ON_TIME}]
    item_counts, sellers_by_order = _order_items(dataset)
    predictions = sorted(((decision, order) for order in orders
                          if (decision := _decision_time(order, stage)) is not None),
                         key=lambda item: (item[0], item[1].order_id))
    completion_heap: list[tuple[datetime, str, OlistOrder]] = []
    for order in orders:
        assert order.delivered_at is not None
        heappush(completion_heap, (order.delivered_at, order.order_id, order))
    seller_counts: dict[str, int] = defaultdict(int)
    seller_delays: dict[str, int] = defaultdict(int)
    examples = []
    for decision, order in predictions:
        while completion_heap and completion_heap[0][0] < decision:
            _, _, completed = heappop(completion_heap)
            for seller in sellers_by_order.get(completed.order_id, ()):
                seller_counts[seller] += 1
                seller_delays[seller] += completed.outcome is Outcome.LATE
        sellers = sellers_by_order.get(order.order_id, ())
        history_count = sum(seller_counts[seller] for seller in sellers)
        history_delays = sum(seller_delays[seller] for seller in sellers)
        history_rate = history_delays / history_count if history_count else None
        estimate = order.estimated_at
        values: dict[str, float | None] = {
            "estimated_lead_days": ((estimate - order.purchase_at).total_seconds() / 86400
                                    if estimate else None),
            "purchase_weekday": float(order.purchase_at.weekday()),
            "item_count": float(item_counts.get(order.order_id, 0)),
            "seller_history_rate": history_rate,
            "seller_history_count_log": log1p(history_count),
        }
        if stage in {PredictionStage.APPROVAL, PredictionStage.CARRIER_HANDOFF}:
            values["approval_elapsed_days"] = ((order.approved_at - order.purchase_at).total_seconds() / 86400
                                                if order.approved_at else None)
        if stage is PredictionStage.CARRIER_HANDOFF:
            values["handoff_elapsed_days"] = ((order.carrier_at - order.purchase_at).total_seconds() / 86400
                                               if order.carrier_at else None)
            values["days_remaining_at_handoff"] = ((order.estimated_at - order.carrier_at).total_seconds() / 86400
                                                    if order.estimated_at and order.carrier_at else None)
        validate_feature_payload(stage, values)
        provenance = {definition.name: {
            "source_file": definition.source_file,
            "source_fields": list(definition.source_fields),
            "event_time": decision.isoformat(),
            "earliest_defensible_availability": decision.isoformat(),
            "decision_time_cutoff": decision.isoformat(),
            "missing": values.get(definition.name) is None,
            "missing_semantics": definition.missing_semantics,
            "availability_assumption": definition.availability_assumption,
            "investigation_action": None,
        } for definition in FEATURE_REGISTRY if definition.name in values}
        example = TemporalExample(order.order_id, stage, decision, order.delivered_at,
            order.outcome.value, values, provenance, history_count > 0)
        example.require_no_future_fields()
        examples.append(example)
    return examples


def snapshot_for_stage(order: OlistOrder, stage: PredictionStage) -> dict[str, object]:
    mapping = {PredictionStage.PURCHASE: Snapshot.PURCHASE,
               PredictionStage.APPROVAL: Snapshot.APPROVAL,
               PredictionStage.CARRIER_HANDOFF: Snapshot.CARRIER_HANDOFF}
    snapshot = order.snapshot(mapping[stage])
    if PROHIBITED_PRE_OUTCOME_FIELDS & set(snapshot):
        raise TemporalFeatureError("snapshot exposes a future outcome")
    return snapshot
