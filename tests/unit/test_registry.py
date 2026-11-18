from __future__ import annotations

import pytest

from src import registry


def test_import_path_reference():
    assert registry.resolve("selector", "collections:OrderedDict").__name__ == "OrderedDict"


def test_unknown_builtin_lists_choices():
    with pytest.raises(registry.PluginError, match="built-ins"):
        registry.resolve("callgraph", "doxygen")


def test_bad_import_path():
    with pytest.raises(registry.PluginError):
        registry.resolve("callgraph", "no_such_module_xyz:Thing")
    with pytest.raises(registry.PluginError):
        registry.resolve("callgraph", "collections:NoSuchAttr")


def test_register_custom_builtin():
    registry.register("callgraph", "test-ordered", "collections:OrderedDict")
    try:
        assert registry.resolve("callgraph", "test-ordered").__name__ == "OrderedDict"
    finally:
        registry.BUILTINS["callgraph"].pop("test-ordered")


def test_every_kind_has_builtins():
    for kind in registry.kinds():
        assert registry.BUILTINS[kind]
