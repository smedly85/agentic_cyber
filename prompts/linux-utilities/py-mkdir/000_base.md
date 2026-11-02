# Task: Create py_mkdir — checkpoint 000

There is intentionally no starter implementation. Generate the program from scratch.

Modify only `src/py_mkdir/py_mkdir.py`; executable: `build/py_mkdir.py`.

Accept one or more directory operands. Create each named final directory; missing parents, existing entries (including directories), permission failures and incompatible path components are errors. Do not read stdin. Successful creation uses 0777 masked by the process umask. Exercise umasks 0000, 0022 and 0077. Process operands in order and continue after per-operand errors. Exit 0 only if all operands succeed, otherwise 1; stdout is empty, successful stderr is empty, and failures produce diagnostics identifying the operand. Diagnostics follow GNU 9.11 wording where the visible corpus asserts exact text, with program name `mkdir`.

Accept `--` as the option terminator; subsequent arguments, including dash-prefixed names, are literal operands. Bare `-` is an operand. Parse supported options before mutation, including options following operands. Unknown options and missing operands produce stderr and status 1. No other options are supported. Paths are byte strings, not necessarily UTF-8. Directory symlinks in parent components are traversed; do not replace symlinks or nondirectories. Permission, allocation and I/O failures must be diagnosed without crashing. Ownership, ACLs, SELinux, extended attributes and concurrent filesystem mutation are excluded.

## Implementation and validation

Use a standalone Python 3.12.8 program with a Python 3 shebang and main entry point, standard library only. Choose the internal architecture and algorithms independently. Do not copy implementations or delegate functionality through external utilities, subprocesses, shells, os.system, popen, exec/spawn or ctypes. Do not add flags or functionality beyond this checkpoint. Preserve arbitrary pathname and file bytes and handle ordinary errors without uncaught tracebacks. The controller verifies nonempty source and compiles it in memory without executing it; execution uses the pinned Python interpreter inside the isolated Linux case container, not a host launcher.

The controller builds inside Linux Docker with:

    python3 "$HELDOUT_ROOT/scripts/docker_benchmark.py" build --utility py-mkdir

The visible checkpoint bundle is `tests/py-mkdir-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/py-mkdir-test-suite/judge_candidate.sh build/py_mkdir.py 

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
