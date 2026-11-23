## Session conditions

This is a fully automated, non-interactive implementation task in Aider.
The editable source and selected read-only files are supplied through Aider.
Use the supplied contents; a path mentioned in the prompt does not mean you
can independently open it. Do not promise or claim to inspect files, search
the repository, or run commands using tools unavailable in this session.

No user is available to answer questions or approve work. Do not ask questions,
request approval, defer implementation, or finish with a proposed plan or an
offer to continue. Produce concrete implementation instructions and source
edits during the current invocation, within the allowed file scope.

If a requirement is ambiguous or underspecified, choose the most reasonable
interpretation consistent with the rest of this prompt and proceed. State the
interpretation you chose in your final response.

Every requirement in the supplied checkpoint prompt is mandatory within its
stated scope. "Base checkpoint" and "no options" do not mean illustrative or
minimal demonstration functionality: implement the complete specified baseline.
Later checkpoints add only their specified features; do not defer current
requirements to them or implement future checkpoint flags early.

In architect/editor mode, the architect must give the editor complete, concrete
implementation instructions covering all required behavior, argument handling,
filesystem semantics, safeguards, errors and exit status. The editor must apply
the corresponding source edits now. Do not substitute exploratory commentary,
repeated reconsideration, or a partial feature sketch for this handoff.

The controller handles compilation, validation, and subsequent repair
invocations. Build and validation commands in the task describe that controller
workflow; do not claim to have run them. Correct reported compiler errors and
warnings in the source. Do not wait for another invocation to implement known
requirements or run an autonomous validation/repair loop. Keep any completion
report brief and factual, describing actual edits and unresolved constraints
without conversational closing language. This session rule does not suppress
confirmation prompts that the implemented utility is explicitly required to emit.

Nothing in this section changes what the program must do. The task,
its scope, and the validation that follows are defined by the rest of this
prompt.

# Task: Create rust_sort — checkpoint 000

There is intentionally no starter implementation. Generate the program from scratch.

Modify only `src/rust_sort/rust_sort.rs`; executable: `build/rust_sort`.

Read only standard input. Records are arbitrary byte strings separated by newline, including empty records, NUL bytes and invalid UTF-8. Empty input produces empty output. A final nonempty unterminated record is still a record. Emit every output record followed by newline. Sort records in unsigned bytewise lexicographic ascending order in LC_ALL=C, preserving duplicates. Successful output has status 0 and empty stderr. Do not modify record contents.

There are no file operands, including `-`. A bare `--` ends option parsing but does not permit operands. Unknown options or any operands produce empty stdout, a usage diagnostic on stderr and status 2. Once supported, short options may be clustered, repeated options are idempotent and their order does not affect results. Handle long records and input/output/allocation errors without crashes; operational errors return 2 with stderr. Exclude locale-specific ordering, keys, numeric ordering, stable-sort options, merge mode, random order, obsolete key syntax, POSIXLY_CORRECT compatibility, output files, zero-delimited records and all other flags.

## Implementation and validation

Use one standalone Rust 2021 source file, Rust 1.85.1 and the standard library only, with applicable POSIX filesystem behavior. Choose the internal architecture and algorithms independently. No unsafe blocks, Cargo dependencies, external utilities, subprocess delegation or copied implementations. Do not add flags or functionality beyond this checkpoint. Handle ordinary errors without panics; preserve arbitrary pathname and file bytes.

The controller builds inside Linux Docker with:

    rustc --edition=2021 -C opt-level=2 -D warnings src/rust_sort/rust_sort.rs -o build/rust_sort

The visible checkpoint bundle is `tests/rust-sort-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/rust-sort-test-suite/judge_candidate.sh build/rust_sort 

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
