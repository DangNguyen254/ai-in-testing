"""Identifier splitting and static pytest id computation (checked against pytest's IdMaker)."""

from __future__ import annotations

import ast
from typing import Any

import pytest
from _pytest.mark.structures import ParameterSet
from _pytest.python import IdMaker

from ticket2test.index.pytest_ids import compute_test_ids
from ticket2test.index.tokens import split_identifier, tokenize

# --- identifier splitting --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "parts"),
    [
        ("snake_case_name", ["snake", "case", "name"]),
        ("CamelCaseName", ["camel", "case", "name"]),
        ("HTTPServerError", ["http", "server", "error"]),
        ("getHTTPResponseCode", ["get", "http", "response", "code"]),
        ("_private_helper", ["private", "helper"]),
        ("__init__", ["init"]),
        ("utf8_decode", ["utf", "8", "decode"]),
        ("ItemEditorPage", ["item", "editor", "page"]),
        ("URL", ["url"]),
        ("x", ["x"]),
    ],
)
def test_split_identifier(name: str, parts: list[str]) -> None:
    assert split_identifier(name) == parts


def test_tokenize_keeps_whole_identifier_and_drops_noise() -> None:
    tokens = tokenize("def test_merge_url(self): return self.client._merge_url(x)")
    assert "merge_url" in tokens and "test_merge_url" in tokens
    assert tokens.count("merge") == 2
    for noise in ("def", "self", "return", "x"):
        assert noise not in tokens


def test_tokenize_matches_dotted_chains_and_prose() -> None:
    assert tokenize("nav.inventory.item_editor") == [
        "nav",
        "inventory",
        "item_editor",
        "item",
        "editor",
    ]
    assert tokenize("Invite user") == ["invite", "user"]


# --- pytest ids vs pytest's own IdMaker -----------------------------------------------------


def _pytest_ids(decorator: str) -> list[str]:
    """Ids pytest itself would give for one parametrize decorator (no test file is run)."""
    call = ast.parse(decorator, mode="eval").body
    assert isinstance(call, ast.Call)
    namespace: dict[str, Any] = {"pytest": pytest}
    args = [eval(compile(ast.Expression(a), "<d>", "eval"), namespace) for a in call.args]
    kwargs = {
        k.arg: eval(compile(ast.Expression(k.value), "<d>", "eval"), namespace)
        for k in call.keywords
        if k.arg
    }
    argnames, parametersets = ParameterSet._for_parametrize(
        args[0],
        args[1],
        func=None,
        config=None,
        nodeid="t",  # type: ignore[arg-type]
    )
    maker = IdMaker(argnames, parametersets, None, kwargs.get("ids"), None, "t")
    return [str(i) for i in maker.make_unique_parameterset_ids()]


@pytest.mark.parametrize(
    "decorator",
    [
        'pytest.mark.parametrize("q", [1, 50])',
        'pytest.mark.parametrize("q", ["0", "-1"])',
        'pytest.mark.parametrize("a,b", [(1, "x"), (2, "y")])',
        'pytest.mark.parametrize(("a", "b"), [[1, None], [2.5, True]])',
        'pytest.mark.parametrize("v", ["é", "tab\\there", "", "nul\\x00"])',
        'pytest.mark.parametrize("v", [b"\\xc3\\xa9", b"ok"])',
        'pytest.mark.parametrize("v", [{"k": 1}, [1, 2], (3,)])',
        'pytest.mark.parametrize("v", [1, 1, 2, 1])',
        'pytest.mark.parametrize("v", ["a", "a", "a0"])',
        'pytest.mark.parametrize("v", [1, 2, 3], ids=["one", None, "three"])',
        'pytest.mark.parametrize("v", [1, 2], ids=[10, 20])',
        'pytest.mark.parametrize("v", [pytest.param(1, id="first"), 2, pytest.param(3)])',
        'pytest.mark.parametrize("v", [pytest.param("x", marks=pytest.mark.skip)])',
        'pytest.mark.parametrize("v", [1j, -0.5, 1e20])',
    ],
)
def test_single_decorator_ids_match_pytest(decorator: str) -> None:
    ours = compute_test_ids("t", [decorator])
    assert ours.computed, ours.note
    assert ours.names == [f"t[{i}]" for i in _pytest_ids(decorator)]


def test_stacked_decorators_bottom_first() -> None:
    ids = compute_test_ids(
        "test_x",
        [
            'pytest.mark.priority("p2")',
            'pytest.mark.parametrize("mode", ["typed", "pasted"])',
            'pytest.mark.parametrize("q", ["0", "-1"])',
        ],
    )
    assert ids.names == [
        "test_x[0-typed]",
        "test_x[0-pasted]",
        "test_x[-1-typed]",
        "test_x[-1-pasted]",
    ]
    assert [d.argnames for d in ids.decorators] == [["mode"], ["q"]]


def test_class_level_parametrize_comes_after_function_ids() -> None:
    ids = compute_test_ids(
        "test_x",
        ['pytest.mark.parametrize("a", [1, 2])'],
        class_decorators=['pytest.mark.parametrize("b", ["x"])'],
    )
    assert ids.names == ["test_x[1-x]", "test_x[2-x]"]


def test_not_parametrized() -> None:
    ids = compute_test_ids("test_plain", ['pytest.mark.suite("smoke")'])
    assert ids.names == ["test_plain"] and ids.computed


@pytest.mark.parametrize(
    ("decorators", "kwargs", "fragment"),
    [
        (['pytest.mark.parametrize("v", VALUES)'], {}, "argvalues is not a literal list"),
        (['pytest.mark.parametrize("v", [make()])'], {}, "non-literal value"),
        (['pytest.mark.parametrize("v", [1], ids=str)'], {}, "non-literal value"),
        (['pytest.mark.parametrize("v", [])'], {}, "empty argvalues"),
        (
            [],
            {"param_names": ["client"], "parametrized_fixtures": frozenset({"client"})},
            "fixture",
        ),
        (['pytest.mark.parametrize("v", [1])'], {"custom_id_hook": True}, "hook"),
    ],
)
def test_not_statically_computable_is_flagged(
    decorators: list[str], kwargs: dict[str, Any], fragment: str
) -> None:
    ids = compute_test_ids("test_x", decorators, **kwargs)
    assert not ids.computed
    assert ids.note is not None and fragment in ids.note
    assert ids.names == ["test_x"]
