"""FileInfo -> Chunks. A test chunk = the test function + its decorators/markers + JSON entries."""

from __future__ import annotations

import ast
import fnmatch
from collections.abc import Callable
from typing import Any, NamedTuple

from ticket2test.config import IndexSettings
from ticket2test.index.catalog import SymbolCatalog
from ticket2test.index.extract import ClassInfo, FileInfo, FunctionInfo
from ticket2test.index.pytest_ids import compute_test_ids, is_parametrize
from ticket2test.models.chunk import Chunk, DataFormat, Marker, Parametrize


class DataFile(NamedTuple):
    format: DataFormat
    entries: dict[str, Any]  # pytest id -> entry


DataReader = Callable[[str], DataFile | None]


def is_test_file(path: str, settings: IndexSettings) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in settings.test_file_globs)


def data_file_for(path: str, settings: IndexSettings) -> str:
    return path.removesuffix(".py") + settings.data_file_suffix


def parse_marker(decorator: str, source: str = "function") -> Marker | None:
    """``pytest.mark.priority("p1")`` -> Marker(name="priority", args=["p1"])."""
    head, _, rest = decorator.partition("(")
    parts = head.strip().split(".")
    if len(parts) < 2 or parts[-2] != "mark" or parts[-1] == "parametrize":
        return None
    args: list[Any] = []
    if rest:
        try:
            call = ast.parse(decorator, mode="eval").body
        except SyntaxError:
            call = None
        if isinstance(call, ast.Call):
            for arg in call.args:
                try:
                    args.append(ast.literal_eval(arg))
                except (ValueError, TypeError, SyntaxError):
                    args.append(ast.unparse(arg))
    return Marker(name=parts[-1], args=args, source=source)  # type: ignore[arg-type]


def build_chunks(
    info: FileInfo,
    catalog: SymbolCatalog,
    settings: IndexSettings,
    read_data: DataReader,
    custom_id_hook: bool = False,
) -> list[Chunk]:
    test_file = is_test_file(info.path, settings)
    data: DataFile | None = None
    data_path = data_file_for(info.path, settings)
    if test_file:
        data = read_data(data_path)
    page_objects = set(catalog.page_objects)
    parametrized_fixtures = frozenset(n for n, p in catalog.fixtures.items() if p)

    chunks: list[Chunk] = []
    for fn in info.functions:
        if test_file and fn.name.startswith(settings.test_function_prefix):
            chunks.append(
                _test_chunk(info, fn, None, data, data_path, parametrized_fixtures, custom_id_hook)
            )
        else:
            chunks.append(_function_chunk(info, fn, None))

    for cls in info.classes:
        qualname = f"{info.module}.{cls.name}"
        is_test_class = test_file and cls.name.startswith(settings.test_class_prefix)
        if qualname in page_objects:
            chunks.append(_class_chunk(info, cls, "page_object", whole=True))
        else:
            chunks.append(_class_chunk(info, cls, "class", whole=False))
        for method in cls.methods:
            if is_test_class and method.name.startswith(settings.test_function_prefix):
                chunks.append(
                    _test_chunk(
                        info, method, cls, data, data_path, parametrized_fixtures, custom_id_hook
                    )
                )
            else:
                chunks.append(_function_chunk(info, method, cls))
    return chunks


def _function_chunk(info: FileInfo, fn: FunctionInfo, cls: ClassInfo | None) -> Chunk:
    qualname = f"{cls.name}.{fn.name}" if cls else fn.name
    return Chunk(
        id=f"{info.path}::{qualname}",
        file_path=info.path,
        symbol_name=fn.name,
        qualname=qualname,
        kind="function",
        code=fn.code,
        start_line=fn.start_line,
        end_line=fn.end_line,
        docstring=fn.docstring,
        refs=fn.refs,
        class_name=cls.name if cls else None,
        decorators=fn.decorators,
    )


def _class_chunk(info: FileInfo, cls: ClassInfo, kind: str, whole: bool) -> Chunk:
    return Chunk(
        id=f"{info.path}::{cls.name}",
        file_path=info.path,
        symbol_name=cls.name,
        qualname=cls.name,
        kind=kind,  # type: ignore[arg-type]
        code=cls.code if whole else cls.header_code,
        start_line=cls.start_line,
        end_line=cls.end_line,
        docstring=cls.docstring,
        refs=cls.refs if whole else cls.header_refs,
        decorators=cls.decorators,
    )


def _test_chunk(
    info: FileInfo,
    fn: FunctionInfo,
    cls: ClassInfo | None,
    data: DataFile | None,
    data_path: str,
    parametrized_fixtures: frozenset[str],
    custom_id_hook: bool,
) -> Chunk:
    qualname = f"{cls.name}.{fn.name}" if cls else fn.name
    class_decorators = cls.decorators if cls else []
    params = [p.name for p in fn.params if p.name not in ("self", "cls")]
    ids = compute_test_ids(
        fn.name,
        fn.decorators,
        class_decorators,
        params,
        parametrized_fixtures,
        custom_id_hook,
    )
    argnames = {name for info_ in ids.decorators for name in info_.argnames}
    markers = [m for d in fn.decorators if (m := parse_marker(d, "function"))]
    markers += [m for d in class_decorators if (m := parse_marker(d, "class"))]
    entries = {n: data.entries[n] for n in ids.names if data and n in data.entries}
    return Chunk(
        id=f"{info.path}::{qualname}",
        file_path=info.path,
        symbol_name=fn.name,
        qualname=qualname,
        kind="test",
        code=fn.code,
        start_line=fn.start_line,
        end_line=fn.end_line,
        docstring=fn.docstring,
        refs=fn.refs,
        class_name=cls.name if cls else None,
        decorators=fn.decorators,
        markers=markers,
        parametrize=[
            Parametrize(source=p.source, argnames=p.argnames, ids=p.ids)
            for p in ids.decorators
            if is_parametrize(p.source)
        ],
        fixtures=[p for p in params if p not in argnames],
        test_ids=ids.names,
        test_ids_computed=ids.computed,
        test_ids_note=ids.note,
        data_file=data_path if data is not None else None,
        data_entries=entries,
        data_format=data.format if data is not None else None,
    )
