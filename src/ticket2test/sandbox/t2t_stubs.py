"""pytest plugin, run only inside the sandbox container (``-p t2t_stubs``).

Modules in the stub folder (``sandbox.stub_dir``, copied to ``/work/stubs``) replace the
suite's modules of the same top-level name, whatever the suite does to ``sys.path`` (a
``pythonpath`` setting or a conftest inserting the repo root would otherwise win). Loaded
before any conftest, so the suite's own imports already see the stubs. Plain Python that also
runs on older interpreters (the suite's own Python version).
"""

from __future__ import annotations

import importlib.machinery
import os
import sys

STUBS = "/work/stubs"


def _stubbed() -> set[str]:
    names = set()
    for entry in os.listdir(STUBS) if os.path.isdir(STUBS) else []:
        if entry.endswith(".py"):
            names.add(entry[:-3])
        elif os.path.isfile(os.path.join(STUBS, entry, "__init__.py")):
            names.add(entry)
    return names


class _StubFinder:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname in self.names:  # submodules follow the stub package's own __path__
            return importlib.machinery.PathFinder.find_spec(fullname, [STUBS])
        return None


_NAMES = _stubbed()
if _NAMES:
    for _name in _NAMES:
        sys.modules.pop(_name, None)
    sys.meta_path.insert(0, _StubFinder(_NAMES))
