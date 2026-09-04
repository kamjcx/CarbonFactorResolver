# Evidence and generated-artifact policy

This directory preserves compact, public, reviewable evidence that binds an evaluation claim
to an immutable first run, manifest, hash, report, or adjudication. It is not a dumping ground
for every local test output.

## 1. Must remain versioned

Keep these artifacts in Git because removing or rewriting them would break an audit chain:

- frozen benchmark contracts and answers under `data/benchmarks/`;
- project-authored public fixtures under `data/fixtures/` that are required to replay a gate;
- first-run manifests, raw results, Bad Case records, reports, and manifest errata under
  `evidence/`;
- failed RC and sealed first-run records, including NO-GO evidence;
- versioned adjudications that explain why a historical contract was retained or superseded.

These files are immutable evidence. New findings are recorded in a new version, erratum, or
adjudication; historical answers and failed results are not edited to improve metrics.

## 2. Release attachments

Publish artifacts that are useful for release verification but need not accumulate in the
source tree as GitHub Release assets:

- wheel and source distribution;
- release manifest and `SHA256SUMS.txt`;
- Docker image digest or provenance record;
- large reproducible performance output, post-fix reruns, or demo traces when the committed
  first-run evidence and generator are already sufficient for auditability.

Each attachment should be content-hashed and bound to the release tag and commit SHA.

## 3. Local generated output

Keep routine reruns, scratch exports, coverage files, HTML reports, caches, diagnostics, and
temporary performance measurements under `outputs/`, `evidence/**/_local/`, or
`evidence/**/scratch/`. These paths are ignored and must not be cited as release evidence.

Before promoting a local result to versioned evidence, freeze its contract, give it a stable
versioned path, record the environment and commit, and add a SHA-256 manifest. Do not use
names such as `latest`, `rerun`, or `final-final` for authoritative evidence.

## Current repository classification

No existing evidence file was moved or deleted during the portfolio README cleanup. The
review found no duplicate display copy that could be removed without weakening the preserved
audit history. Large JSON evidence is marked as generated for GitHub presentation, while its
raw bytes and Git history remain unchanged.

Detailed results and their limitations are summarized in [Evaluation](../EVALUATION.md).
