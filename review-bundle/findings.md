# Findings: temperature sweep on the `new_mkdir` base checkpoint

Two models, same prompt, same test suite, same harness, same temperature grid.
Analysis is schema-v5 / analyzer v4.1.2. All numbers below come from
`runs/experiments/<model>/000_base_new_mkdir/temp-*/analysis/summary.json`;
the same values are tabulated in `review-bundle/results.csv`.

## What was run

| | gpt-oss:120b | qwen3:235b-a22b |
|---|---|---|
| Temperatures | 0, 0.125, 0.25, 0.5, 1.0, 2.0 | 0, 0.125, 0.25 |
| Attempts per temperature | 10 | 10, 10, 7 |
| Attempts analyzed | 60 | 27 |
| Status | complete | **stopped early** |

Both runs used `--max-loops 3`; gpt-oss ran with `--timeout 1800`, qwen with
`--timeout 5400`.

The qwen sweep was stopped by hand partway through temperature 0.25 after
running overnight. Temperatures 0.5, 1.0 and 2.0 were never started, and
temperature 0.25 has **n = 7, not 10**. The attempt that was mid-flight when it
was stopped (`temp-0p25/attempt-008`) produced no candidate and no metadata, so
it is excluded from every number here — including it would have counted an
unfinished session as a failure.

**The two models are therefore only comparable at temperatures 0, 0.125 and
0.25.** Anything said about the shape of the temperature curve applies to
gpt-oss alone.

## Headline result: nothing passed on the first try

`initial_public_success_rate` is **0.00 at every temperature, for both models,
across all 87 analyzed attempts.** Not one initial generation passed build +
base tests + feature tests.

Every success in this dataset came from the repair loop. The end-to-end success
column and the repair-recovery column are consequently identical everywhere —
the recovery rate *is* the success rate, because the denominator (initial
failures eligible for repair) is the whole population.

Wilson 95% CI on that zero, at n = 10, is [0, 0.28]; at the pooled n = 87 it is
tight enough to treat as a real property of this checkpoint rather than noise.
The practical reading: **for this task the controller-driven repair loop is not
a safety net, it is the mechanism.** A single-shot harness would have measured
0% for both models.

Most repairs land on the first loop:

| Model | 1 loop | 2 loops | 3 loops |
|---|---|---|---|
| gpt-oss:120b | 45 | 10 | 5 |
| qwen3:235b-a22b | 13 | 11 | 3 |

## Success against temperature

| Temp | gpt-oss e2e | gpt-oss pass@1 | qwen e2e | qwen pass@1 |
|---|---|---|---|---|
| 0.0 | 0.90 (9/10) | 0.90 | 0.90 (9/10) | 0.90 |
| 0.125 | 0.80 (8/10) | 0.80 | **0.90 (9/10)** | 0.90 |
| 0.25 | 0.80 (8/10) | 0.80 | 0.71 (5/7) | 0.71 |
| 0.5 | 0.60 (6/10) | 0.60 | — | — |
| 1.0 | 0.40 (4/10) | 0.40 | — | — |
| 2.0 | 0.40 (4/10) | 0.40 | — | — |

gpt-oss degrades monotonically and steeply: 0.90 → 0.40 across the grid, a
better-than-2× drop. The three points where both models exist are within each
other's confidence intervals (all n ≤ 10, Wilson half-widths ≈ ±0.3), so **the
qwen-vs-gpt-oss comparison is not resolved by this data.** Do not report a
winner from these three points.

`pass@5` and `pass@10` are ≈1.0 nearly everywhere, including at temperature 2.0.
Sampling ten times and keeping any passing candidate recovers essentially full
success even where single-shot success has collapsed to 0.40.

## Diversity

Measurement coverage is 1.0 — clang, tree-sitter and GumTree all resolved for
every candidate, so these are complete measurements, not partial ones.

| Model | Temp | Passing n | Effective families | Dominant share | Vendi |
|---|---|---|---|---|---|
| gpt-oss | 0.0 | 9 | 1.00 | 1.00 | 1.11 |
| gpt-oss | 0.125 | 8 | 1.00 | 1.00 | 1.12 |
| gpt-oss | 0.25 | 8 | 1.00 | 1.00 | 1.11 |
| gpt-oss | 0.5 | 6 | 1.00 | 1.00 | 1.08 |
| gpt-oss | 1.0 | 4 | 1.00 | 1.00 | 1.37 |
| gpt-oss | 2.0 | 4 | 1.00 | 1.00 | 1.08 |
| qwen | 0.0 | 9 | 1.00 | 1.00 | 1.07 |
| qwen | 0.125 | 9 | **1.42** | 0.89 | 1.37 |
| qwen | 0.25 | 5 | **1.65** | 0.80 | 1.57 |

Two things stand out.

**gpt-oss collapses to a single architectural family at every temperature.**
Effective family count is exactly 1.00 from 0 through 2.0. Raising temperature
degrades correctness without buying architectural variety — it produces worse
versions of the same design, not different designs. The Vendi bump at 1.0 (1.37)
sits on only 4 passing implementations and its bootstrap CI overlaps the others;
treat it as noise.

**qwen shows genuine architectural spread at low temperature** — 1.42 effective
families at 0.125 and 1.65 at 0.25, against gpt-oss's flat 1.00. This is the
most interesting signal in the dataset. It is also the least certain: 9 and 5
passing implementations respectively, and the sweep was cut off before the
temperatures where the effect would either grow or vanish.

`exact_unique_rate` is 1.0 everywhere — no two attempts ever produced
byte-identical source, even at temperature 0. Textual novelty is therefore not
evidence of architectural novelty, which is exactly why the clustering metric
carries the argument and the hash metric does not.

## Failure and attrition

Infrastructure attrition is 0.00 for both models — no harness-side losses.

gpt-oss recorded **zero** agent-execution failures across 60 attempts. qwen
recorded **3 timeouts** across 27 (1 at temp 0, 2 at temp 0.25), each a session
exceeding the 5400 s limit. These are classified as agent-execution failures,
not infrastructure attrition, and they suppress qwen's measured success rate:
temperature 0.25's 5/7 includes 2 attempts that were cut off mid-work rather
than answering wrongly.

A behavioural difference worth noting:

| Model | `success` | `no_progress` | `loop_limit` | `agent_execution_failure` |
|---|---|---|---|---|
| gpt-oss:120b | 39 | **18** | 3 | 0 |
| qwen3:235b-a22b | 23 | **0** | 1 | 3 |

`no_progress` means a repair session returned byte-identical source and the
controller stopped early rather than spend the remaining budget. **30% of
gpt-oss attempts plateaued this way; qwen never did.** When gpt-oss fails to fix
something on the first repair, it tends to re-emit the same file; qwen always
changed something. This means gpt-oss's failures used less of the repair budget
than its `--max-loops 3` allowance suggests — its numbers are not "3 loops of
effort", they are closer to 1.3.

## Cost

| Model | Attempts | Sessions | Tokens | Wall clock | Per attempt |
|---|---|---|---|---|---|
| gpt-oss:120b | 60 | 140 | 17.5 M | 3.3 h | 3.3 min |
| qwen3:235b-a22b | 27 | 71 | 5.0 M | 17.5 h | 39 min |

**qwen is ~12× slower per attempt for no measured accuracy gain.** I projected
~6× before the run; the real figure is roughly double that, which is why three
temperatures rather than six completed overnight. Finishing the qwen grid at
this rate needs a further ~21 hours.

Reasoning tokens read 0 for both models. That is an Ollama reporting limitation
— its OpenAI-compatible endpoint does not break out reasoning tokens — not an
absence of reasoning. Reasoning *blocks* are counted from the transcripts and
are non-zero for both.

## What I would not conclude from this

- **That either model is better.** Three overlapping temperature points at
  n ≤ 10 cannot separate them.
- **That qwen is more architecturally diverse.** The effect is real in the data
  and absent in gpt-oss, but rests on 5–9 passing implementations at two
  temperatures, one of which has n = 7.
- **That temperature 2.0 is unusable.** pass@10 is still 1.0 there for gpt-oss.
  Single-shot success collapses; best-of-n does not.

## Suggested next steps

1. **Finish the qwen grid** (0.5, 1.0, 2.0, plus the 3 missing attempts at 0.25)
   — ~21 h. Re-running the original command resumes; completed attempts skip.
2. **Raise qwen's timeout above 5400 s** or accept the 3 lost attempts. The
   timeouts are concentrated at higher temperature, exactly where the run was
   heading, so they will get worse.
3. **Feed `--diversity-k-max`** to the analyzer. `family_discovery_auc_at_kmax`
   is null throughout because it was never supplied, so the DF@K curves are
   reported only in full-population form and are not comparable across the
   unequal n values in this dataset.
4. **Treat n = 10 as a floor, not a target,** if the architectural-diversity
   result is the one being pursued. The passing populations that carry it are
   4–9 implementations wide.

## Reproducing

```bash
bash scripts/run_experiment.sh \
  --model ollama/gpt-oss:120b \
  --remote-base-url http://localhost:11434/v1 \
  --temp-list 0.0,0.125,0.25,0.5,1.0,2.0 \
  --runs 10 --max-loops 3 --timeout 1800 \
  --prompt prompts/mkdir/000_base_new_mkdir.md \
  --source src/new_mkdir/new_mkdir.c --source-mode new \
  --test-dir tests/mkdir-test-suite \
  --build-cmd "mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir" \
  --feature-test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir" \
  --output-dir runs/experiments/gpt-oss-120b/000_base_new_mkdir
```

The qwen run is the same with `--model ollama/qwen3:235b-a22b`,
`--timeout 5400`, and a matching `--output-dir`.

One harness caveat for anyone rerunning: each attempt's working directory is
made its own Git repository so that OpenCode's `external_directory` deny rules
take effect. Without it OpenCode resolves the session's project root to the
enclosing checkout, treats every repository path as internal, and the agent can
write outside its sandbox — which it did, into the real source tree, before this
was fixed. Results produced without that fix are not trustworthy.
