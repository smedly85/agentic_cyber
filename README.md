# Agentic code diversification

A configurable, plugin-based orchestrator for LLM code generation and
diversification experiments. It has two modes (full diagram with every component and
config key: [`docs/pipeline.svg`](docs/pipeline.svg)):

- **`python -m src depth`** takes a C or Rust program and selects functions by their call-graph
  depth from `main`. SVF provides the C call graph; RUPTA or the MIR graph provides the
  Rust one. For each selected function, a mini-swe-agent session rewrites it as an
  equivalent but different implementation. The signature must stay exactly the same,
  and the visible tests must still pass. A failed attempt gets controller-driven
  repair attempts.
- **`python -m src lineage`** regenerates a coreutils utility checkpoint by checkpoint
  (000 → 001 → … → final), each stage seeded with the previous stage's accepted source.
  It drives the lineage harness (`src/harness/run_lineage_experiment.sh` →
  `src/harness/run_experiment.sh`), and the pipeline supplies the code generator: either the host's
  Aider or mini-swe-agent in a Docker container with any topology.

Every decision and assumption is listed in [docs/DECISIONS.md](docs/DECISIONS.md).

## Repository layout

```
src/                  all source code (python -m src)
  depth/ lineage/     the two modes
  harness/            lineage pipeline: run_lineage_experiment.sh -> run_experiment.sh per
                      checkpoint, Docker build/judge, held-out judge, test bundles,
                      security evaluator, analysis
  analyzers/          call-graph code run inside the images (SVF helper, MIR driver, RUPTA adapter)
  incontainer/        agent-test, agent-build, agent sessions, LLM cache (run inside containers)
  prompts/            agent prompts (depth mode; lineage/ for lineage mode)
coreutils/            the benchmark: cp, mv, mkdir, sort, grep in C, Rust and Python
  <utility>/
    manifests/        c.json rust.json py.json   (checkpoint ladder, build/judge commands)
    prompts/          c/ rust/ py/               (000_base.md, 001_<feature>.md, ...)
    tests/            shared functional suite: runner, frozen visible suites, held-out corpus
    judges/           c.sh rust.sh py.sh         (checkpoint judge given to the agent)
  shared/             automation notice and repair-continuation template used by every prompt
  docs/               benchmark description, contract, manifest schema
  images.lock.json    pinned IDs of the benchmark images
docker/Dockerfile     every image, one stage each (agent-c, agent-rust, oracle, rust-jail)
docs/                 pipeline.svg, DECISIONS.md, methodology/
tests/                tests for src/ (pytest)
config.toml .env.example
```

A selector is `<language>-<utility>` (`c-sort`, `rust-grep`, `py-mkdir`, ...);
`src/harness/linux_utilities_catalog.py` maps it to the files above.

## Setup

```bash
docker build -f docker/Dockerfile --target agent-c -t agent-c src
docker build -f docker/Dockerfile --target agent-rust -t agent-rust src
cp .env.example .env            # then set AGENT_WORKER_MODEL etc.
python3 -m venv .venv && .venv/bin/pip install pytest   # only for the pipeline's own tests
```

The host needs Python 3.11 or newer and Docker. Nothing else is installed on the host.

## Run

```bash
# Inspect the call graph and selection without running any agent
python3 -m src depth --input path/to/prog.c --dry-run
python3 -m src depth --input path/to/crate --depth 2 --depth-rule eq --dry-run

# Full run (suites can also be set in config.toml)
python3 -m src depth --input path/to/prog --depth 2 \
    --visible-suite path/to/visible --hidden-suite path/to/hidden
```

The pipeline reads `config.toml` from the repo root (or `--config`). CLI flags override it, and
`--print-config` shows the resolved configuration. Models come from `.env`:

| Variable | Used by |
|---|---|
| `AGENT_WORKER_MODEL` | every topology |
| `AGENT_PLANNER_MODEL` | `topology = "planner_worker"` |
| `AGENT_ORCHESTRATOR_MODEL` | `topology = "orchestrator"` |
| `AGENT_ARCHITECT_MODEL`, `AGENT_EDITOR_MODEL` | `python -m src lineage` with `generator = "aider"` |
| `AGENT_<ROLE>_API_BASE`, `AGENT_<ROLE>_API_KEY` | per-role endpoint; falls back to `AGENT_API_BASE` / `AGENT_API_KEY` |

Model names use LiteLLM syntax, for example `ollama_chat/qwen3.6:35b` or `openai/<model>`.

## Parallelism

`-j N` (`depth.parallel`, `lineage.parallel`) runs N agent sessions at once. Your model
server limits how many run at the same time: Ollama serves `OLLAMA_NUM_PARALLEL` requests
at once and queues the rest.

- **depth, independent:** up to N functions at once, each against the original program.
- **depth, cumulative:** functions run in waves of N, all against the same snapshot of
  the evolving program. Accepted candidates are then merged in selection order:
  - The first candidate in a wave is applied directly.
  - Each later candidate is re-located and re-verified in the merged program (splice,
    signature and addition checks, build, visible suite), then its hidden suite runs on
    the merged result.
  - A candidate that does not merge gets one fresh diversification against the merged
    program; its folder ends in `-rebase`.
  - With `-j 1` this is exactly the serial algorithm.
- **lineage:** one `run_lineage_experiment.sh` process per lineage, N at once, writing into
  the same output directory. Each process starts only after the previous one has written
  the shared `lineages.json`. Per-lineage logs are in `<output-dir>/pipeline/logs/`.

## Caching and replay

Everything goes in `[cache] dir` (`runs/cache`), shared by both modes.

- **Step cache** (depth mode): call graphs, locate results and every evaluation (baseline,
  verification, hidden suite, final checks). Entries are keyed by the image ID, a content
  hash of the program and suite, the step's inputs, and a hash of the pipeline's own code. Re-running
  with an unchanged pipeline costs almost nothing, and editing the pipeline invalidates these
  entries. In lineage mode the build and judge belong to the harness, which resumes
  completed stages on their own.
- **LLM cache** (both modes): every model response, including format errors, is stored per
  agent session. The session scope does not depend on the output directory, so a run can
  be replayed into a fresh one.

| `cache.llm` | Behaviour |
|---|---|
| `record` (default) | always call the model and store the response |
| `auto` | reuse a matching response, otherwise call the model and store |
| `replay` | never call the model: sessions run offline (`--network none`), and a miss stops the agent with `CacheMiss` |

`cache.match` selects how `auto`/`replay` find a response:
- **`exact`** keys on the whole conversation plus model and sampling settings.
- **`sequence`** keys on the call index, so recorded actions are replayed even when tool
  outputs differ.

Use `sequence` to test pipeline changes without an LLM:

```bash
python3 -m src depth --input prog.c --depth 2 ...            # records responses
# ...edit the pipeline...
python3 -m src depth --input prog.c --depth 2 ... --replay   # same agent actions, new pipeline, no LLM
python3 -m src lineage --utility c-sort --replay --output-dir runs/lineage/replay-test
```

`record` never reuses responses, so repeating an experiment gives new samples. To share
a cache across repeats with `auto`, set a different `cache.namespace` for each repeat.

## Lineage mode

```bash
python3 -m src lineage --list-utilities
python3 -m src lineage --utility c-sort --dry-run          # every stage's run_experiment.sh command
python3 -m src lineage --utility c-sort --lineages 10 --temperature 0.2
python3 -m src lineage --utility rust-sort --generator aider
```

Settings come from `[lineage]` in `config.toml`, plus `[retry]` (max_loops, session_timeout_s),
`[agent]` (topology, model_class, step_limit) and `[docker]`.

| `lineage.generator` | Models (`.env`) | What runs per stage session |
|---|---|---|
| `minisweagent` (default) | `AGENT_WORKER_MODEL`, plus `AGENT_PLANNER_MODEL`/`AGENT_ORCHESTRATOR_MODEL` per topology | `src.lineage.shim`: a mini-swe-agent session in `agent-c` (C, Python) or `agent-rust` |
| `aider` | `AGENT_ARCHITECT_MODEL`, optional `AGENT_EDITOR_MODEL` | the host's Aider (`lineage.aider.bin`), as `run_lineage_experiment.sh` runs it natively |

How the shim works: `run_experiment.sh` launches its generator as `$AIDER_BIN` with Aider's
flags. The pipeline points `AIDER_BIN` at a generated wrapper around `python -m src.lineage.shim`.

For each session, the shim:
- copies the attempt's workdir to `/work` in a fresh container;
- runs the topology, with:
  - the stage prompt or repair continuation as the task,
  - `agent-build` for a local compile check,
  - `agent-worker` for the orchestrator topology;
- copies back **only** the editable source and discards every other change.

Everything else stays in the harness: building, the checkpoint judge, the held-out
judge, the repair prompts, candidate capture, security evaluation and fingerprints. Lineage
outputs therefore keep the familiar layout, and `src/harness/analyze_lineages.py` reads them as before.

Lineage mode adds:
- `<output-dir>/pipeline/invocation-*.json` and `<output-dir>/pipeline/summary.json`;
- `attempt-*/agent/session-NN/` per agent session (task, trajectories, `agents.jsonl`,
  container log).

The build and judge steps need the linux-utilities benchmark images pinned in
`coreutils/images.lock.json`. `LINUX_BENCHMARK_LOCK` selects another lock.

The agent's sandbox keeps the historical layout (`src/<prog>/…`, `build/<prog>`,
`tests/<selector>-test-suite/` holding that checkpoint's test bundle and judge), so
prompts and judge commands are unchanged; only the host-side sources moved into
`coreutils/`. See [coreutils/docs/manifests.md](coreutils/docs/manifests.md).

## Test suites

The pipeline doesn't come with tests for your program. You supply two self-contained suite
directories, one visible and one hidden. Each has an executable `run`:

```
<suite>/run <project_dir> --report <report.json>
# exit 0 = all passed; report = {"passed": N, "failed": M, "cases": [{"name", "status", "detail"}]}
```

The pipeline builds the program first, so a suite finds the binary inside `<project_dir>`.
`tests/fixtures/suites/` has working examples.

## What a function's agent sees

| Path in container | Contents |
|---|---|
| `/work/project` | the current program, read-only |
| `/src/edit/<fn>.c` or `.rs` | the only file the agent edits |
| `/src/suite` | the visible suite, read-only |
| `agent-test` | splices the function file in, checks the signature and additions, builds, runs the visible suite, prints a summary |
| `agent-worker "<instructions>"` | orchestrator topology only |

(This table describes depth mode. In lineage mode the agent works in `/work`, a copy of the
stage workspace, and has `agent-build` instead of `agent-test`.)

The hidden suite is never mounted into an agent's container. Once an agent finishes,
the controller re-verifies its result in a container with no network and then runs
the hidden suite.

## Plugins

| Kind | Configured by | Built-ins |
|---|---|---|
| Call-graph backend | `callgraph.c_backend`, `callgraph.rust_backend` | `svf`, `rupta`, `mir` |
| Selector | `depth.selector` | `depth` |
| Generator | `agent.generator` | `minisweagent` |
| Locate/splice/signature (runs in-container) | `plugins.language` (module path) | built-in C/Rust |
| Test runner / feedback (runs in-container) | `plugins.test_runner`, `plugins.feedback` (`module:Class`) | `SuiteRunner`, `SummaryFormatter` |

Host-side plugins can be referenced by built-in name or by `package.module:Class`. The
interfaces are in `src/interfaces.py`.

## Outputs

Each depth run writes to `runs/<timestamp>-<input>/`:

- `manifest.json`
- `baseline.json`
- `callgraph.json`
- `selection.json`
- `functions/*/`: one folder per function with its target, its attempts (agent
  trajectories, candidate, verification result, spliced program, hidden result) and
  `record.json`
- `final/` in cumulative mode, or `variants/` in independent mode
- `summary.json`

## The pipeline's own tests

```bash
.venv/bin/python -m pytest tests                 # unit tests + Docker e2e with scripted models
```

The end-to-end tests run the real pipeline (images, SVF/MIR, mini-swe-agent sessions,
verification, hidden suites) using scripted models instead of a real LLM. They are
skipped if the images haven't been built.
