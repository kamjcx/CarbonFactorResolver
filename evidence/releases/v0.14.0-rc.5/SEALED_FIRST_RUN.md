# CFR v0.14.0-rc.5 Sealed First Run

Status: **NO-GO**

Runtime/evaluator freeze: `5f3d656c34a46c67d4ac737c8b312034568cb493`.
Input commit: `1cd70614475aab2224c0c361c06ea7065031dfde`.
Raw output: `outputs/sealed_rc5_first_run.json`; SHA-256
`5fb788af1a6a0b52edfefea890762bf7765e50e6a411b9c0737b94bba6788892`.

All 48 requests returned HTTP 400 before retrieval because the sealed catalogue database
anchor contained 62 rather than 64 lowercase hexadecimal characters. The evaluator reported
0/48 full case contracts, zero retrieval recall, zero Top-1, no HTTP 500, and no safety
escape. No RC5 input or expectation is changed.

RC6 adds a pre-runtime catalogue-anchor validator so this class of malformed sealed input is
rejected before consuming a first run, and requires a wholly new dataset.
