# Contributing

Keep changes small, evidence-backed and compatible with CFR's structured-resolution scope.

1. Create a focused branch from current `main`.
2. Do not add licensed factor data, customer files, secrets, or local absolute paths.
3. Do not change frozen benchmark answers without a versioned adjudication record.
4. Add tests for public contracts, fail-closed behavior and deterministic replay.
5. Run `pytest`, Ruff, mypy, compileall, FactorBench and package build before opening a PR.
6. Explain any metric change with denominators and preserved before/after evidence.

Document parsing, footprint calculation, report generation and automatic factor approval belong
in upstream/downstream projects, not CFR runtime.

