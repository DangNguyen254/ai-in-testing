"""Page-object paths passed as dotted strings are checked like property chains."""

from __future__ import annotations

import shutil
from typing import Any

import pytest

from tests.conftest import REPO_ROOT
from tests.test_validate import GOOD_CODE, _messages
from ticket2test.config import Settings
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.models.generated import GeneratedTest
from ticket2test.validate.validator import path_string_helpers, validate_generated

STANDIN = REPO_ROOT / "standin"
HELPER = '''
   def go_to(self, path):
      """Open a page by its dotted path under the navigator (the real-suite shape)."""
      target = self.nav
      for step in path.split("."):
         target = getattr(target, step)
      return target
'''


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, IndexData]:
    folder = tmp_path_factory.mktemp("paths")
    repo = folder / "repo"
    shutil.copytree(STANDIN, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    base = repo / "framework" / "base_test.py"
    text = base.read_text(encoding="utf-8")
    anchor = "   def unique_name("
    assert anchor in text
    base.write_text(text.replace(anchor, HELPER.lstrip("\n") + "\n" + anchor, 1), "utf-8")
    settings = Settings.model_validate({"paths": {"cache_dir": str(folder / "cache")}})
    index, _, _ = update_index(repo, settings)
    return settings, index


def _validate(setup: tuple[Settings, IndexData], code: str) -> Any:
    settings, index = setup
    generated = GeneratedTest(
        code=code,
        file_name="tests/rules/test_rules_list_filter.py",
        data_file_name="tests/rules/test_rules_list_filter.json",
        data_entries=[],
        data_format="array",
        test_ids=[],
        template_entry_ref=None,
        ticket_id="X",
        draft_ref="X/d1",
        retrieved_chunk_ids=[],
        prompt_version="v",
        provider="f",
        model="m",
        attempts=1,
        context_tokens=0,
    )
    return validate_generated(generated, index.catalog, settings, index=index)


def _with_call(path: str) -> str:
    anchor = "      rules = self.nav.rules.list\n"
    assert anchor in GOOD_CODE
    return GOOD_CODE.replace(anchor, f'      self.go_to("{path}")\n' + anchor, 1)


def test_the_helper_is_discovered(setup: tuple[Settings, IndexData]) -> None:
    settings, index = setup
    assert "go_to" in path_string_helpers(index, settings)
    off = settings.model_copy(
        update={
            "validation": settings.validation.model_copy(
                update={"discover_path_string_helpers": False}
            )
        }
    )
    assert path_string_helpers(index, off) == set()


def test_real_paths_pass_and_invented_ones_fail(setup: tuple[Settings, IndexData]) -> None:
    good = _messages(_validate(setup, _with_call("rules.list")), "names")
    assert not any("page path" in m for m in good)
    rooted = _messages(_validate(setup, _with_call("nav.rules.wizard")), "names")
    assert not any("page path" in m for m in rooted)
    bad = _messages(_validate(setup, _with_call("rules.gadgets")), "names")
    assert any("page path 'rules.gadgets' doesn't resolve" in m for m in bad), bad
