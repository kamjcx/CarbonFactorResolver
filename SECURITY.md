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

Operators remain responsible for TLS, authentication, authorization, rate limiting, protected
logging, secrets management, network policy and licensed data access.

