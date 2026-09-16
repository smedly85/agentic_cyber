# Semantic call-graph calibration fixtures

These small C programs are instrument calibration inputs, not members of the
historical CVE population or generated-code population.  `fixtures.json`
records the expected semantic behavior.  The fixtures deliberately cover
direct calls, five forms of indirect dispatch, a multi-target may-callsite,
recursion, an unavailable external definition, multiple translation units,
duplicate internal-linkage names, and compiler failure.

The production flags are intentionally conservative: `-std=c11 -g -O0
-fno-inline -fno-builtin -fno-discard-value-names`, plus debug path remapping.
Every translation unit is compiled separately with `-emit-llvm -c`; multi-TU
fixtures are combined with the matching `llvm-link`.  No optimized source or
Tree-sitter graph is used by this calibration.
