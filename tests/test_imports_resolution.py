"""Phase 3 of the real-suite fit plan: names a module gets from its imports. Two classes with
the same name in different modules are told apart by what the module imports; a star import
binds what its module defines; new code never uses star imports."""

from __future__ import annotations

from pathlib import Path

import pytest

from ticket2test.config import Settings
from ticket2test.index.catalog import import_map
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.generated import GeneratedTest
from ticket2test.validate.validator import validate_generated

FILES = {
    "pages/__init__.py": "from pages.b import Page\n",
    "pages/a.py": "class Page:\n    def save(self):\n        pass\n",
    "pages/b.py": "class Page:\n    def publish(self):\n        pass\n",
    "helpers.py": "VALUE = 1\n\n\ndef make_thing():\n    return VALUE\n",
    "more.py": "from helpers import *\n\n\ndef other():\n    return make_thing()\n",
}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    root = tmp_path_factory.mktemp("repo")
    for path, text in FILES.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    settings = Settings.model_validate(
        {"paths": {"cache_dir": str(tmp_path_factory.mktemp("cache"))}}
    )
    index, _, _ = update_index(root, settings)
    return settings, index


def test_import_maps_resolve_aliases_and_relative_imports() -> None:
    names, stars = import_map(
        ["import os.path", "import a.b as ab", "from .sib import X as Y", "from m import *"],
        "pkg.mod",
    )
    assert names == {"os": "os", "ab": "a.b", "Y": "pkg.sib.X"}
    assert stars == ["m"]


def test_the_same_class_name_follows_the_modules_imports(built: tuple[Settings, IndexData]) -> None:
    catalog = built[1].catalog
    assert {"pages.a.Page", "pages.b.Page"} <= set(catalog.classes)  # never merged
    assert catalog.class_named("Page", "pages.a").qualname == "pages.a.Page"  # type: ignore[union-attr]
    assert catalog.class_named("Page", "pages.b").qualname == "pages.b.Page"  # type: ignore[union-attr]
    # "from pages import Page" goes through the package's re-export to pages.b
    assert catalog.class_named("Page", "pages").qualname == "pages.b.Page"  # type: ignore[union-attr]


def test_star_imports_bind_what_their_module_defines(built: tuple[Settings, IndexData]) -> None:
    catalog = built[1].catalog
    names, known = catalog.star_names("helpers")
    assert {"VALUE", "make_thing"} <= names and known
    more, known = catalog.star_names("more")
    assert {"make_thing", "other"} <= more and known
    assert catalog.star_names("selenium.webdriver") == (set(), False)
    assert catalog.imported("more", "make_thing") == "helpers.make_thing"


def _generated(code: str) -> GeneratedTest:
    return GeneratedTest(
        code=code,
        file_name="tests/test_x.py",
        data_file_name="tests/test_x.json",
        data_entries=[],
        data_format="array",
        test_ids=["test_a"],
        template_entry_ref=None,
        ticket_id="X-1",
        draft_ref="X-1/d1",
        retrieved_chunk_ids=[],
        prompt_version="test",
        provider="fake",
        model="fake",
        attempts=1,
        context_tokens=0,
    )


def _findings(built: tuple[Settings, IndexData], code: str) -> list[tuple[str, str, str]]:
    settings, index = built
    report = validate_generated(_generated(code), index.catalog, settings, index=index)
    return [(f.check, f.severity, f.message) for f in report.findings]


def test_a_star_import_from_the_repo_binds_names_but_is_flagged(
    built: tuple[Settings, IndexData], tmp_path: Path
) -> None:
    code = "from helpers import *\n\n\ndef test_a():\n   make_thing()\n   nothing_here()\n"
    found = _findings(built, code)
    names = [(sev, msg) for check, sev, msg in found if check == "names"]
    assert names == [("error", "undefined name 'nothing_here'")]  # make_thing is bound
    assert any(check == "star_imports" and sev == "error" for check, sev, _ in found)


def test_a_star_import_from_outside_the_repo_makes_unknown_names_warnings(
    built: tuple[Settings, IndexData],
) -> None:
    code = "from selenium.webdriver import *\n\n\ndef test_a():\n   Chrome()\n"
    names = [(sev, msg) for check, sev, msg in _findings(built, code) if check == "names"]
    assert len(names) == 1 and names[0][0] == "warning" and "can't be checked" in names[0][1]


def test_a_copied_star_import_becomes_the_names_the_code_uses(
    built: tuple[Settings, IndexData],
) -> None:
    """Found on the v7 dev run: the template's shell carried its star import into every attempt,
    so the star-import check failed until the repair rounds ran out."""
    from ticket2test.generate.generator import explicit_star_imports

    catalog = built[1].catalog
    code = "from helpers import *\nfrom os import *\n\n\ndef test_a():\n   make_thing()\n"
    fixed = explicit_star_imports(code, catalog)
    assert fixed.startswith("from helpers import make_thing\nfrom os import *\n")
    unused = explicit_star_imports("from helpers import *\n\n\ndef test_a():\n   pass\n", catalog)
    assert "import" not in unused


def test_import_roots_name_modules_the_way_tests_import_them(tmp_path: Path) -> None:
    """Found on the real suite: its framework lives in a folder the suite puts on the import
    path, so `from framework.x import Y` was an unknown module to the tool."""
    from ticket2test.index.extract import module_name

    assert module_name("svc/test/framework/pages/a.py", ["svc/test"]) == "framework.pages.a"
    assert module_name("svc/test/tester/_shared.py", ["svc/test", "svc/test/tester"]) == "_shared"
    assert module_name("svc/other.py", ["svc/test"]) == "svc.other"
    repo = tmp_path / "repo"
    files = {
        "svc/test/framework/__init__.py": "",
        "svc/test/framework/pages.py": "class Page:\n   def save(self):\n      pass\n",
        "svc/test/tester/_shared.py": "VALUE = 1\n",
        "svc/test/tester/area/test_a.py": (
            "import _shared\nfrom framework.pages import Page\n\n\n"
            "def test_a():\n   Page().save()\n   assert _shared.VALUE\n"
        ),
    }
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")

    def import_errors(roots: list[str]) -> list[str]:
        settings = Settings.model_validate(
            {
                "paths": {"cache_dir": str(tmp_path / f"cache{len(roots)}")},
                "index": {"import_roots": roots},
            }
        )
        index, _, _ = update_index(repo, settings)
        code = files["svc/test/tester/area/test_a.py"]
        generated = _generated(code).model_copy(
            update={"file_name": "svc/test/tester/area/test_a.py"}
        )
        report = validate_generated(generated, index.catalog, settings, index=index)
        return [f.message for f in report.findings if f.check == "imports"]

    assert len(import_errors([])) == 2  # without roots: both imports look unknown
    assert import_errors(["svc/test", "svc/test/tester"]) == []


def test_sibling_modules_and_import_fallbacks(tmp_path: Path) -> None:
    """Found on the real suite: tests import modules from their own folder (pytest puts it on
    the import path), and legacy code imports a Python 2 name inside try/except ImportError."""
    repo = tmp_path / "repo"
    files = {
        "tests/area/helper_base.py": "class AreaBase:\n   def helper(self):\n      pass\n",
        "tests/area/test_a.py": (
            "import helper_base\n"
            "from helper_base import AreaBase\n"
            "try:\n   import urlparse\n"
            "except ImportError:\n   from urllib import parse as urlparse\n"
            "\n\nclass TestA(AreaBase):\n   def test_a(self):\n      self.helper()\n"
        ),
    }
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    settings = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})
    index, _, _ = update_index(repo, settings)
    found = index.catalog.class_named("AreaBase", "tests.area.test_a")
    assert found is not None and found.qualname == "tests.area.helper_base.AreaBase"
    generated = _generated(files["tests/area/test_a.py"]).model_copy(
        update={"file_name": "tests/area/test_a.py"}
    )
    report = validate_generated(generated, index.catalog, settings, index=index)
    assert [f.message for f in report.findings if f.check == "imports"] == []


def test_a_function_local_import_decides_which_class_a_name_means(tmp_path: Path) -> None:
    """Found on the real suite: several modules define the same page class name, and each
    property imports the right one inside its body; the module-wide guess picked another."""
    repo = tmp_path / "repo"
    files = {
        "pages/a.py": "class Page:\n   def save(self):\n      pass\n",
        "pages/b.py": "class Page:\n   def publish(self):\n      pass\n",
        "nav.py": (
            "class Nav:\n   @property\n   def area(self):\n"
            "      from pages.b import Page\n\n      return Page()\n"
        ),
    }
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    settings = Settings.model_validate({"paths": {"cache_dir": str(tmp_path / "cache")}})
    index, _, _ = update_index(repo, settings)
    catalog = index.catalog
    _owner, member = catalog.members_of("nav.Nav")["area"]
    assert member.type_text == "pages.b.Page"
    page = catalog.resolve_type(member.type_text, "nav")
    assert page is not None and page.qualname == "pages.b.Page"
