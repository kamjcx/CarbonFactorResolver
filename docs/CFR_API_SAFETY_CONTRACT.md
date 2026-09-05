# CFR Public API Safety Contract

Status: PR-A candidate contract
API version: `1.0`

## Deployment boundary

The default `create_app` is a JSON-only factor-resolution data plane. It is suitable only for a
trusted single scope or behind a gateway that enforces identity, tenant/project scope, authorization,
rate limits and network policy. `create_app` does not implement multi-tenant authorization and this
contract must not be cited as evidence that a complete identity system exists.

The separately constructed `create_admin_app` is an admin/developer control plane. It requires an
injected authorizer for sensitive operations and must run on a separately protected interface. Full
traces and diagnostics are available only through this explicit surface.

## Request contract

`POST /api/v1/resolve` accepts one closed JSON `ResolutionRequestDTO`. Unknown fields and explicit
JSON `null` values are rejected;
`material_name` and `quantity` are required. Strict validation rejects:

- booleans or strings used as numeric quantity, year or `top_k` values;
- null or blank `material_name`;
- NaN and positive/negative infinity;
- unsupported `subject_type` values;
- explicit null, empty, partial, extra-field or incorrectly nested unit-conversion evidence;
- the debug-only `min_score` field and every other unknown property.

The validated DTO is converted to an explicit mapping and then independently validated by the
domain `ResolutionRequest`. HTTP validation does not replace domain validation.

The endpoint accepts `application/json` and structured `+json` media types only. It has no file,
multipart, `UploadFile`, PDF, DOCX, spreadsheet or OCR capability.

## Public response contract

Production resolve, idempotent replay and `GET /api/v1/resolutions/{request_id}` all use
`PublicRecommendationDTO`. It is built from an allowlist and contains:

- request status, follow-up decision, message and stable reason codes;
- formal `candidates` and `reviewable_candidates` reference summaries;
- factor value/unit, result tier, score, limitations, assumptions and warnings;
- a bounded source-evidence summary without local/runtime locators or arbitrary metadata;
- `MORE_INPUT` questions and public confidence summaries.

It never serializes the full domain recommendation and therefore excludes full trace entries,
diagnostic candidates, internal qualification/conversion metadata, runtime timestamps, mutable
revisions, catalog/registry/policy anchors, accounting assignments and transformation internals.
The admin debug endpoint deliberately retains the full diagnostic response as a separate contract.

## Error contract

Every handled validation/HTTP failure and every unhandled failure returns a stable JSON envelope.
The readiness 503 variant adds only three documented integer counters: `required_total`,
`required_unavailable` and `optional_unavailable`.

The shared envelope is:

```json
{
  "api_version": "1.0",
  "request_id": "opaque-safe-id",
  "correlation_id": "opaque-safe-id",
  "error": {
    "reason_code": "REQUEST_VALIDATION_FAILED",
    "message": "request validation failed"
  },
  "detail": {
    "reason_code": "REQUEST_VALIDATION_FAILED",
    "message": "request validation failed"
  }
}
```

`detail` remains an API-v1 compatibility alias of `error`. Responses also carry
`X-CFR-API-Version`, `X-Request-ID` and `X-Correlation-ID`. Caller IDs that fail the safe opaque-ID
syntax are replaced rather than reflected. Internal exception text, paths, credentials and payloads
are never returned.

Expected malformed input returns 400, 415 or 422; request-ID scope/payload conflicts return 409;
unhandled failures return a redacted 500 envelope. Status codes do not change the response identity
or disclosure contract.
