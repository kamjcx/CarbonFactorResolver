# CFR Catalog–Candidate–Approval–Lock–Trace Integrity Contract

Status: `FROZEN` for PR3  
Schema versions: `cfr.catalog/v2`, `cfr.decision/v1`, `cfr.trace/v1`, `cfr.lock/v1`

## Purpose

This contract makes the selected factor and its evidence a content-addressed
decision. A stable record ID, catalogue name, source version or approval row is
not sufficient by itself. Every transition binds the exact bytes and policy
anchors that produced the decision.

## Catalogue contract

A v2 catalogue response contains:

```json
{
  "catalog_version": "publisher-release-id",
  "database": {
    "name": "publisher artifact name",
    "sha256": "optional artifact SHA-256"
  },
  "manifest": {
    "schema_version": "cfr.catalog/v2",
    "catalog_content_sha256": "SHA-256 of canonical records",
    "publisher_id": "stable publisher identifier"
  },
  "records": []
}
```

The resolver recomputes `catalog_content_sha256`. It rejects a mismatch with
`CatalogIntegrityError`. It never treats `publisher_id` as verified identity.
Publisher identity becomes verified only when a signature is present and a
deployment-supplied signature verifier accepts it. A signature without a
configured verifier is rejected.

Canonicalization uses the complete whitelisted record schema, explicit nulls,
type-preserving normalized decimal values, sorted object keys, stable ordering
for records and semantically unordered lists, UTF-8, and compact JSON. Unknown
v2 record fields fail closed so a future result-driving field cannot silently
fall outside the digest.

`database.sha256` remains the optional source artifact identity.
`manifest.catalog_content_sha256` is the authoritative record-content identity.
Both are retained in `DatabaseVersionAnchor`.

## Dataset-policy binding

Every `CatalogDatasetPolicy` that can inherit evidence, lower source priority,
or supply a production approval ID must declare the exact
`catalog_content_sha256` to which it applies. Matching names, standards,
categories, labels or source versions without that digest are insufficient.
An unbound policy does not apply.

## Decision binding

`SourceRecord.content_sha256` covers numeric value and unit, material identity,
boundary/modules, geography, year, form, composition, process, factor kind,
subject type, quality/admission state, declared product, evidence locator/hash,
and normalized metadata.

`Candidate.content_sha256` additionally covers ranking inputs and output,
qualification limitations, result tier, gaps, transformations, parameters,
assumptions, warnings and factor-application preview fields.

`Recommendation.content_sha256` covers its revision, status, all candidate
digests, follow-up decision, reason codes, review channels and the exact:

- catalogue anchor digest;
- semantic-registry anchor digest;
- deployment-policy anchor digest.

## Approval and lock compare-and-set

An approval is valid only when it binds:

- candidate content digest;
- recommendation content digest and revision;
- catalogue, registry and policy anchors;
- live trace revision and chain digest;
- reviewer identity.

Legacy approvals lacking these fields may be inspected but cannot lock. The
store atomically compares the expected recommendation and trace revision before
committing one approval event. At most one approved candidate exists for a
request.

Locking repeats all eligibility checks, validates every approval binding, then
uses compare-and-set against the current recommendation and trace. Candidate
content changes (including `1.2` to `12.0`), recommendation revision changes, or
anchor changes fail closed.

## Live trace and locked evidence

`ResolutionTrace` remains appendable. Every entry includes the previous hash
and its own content hash. Verification detects content mutation, deletion and
reordering.

`LockedResolutionEvidenceSnapshot` is a separate immutable object. Locking
freezes the exact trace revision, chain digest, anchors and canonical entry
bytes. Later live annotations do not change the snapshot bytes or SHA-256.

## Migration and compatibility

- Legacy catalogue payloads without `manifest` are read through an explicit
  unverified migration path. CFR recomputes their content digest, labels the
  publisher `unverified-legacy`, and does not infer publisher verification.
- Legacy `database.sha256` values remain artifact/version anchors; they are not
  reinterpreted as v2 record-content digests.
- Legacy or unbound dataset policies no longer grant inherited formal evidence,
  production approval or priority.
- Legacy approvals without decision digests fail closed at lock time. A caller
  must re-resolve against a v2 catalogue and obtain a new human approval.
- Locked v1 objects are not silently rewritten. A persistent store adapter must
  migrate them explicitly or reject them; the in-memory reference store rejects
  incomplete objects.

## Store adapter requirements

Production adapters implementing `ResolutionStorePort` must provide equivalent
transactional semantics to the in-memory reference adapter:

1. unique resolution run per `request_id`;
2. append-only trace revision with prefix verification;
3. atomic approval plus trace append;
4. one approved candidate per request;
5. atomic lock plus trace append using expected recommendation digest and trace
   revision;
6. immutable locked evidence bytes and digest.

Database implementations should enforce these rules with unique constraints,
row revisions and a transaction (`UPDATE ... WHERE revision = ?` or an
equivalent compare-and-set primitive).

