# Structured Electricity Admission Adjudication

## Decision

**CLOSED FOR v0.14.1: remain blocked pending formal source evidence.**

Three deployment-side structured electricity records were reported as correctly recalled
but not admitted. Their licensed records, stable source IDs, complete declared-product
scope, lifecycle boundary, geography/year applicability and evidence anchors are not part
of this public repository. CFR therefore cannot independently prove that they satisfy all
qualification dimensions.

The release does not add them to a public fixture, fabricate missing metadata, lower an
admission threshold, or mark them approved. Continued blocking is the correct deterministic
outcome and is not a retrieval failure. The synthetic `pc:grid-electricity-cn` and other
public evaluation records are test fixtures only and do not approve deployment records.

## Required evidence for a future admission

- stable source ID and authorized catalogue/database anchor;
- exact factor kind and explicit `energy` subject;
- canonical impact/activity unit and value from the source record;
- declared product identifying the electricity carrier/mix;
- lifecycle boundary/modules, geography, year and applicability limits;
- source-quality status, document status and admission eligibility;
- source locator/hash and the applicable human approval record.

Only a new versioned catalogue record containing those fields may be reconsidered. Formal
factor admission remains independent of software-release QA and requires human approval.
