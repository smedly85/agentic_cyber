"""Canonical identities and shared functional-suite ownership (protocol version 1)."""
from pathlib import Path

UTILITIES = ('cp', 'mv', 'mkdir', 'sort')
LANGUAGES = ('c', 'rust', 'py')
SELECTORS = tuple(f'{language}-{utility}' for language in LANGUAGES for utility in UTILITIES)
PROTOCOL_VERSION = 1


def utility_name(selector):
    if selector not in SELECTORS:
        raise ValueError('not a standardized Linux selector: ' + selector)
    return selector.split('-', 1)[1]


def language_name(selector):
    utility_name(selector)
    return selector.split('-', 1)[0]


def suite_root(repo: Path, selector: str, fallback: str = '') -> Path:
    if selector in SELECTORS:
        return repo / 'tests' / ('c-' + utility_name(selector) + '-test-suite')
    return repo / fallback
