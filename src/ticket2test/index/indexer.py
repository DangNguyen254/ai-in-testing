"""Build, persist, and reload a repo index (chunks, symbol catalog, search tokens).

The index lives in ``<paths.cache_dir>/index/<repo>-<hash>/index.json``. Rebuilds re-parse
only files whose content hash changed; loading a saved index parses nothing.
A file that can't be read or parsed is logged and skipped, never fatal.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ticket2test.adapters.repo.local_path import LocalPathRepoSource, RepoReadError
from ticket2test.config import DataSettings, Settings
from ticket2test.index.catalog import SymbolCatalog, build_catalog
from ticket2test.index.chunks import DataFile, build_chunks, is_test_file
from ticket2test.index.datafile import split_defaults
from ticket2test.index.extract import FileInfo, ParseError, extract_file, sha256_of
from ticket2test.index.search import SearchIndex, chunk_search_text
from ticket2test.index.tokens import tokenize
from ticket2test.models.chunk import Chunk

log = logging.getLogger(__name__)

INDEX_VERSION = 13  # 2: syntax-tree refs; 3: array data files, returned calls; 4: imports;
# 5: inherited tests and class variants; 6: defaults rows, per-function data files;
# 7: page objects by type traversal, chains_truncated; 8: Python 3 parse check;
# 9: return self-chains; 10: per-module import maps and star imports;
# 11: function-local imports; 12: search tokens rebuilt on load, not saved;
# 13: tokens built on first search, sections written one at a time
INDEX_FILE = "index.json"


class SkippedFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    reason: str


class FileRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str
    info: FileInfo | None = None  # None when the file was skipped
    error: str | None = None


class IndexData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = INDEX_VERSION
    repo_root: str
    settings_fingerprint: str
    built_at: datetime
    name_boost: int = 3  # index.name_boost the search tokens are built with
    files: dict[str, FileRecord] = Field(default_factory=dict)
    chunks: list[Chunk] = Field(default_factory=list)
    # Search tokens per chunk: built on the first search (check-suite never searches), never
    # saved. Read them through search_index() or token_map().
    tokens: dict[str, list[str]] = Field(default_factory=dict)
    catalog: SymbolCatalog = Field(default_factory=SymbolCatalog)

    def token_map(self) -> dict[str, list[str]]:
        if not self.tokens and self.chunks:
            self.tokens = _tokens(self.chunks, self.name_boost)
        return self.tokens

    def search_index(self) -> SearchIndex:
        return SearchIndex(self.chunks, self.token_map())


class BuildStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: int = 0
    parsed: int = 0
    reused: int = 0
    skipped: list[SkippedFile] = Field(default_factory=list)
    chunks_by_kind: dict[str, int] = Field(default_factory=dict)
    symbols: int = 0
    chains: int = 0
    chains_truncated: bool = False  # the chain list hit index.max_chain_entries
    seconds: float = 0.0


def settings_fingerprint(settings: Settings) -> str:
    sections = {"index": settings.index.model_dump(mode="json"), "data": settings.data.model_dump()}
    dump = json.dumps(sections, sort_keys=True)
    return hashlib.sha256(f"{INDEX_VERSION}:{dump}".encode()).hexdigest()[:16]


def index_dir(repo_root: Path, settings: Settings) -> Path:
    root = repo_root.resolve()
    key = hashlib.sha256(str(root).lower().encode()).hexdigest()[:10]
    return settings.paths.cache_dir / "index" / f"{root.name}-{key}"


def load_index(directory: Path, settings: Settings) -> IndexData | None:
    """The saved index, or None if missing, unreadable, or built with other settings."""
    path = directory / INDEX_FILE
    if not path.is_file() or not _same_build(path, settings):
        return None  # a large index isn't read just to find it can't be used
    try:
        data = IndexData.model_validate_json(path.read_bytes())
    except ValueError:
        log.warning("Ignoring unreadable index at %s", path)
        return None
    if data.version != INDEX_VERSION or data.settings_fingerprint != settings_fingerprint(settings):
        return None
    return data


def load_files(directory: Path, settings: Settings) -> dict[str, FileRecord] | None:
    """Only the saved index's file records (what an incremental build reuses), without
    reading its chunks and catalog into memory. None when it can't be reused."""
    path = directory / INDEX_FILE
    if not path.is_file() or not _same_build(path, settings):
        return None
    raw = path.read_bytes()
    start = raw.find(b'"files":')
    end = raw.find(b',"chunks":', start)  # no data key in a file record is named so
    if start < 0 or end < 0:
        return None
    try:
        return _FILES.validate_json(raw[start + len(b'"files":') : end])
    except ValueError:
        log.warning("Ignoring unreadable index at %s", path)
        return None


_HEAD = re.compile(
    rb'"version":(\d+),"repo_root":(?:"(?:[^"\\]|\\.)*"),"settings_fingerprint":"(\w+)"'
)


def _same_build(path: Path, settings: Settings) -> bool:
    """The saved index was built by this version with these settings, read from its first
    bytes (the fields are written first). True when that can't be told: the full read decides."""
    with path.open("rb") as handle:
        head = handle.read(8192)
    found = _HEAD.search(head)
    if found is None:
        return True
    version, fingerprint = int(found.group(1)), found.group(2).decode()
    return version == INDEX_VERSION and fingerprint == settings_fingerprint(settings)


def _tokens(chunks: list[Chunk], boost: int) -> dict[str, list[str]]:
    return {c.id: tokenize(chunk_search_text(c, boost)) for c in chunks}


_FILES = TypeAdapter(dict[str, FileRecord])
_CHUNKS = TypeAdapter(list[Chunk])
_CATALOG = TypeAdapter(SymbolCatalog)


def save_index(data: IndexData, directory: Path, attempts: int = 5) -> Path:
    """Write atomically (temp file + rename). On Windows a scanner can briefly lock the new
    file, so the rename is retried, up to ``attempts`` times."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / INDEX_FILE
    tmp = path.with_suffix(".tmp")
    # one section at a time (no buffer of the whole index); the head fields first, in the
    # model's order (_same_build reads them); tokens are never saved
    head = data.model_dump_json(include={"version", "repo_root", "settings_fingerprint"})
    rest = data.model_dump_json(include={"built_at", "name_boost"})
    with tmp.open("wb") as out:
        out.write(head[:-1].encode() + b"," + rest[1:-1].encode())
        out.write(b',"files":' + _FILES.dump_json(data.files))
        out.write(b',"chunks":' + _CHUNKS.dump_json(data.chunks))
        out.write(b',"catalog":' + _CATALOG.dump_json(data.catalog) + b"}")
    for attempt in range(1, attempts + 1):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(0.05 * attempt)
    return path


def build_index(
    repo: LocalPathRepoSource,
    settings: Settings,
    previous: IndexData | dict[str, FileRecord] | None = None,
) -> tuple[IndexData, BuildStats]:
    """``previous``: an earlier index, or just its file records; unchanged files are reused."""
    started = time.perf_counter()
    stats = BuildStats()
    records: dict[str, FileRecord] = {}
    old = previous.files if isinstance(previous, IndexData) else (previous or {})

    for rel in repo.list_files((".py",)):
        path = rel.as_posix()
        stats.files += 1
        try:
            source = repo.read_bytes(rel)
        except (OSError, RepoReadError) as exc:
            records[path] = _skip(stats, path, "", str(exc))
            continue
        digest = sha256_of(source)
        cached = old.get(path)
        if cached is not None and cached.sha256 == digest:
            stats.reused += 1
            records[path] = cached
            if cached.info is None:
                stats.skipped.append(SkippedFile(path=path, reason=cached.error or "skipped"))
            continue
        stats.parsed += 1
        try:
            text = source.decode("utf-8")
            legacy = _python3_error(text)
            if legacy is not None:  # tree-sitter would accept it; Python 3 can't run it
                records[path] = _skip(stats, path, digest, f"{path}: {legacy}")
                continue
            records[path] = FileRecord(
                sha256=digest, info=extract_file(path, source, settings.index.import_roots)
            )
        except UnicodeDecodeError:
            records[path] = _skip(stats, path, digest, f"{path}: not valid UTF-8")
        except ParseError as exc:
            records[path] = _skip(stats, path, digest, str(exc))

    infos = [r.info for r in records.values() if r.info is not None]
    index_settings = settings.index
    catalog = build_catalog(
        infos,
        chain_roots=index_settings.chain_roots,
        max_chain_depth=index_settings.max_chain_depth,
        max_chain_entries=index_settings.max_chain_entries,
    )
    custom_id_hook = any(
        info.path.endswith("conftest.py")
        and any(fn.name == "pytest_make_parametrize_id" for fn in info.functions)
        for info in infos
    )

    infos_by_path = {info.path: info for info in infos}
    data_names: dict[str, list[str]] = {}  # folder -> data file names (function_data_prefix)
    if index_settings.function_data_prefix:
        for rel in repo.list_files((index_settings.data_file_suffix,)):
            data_names.setdefault(str(rel.parent), []).append(rel.name)
    read: dict[str, DataFile | None] = {}  # each data file parsed once; tests share its entries

    def read_data(path: str) -> DataFile | None:
        if path not in read:
            read[path] = _read_data_file(repo, path, settings.data)
        return read[path]

    chunks: list[Chunk] = []
    for info in infos:
        chunks.extend(
            build_chunks(
                info,
                catalog,
                index_settings,
                read_data,
                custom_id_hook,
                infos_by_path,
                lambda folder: data_names.get(folder, []),
            )
        )

    markers: dict[str, set[str]] = {}
    for chunk in chunks:
        for marker in chunk.markers:
            values = markers.setdefault(marker.name, set())
            if marker.args:
                values.add(str(marker.args[0]))
    catalog.markers = {k: sorted(v) for k, v in sorted(markers.items())}

    data = IndexData(
        repo_root=str(repo.root),
        settings_fingerprint=settings_fingerprint(settings),
        built_at=datetime.now(UTC),
        name_boost=index_settings.name_boost,
        files=records,
        chunks=chunks,
        catalog=catalog,
    )
    stats.symbols = len(catalog.symbols)
    stats.chains = len(catalog.chains)
    stats.chains_truncated = catalog.chains_truncated
    if catalog.chains_truncated:
        log.warning("Chain list cut at %d entries (index.max_chain_entries)", len(catalog.chains))
    for chunk in chunks:
        stats.chunks_by_kind[chunk.kind] = stats.chunks_by_kind.get(chunk.kind, 0) + 1
    stats.seconds = round(time.perf_counter() - started, 3)
    return data, stats


def update_index(
    repo_root: Path, settings: Settings, force: bool = False
) -> tuple[IndexData, BuildStats, Path]:
    """Build (incrementally unless ``force``) and save. Returns the index file path too."""
    repo = LocalPathRepoSource(
        repo_root, ignore=settings.index.ignore, max_file_bytes=settings.index.max_file_bytes
    )
    directory = index_dir(repo_root, settings)
    previous = None if force else load_files(directory, settings)  # all it reuses
    data, stats = build_index(repo, settings, previous)
    del previous
    return data, stats, save_index(data, directory, settings.index.save_attempts)


def _python3_error(text: str) -> str | None:
    """Why the file doesn't parse as Python 3 (legacy Python 2 code, a broken file), or None.
    Such a file can't run, so it is left out instead of becoming chunks a test is copied from."""
    try:
        ast.parse(text)
    except SyntaxError as exc:
        return f"does not parse as Python 3 (line {exc.lineno}: {exc.msg}); legacy code?"
    except ValueError as exc:  # null bytes
        return f"does not parse as Python 3 ({exc})"
    return None


def _skip(stats: BuildStats, path: str, digest: str, reason: str) -> FileRecord:
    log.warning("Skipping %s", reason)
    stats.skipped.append(SkippedFile(path=path, reason=reason))
    return FileRecord(sha256=digest, error=reason)


def _read_data_file(
    repo: LocalPathRepoSource, path: str, data_cfg: DataSettings
) -> DataFile | None:
    """Entries by pytest id, from an array of entries (each with the id field, after an optional
    defaults row) or an object keyed by id."""
    id_field = data_cfg.id_field
    rel = PurePosixPath(path)
    if not repo.exists(rel):
        return None
    try:
        data = json.loads(repo.read_text(rel))
    except (OSError, RepoReadError, ValueError) as exc:
        log.warning("Skipping data file %s: %s", path, exc)
        return None
    if isinstance(data, dict):
        return DataFile(format="object", entries=data)
    if not isinstance(data, list):
        return None
    defaults, rows = split_defaults(data, data_cfg)
    entries: dict[str, Any] = {}
    for entry in rows:
        if isinstance(entry, dict) and isinstance(entry.get(id_field), str):
            entries[entry[id_field]] = entry
    if len(entries) < len(rows):
        log.warning(
            "Data file %s: %d entries without a unique %r", path, len(rows) - len(entries), id_field
        )
    return DataFile(format="array", entries=entries, defaults=defaults)


__all__ = [
    "BuildStats",
    "IndexData",
    "build_index",
    "index_dir",
    "is_test_file",
    "load_index",
    "save_index",
    "update_index",
]
