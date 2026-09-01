# CFR RC Evidence Rebase Map

PR #5 was rebased after PR #4 merged into `main`. Immutable raw first-run files retain the
Git SHA observed at execution; they are not rewritten. The following patch-equivalent commits
bind that historical evidence to the final PR branch:

| Evidence role | First-run/original SHA | Rebased equivalent |
|---|---|---|
| RC3 runtime freeze | `d5abf8e0c110e692e79d99d02f9e9d8de7347bb5` | `7e5adc9` |
| RC3 input commit | `fa96997c9c9cbc0df2c02a9319233a6c9b383502` | `efa6012` |
| RC4 runtime/evaluator freeze | `b21b8ea48a4ec400372db1621c5d3313f9fe7ca8` | `ee43a04` |
| RC4 input commit | `66836c7a932de32d7768ba3f2a9eec17f1b297c6` | `cd7298b` |
| RC5 runtime/evaluator freeze | `5f3d656c34a46c67d4ac737c8b312034568cb493` | `91c8e1d` |
| RC5 input commit | `1cd70614475aab2224c0c361c06ea7065031dfde` | `2bec843` |
| RC6 runtime/evaluator freeze | `1c8be4ca3ef0a1402a0ef343a024972e7a0e6320` | `e87f146` |
| RC6 input commit | `2d4cb669339908f5456643d1ebf94dcbf62b1f9a` | `702a8a2` |

`git range-diff` reports each pair as patch-equivalent (`=`). Release manifests and remote CI
bind the final branch SHA; preserved raw outputs bind the original execution SHA and input
hashes. This separation prevents falsifying historical evidence while keeping the release
lineage reproducible after the required rebase.
