"""pytest plugin, run only inside the sandbox container (``-p t2t_stubs``).

Modules in the stub folder (``sandbox.stub_dir``, copied to ``/work/stubs``) replace the
suite's modules of the same dotted name, whatever the suite does to ``sys.path`` (a
``pythonpath`` setting or a conftest inserting the repo root would otherwise win). A stub may
be a top-level module or package (``deploy.py``, ``deploy/__init__.py``) or one module inside a
real package (``framework/runtime_config.py`` without ``framework/__init__.py``: only that
module is replaced). Loaded before any conftest, so the suite's own imports already see the
stubs. Plain Python that also runs on older interpreters (the suite's own Python version).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys

STUBS = os.environ.get("T2T_STUBS_DIR", "/work/stubs")


def _stubbed() -> dict[str, tuple[str, bool]]:
    """Dotted module name -> (file, is_package) for every stub."""
    found: dict[str, tuple[str, bool]] = {}
    if not os.path.isdir(STUBS):
        return found
    for folder, _dirs, files in os.walk(STUBS):
        rel = os.path.relpath(folder, STUBS)
        parts = [] if rel == "." else rel.replace(os.sep, "/").split("/")
        for name in files:
            if not name.endswith(".py"):
                continue
            if name == "__init__.py":
                if parts:
                    found[".".join(parts)] = (os.path.join(folder, name), True)
            else:
                found[".".join([*parts, name[:-3]])] = (os.path.join(folder, name), False)
    return found


class _StubFinder:
    def __init__(self, stubs: dict[str, tuple[str, bool]]) -> None:
        self.stubs = stubs

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> importlib.machinery.ModuleSpec | None:
        stub = self.stubs.get(fullname)
        if stub is None:
            return None
        file, package = stub
        locations = [os.path.dirname(file)] if package else None
        return importlib.util.spec_from_file_location(
            fullname, file, submodule_search_locations=locations
        )


_STUBS = _stubbed()
if _STUBS:
    for _name in _STUBS:
        sys.modules.pop(_name, None)
    sys.meta_path.insert(0, _StubFinder(_STUBS))
