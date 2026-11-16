# c-grep canonical functional corpus

This is the sole functional-corpus owner for `c-grep`, `rust-grep`, and
`py-grep`. It specifies a bounded fixed-byte substring utility, not general GNU
grep. Public cases live in `suites/linux.json.gz`; independently transformed
held-out cases live in `heldout/heldout_cases.json.gz`.

All expected results are freshly frozen in Linux/AMD64 Docker from GNU grep
3.12 through `tests/reference_generators/standard_grep_oracle.py`. The adapter
adds `-a -F`, pins `LC_ALL=C`, and orders recursive files by ascending raw
filename bytes. Bounded option rejection is specification-derived and recorded
as such. The legacy `tests/grep-test-suite` goldens are not copied.

`gen/inputs.json.gz` contains inputs only. `gen/generate.py` delegates to the
standard Docker freezer. Agent-visible bundles contain only allowlisted runtime
files and checkpoint-eligible public cases; no generator, oracle, manifest, or
held-out case is staged.
