# CFR Public Error Contract v1

Public endpoints never reflect raw exception messages. Stable codes are:

| Endpoint | Code | Meaning |
|---|---|---|
| `POST /api/v1/resolve` | `INVALID_RESOLUTION_REQUEST` | Structured request validation failed. |
| admin/dev `POST /api/v1/benchmarks/runs` | `BENCHMARK_RUN_FAILED` | Offline benchmark execution failed. This route is absent from the production app. |
| admin/dev `GET /api/v1/benchmarks/compare` | `BENCHMARK_COMPARISON_FAILED` | Runs cannot be compared. This route is absent from the production app. |
| `GET /api/v1/connectors/health` | `HEALTH_PROBE_FAILED` | A connector probe failed; details remain server-side. |

The production health response is readiness-only and contains no connector host, credential,
filesystem path, or exception detail. Full connector diagnostics, resolution traces, debug
resolution and benchmark execution are available only from `create_admin_app` on a separately
bound admin/dev port. Without an injected authorizer these routes return
`ADMIN_AUTHORIZATION_REQUIRED` and perform no operation.

Local catalogue `TimeoutError` and `ConnectionError` are captured in Trace by exception class
only. Resolution continues fail-closed and returns no invented candidate. A completed failed
resolution consumes its `request_id`; retry uses a new request ID.

