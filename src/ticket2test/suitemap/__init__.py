"""The suite map: per-area summaries of the target test suite, built from the index by code."""

from ticket2test.suitemap.build import build_map
from ticket2test.suitemap.render import load_map, write_map

__all__ = ["build_map", "load_map", "write_map"]
