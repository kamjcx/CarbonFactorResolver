# CFR Review Workflow State Machine v1

Status: **FROZEN** for PR-C (`codex/review-workflow-state-machine-v1`).

This contract governs only human review decisions and immutable locking. It does
not change retrieval, ranking, semantic matching, candidate identity, catalog
content, factor values, qualification, or the public resolve API.

## States

A resolution run has one of three review states:

- `OPEN`: no candidate has been approved and the resolution is not locked.
- `SELECTED`: exactly one candidate has an `APPROVED` decision. Other candidates
  may independently have `REJECTED` decisions.
- `LOCKED`: the selected candidate and its approval have been committed to an
  immutable `LockedResolution`.

Each candidate has at most one terminal human decision in a resolution run:
`APPROVED` or `REJECTED`. A request can have at most one approved candidate and
at most one lock.

## Legal transitions

- `OPEN -> OPEN`: reject any undecided candidate.
- `OPEN -> SELECTED`: approve one undecided candidate.
- `SELECTED -> SELECTED`: reject any other undecided candidate.
- `SELECTED -> LOCKED`: lock the approved candidate.
- An exact replay of a committed approve or reject operation returns the
  previously committed object without appending another trace event. A lock
  retry for the already locked candidate returns the canonical immutable lock;
  its original reviewer identity is never replaced by the retrying caller.

The order of independent decisions does not change lockability. In particular,
`approve A -> reject B -> lock A` and `reject B -> approve A -> lock A` are both
valid. Their append-only audit traces may differ in event order, while the same
candidate and decision bindings govern the final lock.

## Forbidden transitions

- Approving a rejected candidate or rejecting an approved candidate.
- Approving a second candidate in the same resolution run.
- Locking an unapproved candidate or a candidate different from the approved
  candidate.
- Any new or conflicting decision after lock.
- Reusing the same candidate decision with a different status, reviewer, note,
  or approval mode.
- Committing against an explicitly supplied stale trace revision.

All conflicts fail closed with stable domain errors. The administration API maps
state conflicts and stale revisions to stable HTTP 409 reason codes and never
returns internal exception text.

## Integrity bindings

Every decision remains bound to the exact candidate digest, recommendation
digest and revision, database anchor, semantic registry anchor, policy anchor,
verified reviewer identity, and the append-only trace prefix created by that
decision.

A later legal decision may extend the trace but cannot invalidate an earlier
approval. Locking verifies the approval's recorded trace revision and chain hash
against the corresponding immutable prefix of the current trace. Rewritten,
missing, or non-prefix history fails closed.

## Concurrency and retry

The store is the atomic authority for decision and lock commits.

- Compare-and-set checks cover the recommendation digest and trace revision.
- An explicit expected revision is strict: a mismatch raises
  `STALE_REVIEW_REVISION` and is not retried.
- Without an explicit revision, the engine may retry a bounded number of times
  after a concurrent legal trace append.
- Concurrent exact duplicate operations converge on one stored decision or lock.
- Concurrent conflicting approvals have one winner; all other attempts fail
  closed. Double lock is impossible.
- Reconstructing the engine over the same store preserves state and permits the
  next legal transition.

## Administration API identity

Review mutations exist only on the isolated administration application. Request
bodies do not accept a reviewer identity. The reviewer is always the
`actor_id` supplied by the verified authorization context. The public
`create_app` surface remains read/resolve-only and unchanged.
