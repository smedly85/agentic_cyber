"""The pipeline command line.

    python -m src depth [--config config.toml] [--input P] [--depth D] ...
    python -m src lineage [--config config.toml] [--utility NAME] [--lineages N] ...

The TOML defaults to <repo root>/config.toml; CLI flags override it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from src import DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from src.config import (
    ACCUMULATIONS,
    DEPTH_RULES,
    LANGUAGES,
    LINEAGE_GENERATORS,
    LLM_MATCH,
    LLM_MODES,
    ORDERS,
    TOPOLOGIES,
    ConfigError,
    check_ready_for_lineage,
    check_ready_for_run,
    load_config,
    redacted,
)

# CLI dest -> dotted config key
DEPTH_FLAG_KEYS = {
    "language": "depth.language",
    "input": "depth.input",
    "depth": "depth.depth",
    "depth_rule": "depth.rule",
    "order": "depth.order",
    "seed": "depth.seed",
    "accumulation": "depth.accumulation",
    "output_dir": "depth.output_dir",
    "callgraph_backend": None,  # language-dependent, handled below
    "topology": "agent.topology",
    "max_loops": "retry.max_loops",
    "session_timeout": "retry.session_timeout_s",
    "visible_suite": "tests.visible_suite",
    "hidden_suite": "tests.hidden_suite",
    "parallel": "depth.parallel",
}
CACHE_FLAG_KEYS = {
    "llm_cache": "cache.llm",
    "cache_match": "cache.match",
    "cache_namespace": "cache.namespace",
    "cache_dir": "cache.dir",
}


LINEAGE_FLAG_KEYS = {
    "utility": "lineage.utility",
    "generator": "lineage.generator",
    "lineages": "lineage.lineages",
    "lineage_start": "lineage.lineage_start",
    "output_dir": "lineage.output_dir",
    "temperature": "lineage.sampling.temperature",
    "topology": "agent.topology",
    "max_loops": "retry.max_loops",
    "session_timeout": "retry.session_timeout_s",
    "parallel": "lineage.parallel",
}


def add_cache_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("caching")
    group.add_argument("--llm-cache", choices=LLM_MODES, help="off | record (default) | auto (reuse matches) | replay (no LLM)")
    group.add_argument("--cache-match", choices=LLM_MATCH, help="how auto/replay look up responses: exact | sequence")
    group.add_argument("--cache-namespace", help="separate independent repeats that share a cache")
    group.add_argument("--cache-dir")
    group.add_argument("--replay", action="store_true", help="shorthand: --llm-cache replay --cache-match sequence")
    group.add_argument("--no-cache", action="store_true", help="disable every cache for this run")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src", description=__doc__.splitlines()[1].strip() if __doc__ else None)
    sub = parser.add_subparsers(dest="mode", required=True)

    depth = sub.add_parser("depth", help="diversify functions selected by call-graph depth")
    depth.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="TOML config (default: repo-root config.toml)")
    depth.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH, help="model .env (default: repo-root .env)")
    depth.add_argument("--language", choices=LANGUAGES)
    depth.add_argument("--input", help="C/Rust file or project directory")
    depth.add_argument("--depth", type=int, help="depth D; omit to select all eligible functions")
    depth.add_argument("--depth-rule", choices=DEPTH_RULES)
    depth.add_argument("--include-unreachable", action="store_true", default=None)
    depth.add_argument("--order", choices=ORDERS)
    depth.add_argument("--seed", type=int)
    depth.add_argument("--accumulation", choices=ACCUMULATIONS)
    depth.add_argument("--output-dir")
    depth.add_argument("--callgraph-backend", help="name or module:Class for the input's language")
    depth.add_argument("--topology", choices=TOPOLOGIES)
    depth.add_argument("--max-loops", type=int)
    depth.add_argument("--session-timeout", type=float)
    depth.add_argument("--visible-suite")
    depth.add_argument("--hidden-suite")
    depth.add_argument("-j", "--parallel", type=int, help="functions diversified concurrently")
    depth.add_argument("--dry-run", action="store_true", help="compute call graph + selection only")
    depth.add_argument("--print-config", action="store_true", help="print resolved config (secrets redacted) and exit")
    add_cache_flags(depth)

    lineage = sub.add_parser("lineage", help="regenerate a utility checkpoint by checkpoint (run_lineage_experiment.sh)")
    lineage.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="TOML config (default: repo-root config.toml)")
    lineage.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH, help="model .env (default: repo-root .env)")
    lineage.add_argument("--utility", help="<language>-<utility> selector, e.g. c-sort (coreutils/<utility>/manifests/<language>.json)")
    lineage.add_argument("--generator", choices=LINEAGE_GENERATORS)
    lineage.add_argument("--topology", choices=TOPOLOGIES, help="mini-swe-agent topology (generator minisweagent)")
    lineage.add_argument("--lineages", type=int)
    lineage.add_argument("--lineage-start", type=int)
    lineage.add_argument("--temperature", type=float)
    lineage.add_argument("--max-loops", type=int)
    lineage.add_argument("--session-timeout", type=float)
    lineage.add_argument("--output-dir")
    lineage.add_argument("--force", action="store_true", default=None, help="rerun stages that are already complete")
    lineage.add_argument("--analyze", action="store_true", default=None, help="run src/harness/analyze_lineages.py afterwards")
    lineage.add_argument("--list-utilities", action="store_true", help="list utility manifests and exit")
    lineage.add_argument("--dry-run", action="store_true", help="print every stage command without running anything")
    lineage.add_argument("--print-plan", action="store_true", help="print the resolved stage plan and exit")
    lineage.add_argument("--print-config", action="store_true", help="print resolved config (secrets redacted) and exit")
    lineage.add_argument("-j", "--parallel", type=int, help="lineages run concurrently")
    add_cache_flags(lineage)
    return parser


def cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    keys = LINEAGE_FLAG_KEYS if args.mode == "lineage" else DEPTH_FLAG_KEYS
    for dest, key in keys.items():
        value = getattr(args, dest, None)
        if key is not None and value is not None:
            overrides[key] = value
    if args.mode == "lineage":
        for flag in ("force", "analyze"):
            if getattr(args, flag):
                overrides[f"lineage.{flag}"] = True
    elif args.include_unreachable:
        overrides["depth.include_unreachable"] = True
    for dest, key in CACHE_FLAG_KEYS.items():
        if getattr(args, dest, None) is not None:
            overrides[key] = getattr(args, dest)
    if args.replay:
        overrides["cache.llm"] = "replay"
        overrides.setdefault("cache.match", "sequence")
    if args.no_cache:
        overrides["cache.enabled"] = False
    return overrides


def main_lineage(args: argparse.Namespace) -> int:
    from src.lineage import runner

    if args.list_utilities:
        for name in runner.available_utilities():
            print(name)
        return 0
    try:
        config = load_config(args.config, args.env_file, cli_overrides(args), require_config_file=args.config != DEFAULT_CONFIG_PATH)
    except ConfigError as exc:
        print(f"pipeline: config error: {exc}", file=sys.stderr)
        return 2
    if args.print_config:
        print(json.dumps(redacted(config), indent=2, sort_keys=True))
        return 0
    problems = check_ready_for_lineage(config)
    if not (args.dry_run or args.print_plan):
        problems += runner.check_ready(config)
    if problems:
        for problem in problems:
            print(f"pipeline: {problem}", file=sys.stderr)
        return 2
    mode = "dry-run" if args.dry_run else "print-plan" if args.print_plan else "run"
    try:
        return runner.run_lineage(config, mode=mode)
    except ConfigError as exc:
        print(f"pipeline: config error: {exc}", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "lineage":
        return main_lineage(args)

    overrides = cli_overrides(args)
    try:
        config = load_config(args.config, args.env_file, overrides, require_config_file=args.config != DEFAULT_CONFIG_PATH)
        if args.callgraph_backend:
            language = config["depth"]["language"]
            if language is None:
                raise ConfigError("--callgraph-backend needs depth.language")
            config["callgraph"][f"{language}_backend"] = args.callgraph_backend
    except ConfigError as exc:
        print(f"pipeline: config error: {exc}", file=sys.stderr)
        return 2

    if args.print_config:
        print(json.dumps(redacted(config), indent=2, sort_keys=True))
        return 0

    from src.depth.runner import run_depth  # imported lazily: heavy deps

    if not args.dry_run:
        problems = check_ready_for_run(config)
        if problems:
            for problem in problems:
                print(f"pipeline: {problem}", file=sys.stderr)
            return 2
    return run_depth(config, dry_run=args.dry_run)
