# Evaluation gate audit — main 5155a68

This read-only baseline was captured before changing evaluator or CI gate code. Resolver
runtime code, candidate IDs, factor values, ranking, qualification, and frozen answers were
not changed.

## Bound state

| Item | SHA-256 / commit |
|---|---|
| `main` | `5155a6829fcdd521f04359263f543245a1c6b03f` |
| `pyproject.toml` | `cad796270cfad81e3f59e6dd36c6b5e3d3fc28c4563e5c63f6a7d5350555a2c1` |
| `uv.lock` | `63078667b69a992bda8b243e568a200f376bc79395eaec3a291ce3e97149adf1` |
| Autonomous generated contract | `5882e4de5b7831bc757eb2e0c3ab3cf25026773035f6bf7ead647f00417d4b6f` |
| Portfolio challenge | `e99858e99c735ee334d1015364edf257dce12080c8e40a3d8e20acf16ab5b498` |
| Combined portfolio catalogue | `328e433dc39c539f231bad643478266880f34a95f630eb808e5eb114f31b90a4` |

The portfolio and committed audit-artifact hashes use canonical LF/text or canonical JSON
hashing rules; raw filesystem hashes may differ across line-ending platforms.

## Autonomous evaluation result

- execution completed;
- process exit before gate repair: `0`;
- raw `hard_gates_pass`: `false`;
- raw Bad Cases: `100`;
- unresolved after validating six versioned adjudications: `94`;
- raw forbidden candidate escapes: `6`;
- unadjudicated forbidden escapes: `0`;
- Direct Top-1: `241/259` (`93.05%`);
- Recall@5: `257/259` (`99.23%`);
- MORE_INPUT recall: `5/5` (`100%`);
- deterministic replay: `414/414` (`100%`).

The repaired CLI returns exit code `2` for this unchanged quality result and still writes the
machine-readable inventory and report.

## Root-cause inventory

| Root cause | Count | Risk |
|---|---:|---|
| geography | 3 | HIGH; versioned accepted limitation |
| year / temporal | 3 | HIGH; versioned accepted limitation |
| boundary | 3 | CRITICAL |
| subject | 1 | CRITICAL |
| unit | 2 | CRITICAL |
| generic exact / alias ambiguity | 16 | HIGH |
| provenance | 60 | HIGH |
| catalogue-coverage status contract | 12 | MEDIUM |
| declared product | 0 | — |
| expected MORE_INPUT but recommended | 0 | — |
| expected recommendation but asked | 0 | — |
| oracle / preset error | 0 | — |
| stale report | 0 runtime cases; 3 stale hard-coded portfolio findings removed | MEDIUM |

The six accepted limitations remain visible in raw failure and forbidden-escape counts. Their
machine adjudications bind evaluator contract, case, input, reason, reviewer/authority, and
effective version; they are excluded only from the enforceable unadjudicated-escape count.

## Portfolio validation result

- execution completed;
- process exit before gate repair: `0`;
- full-CFR decision accuracy: `53/60` (`88.33%`);
- MORE_INPUT positive recall: `4/10` (`40%`);
- Top-1 and Recall@5 on retrieval cases: `40/40` (`100%`);
- wrong candidate rate: `6/46` (`13.04%`);
- forbidden, boundary, subject, and runtime-error counts: `0`.

The repaired portfolio gate therefore returns exit code `2`. Its findings are generated from
the current JSON rather than the three obsolete fixed statements about already-repaired API,
exception-redaction, and approval-state defects.

Full per-case data: [bad_case_inventory.json](bad_case_inventory.json). Human summary:
[BAD_CASE_REPORT.md](BAD_CASE_REPORT.md).
