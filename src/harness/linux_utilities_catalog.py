"""Canonical identities and on-disk layout of the coreutils benchmark (protocol version 1).

A selector is `<language>-<utility>` (e.g. `c-sort`). Everything a selector needs
lives under `coreutils/<utility>/`:

    manifests/<language>.json   checkpoint ladder, build/judge commands
    prompts/<language>/NNN_*.md checkpoint prompts
    judges/<language>.sh        checkpoint judge (placed in the agent's test bundle)
    tests/                      the shared functional suite (one per utility)

Manifest fields `test_dir` and `judge` describe the agent's sandbox layout
(`tests/<selector>-test-suite/...`), not host paths: the host sources are
resolved here.
"""
from pathlib import Path

UTILITIES = ('cp', 'mv', 'mkdir', 'sort', 'grep')
LANGUAGES = ('c', 'rust', 'py')
SELECTORS = tuple(f'{language}-{utility}' for language in LANGUAGES for utility in UTILITIES)
PROTOCOL_VERSION = 1
COREUTILS = 'coreutils'


def utility_name(selector):
    if selector not in SELECTORS:
        raise ValueError('not a standardized Linux selector: ' + selector)
    return selector.split('-', 1)[1]


def language_name(selector):
    utility_name(selector)
    return selector.split('-', 1)[0]


def utility_root(repo: Path, selector: str) -> Path:
    return Path(repo) / COREUTILS / utility_name(selector)


def manifest_path(repo: Path, selector: str) -> Path:
    return utility_root(repo, selector) / 'manifests' / (language_name(selector) + '.json')


def judge_path(repo: Path, selector: str) -> Path:
    return utility_root(repo, selector) / 'judges' / (language_name(selector) + '.sh')


def suite_root(repo: Path, selector: str, fallback: str = '') -> Path:
    if selector in SELECTORS:
        return utility_root(repo, selector) / 'tests'
    return Path(repo) / fallback


def available_selectors(repo: Path) -> list:
    return [s for s in SELECTORS if manifest_path(repo, s).is_file()]
