# Security Policy

## Supported version

Security fixes are applied to the latest tagged portfolio release. This project is a research
prototype and does not promise production support or service-level response times.

## Reporting

Do not open a public issue containing credentials, licensed datasets, customer evidence, or an
exploitable trace. Use GitHub's private security advisory workflow for this repository.

## Security boundaries

- `/api/v1/resolve` accepts JSON only; there is no file-upload or OCR surface.
- Public failures use stable reason codes and do not reflect internal exception messages.
- Catalogue transport failures fail closed and cannot create approvable candidates.
- Formal approval remains human-controlled; rejected candidates cannot be re-approved in the
  same immutable resolution run.
- Default and API installs exclude document-parsing dependencies.
- Production images exclude local outputs, credentials, databases, documents and build tools.
- Generic runtime code contains no customer-specific catalog-priority default. A policy bundle that
  grants production approval is accepted only when bound to the exact catalog content and verified
  by a deployment-supplied signature verifier.
- Live structured-source URLs are HTTPS-only, same-origin by default, DNS/IP checked against
  non-public address ranges, and revalidated at every declared redirect hop. DNS resolution is
  included in the total request budget; connector response size, complexity, document count and
  elapsed time are bounded.
- The production app exposes no benchmark execution, debug resolution, full trace or full
  diagnostics routes. Those routes exist only on an explicit admin/dev app and fail closed unless
  a deployment authorizer supplies actor, tenant, project and permission context. Admin resolution
  and benchmark objects are tenant/project scoped.

Operators remain responsible for gateway authentication, authorization policy implementation,
rate limiting, protected logging, secrets management, egress network policy and licensed data
access. CFR defines an injectable authorization port; it does not claim to provide enterprise IAM.
The public repository also does not provide a production signing trust root, key rotation,
multi-instance atomic idempotency store, registry attestation, monitoring, recovery, or SLA.

