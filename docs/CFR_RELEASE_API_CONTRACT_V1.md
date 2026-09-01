# CFR Public Error Contract v1

Public endpoints never reflect raw exception messages. Stable codes are:

| Endpoint | Code | Meaning |
|---|---|---|
| `POST /api/v1/resolve` | `INVALID_RESOLUTION_REQUEST` | Structured request validation failed. |
| `POST /api/v1/benchmarks/runs` | `BENCHMARK_RUN_FAILED` | Offline benchmark execution failed. |
| `GET /api/v1/benchmarks/compare` | `BENCHMARK_COMPARISON_FAILED` | Runs cannot be compared. |
| `GET /api/v1/connectors/health` | `HEALTH_PROBE_FAILED` | A connector probe failed; details remain server-side. |

Local catalogue `TimeoutError` and `ConnectionError` are captured in Trace by exception class
only. Resolution continues fail-closed and returns no invented candidate. A completed failed
resolution consumes its `request_id`; retry uses a new request ID.

