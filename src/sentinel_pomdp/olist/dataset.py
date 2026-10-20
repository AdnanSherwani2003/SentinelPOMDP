"""Read the Olist CSV release without extracting or modifying original files."""
from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Iterator

REQUIRED = {
    "olist_orders_dataset.csv": {"order_id", "customer_id", "order_status",
        "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date"},
    "olist_order_items_dataset.csv": {"order_id", "order_item_id", "product_id", "seller_id"},
    "olist_customers_dataset.csv": {"customer_id", "customer_unique_id"},
    "olist_sellers_dataset.csv": {"seller_id"},
    "olist_products_dataset.csv": {"product_id"},
    "olist_order_payments_dataset.csv": {"order_id", "payment_sequential"},
    "olist_order_reviews_dataset.csv": {"review_id", "order_id"},
    "olist_geolocation_dataset.csv": {"geolocation_zip_code_prefix"},
    "product_category_name_translation.csv": {"product_category_name", "product_category_name_english"},
}

class OlistDatasetError(ValueError): pass

class Outcome(str, Enum):
    LATE = "shipment_delayed"
    ON_TIME = "shipment_on_time"
    UNKNOWN = "unknown"
    EXCLUDED = "excluded"

class Snapshot(str, Enum):
    PURCHASE = "PURCHASE"
    APPROVAL = "APPROVAL"
    CARRIER_HANDOFF = "CARRIER_HANDOFF"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"

def _dt(value: str | None) -> datetime | None:
    if not value or not value.strip(): return None
    try: return datetime.fromisoformat(value.strip())
    except ValueError: return None

@dataclass(frozen=True)
class OlistOrder:
    order_id: str; customer_id: str; status: str; purchase_at: datetime
    approved_at: datetime | None; carrier_at: datetime | None
    delivered_at: datetime | None; estimated_at: datetime | None; source_row: int

    @property
    def outcome(self) -> Outcome:
        if self.status in {"canceled", "unavailable"}: return Outcome.EXCLUDED
        if self.status != "delivered": return Outcome.UNKNOWN
        if not self.delivered_at or not self.estimated_at: return Outcome.UNKNOWN
        if (self.delivered_at < self.purchase_at or self.estimated_at < self.purchase_at
                or (self.approved_at and (self.approved_at < self.purchase_at or self.delivered_at < self.approved_at))
                or (self.carrier_at and (self.carrier_at < self.purchase_at or self.delivered_at < self.carrier_at))):
            return Outcome.UNKNOWN
        return Outcome.LATE if self.delivered_at.date() > self.estimated_at.date() else Outcome.ON_TIME

    def snapshot(self, mode: Snapshot) -> dict[str, object]:
        # The exported status is the final status, not the status at purchase.
        result: dict[str, object] = {"order_id": self.order_id,
            "purchase_at": self.purchase_at.isoformat(),
            "estimated_delivery_date": self.estimated_at.date().isoformat() if self.estimated_at else None}
        if mode in {Snapshot.APPROVAL, Snapshot.CARRIER_HANDOFF, Snapshot.DELIVERY_COMPLETED}:
            result["approved_at"] = self.approved_at.isoformat() if self.approved_at else None
        if mode in {Snapshot.CARRIER_HANDOFF, Snapshot.DELIVERY_COMPLETED}:
            result["carrier_handoff_at"] = self.carrier_at.isoformat() if self.carrier_at else None
        if mode is Snapshot.DELIVERY_COMPLETED:
            result["final_status"] = self.status
            result["delivered_at"] = self.delivered_at.isoformat() if self.delivered_at else None
            result["outcome"] = self.outcome.value
        return result

@dataclass
class TableInventory:
    filename: str; bytes: int; sha256: str; rows: int; columns: list[str]
    missing: dict[str, int]; duplicate_primary_keys: int = 0

@dataclass
class OlistInventory:
    dataset_path: str; dataset_version: str; archive_sha256: str
    license: str = "CC BY-NC-SA 4.0"; tables: dict[str, TableInventory] = field(default_factory=dict)
    referential_integrity: dict[str, int] = field(default_factory=dict)
    order_date_range: dict[str, str | None] = field(default_factory=dict)
    order_status_counts: dict[str, int] = field(default_factory=dict)
    outcome_counts: dict[str, int] = field(default_factory=dict)
    invalid_date_orderings: int = 0

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

class OlistDataset:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._hash_cache: dict[str, str] = {}
        if not self.path.exists(): raise OlistDatasetError(f"dataset path does not exist: {self.path}")
        self._zip = self.path.is_file() and zipfile.is_zipfile(self.path)
        missing = sorted(set(REQUIRED) - set(self.names()))
        if missing: raise OlistDatasetError("missing required Olist tables: " + ", ".join(missing))

    def names(self) -> list[str]:
        if self._zip:
            with zipfile.ZipFile(self.path) as zf:
                unsafe = [n for n in zf.namelist() if Path(n).is_absolute() or ".." in Path(n).parts]
                if unsafe: raise OlistDatasetError("archive contains unsafe paths")
                basenames = [Path(n).name for n in zf.namelist() if not n.endswith("/")]
                duplicates = [n for n, c in Counter(basenames).items() if c > 1 and n in REQUIRED]
                if duplicates: raise OlistDatasetError("ambiguous archive tables: " + ", ".join(duplicates))
                return basenames
        if self.path.is_dir(): return [p.name for p in self.path.rglob("*.csv")]
        raise OlistDatasetError("dataset must be a directory or ZIP archive")

    def _bytes(self, name: str) -> bytes:
        if name not in REQUIRED: raise OlistDatasetError("unrecognized table")
        if self._zip:
            with zipfile.ZipFile(self.path) as zf:
                matches = [n for n in zf.namelist() if Path(n).name == name]
                if len(matches) != 1: raise OlistDatasetError(f"ambiguous table: {name}")
                info = zf.getinfo(matches[0])
                if info.file_size > 100_000_000: raise OlistDatasetError("table exceeds bounded size")
                if info.file_size > max(1,info.compress_size)*200:
                    raise OlistDatasetError("archive table exceeds safe expansion ratio")
                return zf.read(info)
        matches = list(self.path.rglob(name))
        if len(matches) != 1: raise OlistDatasetError(f"ambiguous table: {name}")
        return matches[0].read_bytes()

    def rows(self, name: str) -> Iterator[tuple[int, dict[str, str]]]:
        raw = self._bytes(name)
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="strict"), newline=""))
        if not reader.fieldnames or not REQUIRED[name].issubset(reader.fieldnames):
            raise OlistDatasetError(f"invalid schema for {name}")
        for row_number, row in enumerate(reader, start=2): yield row_number, dict(row)

    def orders(self, limit: int | None = None) -> Iterator[OlistOrder]:
        count = 0
        for row_number, r in self.rows("olist_orders_dataset.csv"):
            purchase = _dt(r["order_purchase_timestamp"])
            if purchase is None: continue
            yield OlistOrder(r["order_id"], r["customer_id"], r["order_status"], purchase,
                _dt(r["order_approved_at"]), _dt(r["order_delivered_carrier_date"]),
                _dt(r["order_delivered_customer_date"]), _dt(r["order_estimated_delivery_date"]), row_number)
            count += 1
            if limit is not None and count >= limit: break

    def content_hash(self, name: str, *, refresh: bool = False) -> str:
        if refresh or name not in self._hash_cache:
            self._hash_cache[name] = sha256(self._bytes(name)).hexdigest()
        return self._hash_cache[name]

    def eligibility_breakdown(self) -> dict[str, int]:
        """Mutually exclusive, ordered reasons for chronological outcome eligibility."""
        counts: Counter[str] = Counter()
        for _, row in self.rows("olist_orders_dataset.csv"):
            purchase=_dt(row["order_purchase_timestamp"])
            delivered=_dt(row["order_delivered_customer_date"])
            estimated=_dt(row["order_estimated_delivery_date"])
            approved=_dt(row["order_approved_at"])
            carrier=_dt(row["order_delivered_carrier_date"])
            if delivered is None:
                reason="missing_or_invalid_customer_delivery_date"
            elif purchase is None:
                reason="missing_or_invalid_purchase_date"
            elif row["order_status"] != "delivered":
                reason="non_delivered_final_status"
            elif estimated is None:
                reason="missing_or_invalid_estimated_delivery_date"
            elif (delivered < purchase or estimated < purchase
                  or (approved is not None and (approved < purchase or delivered < approved))
                  or (carrier is not None and (carrier < purchase or delivered < carrier))):
                reason="invalid_date_ordering"
            else:
                reason="eligible"
            counts[reason]+=1
        return dict(counts)

def discover_olist(root: str | Path) -> Path:
    root = Path(root).resolve(); candidates: list[Path] = []
    for p in root.rglob("*"):
        if any(part in {".git", ".venv"} for part in p.parts): continue
        if p.is_file() and p.suffix.lower() == ".zip":
            try:
                if set(REQUIRED).issubset(OlistDataset(p).names()): candidates.append(p)
            except (OlistDatasetError, zipfile.BadZipFile): pass
        elif p.is_dir() and (p / "olist_orders_dataset.csv").exists(): candidates.append(p)
    unique = sorted(set(candidates))
    if len(unique) != 1: raise OlistDatasetError(f"expected one Olist dataset, found {len(unique)}")
    return unique[0]

def inventory_olist(dataset: OlistDataset, version: str) -> OlistInventory:
    archive_hash = sha256(dataset.path.read_bytes()).hexdigest() if dataset.path.is_file() else "directory"
    inv = OlistInventory(str(dataset.path), version, archive_hash)
    key_fields = {"olist_orders_dataset.csv": ("order_id",), "olist_customers_dataset.csv": ("customer_id",),
        "olist_sellers_dataset.csv": ("seller_id",), "olist_products_dataset.csv": ("product_id",),
        "olist_order_items_dataset.csv": ("order_id", "order_item_id"),
        "olist_order_payments_dataset.csv": ("order_id", "payment_sequential"),
        "olist_order_reviews_dataset.csv": ("review_id",)}
    sets: dict[str, set[str]] = {}; purchases: list[datetime] = []
    for name in REQUIRED:
        raw = dataset._bytes(name); rows = 0; missing = Counter(); seen = set(); dup = 0; columns = []
        for _, row in dataset.rows(name):
            rows += 1; columns = list(row)
            for col, val in row.items():
                if not val.strip(): missing[col] += 1
            keys = key_fields.get(name)
            if keys:
                key = "\0".join(row[k] for k in keys)
                if key in seen: dup += 1
                seen.add(key)
            if name == "olist_orders_dataset.csv":
                purchase = _dt(row["order_purchase_timestamp"])
                if purchase: purchases.append(purchase)
        inv.tables[name] = TableInventory(name, len(raw), sha256(raw).hexdigest(), rows, columns, dict(missing), dup)
        if name in {"olist_orders_dataset.csv", "olist_customers_dataset.csv", "olist_sellers_dataset.csv", "olist_products_dataset.csv"}:
            field = key_fields[name][0]; sets[name] = {r[field] for _, r in dataset.rows(name)}
    order_ids=sets["olist_orders_dataset.csv"]; customers=sets["olist_customers_dataset.csv"]
    seller_ids=sets["olist_sellers_dataset.csv"]; products=sets["olist_products_dataset.csv"]
    orphan_items=orphan_sellers=orphan_products=0
    for _, r in dataset.rows("olist_order_items_dataset.csv"):
        orphan_items += r["order_id"] not in order_ids; orphan_sellers += r["seller_id"] not in seller_ids; orphan_products += r["product_id"] not in products
    orphan_customers=sum(r["customer_id"] not in customers for _,r in dataset.rows("olist_orders_dataset.csv"))
    inv.referential_integrity={"orders_missing_customer":orphan_customers,"items_missing_order":orphan_items,
        "items_missing_seller":orphan_sellers,"items_missing_product":orphan_products,
        "payments_missing_order":sum(r["order_id"] not in order_ids for _,r in dataset.rows("olist_order_payments_dataset.csv")),
        "reviews_missing_order":sum(r["order_id"] not in order_ids for _,r in dataset.rows("olist_order_reviews_dataset.csv"))}
    inv.order_date_range={"min_purchase":min(purchases).isoformat() if purchases else None,"max_purchase":max(purchases).isoformat() if purchases else None}
    orders=list(dataset.orders()); inv.order_status_counts=dict(Counter(o.status for o in orders))
    inv.outcome_counts=dict(Counter(o.outcome.value for o in orders))
    inv.invalid_date_orderings=sum(bool((o.approved_at and o.approved_at<o.purchase_at) or
        (o.carrier_at and o.carrier_at<o.purchase_at) or (o.delivered_at and o.delivered_at<o.purchase_at)) for o in orders)
    return inv
