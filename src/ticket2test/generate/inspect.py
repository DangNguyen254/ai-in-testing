"""Static inspection of generated code (parsed with tree-sitter; the code is never run)."""

from __future__ import annotations

from ticket2test.index.extract import FunctionInfo, ParseError, extract_file
from ticket2test.index.pytest_ids import compute_test_ids


def computed_test_ids(
    code: str, test_prefix: str = "test", class_prefix: str = "Test"
) -> list[str]:
    """Pytest names the code would produce. Raises ValueError with a message for the LLM."""
    try:
        info = extract_file("generated.py", code.encode("utf-8"))
    except ParseError as exc:
        raise ValueError(f"the code does not parse: {exc}") from exc

    ids: list[str] = []
    problems: list[str] = []
    tests: list[tuple[FunctionInfo, list[str]]] = [
        (fn, []) for fn in info.functions if fn.name.startswith(test_prefix)
    ]
    for cls in info.classes:
        if cls.name.startswith(class_prefix):
            tests += [(m, cls.decorators) for m in cls.methods if m.name.startswith(test_prefix)]
    for fn, class_decorators in tests:
        result = compute_test_ids(fn.name, fn.decorators, class_decorators)
        if not result.computed:
            problems.append(f"{fn.name}: {result.note}")
        ids.extend(result.names)
    if problems:
        raise ValueError(
            "parametrize values must be literals so the ids are known before running: "
            + "; ".join(problems)
        )
    if not ids:
        raise ValueError(
            f"no test found: define a method named {test_prefix}_... in a class named "
            f"{class_prefix}..."
        )
    return ids
