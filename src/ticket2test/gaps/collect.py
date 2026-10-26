"""Candidates for missing pieces, from a generated test (logic) and investigator hints.

The main source is the generated test itself: when it reaches a member the catalog doesn't
have (``nav.files.policy.add_hash()`` on a page without ``add_hash``), or calls a plain name
nothing defines, the generator tried to use something the suite lacks. The model never has to
judge that something doesn't exist; it only tried to use it.
"""

from __future__ import annotations

import ast

from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData
from ticket2test.models.gaps import MissingKind, MissingPiece
from ticket2test.models.generated import GeneratedTest
from ticket2test.models.retrieval import MissingHint
from ticket2test.validate.code import bound_names
from ticket2test.validate.validator import chain_analysis


def from_generated(
    generated: GeneratedTest, index: IndexData, settings: Settings
) -> list[MissingPiece]:
    catalog = index.catalog
    pieces: dict[tuple[str, str], MissingPiece] = {}
    # A patch holds the whole existing file: only the new tests' needs count (an existing test
    # may call something the suite lacks, e.g. a test the eval left out).
    new = {i.split("[", 1)[0] for i in generated.new_test_ids}
    for test, found in chain_analysis(generated, index, settings).items():
        if new and test not in new:
            continue
        for use in found.uses:
            if use.status != "missing" or use.missing_owner is None:
                continue
            resolved = sum(step.owner is not None for step in use.steps)
            step = use.steps[resolved]
            owner = use.missing_owner
            kind: MissingKind = "page_object_member" if _is_page_object(owner, index) else "helper"
            key = (owner, step.name)
            pieces.setdefault(
                key,
                MissingPiece(
                    kind=kind,
                    owner=owner,
                    name=step.name,
                    needed_for=f"{test} line {use.line}: {use.text}",
                    source="generated",
                ),
            )
    try:
        tree = ast.parse(generated.code)
    except SyntaxError:
        return list(pieces.values())
    bound = bound_names(tree)
    scopes: list[ast.AST] = [
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in new
    ] or ([tree] if not new else [])
    for node in (inner for scope in scopes for inner in ast.walk(scope)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id not in bound
            and not catalog.find(node.func.id)
        ):
            pieces.setdefault(
                ("", node.func.id),
                MissingPiece(
                    kind="helper",
                    owner="",
                    name=node.func.id,
                    needed_for=f"line {node.lineno}: {node.func.id}(...)",
                    source="generated",
                ),
            )
    return list(pieces.values())


def from_hints(hints: list[MissingHint]) -> list[MissingPiece]:
    return [
        MissingPiece(
            kind=h.kind, owner=h.owner, name=h.name, needed_for=h.needed_for, source="investigator"
        )
        for h in hints
    ]


def _is_page_object(qualname: str, index: IndexData) -> bool:
    catalog = index.catalog
    page_objects = set(catalog.page_objects)
    return qualname in page_objects or any(
        base.qualname in page_objects for base in catalog.mro(qualname)
    )
