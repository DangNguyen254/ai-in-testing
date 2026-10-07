"""Test reuse through classes: inherited test methods and decorator-generated class variants.

- **Inherited tests.** A test class collects every test method of its bases that it doesn't
  override, including bases outside test files (shared base modules). Bases are resolved
  through the symbol catalog, so they may live in other files.
- **Class variants.** A class decorator configured in ``index.class_variant_decorators``
  generates one test class per value (e.g. ``@variants("delivery", "converted", "original")``
  -> ``TestXConverted``, ``TestXOriginal``); pytest collects the generated classes, not the
  decorated one. The rule says which positional string arguments are the values and how the
  generated classes are named.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping

from ticket2test.config import ClassVariantRule
from ticket2test.index.catalog import SymbolCatalog
from ticket2test.index.extract import ClassInfo, FileInfo, FunctionInfo


def variant_classes(
    class_name: str, decorators: list[str], rules: Mapping[str, ClassVariantRule]
) -> list[str] | None:
    """Names of the classes a variant decorator generates, or None if there is none."""
    for decorator in decorators:
        name = decorator.split("(", 1)[0].strip()
        rule = rules.get(name) or rules.get(name.rsplit(".", 1)[-1])
        if rule is None:
            continue
        values = _string_args(decorator)[rule.values_from :]
        return [
            rule.name.format(
                cls=class_name,
                value=value,
                value_title="".join(part.title() for part in value.split("_")),
            )
            for value in values
        ]
    return None


def inherited_tests(
    info: FileInfo,
    cls: ClassInfo,
    catalog: SymbolCatalog,
    infos: Mapping[str, FileInfo],
    test_prefix: str,
) -> list[tuple[FileInfo, ClassInfo, FunctionInfo]]:
    """(defining file, defining class, method) for each test the class inherits, MRO order."""
    entry = catalog.classes.get(f"{info.module}.{cls.name}")
    if entry is None:
        return []
    seen = {m.name for m in cls.methods}
    found: list[tuple[FileInfo, ClassInfo, FunctionInfo]] = []
    for base in catalog.mro(entry.qualname)[1:]:
        base_info = infos.get(base.file_path)
        base_cls = (
            next((c for c in base_info.classes if c.name == base.name), None) if base_info else None
        )
        if base_info is None or base_cls is None:
            continue
        for method in base_cls.methods:
            if method.name.startswith(test_prefix) and method.name not in seen:
                seen.add(method.name)
                found.append((base_info, base_cls, method))
    return found


def _string_args(decorator: str) -> list[str]:
    try:
        node = ast.parse(decorator, mode="eval").body
    except SyntaxError:
        return []
    if not isinstance(node, ast.Call):
        return []
    return [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
