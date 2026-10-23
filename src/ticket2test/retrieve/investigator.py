"""The retrieval investigator: a bounded agent that explores the indexed suite.

Each turn the LLM reads the ticket, the first search results and everything its earlier tool
calls returned, then asks for a few more read-only tool calls, updates the list of chunks the
new test needs, and says when it is done. Code runs the tools, enforces the budgets (turns,
actions per turn, output size per tool, transcript size) and checks what comes back: kept ids
that don't exist are dropped and recorded. The tools only read the index; nothing is executed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ticket2test.config import InvestigatorSettings, Settings
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.chunk import Chunk
from ticket2test.models.retrieval import (
    Investigation,
    InvestigatorAction,
    InvestigatorStep,
    KeptChunk,
)
from ticket2test.prompts import PromptTemplate
from ticket2test.retrieve.query import verify_identifiers
from ticket2test.security import scrub_text

if TYPE_CHECKING:  # avoids an import cycle with retrieve.pipeline
    from ticket2test.retrieve.pipeline import Retriever


@dataclass
class _Transcript:
    """Tool calls and their outputs, oldest first; older output is cut to fit the budget."""

    max_chars: int
    entries: list[tuple[str, str]] = field(default_factory=list)  # (call, output)

    def add(self, call: str, output: str) -> None:
        self.entries.append((call, output))

    def render(self) -> str:
        if not self.entries:
            return "(no tool calls yet)"
        blocks = [f"> {call}\n{output}" for call, output in self.entries]
        total = sum(len(b) for b in blocks)
        i = 0
        while total > self.max_chars and i < len(blocks) - 1:
            call = self.entries[i][0]
            short = f"> {call}\n(output removed to fit the budget; run it again if needed)"
            total -= len(blocks[i]) - len(short)
            blocks[i] = short
            i += 1
        return "\n\n".join(blocks)


class IndexTools:
    """The investigator's tools. Read-only over the index; every output is scrubbed and cut."""

    def __init__(self, retriever: Retriever, cfg: InvestigatorSettings) -> None:
        self.retriever = retriever
        self.cfg = cfg

    def run(self, action: InvestigatorAction) -> str:
        arg = action.arg.strip()
        handler = getattr(self, f"_{action.tool}")
        text: str = handler(arg)
        text = scrub_text(text)
        limit = self.cfg.max_tool_output_chars
        if len(text) > limit:
            text = text[:limit] + f"\n... (cut at {limit} characters)"
        return text

    # --- tools ---------------------------------------------------------------------------

    def _search(self, query: str) -> str:
        hits = self.retriever.bm25(query, "investigator")[: self.cfg.results_per_search]
        return self._list([c for c, _ in hits]) or "no results"

    def _grep(self, identifier: str) -> str:
        names, _ = verify_identifiers([identifier], self.retriever.catalog)
        if not names:
            return f"{identifier!r} is not a known identifier"
        name = names[0]
        found = self.retriever.grep(name, "investigator")
        if found:
            return self._list([c for c, _ in found])
        uses = self.retriever.count_containing(name)
        if uses:  # a refusal is not absence: a weak model read it as "doesn't exist"
            defined = [c.id for c in self.retriever.definitions_of(name)][:3]
            where = f"; defined in {', '.join(defined)}" if defined else ""
            return (
                f"{name!r} exists: it is used in {uses} chunks, too many to list{where}. "
                "Use search with more words, or tests_using / callers, to narrow it down"
            )
        return f"{name!r} matches nothing"

    def _open(self, chunk_id: str) -> str:
        chunk = self._chunk(chunk_id)
        if chunk is None:
            return self._unknown(chunk_id)
        lines = [f"{chunk.id} [{chunk.kind}] lines {chunk.start_line}-{chunk.end_line}"]
        if chunk.kind == "test":
            lines.append(f"test ids: {', '.join(chunk.test_ids) or '(none)'}")
            if chunk.data_entries:
                first = next(iter(chunk.data_entries.values()))
                keys = sorted(first) if isinstance(first, dict) else []
                lines.append(f"data entries: {len(chunk.data_entries)}, keys: {', '.join(keys)}")
        lines.append(chunk.code)
        return "\n".join(lines)

    def _callers(self, name: str) -> str:
        short = name.rsplit(".", 1)[-1]
        found = [c for c in self.retriever.chunks.values() if short in c.refs.calls]
        return self._list(sorted(found, key=lambda c: c.id)) or f"nothing calls {short!r}"

    def _tests_using(self, name: str) -> str:
        short = name.rsplit(".", 1)[-1]
        found = [c for c in self.retriever.users_of(short) if c.kind == "test"]
        return self._list(found) or f"no test references {short!r}"

    def _chain(self, prefix: str) -> str:
        prefix = prefix.rstrip(".")
        depth = prefix.count(".") + 1 if prefix else 0
        rows = [
            e
            for e in self.retriever.catalog.chains
            if e.chain.count(".") == depth and (not prefix or e.chain.startswith(prefix + "."))
        ]
        if not rows:
            return f"no page-object members under {prefix!r}"
        return "\n".join(f"{e.chain} ({e.kind}{' -> ' + e.type if e.type else ''})" for e in rows)

    def _data(self, chunk_id: str) -> str:
        chunk = self._chunk(chunk_id)
        if chunk is None:
            return self._unknown(chunk_id)
        if not chunk.data_entries:
            return f"{chunk.id} has no data entries"
        return json.dumps(chunk.data_entries, indent=1, ensure_ascii=False)

    # --- helpers -------------------------------------------------------------------------

    def _chunk(self, chunk_id: str) -> Chunk | None:
        return self.retriever.chunks.get(chunk_id)

    def _unknown(self, chunk_id: str) -> str:
        return f"no chunk with id {chunk_id!r} (use an id exactly as a tool listed it)"

    def _list(self, chunks: list[Chunk]) -> str:
        limit = self.cfg.results_per_search
        rows = [f"{c.id} [{c.kind}]" for c in chunks[:limit]]
        if len(chunks) > limit:
            rows.append(f"... and {len(chunks) - limit} more")
        return "\n".join(rows)


def investigate(
    client: LLMClient,
    prompt: PromptTemplate,
    retriever: Retriever,
    ticket_text: str,
    first_results: list[str],
    settings: Settings,
) -> Investigation:
    cfg = settings.retrieval.investigator
    tools = IndexTools(retriever, cfg)
    transcript = _Transcript(cfg.max_transcript_chars)
    calls: list[str] = []
    seen: set[tuple[str, str]] = set()
    step = InvestigatorStep(thought="", actions=[], keep=[], missing=[], done=False)
    llm_calls = 0
    stopped = "budget"
    steps = 0
    for steps in range(1, cfg.max_steps + 1):
        user = prompt.render_user(
            ticket_text=scrub_text(ticket_text),
            first_results=scrub_text("\n".join(first_results)) or "(no results)",
            transcript=transcript.render(),
            kept=_render_kept(step.keep),
            step=str(steps),
            max_steps=str(cfg.max_steps),
            max_actions=str(cfg.max_actions_per_step),
            max_kept=str(cfg.max_kept),
        )
        result = complete_structured(
            client,
            LLMRequest(
                messages=(
                    Message(role="system", content=prompt.system),
                    Message(role="user", content=user),
                ),
                temperature=settings.llm.temperature,
                seed=settings.llm.seed,
                max_output_tokens=min(settings.llm.max_output_tokens, 4000),
                json_schema=strict_schema(InvestigatorStep),
                model=model_name(settings, "investigate"),
            ),
            InvestigatorStep,
            max_retries=settings.llm.max_retries_on_bad_json,
        )
        llm_calls += result.attempts
        step = result.value
        if step.done:
            stopped = "done"
            break
        if not step.actions:
            stopped = "no_actions"
            break
        for action in step.actions[: cfg.max_actions_per_step]:
            call = f"{action.tool}({action.arg!r})"
            if (action.tool, action.arg) in seen:
                transcript.add(call, "(already run; see its output above)")
                continue
            seen.add((action.tool, action.arg))
            output = tools.run(action)
            transcript.add(call, output)
            calls.append(f"{call} -> {output.count(chr(10)) + 1} line(s)")
    kept, dropped = _checked_keep(step.keep, retriever, cfg.max_kept)
    return Investigation(
        steps=steps,
        tool_calls=calls,
        kept=kept,
        missing=list(step.missing),
        dropped_ids=dropped,
        stopped=stopped,  # type: ignore[arg-type]
        llm_calls=llm_calls,
    )


def _render_kept(keep: list[KeptChunk]) -> str:
    return "\n".join(f"{k.chunk_id}: {k.why}" for k in keep) or "(nothing kept yet)"


def _checked_keep(
    keep: list[KeptChunk], retriever: Retriever, max_kept: int
) -> tuple[list[KeptChunk], list[str]]:
    """Only ids that exist, each once, at most ``max_kept``."""
    kept: list[KeptChunk] = []
    dropped: list[str] = []
    for item in keep:
        if item.chunk_id not in retriever.chunks:
            dropped.append(item.chunk_id)
        elif all(k.chunk_id != item.chunk_id for k in kept) and len(kept) < max_kept:
            kept.append(item)
    return kept, dropped
