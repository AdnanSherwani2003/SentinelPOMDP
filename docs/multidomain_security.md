# Multi-domain security boundary

- Tenant identity comes from the authenticated principal, never from a pack or URL.
- Listing, detail, review, activation and investigation all query the authenticated
  tenant partition.
- Authoring requires `domain-pack:manage`; approval/activation requires
  `model:approve` and reviewer/admin authority; execution requires
  `investigation:execute`.
- Pydantic rejects unknown configuration fields. Tool names, mapping data types and
  validation rules are allow-listed.
- No pack can supply Python, imports, shell, filesystem paths, executable expressions
  or unrestricted Cypher.
- Domain adapters receive the authenticated tenant and use parameterized repository
  interfaces. A procurement tool cannot run for Olist unless a server adapter and the
  approved pack both register it.
- Active evidence must have approved provenance. Withdrawn documents disappear from
  usable evidence without erasing audit history.
- Source groups prevent a copied or derived record from being counted as another
  independent witness.
- The LLM remains optional and untrusted. It cannot add tools, alter probabilities,
  approve packs, grant access, satisfy an evidence gate or override the planner.
- Durable domain validation uses the existing Implementation 18 queue, leases,
  fencing, cancellation and tenant-scoped job access; there is no second queue.
