# Olist graph model

The graph maps only relationships present in the CSVs:

    OlistOrder --ORDER_CONTAINS_ITEM--> OlistOrderItem
    OlistCustomer --CUSTOMER_PLACED_ORDER--> OlistOrder
    OlistOrderItem --ITEM_SOLD_BY_SELLER--> OlistSeller
    OlistOrderItem --ITEM_REFERENCES_PRODUCT--> OlistProduct
    OlistOrder --OLIST_DELIVERY_OUTCOME--> DeliveryEvent

An order may have many items and sellers. The delivery outcome remains order-level. Every related fact explicitly carries causal_attribution: false; the graph never creates SELLER_CAUSED_DELAY.

The current bounded importer publishes customers, orders, delivery events, items, sellers, products, and the listed relations. Payment and review schemas are inventoried but are intentionally not published in the first prediction channel: payments can multiply joins and reviews occur after delivery.

Graph identity is the tuple (tenant_id, entity_id/fact_id). Repository queries always require the trusted tenant. An order imported into tenant_olist_research cannot be retrieved from another tenant.
