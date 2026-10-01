# cp Rust-generation functional suite

The frozen-case runner and checkpoint wrapper follow the chmod suite architecture.
All judging uses committed frozen expected filesystem state, stdout, stderr
class and exit status. It never executes the functional oracle.
Visible cases live under suites/; controller-only structural duals live under
heldout/. scripts/heldout_judge.py invokes this same runner after repair.
Only scripts/stage_test_bundle.py may prepare agent-visible tests.

Checkpoint flags, cumulatively: 000: none; 001: -f; 002: -f -i; 003: -f -i -r.
Each case declares its required flags. Earlier cases remain regression coverage.
The canonical semantic anchor is copy_path.

## Functional oracle and offline commands

Set CP_ORACLE_BIN to your GNU Coreutils 9.11 cp executable.
No default path or fallback is permitted. Identity must exactly match
`cp (GNU coreutils) 9.11`. Generation refuses mismatched versions and
non-root permission cases cannot be frozen as root.

From the repository root:

    python3 tests/cp-test-suite/gen/generate.py
    bash tests/cp-test-suite/selfcheck.sh
    python3 tests/cp-test-suite/gen/generate.py --audit
    python3 tests/cp-test-suite/diff_fuzz.py --candidate /absolute/candidate --seed 1 --count 100 --output /tmp/cp-regressions.json

Generation executes every case twice and compares byte-identical compressed
artifacts. gzip mtime is zero; manifests hash both corpora. --check repeats this
without writing. --audit needs no oracle and checks hashes, schema, flags and
checkpoint leakage. Fuzzing records oracle-derived reproductions outside the
repository; no automatic corpus promotion occurs.

## Filesystem and platform contract

Darwin/macOS and Linux POSIX filesystems are supported; Windows judging is
rejected. Formal experiments run on Darwin. This bounded corpus does not set
required_platform to Darwin: cases use same-filesystem operations with pipe
stdin, C locale, umask 022 and non-colliding ASCII fixture names. Invalid-byte
missing operands test non-UTF-8 argument handling; APFS cannot create such names.
Case-fold collisions and Unicode normalization are excluded. No EXDEV fallback,
ACLs, xattrs, ownership, special mode bits, errno wording, timestamps, allocation
or inode/device values enter comparisons. Source/target ordinary rwx modes are
compared only in cases with mode_paths; all cases compare exact path sets,
types, content hashes and link targets. Symlinks are never followed by snapshots.

Inspection of the GNU 9.11 option logic confirms independent cp force/interactive
handling and ordered mv handling. Runtime reproducibility and oracle self-pass
are checked on the generating host; a Darwin self-check is still required before
formal collection. This is not a claim that Darwin execution occurred in WSL.

Every case uses a fresh temporary directory. Fixture/operand paths, symlink
targets and symlink ancestors are validated before filesystem mutation. Absolute,
escaping and unbalanced parent paths are refused. Permission tests are skipped
explicitly for root at judging time; freeze requires a non-root account.
Temporary directories isolate normal executions, not malicious executables:
the lineage host's process/container restrictions remain necessary for hostile code.

## Separate scientific provenance

GNU Coreutils 9.11 is solely the independent functional behavioral oracle.
uutils/coreutils is the planned historical Rust vulnerability source; no uutils
source is downloaded or staged. See docs/rust_lineages.md. C AST, sanitizer,
GumTree and call-graph analyses do not support these Rust candidates.
