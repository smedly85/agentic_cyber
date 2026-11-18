# The pipeline decisions and assumptions

This file records how the pipeline was built. Decisions marked **(user)** were made by you
during planning. Those marked **(impl)** were made during implementation after you
asked for no more questions, so treat them as defaults you can revisit. Each entry
says where to change it.

## Scope and architecture
- **(user)** Depth mode was built first; lineage mode followed (see "Lineage mode" below).
- **(user)** The pipeline is a `src/` Python package in this repo. The orchestrator loop is new Python code that reuses the existing analyzers rather than calling `run_experiment.sh`.
- **(impl)** All language work runs inside the per-language Docker images: compiling, call graphs, locating functions, splicing, signature checks, building and running tests. The host only orchestrates, and its Python has no third-party dependencies (pytest is needed only for the pipeline's own tests). The repo is mounted read-only at `/agent-src` in every container, so code changes need no image rebuild. The manifest records the git commit, including `+dirty`.
- **(impl)** Only agent sessions have network access. Locate, verify, baseline, hidden-suite and call-graph containers all run with `--network none`, every capability dropped, no-new-privileges and cpu/memory/pids limits.

## Configuration
- **(user)** `.env` holds models only: `AGENT_<ROLE>_MODEL/_API_BASE/_API_KEY`, with `AGENT_API_BASE`/`AGENT_API_KEY` as fallbacks. `config.toml` (repo root by default) holds everything else. Precedence is CLI > env > TOML > defaults.
- **(impl)** Process environment variables override values in the `.env` file. Putting a `[models]` table in TOML is an error. API keys are redacted in the manifest and in logged docker argv.
- **(impl)** If `depth.language` is unset, it is inferred from the input: `.c` gives C, `.rs` or `Cargo.toml` gives Rust.

## Call graphs and selection
- **(user)** C uses SVF at the repo's pinned commit `67efb77`. **(user, revised)** It runs against LLVM 21 inside `agent-c`, because that SVF commit hard-codes LLVM 21. Your machine's LLVM is untouched.
- **(impl)** SVF writes `<extapi>.pre.bc` next to `extapi.bc`. Each run copies `extapi.bc` into a private temp dir and passes `-extapi=`, so the image stays read-only and parallel runs are safe. The SVF options are otherwise the historical `-stat=false -ff-eq-base`.
- **(impl)** SVF only sees functions that clang emits. An unused `static` function such as `unused_debug` in the C fixture is not emitted at `-O0`, so it never appears, even with `include_unreachable`.
- **(user)** Rust supports RUPTA (the default) and the lightweight MIR graph, both pluggable. **(impl)** RUPTA runs as `pta --pta-type ander` (`cs` is available via `[callgraph.options] rupta_pta_type`). Its known gaps from `rust_rupta_v1/README.md` still apply.
- **(impl)** Rust graph nodes are monomorphised instances. They collapse onto source functions using the pipeline's compiler inventory (`rs-items`): MIR nodes by source span, RUPTA nodes by verbose def path such as `{impl#2}::add` with generic arguments stripped. A function's depth is the minimum over its instances. Closures are not separate targets.
- **(impl)** Rust depths are the backends' **raw** depths. Std frames stay in the path, as the repo's backends do, so `is_digit_char` called through `Iterator::all` reports depth 6 or 7, not 3.
- **(user)** The entry is always `main`. **(user)** With no depth given, every eligible reachable function except `main` is selected. With `--depth D`, the rule is `eq|le|ge` (default `le`). `include_unreachable` defaults to off. **(user)** Selection is computed once, from the original program.
- **(user)** Order defaults to shallow-first; deep-first, source and seeded random are also available. **(impl)** Ties break in source order.
- **(impl)** Rust call-graph extraction compiles the crate root directly with `rustc`. Cargo crates **with external dependencies** therefore work for build and test (via `cargo build --offline`, with dependencies vendored or cached) but not for call-graph extraction. Extending this means using `cargo-pta` or `rust_mir/cargo_wrapper.py`.

## Editing surface and checks
- **(user)** The agent edits a single function file. **(impl)** It lives at `/src/edit/<sanitized name>.<c|rs>`. The program is mounted read-only at `/work/project`, and only the function file is harvested.
- **(impl)** The function file starts as the exact original definition text:
  - **C:** clang's FunctionDecl range.
  - **Rust:** the item span widened backwards over attribute and doc-comment lines.
- **(impl)** Splicing replaces exactly those bytes. Added `#include` lines (C) or column-0 `use` declarations (Rust) are moved to the top of the file, or for Rust, to the crate root. Everything else stays where the agent put it, so helpers must come before their use in C. For a Rust method, the content goes inside the `impl` block, and the prompt tells the agent so.
- **(user)** Additions are classified automatically from compiler output into helpers, includes/uses, and globals/types (Rust `impl` blocks count as globals/types). **(user)** The toggles `allow_new_helpers`, `allow_new_includes` and `allow_new_globals_types` all default to on.
- **(user)** Signature checks are compiler-based and cover name, parameter types and names, return type, and qualifiers/attributes, plus generics, lifetimes and where-clauses for Rust:
  - **C:** clang's FunctionDecl `type`, parameter names, storage class, inline, variadic, and explicit attribute nodes.
  - **Rust:** rustc's `fn_sig`, `predicates_of`, generics, parameter patterns, `visibility` (crate hash removed), `asyncness`, plus the whitespace-normalized header and attribute text.
- **(impl)** A candidate whose code equals the original after removing all whitespace is rejected as `UNCHANGED`, because it is not a diversification.
- **(user)** A signature or addition violation is a failure that is fed back to the agent; it is not an immediate rejection.
- **(impl)** Macro-generated C functions:
  - They are located through clang's expansion range, so the function file holds the macro *invocation* text.
  - Replacing it with a hand-written definition works only if that invocation produces exactly that one function; otherwise the build or classification fails and is reported.
  - Functions defined in headers are edited in the header.

## Build and tests
- **(impl)** If `build.cmd` is unset:
  - **C:** run `make` if there is a Makefile, otherwise `clang -std=gnu11 -O0 -g <flags> <sources> -o <stem>`.
  - **Rust:** run `cargo build --offline --quiet`, or `rustc -g` for a single file.
- **(user)** Test suites are standalone directories. **(impl)** The contract is `<suite>/run <project_dir> --report <json>`: exit 0 means pass, and the report is `{passed, failed, cases:[{name,status,detail}]}`. A suite must be **self-contained**, because only its directory is mounted. The suite is run after the build, so it finds the binary in the project directory.
- **(user)** The agent sees a summary of pass/fail counts plus a capped list of failing cases (`[tests.feedback]`).
- **(user)** The original program must pass both suites, or the run aborts. **(user)** The hidden suite runs only after a function is accepted. It is recorded but never fed back and never mounted in agent containers.
- **(impl)** Acceptance is not taken from the agent's word. After every session the controller re-runs splice, checks, build and visible suite in a fresh container with no network.
- **(impl)** In cumulative mode, the final program is checked once more against both suites (`final_visible_ok`, `final_hidden_ok` in `summary.json`).

## Agent sessions
- **(user)** The harness is mini-swe-agent 2.4.6, installed in the images. **(user)** The agent runs inside the container.
- **(impl)** The pipeline uses mini-swe-agent's own bundled templates and puts its task into `{{task}}`: `mini.yaml` for tool-calling `litellm` (the default `agent.model_class`) and `default.yaml` for `litellm_textbased`. Cost tracking is set to `ignore_errors`, since local models have no price table.
- **(user)** The topologies are `single`, `planner_worker` and `orchestrator`. **(impl)**
  - **planner_worker:** the planner writes `/src/session/plan.md`, and the worker gets the task plus that plan.
  - **orchestrator:** the orchestrator calls `agent-worker "<instructions>"`, which starts a nested worker session and prints its exit status and the latest `agent-test` summary. That the orchestrator does not edit the file itself is stated in its prompt but not enforced.
- **(impl)** Prompts are in `src/prompts/*.md` (Jinja2, rendered in-container): task, repair, planner, orchestrator, and two worker variants.
- **(impl)** `[docker] agent_network = auto` uses host networking for agent containers when the model endpoint is host-local (for example Ollama on `127.0.0.1`), and bridge networking otherwise. `bridge` rewrites local endpoints to `host.docker.internal`, which needs the service to listen on more than loopback.

## Retries
- **(user)** Each session is bounded by `retry.session_timeout_s` (mini-swe-agent's wall-time limit, plus a docker timeout with 300 s slack), `agent.step_limit`, and an optional token budget (`retry.token_budget`, off by default).
- **(user)** Up to `retry.max_loops` fresh repair sessions follow. **(impl)** A repair session starts from the previous attempt's function file and gets the controller's failure summary plus the original definition.
- **(impl)** Stop reasons:
  - `success`
  - `loop_limit`
  - `no_progress`: a repair session left the file byte-identical
  - `timeout`
  - `infrastructure_failure`: the agent container produced no session record
  - `locate_failed`
- **(user)** A function that exhausts its retries keeps its original definition, and the run continues with the next function.

## Outputs
Each run writes `runs/<timestamp>-<input>/` (configurable) containing:
- `manifest.json`: redacted config, git commit, image id, argv
- `baseline.json`
- `callgraph/` (raw backend output) and `callgraph.json` (normalized)
- `selection.json`
- `functions/NNN-<id>/`: `target.json`, `original.txt`, `record.json`, and `attempt-K/` with the session dir, `candidate.txt`, `verification.json`, `spliced/` and `hidden.json`
- `work/` and `final/` (cumulative mode) or `variants/` (independent mode)
- `summary.json`

## Images
- **(user)** Per-language images built from Ubuntu 24.04 (pinned by digest):
  - `agent-c`: LLVM/Clang 21 and SVF
  - `agent-rust`: Rust 1.93.0 with rustc-dev (builds, MIR driver, `rs-items`), plus `nightly-2024-02-03` for RUPTA at commit `b19f187e`
- Build them with `docker build -f docker/Dockerfile --target agent-c -t agent-c src` (and `agent-rust`). Each run records the image ID in its manifest.

## Lineage mode
- **(impl)** `python -m src lineage` does not reimplement the lineage machinery. It maps its config to the flags of `src/harness/run_lineage_experiment.sh` and runs that script, which in turn calls `src/harness/run_experiment.sh` for each stage. Everything below stays exactly as before:
  - the manifest and stage plan, and the per-checkpoint test bundles;
  - seed inheritance, the controller repair loop and its continuation prompts;
  - Docker build and checkpoint judge, held-out judge, security evaluation;
  - candidate capture, configuration fingerprints, the output layout and `analyze_lineages.py`.
- **(impl)** The generator is pluggable (`lineage.generator`):
  - **`minisweagent`** (default) gives both modes the same harness.
  - **`aider`** runs the host's Aider unchanged, as today. Aider is not installed on this machine, so that path is wired and dry-run-checked but has not been run here.
- **(impl)** The mini-swe-agent generator is an **Aider-compatible shim** (`src/lineage/shim.py`). `run_experiment.sh` runs whatever `AIDER_BIN` points to, so the pipeline generates a wrapper and passes it as `AIDER_BIN`. Each shim invocation:
  - copies the workdir into a fresh hardened container at `/work`;
  - runs the configured topology;
  - copies back **only** the `--file` source, discarding every other change. This matches Aider's structural edit boundary.
- **(impl)** The shim writes Aider's `Applied edit to <file>` line when the source changed, so `run_experiment.sh`'s existing `applied_edit` observation still works.
- **(impl)** It returns exit code 1 when the container produced no session record (an infrastructure failure). It returns 124 if the container timed out. On SIGTERM from the script's `timeout`, it stops its container and **still copies back the source written so far**, then exits 143, as Aider leaves partial edits in place. The agent's own wall-time limit is set to `session_timeout_s - 120` (at least half of it), so it normally finishes before the script's `timeout` fires. The prompt states the time limit and asks the agent to submit once the implementation is complete. This came out of a real c-sort run: the agent spent the whole 1500 s refining a working 203-line implementation, and the first shim version discarded it on SIGTERM.
- **(impl)** Image selection: `agent-rust` for `.rs` sources, `agent-c` for `.c` and `.py` (it has gcc, clang and python3). Python utilities therefore run in `agent-c`.
- **(impl)** Inside the session the agent gets `agent-build`, a local compile check that approximates the official build:
  - **C:** `gcc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2`
  - **Rust:** `rustc --edition=2021 -C opt-level=2 -D warnings`
  - **Python:** `python3 -m py_compile`
  - Override with `lineage.check_cmd`.
- **(impl)** The visible tests' judge needs the controller's Docker sandbox and cannot run inside the agent container. The prompt says so; the script's post-session validation, followed by a repair session, is the feedback loop, exactly as with Aider (which runs with `--no-auto-test`).
- **(impl)** Compiler versions inside `agent-c`/`agent-rust` differ from the pinned benchmark images (gcc 12.2, rustc 1.85.1). `agent-build` is advisory; only the official build counts.
- **(impl)** Prompts: the stage prompt or repair continuation produced by `run_experiment.sh` is used verbatim as the task. `src/prompts/lineage/task.md` appends a "How this session works" section, which says it supersedes the Aider-specific session-conditions notice those prompts contain. The planner, orchestrator and worker variants live in `src/prompts/lineage/`.
- **(impl)** Fingerprint and provenance: the script needs two distinct model names and fingerprints both.
  - `--model` carries the worker model.
  - `--editor-model` is the label `minisweagent/<topology>`.
  - The shim's `--version` string, `minisweagent-shim <ver> (mini-swe-agent 2.4.6, topology=…)`, becomes `aider_version`.
  - `--model-provenance-json` gets a `pipeline` object with generator, topology, role models, model class, step limit, token budget, check command and agent image ID.
  - So changing any of these refuses to resume an existing output dir, just as changing a sampling value does.
  - `lineage.json` still says `agent_backend: "aider"`, because that field is hard-coded in `src/harness/lineage_state.py`. Use `aider_version` and `model_provenance.agent` to identify the pipeline runs.
- **(impl)** Sampling: `[lineage.sampling]` is forwarded to the script. The shim then reads the architect entry of the per-attempt `aider-model-settings.yml` and applies those values to **every** agent role, so what is fingerprinted is what is sent. `[agent.sampling]` applies only to depth mode. The editor's pinned temperature 0 and seed 0 apply only to Aider.
- **(impl)** Models:
  - **minisweagent:** the usual `AGENT_<ROLE>_*` variables. API keys reach the shim through a private 0600 temp file that is deleted after the run, because `run_experiment.sh` runs the generator under `env -i`.
  - **aider:** `AGENT_ARCHITECT_MODEL` and optional `AGENT_EDITOR_MODEL`. The endpoint is passed as `--remote-base-url`, and the key travels in `AGENT_LINEAGE_API_KEY` via `--remote-api-key-env`. The script supports one endpoint, so differing architect and editor endpoints are rejected.
- **(impl)** Shared knobs: `[retry] max_loops` and `session_timeout_s` become `--max-loops` and `--timeout`.
- **(impl)** Default output directory: `runs/lineage/<utility>/<aider-<architect>|msa-<topology>-<worker>>/temp-<T>`. It is stable, so rerunning resumes, and the script's fingerprint check guards against mixing configurations.
- **(impl) Change to existing machinery:** `src/harness/docker_benchmark.py main()` now splits off the `--` that `judge_candidate.sh` passes before calling argparse. On this machine's CPython 3.12.3, argparse rejected `judge --utility X --candidate Y --`, so every checkpoint judge failed as an infrastructure failure for **any** generator. Behaviour is unchanged on Pythons that already accepted it.
- **(impl)** Ollama's default context window is too small for whole-utility sessions. The first real run hit `finish_reason=length` three times and ended in `RepeatedFormatError`. Set `lineage.sampling.num_ctx`, for example 32768.

## Caching
- **(impl)** One cache root is shared by both modes: `[cache] dir`, default `runs/cache`, now in `.gitignore`. `cache.enabled = false` (`--no-cache`) turns everything off.
- **(impl)** **Step cache** (depth mode, `cache.steps`):
  - **What is cached:** call graphs (normalized graph plus the raw backend output), locate, and every `agent-test` evaluation: baseline, verification including the spliced project, hidden suite, merge checks and final checks.
  - **Key:** image ID, a content hash of the program and suite trees (`build/`, `target/` and `.git` are ignored), the step's inputs (context, target, candidate text, feedback settings, docker limits) and a hash of the pipeline's code (including the vendored `src/analyzers`). Any pipeline edit therefore invalidates these entries.
  - **Not cached:** infrastructure failures.
  - **Assumption:** the build and suites are deterministic for identical inputs. A flaky suite would have its first result frozen; use `--no-cache` for such suites.
- **(impl)** **LLM cache** (both modes): implemented inside the agent container (`src/incontainer/llm_cache.py`) as a wrapper around the mini-swe-agent model.
  - Every response is stored under two keys:
    - **exact:** scope + agent label + model, model class and sampling + the model-visible conversation, with timestamps and extras removed;
    - **sequence:** scope + agent label + call index.
  - Format errors such as `finish_reason=length` are stored too and re-raised on replay.
  - **Scope:** `[cache] namespace` plus a session identity that does not depend on the output directory:
    - **depth:** input program hash, function key, attempt number, topology, and `rebase` when applicable;
    - **lineage:** utility, lineage ID, checkpoint, temperature, attempt, session number, topology.
- **(impl)** Modes: `record` (the default, which keeps experiments' sampling semantics), `auto`, `replay`. `--replay` is shorthand for `replay` + `sequence`.
  - Replay sessions run with `--network none`. A replay needs no model in `.env`; a placeholder name is used. An exact-match replay, however, needs the same model names, because they are part of the key.
  - A replay miss raises `CacheMiss`, which the agent records as its exit status. The controller then handles that attempt like any other failure.
- **(impl)** Cache settings are not in the lineage fingerprint, because `record` does not change what is sampled. Put a replay or `auto` run in its own output directory.

## Parallelism and pipeline optimizations
- **(impl)** `depth.parallel` (`-j`):
  - **Independent mode** is embarrassingly parallel.
  - **Cumulative mode** uses waves of N against one snapshot, then an ordered merge. Every merged candidate is re-verified in the program it actually lands in, so the final program has the same guarantees as a serial run.
  - When a merge fails, the function gets **one** fresh diversification (`-rebase`) against the merged program rather than being dropped. Its original attempt is recorded in `rebased_from`.
  - With `-j 1`, behaviour and outputs are those of the serial algorithm.
  - **Note:** in a wave, functions see the program as of the wave's start, not their wave-mates' rewrites. This is a deliberate trade of a little sequential context for throughput.
- **(impl)** `lineage.parallel`:
  - Each lineage runs as its own script process (`--lineage-start k --lineages 1`) in the shared output dir.
  - Starts are staggered until each process prints `=== lineage-NNN ===`, because the script read-modify-writes `lineages.json` only before that point. This avoids lost updates without touching the script.
- **(impl)** Optimizations:
  - Baseline visible and hidden suites, and the final visible and hidden checks, run concurrently.
  - Repeated runs hit the step cache: a rerun of the toy pipeline skips the call graph, baseline and all verifications.
  - Directory content hashes are memoized within a process, keyed on path, inode, ctime, mtime and size, never on mtime alone (copytree preserves mtimes). As git does for "racy" files, a tree changed in the last 2 s is always re-hashed, because file timestamps are coarse and a tree recreated within one tick can repeat every stat field.

## Repository restructure (tool source at the root)
Request: make the tool the repository root, drop what is redundant, keep prompts and the rest of the useful material, and group the benchmark under `coreutils/<utility>/` with folders for tests and prompts.
- **(impl)** Layout: `src/` (package), `src/harness/` (lineage harness), `coreutils/` (benchmark), `docker/`, `docs/`, `tests/` (pytest), `config.toml`, `.env.example`. The tool README is the root README.
- **(impl)** `coreutils/<utility>/` for cp, mv, mkdir, sort, grep:
  - `manifests/{c,rust,py}.json`: the former `experiments/utilities/<lang>-<utility>.json`.
  - `prompts/{c,rust,py}/`: the former `prompts/linux-utilities/<lang>-<utility>/`.
  - `tests/`: the shared functional suite (formerly `tests/c-<utility>-test-suite`, which the Rust and Python selectors already shared).
  - `judges/{c,rust,py}.sh`: the per-language checkpoint judges. The Rust/Python descriptor directories held only a judge, a pointer `config.json` and a README, so they were folded in here.
  - `coreutils/shared/`: the automation notice and the repair-continuation template. `coreutils/docs/`: benchmark description, contract (fingerprinted by the plan), grep addendum, input provenance, manifest schema.
- **(impl)** Selectors stay `<language>-<utility>` (`c-sort`, …), so CLI usage and identities are unchanged. `src/harness/linux_utilities_catalog.py` is the single place that maps a selector to its manifest, suite and judge.
- **(decision)** Manifest `test_dir`/`judge` (and `source_path`, `executable_path`) keep describing the **agent's sandbox**, which is unchanged (`tests/c-sort-test-suite/judge_candidate.sh build/c_sort`). Prompts, judge commands and what the agent sees are therefore byte-identical to earlier runs; only host-side sources moved. `prompt` and `shared_functional_suite` are host paths and were updated.
- **(decision)** `scripts/` → `src/harness/`, keeping only what the lineage pipeline, held-out judge, oracle validation, security evaluation and `analyze_lineages.py` use (import closure checked). `tests/reference_generators/{heldout_contract,standard_grep_oracle}.py` → `src/harness/reference_generators/`; `security/{run_security_evaluator.py,common/}` → `src/harness/security/`.
- **(decision)** The call-graph code the pipeline runs (SVF backend and helper, MIR driver and graph, RUPTA adapter) is vendored into `src/analyzers/` with only import paths changed. The rest of `security/semantic_callgraph` was studies and results.
- **(decision)** Removed (all tracked; recoverable with `git checkout 3b72464e -- <path>`): `runs/` (committed results), `security/` (historical corpora, studies, calibration), research scripts (ordered/unified diversity, vessel, publishing, validation), legacy manifests/prompts/suites (unprefixed, `python-*`, `chmod`, `new_sort`), `tests/fixtures` and other research tests, `diagnostics/`, research reports in `docs/`, `docs/benchmarks/` validation outputs, the Makefile (it ran the removed validators), and the 62 KB agentic_cyber README. Methodology write-ups that describe kept components moved to `docs/methodology/` (their internal paths may still name the old layout).
- **(impl)** `.gitignore` now ignores all of `runs/` (outputs only; nothing under it is tracked any more).
- **(note)** Plan fingerprints of new runs differ from pre-restructure runs, because the hashed infrastructure list and prompt paths changed. Resume a pre-restructure output directory only from the old commit.
- **(known issue, pre-existing, not changed)** `src/harness/run_lineage_experiment.sh` passes the selector (e.g. `c-sort`) to `src/harness/security/run_security_evaluator.py`, whose `--utility` accepts only bare names (`sort`), so security evaluation exits 2 for the 15 selectors unless disabled. The same was true before the restructure.

## Standard layout, neutral naming, one Dockerfile
Request: the tool's working name must not appear anywhere in the repository; use the standard place for a tool's source code; make the repository structure standard; `docker/` should hold just one Dockerfile, as small as possible, without scripts or overlap.
- **(decision)** All source code lives in `src/`, which is itself the Python package (`python -m src depth|lineage`, `from src import …`). There is no named package under it, which keeps the name out of the repository. The lineage harness moved to `src/harness/` (repo-root lookups in it are now `parents[2]`). Top level: `src/`, `tests/`, `docs/`, `docker/`, `coreutils/` (benchmark data), `config.toml`, `.env.example`, `README.md`.
- **(decision)** Neutral names. Run parameters live in `config.toml`; env vars `AGENT_*` (`AGENT_WORKER_MODEL`, `AGENT_API_BASE`, …); images `agent-c`, `agent-rust`; in-container tools `agent-test`, `agent-build`, `agent-worker`; per-attempt session dir `agent/`; lineage bookkeeping dir and provenance key `pipeline`; shim version `minisweagent-shim`; depth output default `runs/depth`, lineage `runs/lineage`, cache `runs/cache`; the virtualenv is `.venv`. Prose calls the tool "the pipeline".
- **(decision)** `docker/Dockerfile` is the only file in `docker/`, one stage per image, built from the repo root with `src/` as context (so the SVF helper, MIR driver and `rs_items.rs` are copied directly, with no staging script):
  - `agent-base` holds the apt basics and mini-swe-agent once; `agent-c` (LLVM 21 + SVF) and `agent-rust` (Rust 1.93 + RUPTA + MIR tools) build on it.
  - `oracle` builds GNU Coreutils 9.11 **and** GNU grep 3.12 in one image (formerly a coreutils image plus a grep layer on top); `rust-jail` is the Rust 1.85.1 candidate compiler.
- **(decision)** Removed `build.sh` and `validate.sh`. Building is plain `docker build --target …`; corpus re-validation is a `docker run` of `linux_benchmark.py validate` in the oracle image (documented in `coreutils/docs/benchmark.md`). The corpora are frozen, so the launcher was not needed for runs.
- **(decision)** The two benchmark locks are merged into `coreutils/images.lock.json` (they pin benchmark images, so they belong with the benchmark). Coreutils keys are unchanged, and the grep oracle's fields gained a `grep_` prefix (`grep_oracle_image`, …). The checked-in IDs remain the originally validated images; a rebuild from the merged Dockerfile produces new IDs that need validation before they replace them (`LINUX_BENCHMARK_LOCK` selects a private lock).
- **(decision)** The agent-image lock is gone. A run requires the image to exist and records its ID in the run manifest. Nothing produced the lock any more once the build script was removed.
- **(note)** The old working name never reached git history: this work was uncommitted when it was renamed. (Earlier staging left unreferenced objects in the local `.git`; `git gc --prune=now` drops them.)
