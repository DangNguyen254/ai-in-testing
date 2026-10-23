"""Legacy shapes from real suites: Python 2 files."""

from __future__ import annotations

from pathlib import Path

from ticket2test.config import Settings
from ticket2test.index.indexer import update_index
from ticket2test.suitemap import build_map


def test_python2_files_are_left_out_and_reported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_old.py").write_text(
        'print "old"\n\n\nclass TestOld(object):\n    def test_a(self):\n        print "x"\n',
        encoding="utf-8",
    )
    (repo / "tests" / "test_new.py").write_text("def test_b():\n    pass\n", encoding="utf-8")
    settings = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})
    index, stats, _ = update_index(repo, settings)
    assert [c.symbol_name for c in index.chunks if c.kind == "test"] == ["test_b"]
    (skipped,) = stats.skipped
    assert skipped.path == "tests/test_old.py" and "does not parse as Python 3" in skipped.reason
    overview = build_map(index, settings).overview
    assert overview.skipped_files == [f"tests/test_old.py: {skipped.reason}"]
