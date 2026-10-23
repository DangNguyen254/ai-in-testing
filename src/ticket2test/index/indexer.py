"""Build, persist, and reload a repo index (chunks, symbol catalog, search tokens).

The index lives in ``<paths.cache_dir>/index/<repo>-<hash>/index.json``. Rebuilds re-parse
only files whose content hash changed; loading a saved index parses nothing.
A file that can't be read or parsed is logged and skipped, never fatal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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

INDEX_VERSION = 6  # 2: syntax-tree refs; 3: array data files, returned calls; 4: imports;
# 5: inherited tests and class variants; 6: defaults rows, per-function data files
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
    files: dict[str, FileRecord] = Field(default_factory=dict)
    chunks: list[Chunk] = Field(default_factory=list)
    tokens: dict[str, list[str]] = Field(default_factory=dict)
    catalog: SymbolCatalog = Field(default_factory=SymbolCatalog)

    def search_index(self) -> SearchIndex:
        return SearchIndex(self.chunks, self.tokens)


class BuildStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: int = 0
    parsed: int = 0
    reused: int = 0
    skipped: list[SkippedFile] = Field(default_factory=list)
    chunks_by_kind: dict[str, int] = Field(default_factory=dict)
    symbols: int = 0
    chains: int = 0
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
    if not path.is_file():
        return None
    try:
        data = IndexData.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        log.warning("Ignoring unreadable index at %s", path)
        return None
    if data.version != INDEX_VERSION or data.settings_fingerprint != settings_fingerprint(settings):
        return None
    return data


def save_index(data: IndexData, directory: Path, attempts: int = 5) -> Path:
    """Write atomically (temp file + rename). On Windows a scanner can briefly lock the new
    file, so the rename is retried, up to ``attempts`` times."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / INDEX_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data.model_dump_json(), encoding="utf-8")
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
    repo: LocalPathRepoSource, settings: Settings, previous: IndexData | None = None
) -> tuple[IndexData, BuildStats]:
    started = time.perf_counter()
    stats = BuildStats()
    records: dict[str, FileRecord] = {}
    old = previous.files if previous else {}

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
            source.decode("utf-8")
            records[path] = FileRecord(sha256=digest, info=extract_file(path, source))
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
    chunks: list[Chunk] = []
    for info in infos:
        chunks.extend(
            build_chunks(
                info,
                catalog,
                index_settings,
                lambda p: _read_data_file(repo, p, settings.data),
                custom_id_hook,
                infos_by_path,
            )
        )

    markers: dict[str, set[str]] = {}
    for chunk in chunks:
        for marker in chunk.markers:
            values = markers.setdefault(marker.name, set())
            if marker.args:
                values.add(str(marker.args[0]))
    catalog.markers = {k: sorted(v) for k, v in sorted(markers.items())}

    tokens = {c.id: tokenize(chunk_search_text(c, index_settings.name_boost)) for c in chunks}
    data = IndexData(
        repo_root=str(repo.root),
        settings_fingerprint=settings_fingerprint(settings),
        built_at=datetime.now(UTC),
        files=records,
        chunks=chunks,
        tokens=tokens,
        catalog=catalog,
    )
    stats.symbols = len(catalog.symbols)
    stats.chains = len(catalog.chains)
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
    previous = None if force else load_index(directory, settings)
    data, stats = build_index(repo, settings, previous)
    return data, stats, save_index(data, directory, settings.index.save_attempts)


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
