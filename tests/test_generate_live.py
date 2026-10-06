"""Live: ticket -> draft -> retrieve -> generate for 5 stand-in tickets (real LLM calls).

Run with `uv run --env-file .env pytest -m live tests/test_generate_live.py -v`.
About 3 LLM calls per ticket (draft, query rewrite, generation) plus any retries/follow-ups.
Each generated pair is saved to output/generated/live-<version>/ for human review, where
<version> comes from generate.prompt_version (generate_v4 -> live-v4). A rerun with the same
prompt version overwrites that folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import load_settings
from ticket2test.draft import generate_drafts
from ticket2test.generate.generator import first_party, generate_test
from ticket2test.generate.inspect import computed_test_ids
from ticket2test.index.indexer import update_index
from ticket2test.llm.factory import create_llm_client, model_name
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve
from ticket2test.style import format_entries, format_python

STANDIN = REPO_ROOT / "standin"
TICKETS = ["STND-101", "STND-102", "STND-103", "STND-104", "STND-106"]
OUTPUT_DIR = REPO_ROOT / "output" / "generated"
LF = chr(10)


@pytest.mark.live
@pytest.mark.parametrize("key", TICKETS)
def test_generate_pair_for_standin_ticket(key: str) -> None:
    settings = load_settings(REPO_ROOT / "config.yaml")
    client = create_llm_client(settings)
    model = model_name(settings)
    index, _, _ = update_index(STANDIN, settings)
    ticket = normalize(JiraExportSource(STANDIN / "tickets" / "export.json").fetch(key), settings)

    drafts = generate_drafts(ticket, client, settings, provider=settings.llm.provider, model=model)
    assert drafts.status == "ok", drafts.missing_info
    primary = next(d for d in drafts.drafts if d.kind == "primary")
    retrieval = retrieve(ticket, index, settings, client, primary)
    generated = generate_test(
        primary,
        retrieval,
        index,
        settings,
        client,
        provider=settings.llm.provider,
        model=model,
        conventions=(STANDIN / "CONVENTIONS.md").read_text(encoding="utf-8"),
    )

    # Code and data agree, entries come from the base entry, output follows the style rules.
    ids = computed_test_ids(generated.code)
    assert ids == generated.test_ids
    entry_ids = [e[settings.data.id_field] for e in generated.data_entries]
    assert set(entry_ids) <= set(ids) and len(entry_ids) == len(set(entry_ids))
    assert generated.code == format_python(
        generated.code, settings.style.python, first_party(index, settings)
    )
    assert generated.template_entry_ref is not None
    for entry in generated.data_entries:  # one expectation section at most
        assert sum(k in entry for k in settings.data.expectation_sections) <= 1
    assert key.split("-")[1] not in generated.file_name
    assert generated.review_checklist
    assert generated.retrieved_chunk_ids and generated.draft_ref == primary.id
    assert generated.context_tokens <= settings.context.max_tokens

    version = settings.generate.prompt_version.removeprefix("generate_")
    folder = OUTPUT_DIR / f"live-{version}" / key
    (folder / Path(generated.file_name).parent).mkdir(parents=True, exist_ok=True)
    (folder / generated.file_name).write_text(generated.code, encoding="utf-8", newline=LF)
    (folder / generated.data_file_name).write_text(
        format_entries(
            generated.data_entries, settings.data, settings.style.json_files, generated.data_format
        ),
        encoding="utf-8",
        newline=LF,
    )
    (folder / "generated.json").write_text(generated.model_dump_json(indent=2), encoding="utf-8")
