# Rust cp and mv lineage experiments

These extend the existing manifest, prompt, stage-bundle, repair and promotion
architecture. There is no seed implementation, Cargo project, implementation
template or reference implementation. Checkpoint 000 creates one Rust 2021
file; later checkpoints inherit only their own lineage's preceding candidate.

| Utility | Checkpoints | Future source | Semantic anchor |
|---|---|---|---|
| cp | 000 base → 001 force → 002 interactive → 003 recursive | src/new_cp/new_cp.rs | copy_path |
| mv | 000 base → 001 interactive → 002 force | src/new_mv/new_mv.rs | move_path |

These source paths are declarations, not existing files. The controller creates
the parent directory, but no placeholder candidate. Builds use the manifest's
direct rustc command. Capture retains the source basename, including .rs; the
existing per-lineage seed checks and SHA-256 provenance remain in force. Empty
archival analysis baselines are controller metadata, not agent-visible seeds.

Every prompt requires its anchor on the actual operation path from main. Later
prompts prohibit renaming/removing it. No helper count or artificial depth is
prescribed. Prompt requirements do not claim semantic reachability verification.

## Functional evaluation

The chmod suite is the structural template: native frozen cases, utility-local
engine, cumulative flag-filtering runner, judge wrapper, offline generator and
compressed held-out corpus. The filesystem extension compares complete path
sets, object types, content SHA-256, symlink targets and selected ordinary modes,
alongside stdin, stdout, stderr class and exit status. It contains no cp/mv
behavior model; an external oracle generates all expected outcomes.

GNU Coreutils **9.11** is the independent functional oracle. Explicit
CP_ORACLE_BIN/MV_ORACLE_BIN environment variables select it; exact program/version
checks fail closed. Ordinary judging needs no oracle. Generation runs twice,
requires byte-identical results, uses gzip mtime zero, and hashes both corpora.

The bounded contract supports POSIX Darwin/Linux, same-filesystem operations,
pipe stdin, locale C and umask 022. It excludes EXDEV fallback, trailing-slash
symlink operands, case-fold collisions, Unicode-normalization-sensitive names,
ownership/ACL/xattr/special-bit preservation, timestamps and allocation metadata.
APFS creates only valid UTF-8 filenames, as verified in [Apple's APFS FAQ](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/APFS_Guide/FAQ/FAQ.html).
The non-UTF-8 frozen case therefore uses a missing raw-byte operand and checks
normal error handling, not successful creation of an APFS-incompatible name.
Existing raw-byte names remain in the implementation contract where supported;
the formal corpus does not claim full coverage of that Linux-only fixture.
Stderr wording and host errno text are not compared. Permission tests require
non-root execution. Darwin is the formal host; run suite self-checks there before
collection. Linux self-passes do not claim Darwin validation.

GNU 9.11 option-handler inspection and the [cp manual](https://www.gnu.org/software/coreutils/manual/html_node/cp-invocation.html)
confirm independent force/interactive behavior; the [mv manual](https://www.gnu.org/software/coreutils/manual/html_node/mv-invocation.html)
specifies the last-option relationship. C-locale affirmative answers begin with
ASCII y/Y; leading spaces are not affirmative. Declines contribute exit status
1 under the verified 9.11 oracle. These are explicitly tested.

Only stage_test_bundle.py prepares agent-visible tests. Generators, complete
manifests, READMEs, oracle locations and held-out cases stay out. The existing
heldout_judge.py invokes the same runner after repair; hidden results never
become repair feedback. Existing public promotion semantics remain unchanged:
intermediate held-out failures are recorded without blocking the next public
checkpoint. Controller-only boundary probes test forbidden option aliases.

## Separate historical vulnerability provenance

GNU Coreutils is the **functional behavioral oracle**, not the historical Rust
vulnerability source. **uutils/coreutils** is the separate planned historical
source. Manifests, resolved plans and lineage metadata retain separately named
provenance objects. No affected revision or vulnerability mapping is claimed.
No uutils source is downloaded, embedded or staged into generation sandboxes.

The future workflow is:

    known uutils vulnerability
      → pinned affected uutils revision
      → vulnerable Rust function(s)
      → Rust semantic call graph
      → shortest resolved depth from the utility entry point
      → vulnerability-depth dataset

The future structural backend must support both generated single-file Rust
candidates and pinned historical uutils trees: Rust compilation/LLVM
representation, semantic call graphs, application-function filtering, shortest
entry depth and attack-surface analysis. Standard-library/runtime functions must
not automatically count as application functions; that scientific definition
remains to be specified. Unknown/unresolved locations stay explicit.

## Analysis limitations

Functional generation, validation, capture and inheritance are supported. The
C Tree-sitter grammar/function extraction, Clang AST, GumTree-C, LLVM/SVF C
build integration, C security diagnostics and ASan/UBSan evaluator cannot supply
Rust scientific results. The stage runner skips C structural analysis for .rs.
The security entry point writes an unsupported result with
security_evaluation_completed=false and security_clean=null. Structural and
lineage analysis entry points refuse Rust. The semantic backend already requires
.c files. Raw functional lineage records remain available; a Rust downstream
analyzer is future work.

Suite READMEs document generation, self-checking and bounded seeded fuzzing.
No experiment agent was invoked to generate an application during this task.
