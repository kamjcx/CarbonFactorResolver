# First-run Manifest Erratum

The immutable first execution started from clean commit
`fe4eee7101f4f53b463e65ba3edfd8e9f4641367`. The command explicitly ran
`git status --porcelain` before the evaluator and produced no output.

The preserved `manifest.json` nevertheless records `git_dirty: true` because evaluator
version `fe4eee7` sampled Git status after creating this untracked evidence directory. This
is a Manifest-timing defect, not a pre-existing code change. The raw generated contract,
results, Bad Cases and report are unchanged. Their hashes remain those in the original
Manifest.

The subsequent evaluator correction captures commit and dirty state before creating output
and adds `git_state_captured_before_output: true`. This erratum does not reclassify, rerun or
overwrite the first-run results.
