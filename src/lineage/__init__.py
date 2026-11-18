"""`python -m src lineage`: checkpoint-by-checkpoint utility regeneration.

The stage plan, per-checkpoint test bundles, the controller-driven repair loop,
Docker build/judge, held-out judge, security evaluation, candidate capture and
configuration fingerprints all stay in src/harness/run_lineage_experiment.sh and
src/harness/run_experiment.sh. The pipeline resolves its config into that script's flags
and supplies the code generator:

  generator = "aider"         the host's Aider, exactly as today
  generator = "minisweagent"  src.lineage.shim, an Aider-compatible executable
                              that runs a mini-swe-agent session (any
                              topology) in a hardened per-session container
"""
