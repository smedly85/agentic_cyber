"""The pipeline: a configurable, plugin-based orchestrator over agentic_cyber machinery.

Modes:
  depth    -- diversify functions selected by call-graph depth (signatures kept)
  lineage  -- checkpoint-by-checkpoint utility regeneration (drives
              src/harness/run_lineage_experiment.sh with Aider or mini-swe-agent)
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.toml"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
