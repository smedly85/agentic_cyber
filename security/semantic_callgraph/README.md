# Semantic static may-call graph backend

This is the official scientific call-depth backend. It replaces
syntax-derived scientific call depth, compiles each
C translation unit with Clang, links LLVM bitcode, invokes a dedicated SVF API
helper using AndersenWaveDiff, and computes unnormalised shortest-path depth
from a configured entry function.  It has deliberately **no Tree-sitter or
regex fallback**.

The primary pinned configuration is Clang/LLVM 21.1.8, SVF 3.4 commit
`67efb7745ce47b2b6853fd5696fc22c83d701e6c`, AndersenWaveDiff,
`-stat=false`, and `-ff-eq-base`. Direct and resolved-indirect may-call edges
each count once. Complete multi-target sets are retained, so reachability is a
static possibility rather than a guarantee of runtime execution. Nonnumeric
states remain explicit and are never imputed.

## Stable identity and mapping

The native helper uses LLVM debug metadata retained by `-g -O0`.  A C
definition is identified as `source/file.c::function`; this keeps equal
internal-linkage names in different translation units distinct.  Debug paths
are remapped to repository-relative POSIX paths, so identities and hashes do
not contain host checkout locations.  Callsites retain file, one-based line,
and LLVM's debug column.  A declaration without a definition is represented in
`external_calls`, not as a fabricated internal edge.

## Bitcode production

For each source, the orchestrator runs the equivalent of:

```text
clang -std=c11 -g -O0 -fno-inline -fno-builtin \
  -fno-discard-value-names -fdebug-compilation-dir=. \
  -fdebug-prefix-map=$SOURCE_ROOT=. -emit-llvm -c SOURCE -o TU.bc
```

Any fixture-specific preprocessor definitions and include paths are appended
verbatim and recorded.  Multi-TU inputs are combined with the matching:

```text
llvm-link TU0.bc TU1.bc ... -o linked.bc
```

`-O0` and `-fno-inline` preserve source-level call structure; `-g` preserves
definition/callsite mapping; `-fno-builtin` avoids silently replacing fixture
calls with compiler builtins.  Historical builds must supply their own frozen
defines, include paths, generated headers, and language standard.

## SVF API contract

The helper is based on upstream SVF's supported API sequence:

```text
LLVMModuleSet::preProcessBCs / buildSVFModule
SVFIRBuilder::build
AndersenWaveDiff::createAndersenWaveDiff
PointerAnalysis::getCallGraph / getIndCallMap
CallICFGNode::isIndirectCall
PointerAnalysis::getIndCSCallees
```

It emits JSON, never DOT or scraped diagnostic text.  Direct defined calls are
`direct` edges.  Every member of an SVF-resolved indirect target set is emitted
as an `indirect_resolved` edge carrying the same target-set size.  An empty set
is retained in `unresolved_indirect_callsites`.

The exact live helper invocation is:

```text
semantic-callgraph-svf -stat=false -ff-eq-base linked.bc
```

`-stat=false` keeps SVF statistics off the structured stdout channel.
`-ff-eq-base` models the C/LLVM layout rule needed when opaque-pointer IR
addresses a struct's first field through the base object. The points-to
algorithm remains AndersenWaveDiff; neither option selects targets or parses
human-readable graph output.

## Current isolated setup

The inventoried WSL toolchain is LLVM 21.1.8.  Repository-local SVF 3.4 commit
`67efb7745ce47b2b6853fd5696fc22c83d701e6c` explicitly supports LLVM 21 and 22
and its build script targets LLVM 21.1.0. Use the repository-local build; do
not alter system compiler packages:

```bash
bash scripts/setup_semantic_callgraph_svf.sh
```

The setup script pins CMake 3.31.6 and Ninja 1.11.1.3 in a local virtual
environment, checks out the exact SVF commit, adds the native helper as an SVF
tool, uses `/usr/lib/llvm-21`, and uses Z3 4.15.4 inside the checkout. Existing
CMake builds are reconfigured incrementally rather than removed. On this host,
the helper compiled and linked and all ten executable calibration fixtures
passed; the intentional compiler-failure fixture remained explicit. Hosts
without the helper still return `analysis_failure` with reason
`svf_unavailable`, and live SVF tests skip with that reason.
