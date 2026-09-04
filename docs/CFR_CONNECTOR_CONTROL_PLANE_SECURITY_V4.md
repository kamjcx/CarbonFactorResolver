# CFR connector and control-plane security v4

## Threat model

The structured external-source boundary treats discovery records, document URLs, redirect
locations, DNS answers, response bodies, and caller-supplied benchmark paths as hostile. Threats
include SSRF into cloud metadata or internal services, DNS rebinding, credential forwarding,
redirect laundering, memory/CPU exhaustion, path traversal, unbounded in-memory benchmark state,
and disclosure through errors, traces, health responses, or OpenAPI.

## Frozen deployment boundary

The production app created by `create_app` exposes structured JSON resolution, resolution-state
lookup, a readiness-only connector status, and the static portfolio surface. It does not expose
benchmark run/get/compare, debug resolve, full traces, or full diagnostics.

The explicit `create_admin_app` is a separate control-plane application intended for a separately
bound admin/dev port. Every sensitive operation calls an injected authorizer and requires an
`AuthorizationContext` containing actor, tenant, project, and the relevant permission. With no
authorizer, access fails closed. This is a gateway/IAM integration contract, not an assertion that
CFR implements enterprise identity management. Admin resolution ownership and benchmark runs are
partitioned by tenant and project; another scope receives a not-found response even when it holds
the same operation-level permission.

## Outbound connector invariants

- HTTPS is mandatory. Userinfo and non-HTTP schemes are rejected.
- The configured `OPENEPD_BASE_URL` origin is the only allowed origin by default. Extra document
  hosts must be explicitly allowlisted by deployment configuration and use the configured HTTPS
  port; an allowlisted hostname does not authorize arbitrary ports.
- Literal and DNS-resolved loopback, private, link-local, multicast, reserved, and unspecified
  IPv4/IPv6 addresses are rejected. Each hop produces a `ValidatedRoute`; a deployment transport
  marked with `bound_transport` must connect to one of that route's validated IPs while preserving
  the original hostname for TLS SNI and HTTP Host, then return the observed peer IP for comparison.
  Legacy fetchers without this binding contract do not make live health report `available`.
- Every redirect target and final URL is validated before the next request. Cross-origin redirects
  are rejected by default. An injected transport must not follow redirects itself; it returns one
  `redirect_to` hop and CFR follows it with newly generated per-origin headers.
- Authorization is generated per request and attached only when the target origin exactly matches
  the configured initial origin. It is never forwarded to an allowlisted document origin.
- The transport receives distinct connect and read timeout values. CFR additionally enforces one
  total timeout across asynchronous DNS resolution, connect/read, response consumption and every
  redirect hop, plus maximum streamed bytes, JSON depth and record bounds, document count, and
  redirect count. Timed-out worker threads cannot be forcibly terminated, so deployment transports
  must still honor their own connect/read budgets.
- Public errors use stable reason codes. Response bodies, Authorization/Bearer values, URL query
  strings, and internal addresses are not included in errors or public health output.

## Benchmark runner invariants

Admin benchmark execution requires both authorization and at least one explicit filesystem root.
The resolved path must remain under a root, be an existing `.jsonl` file, and fit the configured
byte ceiling. Symlinks are rejected and the validated bytes are copied once to an isolated
temporary snapshot before runner invocation, avoiding a second read of the caller-controlled path.
Empty roots, traversal, arbitrary files, and oversized datasets fail before runner invocation.
In-memory run retention is keyed by tenant, project and runner-provided run ID, so identical
deterministic IDs in different scopes cannot overwrite one another. Retention is bounded by both
item count and serialized bytes and evicts the oldest item in the process-local control-plane
store.

## Verification boundary

Security tests use injected transports, synthetic payloads, and local temporary files only. They
make no request to OpenEPD or another third-party service and contain no usable credential.
