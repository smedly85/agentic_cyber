# Measuring implementation diversity across N-version LLM programs

`scripts/measure_diversity.py` measures how different a set of independently
generated implementations of the same specification (e.g. several LLM
samples of `mkdir` at different temperatures) actually are, at several
levels each grounded in an established code-similarity paradigm. This
document is the methodology write-up behind the tool: what each level
measures, why it was chosen, what it does and doesn't tell you, and the
validity controls used to sanity-check the numbers. It is written to be
adapted directly into a paper's methodology section.

## Motivation: diversity as a security property, not just a curiosity

The reason to care about implementation diversity here is **N-version
programming / automated software diversity for security**: if an attacker
finds an exploit against one version, a sufficiently *different* version
should not share it. This is the line of work started by Forrest, Somayaji
& Ackley (1997), formalized for security by Cox et al. ("N-Variant
Systems", *USENIX Security* 2006), surveyed by Larsen, Homescu, Brunthaler
& Franz ("SoK: Automated Software Diversity", *IEEE S&P* 2014), and by
Baudry & Monperrus ("The Multiple Facets of Software Diversity", *ACM
Computing Surveys* 2015). All variants here pass the same test suite; the
question is whether they are diverse *in the ways that matter for exploit
non-transferability*, which is a narrower and more falsifiable claim than
generic code similarity.

This is why the tool reports several distinct levels rather than one
composite "diversity score": a single weighted number invites the
objection that the weights were chosen to produce a desired result. Each
level below answers a distinct, individually defensible question.

## What each level contributes (read this before interpreting output)

Every metric here is a *static, syntactic proxy* for the real claim
(exploit non-transferability). None of them establish it directly - only
differential/behavioral testing against real exploits could do that. Given
that, here is what each level does and does not license you to say:

- **Lexical/token (Level 1)** - a manipulation check: "did sampling
  actually produce different artifacts, or cosmetically-edited near
  clones?" It rules out the trivial-diversity objection. It says nothing
  about exploit transfer - renaming variables preserves every bug.
- **AST (Level 2)** - control-flow *shape* difference, robust to
  renaming/formatting. Informative but noisy at the 40-300 LOC scale of
  these programs; treat as a distribution, not a single number, and see
  the scalability note below for larger inputs.
- **API/call-set (Level 3)** - the most interpretable "different
  algorithm" signal. Two variants with disjoint call sets are following
  genuinely different strategies (e.g. manual path-parsing plus a
  `stat()` pre-check vs. delegating straight to `mkdir(2)`) - which means
  bug classes tied to one strategy (e.g. a TOCTOU race between the
  `stat()` check and the `mkdir()` call) cannot exist in the other.
- **Attack-surface (Level 4)** - the level that most directly carries the
  security claim. It profiles the syntactic constructs an exploit would
  actually need: unsafe string calls, fixed-size stack buffers, heap
  calls, indexing. A memory-corruption exploit needs a corresponding
  construct; if two variants' construct sets are disjoint, that exploit
  *class* cannot transfer between them. This is falsifiable per
  vulnerability class and grounded in attack-surface metrics (Manadhata &
  Wing, *IEEE TSE* 2011) and the diversity-for-security SoK above.
  Limitation: it matches on identifier text (e.g. the call name
  `strcpy`), so it is a *syntactic*, not semantic, detector - see
  Calibration below for a concrete case where this matters.
- **Complexity metrics (lizard)** - reported as descriptive per-variant
  statistics only, **not** used as a distance metric: at 40-300 LOC there
  isn't enough range in NLOC/cyclomatic-complexity for it to discriminate
  anything.
- **Neural (Level 5, `--neural`)** - CodeBLEU (Ren et al., 2020) and
  code-model embedding cosine similarity, included for comparability with
  the LLM-codegen literature. Treat a *high* neural similarity between
  syntactically/structurally distant variants as a genuine negative
  result worth reporting, not noise: it says the embedding space in
  question does not discriminate the kind of diversity this tool is
  built to find. Empirically (see Results below) this is exactly what
  happened on the two real mkdir variants in this repo.
- **Cross-level correlation is itself a finding.** If lexical similarity
  does not predict attack-surface similarity, then token-level clone
  detection is the wrong instrument for a security-diversity claim - a
  methodological result in its own right, not just a diagnostic.

## Level definitions

### Level 1 - Lexical / token similarity
Clone-detection paradigm: Type-1 (identical), Type-2 (renamed), Type-3
(near-miss) clones (Roy, Cordy & Koschke, *Science of Computer Programming*
2009).
- **Normalized Levenshtein ratio** (RapidFuzz) on comment-stripped,
  whitespace-collapsed source.
- **Type-2-normalized token winnowing / Jaccard**: identifiers and
  literals are rewritten to class placeholders (`ID`, `NUM`, `STR`,
  `CHAR`) following the CCFinder normalization (Kamiya, Kusumoto & Inoue,
  *IEEE TSE* 2002), then compared via winnowing k-gram fingerprints
  (Schleimer, Wilkerson & Aiken, *SIGMOD* 2003 - the MOSS algorithm, the
  standard plagiarism-detection technique) and Jaccard similarity of the
  fingerprint sets.

### Level 2 - AST / structural similarity
Normalized tree edit distance between tree-sitter C parse trees (named
nodes only - see Scalability below), computed with APTED (Pawlik &
Augsten, *TODS* 2015 / *Information Systems* 2016), normalized by the
larger tree's size: `similarity = 1 - TED / max(size_a, size_b)`.

### Level 3 - API / strategy profile
Jaccard distance over the set of called function names (extracted via a
tree-sitter `call_expression` walk), plus lizard complexity metrics
reported descriptively (NLOC, cyclomatic complexity, function count, max
nesting - not used as a distance).

### Level 4 - Attack-surface / security-construct profile
A five-category count vector per variant, extracted via tree-sitter:
`unsafe_calls` (`strcpy`, `strcat`, `sprintf`, `gets`, `vsprintf`),
`bounded_risky_calls` (`strncpy`, `strncat`, `snprintf`, `memcpy`,
`memmove`, `stpcpy`), `heap_calls` (`malloc`/`calloc`/`realloc`/`free`/...),
`fixed_stack_buffers` (local array declarations with a literal/macro
size), and `indexing_ops` (`subscript_expression` count). Similarity is
the average of cosine similarity over the raw count vector (scale-
sensitive) and Jaccard similarity over which categories are present at
all (scale-insensitive) - both are also reported per-variant in
`summary.json["per_variant"][label]["attack_surface_vector"]` for direct
inspection.

### Level 5 - Neural / learned similarity (`--neural`, optional)
- **CodeBLEU** (Ren et al., 2020): weighted n-gram + syntax (AST subtree
  match) + dataflow match. CodeBLEU is asymmetric (reference-based); the
  tool reports the mean of both directions.
- **Embedding cosine distance**: mean-pooled last-hidden-state embedding
  from a pretrained code model (default `microsoft/unixcoder-base`) via
  HuggingFace `transformers`, cosine similarity between pairs.

Tool selection across all levels follows the empirical comparison of 30
code-similarity detectors in Ragkhitwetsagul, Krinke & Clark (*EMSE*
2018), which is a reasonable starting citation for justifying this
particular toolset choice in a paper.

## Aggregation

For a set of N variants, each level produces an N x N similarity matrix
(`<level>.csv`) and a heatmap (`figures/<level>_heatmap.png`). Set-level
summaries report mean pairwise distance (overall diversity), min pairwise
distance (the closest, most redundant pair - the one most likely to share
an exploit), and the full distribution (`figures/distance_distribution.png`).
For N >= 3, the tool also runs agglomerative clustering (average linkage,
precomputed 1-similarity distance, `--cluster-threshold` controls the cut)
with silhouette scoring where well-defined, to detect *pseudo-diversity* -
variants that read as textually different but collapse into one strategy
cluster - and computes Spearman correlation between every pair of levels'
pairwise-distance vectors (`figures/cross_level_correlation.png`).

## Validity controls

- **Size normalization**: every similarity is normalized by program/tree/
  token size so that a large-vs-small-file pair doesn't trivially dominate
  the score.
- **Calibration controls** (`--calibrate`): (a) an identical copy of a
  fixture program must score 1.0 at every classical level; (b) a copy with
  every identifier systematically renamed (a synthetic Type-2 clone) must
  score ~1.0 on `ast_ted` and `lexical_winnowing` (both are structural/
  normalized and therefore rename-invariant) while `lexical_levenshtein`
  drops (raw text differs). Run `python3 scripts/measure_diversity.py
  --calibrate` to reproduce; both controls pass in this repo's current
  implementation. One informative *failure mode* the renamed-copy control
  surfaces: because the renaming fixture renames every identifier
  including library-call names (an artificial worst case - real programs
  can't rename `strncpy` itself without breaking compilation), the
  `attack_surface` and `api_callset` levels drop for that synthetic
  control even though nothing "real" changed. This is a genuine and
  disclosed limitation of syntactic (non-semantic) call-name matching: a
  program that aliased a dangerous call behind a wrapper function would
  evade Level 3/4 detection. Worth stating explicitly as a threat to
  validity rather than glossing over.
- **Real-world diversity anchor**: the tool was run against five
  independently developed, real-world `mkdir` implementations vendored
  under `tests/diversity-anchors/mkdir/` (GNU coreutils, BusyBox, toybox,
  FreeBSD, NetBSD - provenance and pinned versions in that directory's
  `SOURCES.md`). Independent human development is the closest available
  approximation to a diversity gold standard (Avizienis, "The N-Version
  Approach to Fault-Tolerant Software", *IEEE TSE* 1985). This anchor run
  is also a strong sanity check on the tool itself, not just a scale
  reference: **FreeBSD and NetBSD's implementations, which share a common
  1983 BSD ancestor (both files carry the identical "Regents of the
  University of California" copyright header), scored as by far the
  closest pair at every level** - AST similarity 0.33 vs. 0.07-0.17 for
  every other pair, API-callset Jaccard 0.48 vs. <=0.13 elsewhere,
  attack-surface similarity 0.92-1.0 vs. <=0.74 elsewhere. The tool
  recovered a known genealogical relationship it was never told about,
  which is meaningful construct validity evidence beyond the synthetic
  calibration controls. Report LLM-variant diversity relative to this
  anchor set's distribution, not in isolation.

## Scalability note (Level 2, AST tree edit distance)

APTED's cost grows much faster than linearly with tree size for large or
structurally dissimilar trees. Using tree-sitter's *named* nodes only
(excluding punctuation/keyword leaves - which is also the methodologically
correct notion of "AST" as opposed to a full concrete syntax tree) was
necessary in practice: on this repo's ~300-line GNU coreutils `mkdir.c`
against the ~50-line toybox implementation, using all (including
anonymous/punctuation) parse-tree nodes did not finish in several minutes;
restricting to named nodes reduced the tree from ~1800 to ~1024 nodes and
the same pair completed in ~1.3s. `measure_diversity.py` additionally caps
tree size at `MAX_AST_NODES = 20000` (named nodes) as a safety valve -
pairs that exceed it report `NaN` for `ast_ted` with a printed warning
rather than hanging, and downstream clustering/correlation for that level
degrade gracefully. This ceiling was never approached by any file in this
repo's actual corpus (largest observed: ~1024 named nodes); it exists for
robustness against much larger inputs, not because it was needed here.

## Results on this repo's current corpus (for context)

As of this writing, `runs/` contains exactly two generated `mkdir`
variants (see repo root `runs/runs_vessel/sandboxed/mkdir/...`, 125 and 38
lines). Running the classical levels on them:

| Level | Similarity |
|---|---|
| lexical_levenshtein | 0.47 |
| lexical_winnowing | 0.16 |
| ast_ted | 0.25 |
| api_callset | 0.33 |
| attack_surface | 0.55 |

The attack-surface divergence is concrete and interpretable: the 125-line
variant parses paths manually into fixed `PATH_MAX` stack buffers using
`strcpy`/`strncpy`/`snprintf` (`unsafe_calls: 7, bounded_risky_calls: 2,
fixed_stack_buffers: 4`), while the 38-line variant passes `argv` pointers
directly to `mkdir(2)` with no local buffers at all (`unsafe_calls: 0,
fixed_stack_buffers: 0`). A stack-buffer-overflow exploit against the
first variant's path-parsing logic has no construct to attach to in the
second - a concrete instance of the exploit-non-transferability argument
this whole methodology is built to support.

Under `--neural`, the same pair scores CodeBLEU similarity 0.35 (broadly
consistent with the classical levels) but embedding cosine similarity
**0.85** - substantially higher than every classical/attack-surface
signal. Read at face value this is a negative result about the embedding
metric: `microsoft/unixcoder-base`'s general-purpose embedding space
clusters both programs as "similar C code that implements mkdir" and does
not resolve the security-relevant difference in how they do it. This is
worth reporting as-is (a real finding about which metrics discriminate
security-relevant diversity and which don't) rather than discarding the
neural level; it's exactly the kind of cross-level divergence the
methodology is designed to surface.

With only two generated variants, clustering and cross-level correlation
are skipped (both require >= 3 variants) - this is itself worth noting:
the pipeline currently produces far fewer usable variants than intended
(see `runs/sandboxed/mkdir/` for the newer run, which produced zero code
due to `opencode_permission_rejected`), so a stronger empirical diversity
claim needs more successful generation runs, not just a better metric.

## Deferred: behavioral / differential-testing ground truth

The strongest possible evidence for the exploit-non-transferability
hypothesis - and the natural next step - is differential/behavioral
testing: run every variant against a shared input corpus and measure
divergence in observable behavior (exit code, stdout/stderr, resulting
filesystem state), following the failure-independence line of work
(Knight & Leveson, "An Experimental Evaluation of the Assumption of
Independence in Multiversion Programming", *IEEE TSE* 1986; Littlewood &
Miller, "Conceptual Modeling of Coincident Failures in Multiversion
Software", *IEEE TSE* 1989). This was deliberately deferred rather than
built now, since `tests/mkdir-test-suite/` already provides an exhaustive
golden/fuzz suite whose existing per-run `test.log`s constitute a coarse
behavioral observation vector - worth mining first to see how much
divergence it already exposes before investing in a dedicated harness.
Fuzzing-based crash-overlap (does an input that crashes variant A also
crash variant B?) is the natural extension once a harness exists, and
would be the most direct possible test of the paper's central hypothesis.

## Usage

```bash
# Classical levels (1-4) only, no heavyweight deps:
python3 -m pip install -r scripts/diversity-requirements.txt
python3 scripts/measure_diversity.py "runs/**/new_mkdir.c" --out-dir runs/diversity

# Include the real-world anchor set:
python3 scripts/measure_diversity.py "runs/**/new_mkdir.c" \
  --reference "tests/diversity-anchors/mkdir/*.c" --out-dir runs/diversity

# Add neural metrics (downloads a ~500MB model on first use):
python3 -m pip install codebleu torch transformers
python3 scripts/measure_diversity.py "runs/**/new_mkdir.c" --neural

# Sanity-check the tool itself before trusting its output on real data:
python3 scripts/measure_diversity.py --calibrate
```

Output: `<level>.csv` pairwise matrices, `figures/*.png` heatmaps and
distributions, and `summary.json` (set-level statistics, per-variant
diagnostics, clustering, cross-level correlation) under `--out-dir`.
