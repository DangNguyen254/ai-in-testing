"""Live: ticket -> draft -> retrieve -> generate for 5 stand-in tickets (real LLM calls).

Run with `uv run --env-file .env pytest -m live tests/test_generate_live.py -v`.
About 3 LLM calls per ticket (draft, query rewrite, generation) plus any retries/follow-ups.
Each generated pair is saved to output/generated/live/ for human review.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT
from ticket2test.adapters.tickets.jira import JiraExportSource
from ticket2test.config import load_settings
from ticket2test.draft import generate_drafts
from ticket2test.generate.generator import generate_test
from ticket2test.generate.inspect import computed_test_ids
from ticket2test.index.indexer import update_index
from ticket2test.llm.factory import create_llm_client, model_name
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve

STANDIN = REPO_ROOT / "standin"

# The v1 generator builds entries in the v1 stand-in shape (config/seed/inputs/expected);
# stand-in v2 (Phase 3b) replaced it. Re-enabled with generate_v2 (step C).
pytestmark = pytest.mark.skip(reason="v1 generator vs. stand-in v2: rework pending (generate_v2)")
TICKETS = ["STND-101", "STND-102", "STND-103", "STND-104", "STND-106"]
REVIEW_DIR = REPO_ROOT / "output" / "generated" / "live"


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

    # Code and data agree, the config block is copied verbatim, traceability is complete.
    assert computed_test_ids(generated.code) == generated.test_ids == list(generated.data_entries)
    ref = generated.template_entry_ref
    assert ref is not None
    template = next(c for c in index.chunks if c.id == ref.chunk_id).data_entries[ref.entry_key]
    for entry in generated.data_entries.values():
        assert json.dumps(entry["config"]) == json.dumps(template["config"])
    assert generated.retrieved_chunk_ids and generated.draft_ref == primary.id
    assert generated.context_tokens <= settings.context.max_tokens

    folder = REVIEW_DIR / key
    (folder / Path(generated.file_name).parent).mkdir(parents=True, exist_ok=True)
    (folder / generated.file_name).write_text(generated.code, encoding="utf-8")
    (folder / generated.data_file_name).write_text(
        json.dumps(generated.data_entries, indent=2) + "\n", encoding="utf-8"
    )
    (folder / "generated.json").write_text(generated.model_dump_json(indent=2), encoding="utf-8")
