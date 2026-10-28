"""Compare the test ids pytest collected with the ids the tool computes, without showing names.

Usage (from the tool's folder, with the tool's environment):
    uv run --frozen python scripts/compare_collect.py <collect file> <repo root> <rootdir>

<collect file> is what ``pytest --collect-only -q`` printed (one node id per line,
``path/test_x.py::Class::test_y[case]``). <rootdir> is the folder pytest ran from, relative to
the repo root (collected paths are relative to it).

Suites that generate one class per browser or mode (``TestA_<browser>_<mode>::test_b``) run each
method several times; the tool computes the method ids (what data entries are keyed by). So per
file, the set of collected method ids (the part after the last ``::``) is compared with the
tool's. Prints counts and masked shapes only, so the output can be shared.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ticket2test.config import load_settings
from ticket2test.index.indexer import index_dir, load_index

_NODE = re.compile(r"^(?P<path>[^\s:]+\.py)::(?P<rest>\S+)$")


def _shape(test_id: str) -> str:
    """``test_b[x-y]`` -> ``test[2 parts]``: the shape of an id, no names."""
    _, _, bracket = test_id.partition("[")
    if not bracket:
        return "test"
    pieces = bracket.rstrip("]").split("-")
    return f"test[{len(pieces)} part{'s' if len(pieces) > 1 else ''}]"


def main(collect_file: str, repo: str, rootdir: str) -> None:
    runs: dict[str, Counter[str]] = defaultdict(Counter)  # repo path -> method id -> times
    for line in Path(collect_file).read_text(encoding="utf-8", errors="replace").splitlines():
        found = _NODE.match(line.strip())
        if found:
            prefix = rootdir.strip("/").removeprefix(".").strip("/")
            path = f"{prefix}/{found['path']}" if prefix else found["path"]
            runs[path][found["rest"].rsplit("::", 1)[-1]] += 1

    settings = load_settings()
    index = load_index(index_dir(Path(repo), settings), settings)
    if index is None:
        sys.exit("No usable index for this repo and config: run check-suite first.")
    computed: dict[str, set[str]] = {}
    for chunk in index.chunks:
        if chunk.kind == "test" and chunk.file_path in runs:
            computed.setdefault(chunk.file_path, set()).update(chunk.test_ids)

    collected = {path: set(ids) for path, ids in runs.items()}
    same = sum(1 for p in collected if collected[p] == computed.get(p, set()))
    only_collected = Counter(
        _shape(i) for p in collected for i in collected[p] - computed.get(p, set())
    )
    only_computed = Counter(
        _shape(i) for p in collected for i in computed.get(p, set()) - collected[p]
    )
    times = Counter(n for ids in runs.values() for n in ids.values())

    print(
        f"files: {len(collected)} collected, {sum(1 for p in collected if p in computed)} "
        f"in the index, {same} with exactly the same method ids"
    )
    print(
        f"method ids: {sum(map(len, collected.values()))} collected, "
        f"{sum(len(computed.get(p, set())) for p in collected)} computed for the same files"
    )
    print(f"node ids collected: {sum(sum(c.values()) for c in runs.values())}")
    print("runs per method id (browser/mode classes):", dict(sorted(times.items())))
    print("only collected, by shape:", dict(only_collected.most_common(6)) or "none")
    print("only computed, by shape: ", dict(only_computed.most_common(6)) or "none")
    missing = [p for p in collected if p not in computed]
    if missing:
        print(f"files collected but not in the index: {len(missing)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
