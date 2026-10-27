"""FileInfo -> Chunks. A test chunk = the test function + its decorators/markers + JSON entries."""

from __future__ import annotations

import ast
import fnmatch
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from ticket2test.config import IndexSettings
from ticket2test.index.catalog import SymbolCatalog
from ticket2test.index.datafile import function_data_path
from ticket2test.index.extract import ClassInfo, FileInfo, FunctionInfo
from ticket2test.index.inheritance import inherited_tests, variant_classes
from ticket2test.index.pytest_ids import compute_test_ids, is_parametrize
from ticket2test.models.chunk import Chunk, DataFormat, Marker, Parametrize


class DataFile(NamedTuple):
    format: DataFormat
    entries: dict[str, Any]  # pytest id -> entry (own keys)
    defaults: dict[str, Any] | None = None  # the defaults row (index/datafile.py)


DataReader = Callable[[str], DataFile | None]


def is_test_file(path: str, settings: IndexSettings) -> bool:
    """The file name matches ``index.test_file_globs`` and, when ``index.test_paths`` is set,
    the file is inside one of those folders."""
    name = path.rsplit("/", 1)[-1]
    if not any(fnmatch.fnmatch(name, pattern) for pattern in settings.test_file_globs):
        return False
    roots = [p.strip("/") for p in settings.test_paths]
    return not roots or any(path == r or path.startswith(r + "/") for r in roots)


def data_file_for(path: str, settings: IndexSettings) -> str:
    return path.removesuffix(".py") + settings.data_file_suffix


def _data_of(
    info: FileInfo,
    function: str,
    module_data: tuple[DataFile | None, str],
    read_data: DataReader,
    settings: IndexSettings,
) -> tuple[DataFile | None, str]:
    """A per-function data file when the suite has one for this test, else the module's."""
    if settings.function_data_files:
        path = function_data_path(info.path, function, settings)
        if path != module_data[1]:
            found = read_data(path)
            if found is not None:
                if settings.function_file_cases:  # entries name cases: function[case]
                    found = found._replace(entries=case_entries(function, found.entries))
                return found, path
    return module_data


def case_entries(function: str, entries: dict[str, Any]) -> dict[str, Any]:
    """Entries keyed by the pytest id of their case, ``<function>[<entry id>]``."""
    return {
        key if key.startswith(f"{function}[") else f"{function}[{key}]": entry
        for key, entry in entries.items()
    }


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
    infos: Mapping[str, FileInfo] | None = None,
) -> list[Chunk]:
    """Chunks of one file. ``infos`` (every file, by path) lets test classes collect the tests
    they inherit from bases in other files."""
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
            own, own_path = _data_of(info, fn.name, (data, data_path), read_data, settings)
            chunks.append(
                _test_chunk(info, fn, None, own, own_path, parametrized_fixtures, custom_id_hook)
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
        collected = (
            variant_classes(cls.name, cls.decorators, settings.class_variant_decorators)
            if is_test_class
            else None
        ) or []
        for method in cls.methods:
            if is_test_class and method.name.startswith(settings.test_function_prefix):
                own, own_path = _data_of(info, method.name, (data, data_path), read_data, settings)
                chunk = _test_chunk(
                    info, method, cls, own, own_path, parametrized_fixtures, custom_id_hook
                )
                chunks.append(chunk.model_copy(update={"collected_classes": collected}))
            else:
                chunks.append(_function_chunk(info, method, cls))
        if is_test_class and infos is not None:
            prefix = settings.test_function_prefix
            for base_info, base_cls, method in inherited_tests(info, cls, catalog, infos, prefix):
                chunk = _test_chunk(
                    info,
                    method,
                    cls,
                    data,
                    data_path,
                    parametrized_fixtures,
                    custom_id_hook,
                    extra_class_decorators=base_cls.decorators,
                )
                chunks.append(
                    chunk.model_copy(
                        update={
                            "collected_classes": collected,
                            "inherited_from": f"{base_info.path}::{base_cls.name}.{method.name}",
                        }
                    )
                )
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
    extra_class_decorators: list[str] | None = None,
) -> Chunk:
    qualname = f"{cls.name}.{fn.name}" if cls else fn.name
    class_decorators = [*(cls.decorators if cls else []), *(extra_class_decorators or [])]
    params = [p.name for p in fn.params if p.name not in ("self", "cls")]
    ids = compute_test_ids(
        fn.name,
        fn.decorators,
        class_decorators,
        params,
        parametrized_fixtures,
        custom_id_hook,
    )
    names = list(ids.names)
    if data is not None and names == [fn.name]:  # cases from the function's own data file
        cases = [k for k in data.entries if k.startswith(f"{fn.name}[")]
        names = cases or names
    argnames = {name for info_ in ids.decorators for name in info_.argnames}
    markers = [m for d in fn.decorators if (m := parse_marker(d, "function"))]
    markers += [m for d in class_decorators if (m := parse_marker(d, "class"))]
    entries = {n: data.entries[n] for n in names if data and n in data.entries}
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
        test_ids=names,
        test_ids_computed=ids.computed,
        test_ids_note=ids.note,
        data_file=data_path if data is not None else None,
        data_entries=entries,
        data_defaults=(data.defaults or {}) if data is not None else {},
        data_format=data.format if data is not None else None,
    )
