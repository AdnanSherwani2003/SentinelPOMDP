"""Reviewer-authorized, idempotent Olist graph publication and factual lookup."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from itertools import islice
from time import perf_counter
from tempfile import TemporaryDirectory

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.graph.schemas import Document, Entity, Evidence, EvidenceType, RelationFact
from sentinel_pomdp.ingestion.models import (CandidateSource, CandidateStatus, CompanyDocument,
    DocumentStatus, FactCandidate, ReviewAction, SourceLocation)
from sentinel_pomdp.ingestion.service import EnterpriseDataService
from sentinel_pomdp.ingestion.storage import LocalDocumentStore
from sentinel_pomdp.security import AuthenticatedPrincipal, Permission
from .dataset import OlistDataset, Snapshot

def _id(prefix: str, *parts: str) -> str:
    return prefix + "_" + sha256("\0".join(parts).encode()).hexdigest()[:24]

@dataclass(frozen=True)
class ImportSummary:
    tenant_id: str; dataset_version: str; requested_limit: int; imported_orders: int
    entities: int; facts: int; evidence: int; errors: int; elapsed_seconds: float
    orders_per_second: float; reviewer_id: str; idempotent: bool = True
    order_ids: tuple[str,...] = ()
    duplicate_ids: tuple[str,...] = ()
    reconciled_ids: tuple[str,...] = ()
    rejected_ids: tuple[str,...] = ()

class OlistService:
    def __init__(self, dataset: OlistDataset, repository: BaseGraphRepository, *, dataset_version: str="olist-2018",
                 review_service: EnterpriseDataService | None = None):
        self.dataset=dataset; self.repository=repository; self.dataset_version=dataset_version
        self._temporary_store = TemporaryDirectory(prefix="sentinel-olist-review-") if review_service is None else None
        self.review_service = review_service or EnterpriseDataService(LocalDocumentStore(self._temporary_store.name), repository)
        self._eligibility_cache: dict[str,int] | None = None

    def overview(self, tenant_id: str) -> dict[str, object]:
        if self._eligibility_cache is None:
            self._eligibility_cache=self.dataset.eligibility_breakdown()
        candidates=[item for item in self.review_service.store.list_candidates(tenant_id)
                    if item.dataset_id==self.dataset_version]
        return {"dataset_version":self.dataset_version,"tenant_id":tenant_id,
            "imported_orders":len(self.repository.list_entities(tenant_id,"olist_order")),
            "approved_review_records":sum(item.status is CandidateStatus.APPROVED for item in candidates),
            "eligibility":dict(self._eligibility_cache),"predictive_model_status":"NOT_ACTIVATED",
            "evaluation_status":"OFFLINE_CANDIDATE_EVALUATED","external_llm_used":False}

    def _register_source(self, tenant_id: str, filename: str) -> str:
        digest=self.dataset.content_hash(filename,refresh=True)
        document_id=_id("doc",tenant_id,self.dataset_version,filename,digest)
        self.review_service.store.put_document_reference(CompanyDocument(
            document_id=document_id,tenant_id=tenant_id,dataset_id=self.dataset_version,
            source_name=filename,source_type="csv",media_type="text/csv",source_hash=digest,
            version=1,ingestion_id=_id("ing",tenant_id,self.dataset_version,filename,digest),
            status=DocumentStatus.PARSED,classification="public-research",
            byte_size=len(self.dataset._bytes(filename))))
        return document_id

    def _candidate(self, tenant_id: str, fact: RelationFact, *, document_id: str,
                   source_file: str, source_row: int, source_text: str) -> FactCandidate:
        source_hash=self.dataset.content_hash(source_file)
        return FactCandidate(candidate_id=_id("candidate",fact.fact_id,source_hash),
            tenant_id=tenant_id,dataset_id=self.dataset_version,
            subject_id=fact.subject_id,subject_name=fact.subject_id,
            object_id=fact.object_id,object_name=fact.object_id,
            relation_type=fact.relation_type,attributes=fact.attributes,
            sources=[CandidateSource(location=SourceLocation(document_id=document_id,version=1,
                locator=f"row:{source_row}",sheet=source_file,row=source_row,
                source_text=source_text,source_group=f"olist-release:{self.dataset_version}"),
                extraction_method="deterministic_olist_csv",extraction_confidence=1,
                direct_statement=True)],extraction_method="deterministic_olist_csv")

    def _review_fact(self, reviewer: AuthenticatedPrincipal, fact: RelationFact, *,
                     document_id: str, source_file: str, source_row: int,
                     source_text: str, action: ReviewAction) -> FactCandidate:
        candidate=self._candidate(reviewer.tenant_id,fact,document_id=document_id,
            source_file=source_file,source_row=source_row,source_text=source_text)
        stored=self.review_service.store.get_candidate(reviewer.tenant_id,candidate.candidate_id)
        if stored is None:
            self.review_service.store.put_candidate(candidate)
        elif stored.status is CandidateStatus.REJECTED:
            raise ValueError("previously rejected candidate cannot be silently approved")
        elif stored.status is CandidateStatus.APPROVED:
            if self.repository.get_relation_fact(fact.fact_id,reviewer.tenant_id) is None:
                raise ValueError("approved candidate has no published fact; stop for reconciliation")
            return stored
        return self.review_service.review(reviewer.tenant_id,candidate.candidate_id,action,
            reviewer.principal_id,note="Olist bounded batch review",
            publisher=lambda approved: self._publish_reviewed_fact(approved,fact))

    def _publish_reviewed_fact(self, candidate: FactCandidate, fact: RelationFact) -> str:
        if candidate.tenant_id != fact.tenant_id or candidate.relation_type != fact.relation_type:
            raise ValueError("candidate and fact mismatch")
        existing=self.repository.get_relation_fact(fact.fact_id,fact.tenant_id)
        if existing is not None:
            if (existing.relation_type!=fact.relation_type or existing.subject_id!=fact.subject_id
                    or existing.object_id!=fact.object_id
                    or {k:v for k,v in existing.attributes.items() if k!="reviewed_by"}
                       != {k:v for k,v in fact.attributes.items() if k!="reviewed_by"}):
                raise ValueError("published fact changed during review")
            return existing.fact_id
        self.repository.upsert_relation_fact(fact)
        return fact.fact_id

    def _fact_specs(self, tenant_id: str, reviewer_id: str, order, item_rows,
                    orders_doc_id: str, items_doc_id: str) -> list[tuple[RelationFact,str,str,int,str]]:
        if not order.order_id or not order.customer_id:
            raise ValueError("order or customer identifier is missing")
        row_text=(f"order row {order.source_row}: status={order.status}; "
                  f"estimated={order.estimated_at.isoformat() if order.estimated_at else None}; "
                  f"actual={order.delivered_at.isoformat() if order.delivered_at else None}")
        common={"source_file":"olist_orders_dataset.csv","source_row":order.source_row,
                "dataset_version":self.dataset_version,"causal_attribution":False,"reviewed_by":reviewer_id}
        customer=RelationFact(fact_id=_id("fact",tenant_id,self.dataset_version,"CUSTOMER_PLACED_ORDER",order.customer_id,order.order_id),
            tenant_id=tenant_id,relation_type="CUSTOMER_PLACED_ORDER",subject_id=order.customer_id,
            object_id=order.order_id,attributes=common,review_status="APPROVED")
        sellers=sorted({row["seller_id"] for _,row in item_rows})
        attrs={"dataset_version":self.dataset_version,"status":order.status,"purchase_at":order.purchase_at.isoformat(),
            "estimated_delivery_date":order.estimated_at.isoformat() if order.estimated_at else None,
            "actual_delivery_date":order.delivered_at.isoformat() if order.delivered_at else None,
            "outcome":order.outcome.value,"comparison":"actual calendar date > estimated calendar date",
            "source_row":order.source_row,"reviewed_by":reviewer_id,"causal_attribution":False,
            "seller_ids":sellers,"multi_seller":len(sellers)>1}
        delivery=RelationFact(fact_id=_id("fact",tenant_id,self.dataset_version,order.order_id,"delivery"),
            tenant_id=tenant_id,relation_type="OLIST_DELIVERY_OUTCOME",subject_id=order.order_id,
            object_id="delivery_"+order.order_id,attributes=attrs,
            observed_at=order.delivered_at.isoformat() if order.delivered_at else order.purchase_at.isoformat(),
            review_status="APPROVED")
        specs=[(customer,orders_doc_id,"olist_orders_dataset.csv",order.source_row,row_text),
               (delivery,orders_doc_id,"olist_orders_dataset.csv",order.source_row,row_text)]
        seen_items: set[str] = set()
        for row_number,row in item_rows:
            if not all(row.get(key) for key in ("order_item_id","seller_id","product_id")):
                raise ValueError("item identifier, seller, or product is missing")
            item_id=f"{order.order_id}:{row['order_item_id']}"
            if item_id in seen_items:
                raise ValueError("duplicate order-item identifier")
            seen_items.add(item_id)
            item_text=(f"item row {row_number}: order={order.order_id}; item={row['order_item_id']}; "
                       f"product={row['product_id']}; seller={row['seller_id']}")
            for relation,subject,obj in (("ORDER_CONTAINS_ITEM",order.order_id,item_id),
                    ("ITEM_SOLD_BY_SELLER",item_id,row["seller_id"]),
                    ("ITEM_REFERENCES_PRODUCT",item_id,row["product_id"])):
                fact=RelationFact(fact_id=_id("fact",tenant_id,self.dataset_version,relation,subject,obj),
                    tenant_id=tenant_id,relation_type=relation,subject_id=subject,object_id=obj,
                    attributes={"source_file":"olist_order_items_dataset.csv","source_row":row_number,
                        "dataset_version":self.dataset_version,"causal_attribution":False,"reviewed_by":reviewer_id},
                    review_status="APPROVED")
                specs.append((fact,items_doc_id,"olist_order_items_dataset.csv",row_number,item_text))
        return specs

    def preview_orders(self, reviewer: AuthenticatedPrincipal, *, limit: int, offset: int=0) -> dict:
        self._validate_reviewer(reviewer,limit,offset)
        chosen=list(islice(self.dataset.orders(),offset,offset+limit))
        return {"tenant_id":reviewer.tenant_id,"dataset_version":self.dataset_version,
            "archive_sha256":sha256(self.dataset.path.read_bytes()).hexdigest() if self.dataset.path.is_file()
                else self.dataset.content_hash("olist_orders_dataset.csv",refresh=True),
            "offset":offset,"limit":limit,"order_ids":[order.order_id for order in chosen],
            "outcome_counts":{outcome:sum(order.outcome.value==outcome for order in chosen)
                for outcome in sorted({order.outcome.value for order in chosen})},
            "review_required":True}

    def batch_status(self, reviewer: AuthenticatedPrincipal, *, limit: int, offset: int=0) -> dict:
        """Describe durable progress for a bounded batch without changing either store."""
        self._validate_reviewer(reviewer,limit,offset)
        tenant_id=reviewer.tenant_id
        chosen=list(islice(self.dataset.orders(),offset,offset+limit))
        selected={order.order_id for order in chosen}; items={order_id:[] for order_id in selected}
        for row_number,row in self.dataset.rows("olist_order_items_dataset.csv"):
            if row["order_id"] in selected: items[row["order_id"]].append((row_number,row))
        orders_hash=self.dataset.content_hash("olist_orders_dataset.csv",refresh=True)
        items_hash=self.dataset.content_hash("olist_order_items_dataset.csv",refresh=True)
        orders_doc_id=_id("doc",tenant_id,self.dataset_version,"olist_orders_dataset.csv",orders_hash)
        items_doc_id=_id("doc",tenant_id,self.dataset_version,"olist_order_items_dataset.csv",items_hash)
        records=[]
        for order in chosen:
            specs=self._fact_specs(tenant_id,reviewer.principal_id,order,items[order.order_id],
                orders_doc_id,items_doc_id)
            candidates=[self.review_service.store.get_candidate(tenant_id,
                self._candidate(tenant_id,fact,document_id=document_id,source_file=filename,
                    source_row=row_number,source_text=source_text).candidate_id)
                for fact,document_id,filename,row_number,source_text in specs]
            facts=[self.repository.get_relation_fact(fact.fact_id,tenant_id) for fact,_,_,_,_ in specs]
            facts_with_evidence=sum(item is not None and bool(
                self.repository.get_fact_evidence(item.fact_id,tenant_id)[0]) for item in facts)
            approved=sum(item is not None and item.status is CandidateStatus.APPROVED for item in candidates)
            rejected=sum(item is not None and item.status is CandidateStatus.REJECTED for item in candidates)
            if rejected:
                state="REJECTED"
            elif (self.repository.get_entity(order.order_id,tenant_id) is not None
                    and approved==len(specs) and facts_with_evidence==len(specs)):
                state="COMMITTED"
            elif approved or any(item is not None for item in facts):
                state="PARTIAL"
            else:
                state="PENDING"
            records.append({"order_id":order.order_id,"state":state,"expected_facts":len(specs),
                "approved_candidates":approved,"rejected_candidates":rejected,
                "published_facts":sum(item is not None for item in facts),
                "facts_with_evidence":facts_with_evidence})
        counts={state:sum(item["state"]==state for item in records)
                for state in ("COMMITTED","PARTIAL","PENDING","REJECTED")}
        return {"batch_id":_id("batch",tenant_id,self.dataset_version,str(offset),str(limit),orders_hash),
            "tenant_id":tenant_id,"dataset_version":self.dataset_version,"offset":offset,"limit":limit,
            "read_only":True,"state_counts":counts,"orders":records}

    @staticmethod
    def _validate_reviewer(reviewer: AuthenticatedPrincipal, limit: int, offset: int) -> None:
        if (not isinstance(reviewer, AuthenticatedPrincipal) or not reviewer.active
                or not reviewer.tenant_id or not reviewer.principal_id
                or ("reviewer" not in reviewer.roles and Permission.ADMIN not in reviewer.permissions)
                or Permission.DOCUMENT_UPLOAD not in reviewer.permissions):
            raise ValueError("an active authorized reviewer is required")
        if limit < 1 or limit > 10_000: raise ValueError("import limit must be between 1 and 10000")
        if offset < 0: raise ValueError("offset must be nonnegative")

    def import_orders(self, reviewer: AuthenticatedPrincipal, *, limit: int, offset: int=0,
                      expected_archive_sha256: str, review_action: str) -> ImportSummary:
        self._validate_reviewer(reviewer,limit,offset)
        if review_action not in {"APPROVE","REJECT"}: raise ValueError("explicit reviewer decision is required")
        preview=self.preview_orders(reviewer,limit=limit,offset=offset)
        if preview["archive_sha256"]!=expected_archive_sha256:
            raise ValueError("archive changed since batch preview")
        tenant_id=reviewer.tenant_id; reviewer_id=reviewer.principal_id
        started=perf_counter(); chosen=list(islice(self.dataset.orders(),offset,offset+limit))
        source_hash=self.dataset.content_hash("olist_orders_dataset.csv",refresh=True)
        items_hash=self.dataset.content_hash("olist_order_items_dataset.csv",refresh=True)
        expected_orders_doc_id=_id("doc",tenant_id,self.dataset_version,
            "olist_orders_dataset.csv",source_hash)
        expected_items_doc_id=_id("doc",tenant_id,self.dataset_version,
            "olist_order_items_dataset.csv",items_hash)
        for existing_document in self.repository.list_documents(tenant_id):
            if (existing_document.source_uri=="sentinel://olist/olist_orders_dataset.csv"
                    and existing_document.content_hash!=source_hash):
                raise ValueError("a different Olist source is already published; use a reviewed supersession workflow")
            if (existing_document.source_uri in {
                    "sentinel://olist/olist_orders_dataset.csv",
                    "sentinel://olist/olist_order_items_dataset.csv"}
                    and not existing_document.active):
                raise ValueError("a withdrawn Olist source cannot be silently reactivated")
        for order in chosen:
            existing=self.repository.get_entity(order.order_id,tenant_id)
            if (existing is not None
                    and existing.attributes.get("dataset_version")!=self.dataset_version):
                raise ValueError("existing order belongs to a different dataset version")
            if (existing is not None and (
                    self.repository.get_document(expected_orders_doc_id,tenant_id) is None
                    or self.repository.get_document(expected_items_doc_id,tenant_id) is None)):
                raise ValueError("an Olist source is missing or withdrawn; stop for review")
        selected={order.order_id for order in chosen}; items={order_id:[] for order_id in selected}
        for row_number,row in self.dataset.rows("olist_order_items_dataset.csv"):
            if row["order_id"] in selected: items[row["order_id"]].append((row_number,row))
        doc_id=self._register_source(tenant_id,"olist_orders_dataset.csv")
        items_doc_id=self._register_source(tenant_id,"olist_order_items_dataset.csv")
        specs_by_order={order.order_id:self._fact_specs(tenant_id,reviewer_id,order,
            items[order.order_id],doc_id,items_doc_id) for order in chosen}
        if review_action=="REJECT" and any(self.repository.get_entity(order.order_id,tenant_id)
                                           is not None for order in chosen):
            raise ValueError("published orders require separate withdrawal review")
        for order in chosen:
            if self.repository.get_entity(order.order_id,tenant_id) is None:
                continue
            for expected_fact,_,_,_,_ in specs_by_order[order.order_id]:
                current=self.repository.get_relation_fact(expected_fact.fact_id,tenant_id)
                # Absence is recoverable after an interrupted bounded write.  A
                # conflicting committed fact is not: it requires manual review.
                if current is None:
                    continue
                if (current.relation_type!=expected_fact.relation_type
                        or current.subject_id!=expected_fact.subject_id
                        or current.object_id!=expected_fact.object_id
                        or {k:v for k,v in current.attributes.items() if k!="reviewed_by"}
                           != {k:v for k,v in expected_fact.attributes.items() if k!="reviewed_by"}):
                    raise ValueError("existing reviewed fact or provenance differs; stop for manual reconciliation")
        for specs in specs_by_order.values():
            for fact,document_id,filename,row_number,source_text in specs:
                candidate=self._candidate(tenant_id,fact,document_id=document_id,
                    source_file=filename,source_row=row_number,source_text=source_text)
                stored=self.review_service.store.get_candidate(tenant_id,candidate.candidate_id)
                if stored is None:
                    self.review_service.store.put_candidate(candidate)
                elif stored.status is CandidateStatus.REJECTED and review_action=="APPROVE":
                    raise ValueError("previously rejected candidate cannot be silently approved")
                elif stored.status is CandidateStatus.APPROVED and review_action=="REJECT":
                    raise ValueError("approved candidate requires separate withdrawal review")
        if review_action=="REJECT":
            for specs in specs_by_order.values():
                for fact,document_id,filename,row_number,source_text in specs:
                    self._review_fact(reviewer,fact,document_id=document_id,source_file=filename,
                        source_row=row_number,source_text=source_text,action=ReviewAction.REJECT)
            elapsed=perf_counter()-started
            return ImportSummary(tenant_id,self.dataset_version,limit,0,0,0,0,0,
                elapsed,0,reviewer_id,True,(),(),(),tuple(order.order_id for order in chosen))
        self.repository.upsert_document(Document(document_id=doc_id,tenant_id=tenant_id,title="Olist orders dataset",
            source_uri="sentinel://olist/olist_orders_dataset.csv",source_type="csv",classification="public-research",
            content_hash=source_hash,review_status="APPROVED"))
        self.repository.upsert_document(Document(document_id=items_doc_id,tenant_id=tenant_id,title="Olist order items dataset",
            source_uri="sentinel://olist/olist_order_items_dataset.csv",source_type="csv",classification="public-research",
            content_hash=self.dataset.content_hash("olist_order_items_dataset.csv"),review_status="APPROVED"))
        entities=facts=evidence=errors=0
        imported=[]; duplicates=[]; reconciled=[]
        for order in chosen:
            try:
                existed=self.repository.get_entity(order.order_id,tenant_id) is not None
                specs=specs_by_order[order.order_id]
                candidates=[self.review_service.store.get_candidate(tenant_id,
                    self._candidate(tenant_id,fact,document_id=document_id,source_file=filename,
                        source_row=row_number,source_text=source_text).candidate_id)
                    for fact,document_id,filename,row_number,source_text in specs]
                graph_complete=all(
                    (current:=self.repository.get_relation_fact(fact.fact_id,tenant_id)) is not None
                    and bool(self.repository.get_fact_evidence(current.fact_id,tenant_id)[0])
                    for fact,_,_,_,_ in specs)
                if (existed and graph_complete
                        and all(candidate is not None and candidate.status is CandidateStatus.APPROVED
                                for candidate in candidates)):
                    duplicates.append(order.order_id); continue
                before=(entities,facts,evidence)
                self.repository.upsert_entity(Entity(entity_id=order.order_id,tenant_id=tenant_id,entity_type="olist_order",canonical_name=order.order_id,
                    attributes={"dataset_version":self.dataset_version,"status":order.status,"source_row":order.source_row})); entities+=1
                self.repository.upsert_entity(Entity(entity_id=order.customer_id,tenant_id=tenant_id,entity_type="olist_customer",
                    canonical_name=order.customer_id,attributes={"dataset_version":self.dataset_version})); entities+=1
                customer_fact=_id("fact",tenant_id,self.dataset_version,"CUSTOMER_PLACED_ORDER",order.customer_id,order.order_id)
                customer_relation=RelationFact(fact_id=customer_fact,tenant_id=tenant_id,
                    relation_type="CUSTOMER_PLACED_ORDER",subject_id=order.customer_id,object_id=order.order_id,
                    attributes={"source_file":"olist_orders_dataset.csv","source_row":order.source_row,
                                "dataset_version":self.dataset_version,"causal_attribution":False,"reviewed_by":reviewer_id},
                    review_status="APPROVED")
                self._review_fact(reviewer,customer_relation,document_id=doc_id,source_file="olist_orders_dataset.csv",
                    source_row=order.source_row,source_text=specs_by_order[order.order_id][0][4],action=ReviewAction.APPROVE); facts+=1
                delivery_id="delivery_"+order.order_id
                self.repository.upsert_entity(Entity(entity_id=delivery_id,tenant_id=tenant_id,entity_type="delivery_event",canonical_name=f"Delivery {order.order_id}",attributes={})); entities+=1
                fact_id=_id("fact",tenant_id,self.dataset_version,order.order_id,"delivery")
                sellers=sorted({row["seller_id"] for _,row in items[order.order_id]})
                attrs={"dataset_version":self.dataset_version,"status":order.status,"purchase_at":order.purchase_at.isoformat(),
                    "estimated_delivery_date":order.estimated_at.isoformat() if order.estimated_at else None,
                    "actual_delivery_date":order.delivered_at.isoformat() if order.delivered_at else None,
                    "outcome":order.outcome.value,"comparison":"actual calendar date > estimated calendar date",
                    "source_row":order.source_row,"reviewed_by":reviewer_id,"causal_attribution":False,
                    "seller_ids":sellers,"multi_seller":len(sellers)>1}
                delivery_relation=RelationFact(fact_id=fact_id,tenant_id=tenant_id,relation_type="OLIST_DELIVERY_OUTCOME",
                    subject_id=order.order_id,object_id=delivery_id,attributes=attrs,observed_at=order.delivered_at.isoformat() if order.delivered_at else order.purchase_at.isoformat(),review_status="APPROVED")
                self._review_fact(reviewer,delivery_relation,document_id=doc_id,source_file="olist_orders_dataset.csv",
                    source_row=order.source_row,source_text=specs_by_order[order.order_id][1][4],action=ReviewAction.APPROVE); facts+=1
                ev_id=_id("ev",doc_id,str(order.source_row)); content=(f"order row {order.source_row}: status={order.status}; estimated={attrs['estimated_delivery_date']}; actual={attrs['actual_delivery_date']}")
                self.repository.upsert_evidence(Evidence(evidence_id=ev_id,tenant_id=tenant_id,document_id=doc_id,chunk_ref=f"row:{order.source_row}",
                    content=content,source_group=f"olist-release:{self.dataset_version}",observed_at=order.delivered_at.isoformat() if order.delivered_at else order.purchase_at.isoformat(),review_status="APPROVED"))
                self.repository.link_evidence_to_fact(ev_id,fact_id,EvidenceType.SUPPORTS,tenant_id); evidence+=1
                self.repository.link_evidence_to_fact(ev_id,customer_fact,EvidenceType.SUPPORTS,tenant_id)
                for row_number,row in items[order.order_id]:
                    item_id=f"{order.order_id}:{row['order_item_id']}"; seller_id=row["seller_id"]; product_id=row["product_id"]
                    for entity_id,entity_type in ((item_id,"olist_order_item"),(seller_id,"olist_seller"),(product_id,"olist_product")):
                        self.repository.upsert_entity(Entity(entity_id=entity_id,tenant_id=tenant_id,entity_type=entity_type,canonical_name=entity_id,attributes={"dataset_version":self.dataset_version})); entities+=1
                    item_ev_id=_id("ev",items_doc_id,str(row_number))
                    self.repository.upsert_evidence(Evidence(evidence_id=item_ev_id,tenant_id=tenant_id,document_id=items_doc_id,
                        chunk_ref=f"row:{row_number}",content=f"item row {row_number}: order={order.order_id}; item={row['order_item_id']}; product={product_id}; seller={seller_id}",
                        source_group=f"olist-release:{self.dataset_version}",review_status="APPROVED")); evidence+=1
                    for relation,subject,obj in (("ORDER_CONTAINS_ITEM",order.order_id,item_id),("ITEM_SOLD_BY_SELLER",item_id,seller_id),("ITEM_REFERENCES_PRODUCT",item_id,product_id)):
                        link_id=_id("fact",tenant_id,self.dataset_version,relation,subject,obj)
                        item_relation=RelationFact(fact_id=link_id,tenant_id=tenant_id,relation_type=relation,
                            subject_id=subject,object_id=obj,attributes={"source_file":"olist_order_items_dataset.csv","source_row":row_number,
                            "dataset_version":self.dataset_version,"causal_attribution":False,"reviewed_by":reviewer_id},review_status="APPROVED")
                        self._review_fact(reviewer,item_relation,document_id=items_doc_id,source_file="olist_order_items_dataset.csv",
                            source_row=row_number,source_text=f"item row {row_number}: order={order.order_id}; item={row['order_item_id']}; product={product_id}; seller={seller_id}",
                            action=ReviewAction.APPROVE); facts+=1
                        self.repository.link_evidence_to_fact(item_ev_id,link_id,EvidenceType.SUPPORTS,tenant_id)
                if existed:
                    # Upserts repair only absent pieces and preserve stable IDs,
                    # original reviewer metadata, and historical review events.
                    entities,facts,evidence=before
                    reconciled.append(order.order_id)
                else:
                    imported.append(order.order_id)
            except Exception:
                # Stop on an unexpected write failure rather than approving more rows.
                raise
        elapsed=perf_counter()-started
        return ImportSummary(tenant_id,self.dataset_version,limit,len(imported),entities,facts,evidence,errors,
            elapsed,len(imported)/elapsed if elapsed else 0,reviewer_id,True,tuple(imported),tuple(duplicates),tuple(reconciled))

    def lookup(self, tenant_id: str, order_id: str) -> dict:
        facts=self.repository.find_facts(tenant_id,subject_id=order_id,relation_type="OLIST_DELIVERY_OUTCOME")
        if not facts: raise KeyError("order unavailable in tenant scope")
        fact=facts[-1]; support,_=self.repository.get_fact_evidence(fact.fact_id,tenant_id)
        if not support: raise KeyError("order source is unavailable or withdrawn")
        item_facts=self.repository.find_facts(tenant_id,subject_id=order_id,relation_type="ORDER_CONTAINS_ITEM")
        item_ids=[item.object_id for item in item_facts]
        sellers=sorted({link.object_id for item_id in item_ids for link in
                        self.repository.find_facts(tenant_id,subject_id=item_id,relation_type="ITEM_SOLD_BY_SELLER")})
        return {"mode":"HISTORICAL_FACTUAL","order_id":order_id,"outcome":fact.attributes["outcome"],
            "status":fact.attributes["status"],"estimated_delivery_date":fact.attributes["estimated_delivery_date"],
            "actual_delivery_date":fact.attributes["actual_delivery_date"],"causal_attribution":False,
            "fact_id":fact.fact_id,"item_ids":item_ids,"seller_ids":sellers,
            "multi_seller":len(sellers)>1,"sources":[{"document_id":e.document_id,"row":e.chunk_ref,
            "source_file":e.document_title,"content_hash":e.content_hash,"source_group":e.source_group} for e in support]}

    def source_order_row(self, tenant_id: str, order_id: str) -> dict:
        """Fetch a tenant-authorized source projection, retaining the original row locator."""
        result=self.lookup(tenant_id,order_id)
        current_hash=self.dataset.content_hash("olist_orders_dataset.csv",refresh=True)
        if current_hash!=result["sources"][0]["content_hash"]:
            raise KeyError("source file hash no longer matches imported evidence")
        row_number=int(result["sources"][0]["row"].split(":",1)[1])
        for source_row,row in self.dataset.rows("olist_orders_dataset.csv"):
            if source_row==row_number and row["order_id"]==order_id:
                return {"source_file":"olist_orders_dataset.csv","source_row":row_number,
                        "dataset_version":self.dataset_version,"file_sha256":current_hash,
                        "columns":{key:row[key] for key in ("order_id","order_status","order_purchase_timestamp",
                            "order_delivered_customer_date","order_estimated_delivery_date")}}
        raise KeyError("source row no longer matches imported evidence")

    def prospective_snapshot(self, tenant_id: str, order_id: str, mode: Snapshot) -> dict:
        order=next((o for o in self.dataset.orders() if o.order_id==order_id),None)
        if order is None or self.repository.get_entity(order_id,tenant_id) is None: raise KeyError("order unavailable in tenant scope")
        if mode is Snapshot.DELIVERY_COMPLETED: raise ValueError("prospective prediction cannot use delivery-completed snapshot")
        # The published delivery fact contains the final outcome and is never a
        # pre-delivery observation, even if a generic retrospective graph query sees it.
        decision_timestamp={Snapshot.PURCHASE:order.purchase_at,Snapshot.APPROVAL:order.approved_at,
            Snapshot.CARRIER_HANDOFF:order.carrier_at}[mode]
        return {"mode":"PROSPECTIVE_POMDP","claim_type":"PROSPECTIVE_RISK",
                "status":"INSUFFICIENT_MODEL","prediction_timestamp":decision_timestamp.isoformat() if decision_timestamp else None,
                "decision_time":mode.value,"features":order.snapshot(mode),
                "visible_delivery_outcome_facts":[],
                "outcome_hidden":True,"probability_late":None,"decision":"ABSTAIN",
                "model_version":None,"calibration_status":"NOT_APPROVED",
                "model_status":"NO_APPROVED_OLIST_MODEL",
                "investigation_actions":[],
                "reason":"An approved temporal Olist domain model is required before an order-level POMDP answer."}
