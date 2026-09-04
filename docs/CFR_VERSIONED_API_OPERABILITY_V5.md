# CFR Versioned API and Operability Contract V5

## Stable HTTP surface

`/api/v1` remains the compatibility boundary. Successful resolution payloads retain their existing
shape. Every response adds `X-CFR-API-Version: 1.0` and a safe `X-Correlation-ID`; callers may supply
`X-Request-ID` or `X-Correlation-ID`, but an unsafe value is replaced rather than reflected.
The resulting request ID is passed into the Resolver and therefore identifies its stored result and
Trace. It is correlation, not authentication or authorization.

Request IDs are idempotency keys only within their authorized scope. CFR binds each key to the
canonical `ResolutionRequest` fingerprint under an asynchronous per-key lock. Same key plus the same
normalized request replays the stored result; same key plus different business input returns HTTP 409
`RESOLUTION_PAYLOAD_CONFLICT`. Concurrent identical submissions execute once, while concurrent
conflicting submissions produce one result and one stable conflict. Tenant/project ownership is
checked before any replay.

The reference implementation keeps fingerprint bindings and per-key locks in process memory. A
multi-worker or horizontally scaled deployment therefore needs a shared, atomic idempotency store;
cross-process replay guarantees are outside this portfolio runtime's current scope.

`POST /api/v1/resolve` accepts `application/json` (including `+json`) only. Stable errors retain the
compatible `detail.reason_code` and `detail.message` object and add `request_id`. Validation,
not-found, conflict, unavailable dependency and unhandled failure paths do not expose exception
messages, local paths, credentials, payload fragments or stack traces. The production OpenAPI has
no upload, multipart, benchmark, debug, full-trace or full-diagnostics route.

## Liveness and readiness

- `/healthz` answers only whether the process and HTTP loop are alive.
- `/readyz` requires an explicitly supplied engine plus every configured required probe.
- Optional connector failure returns HTTP 200 with aggregate status `degraded`; it does not declare
  the whole service unavailable.
- Required dependency failure returns HTTP 503 with `SERVICE_NOT_READY` and aggregate counts only.

The default production factory creates an empty, unready engine and never loads test fixtures.
Applications must inject their licensed/internal catalog engine and required probes. Demo data is
available only through explicit CLI/Compose `--demo` configuration. The admin app remains a separate,
authorized PR4 surface.

## Stable CLI surface

Standard output is exactly one JSON object for machine consumption. Human diagnostics go to standard
error and never include raw exception text. `--input-json -` accepts a UTF-8 structured request from a
pipeline; a file path is also supported. Resolution without an injected engine requires explicit
`--demo`. Formal `cfr resolve` always calls `resolve`, never `resolve_debug`; the legacy
`--min-score` spelling is retained only to return a stable invalid-request exit and cannot change the
deployment policy.

| Exit | Meaning |
|---:|---|
| `0` | direct/locked/reference-reviewable result, or successful non-resolution command |
| `2` | invalid command, JSON, file or structured request |
| `10` | `more_input_needed` |
| `11` | unresolved, supplier-data or process-model outcome |
| `70` | redacted internal failure |

## Migration from V4

Existing `/api/v1/resolve` JSON callers keep their response fields. They may begin recording the two
new response headers and should use `/readyz`, not `/healthz`, for traffic admission. Local demo users
must add `--demo` to `cfr resolve` and `cfr serve`; `docker compose` already does so explicitly. Scripts
must stop assuming every completed resolution exits zero and handle exit 10/11 as domain outcomes.
