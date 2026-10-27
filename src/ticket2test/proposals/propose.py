"""Agent 2: propose a missing member for an existing test-side class, as a separate patch.

For each reported gap (status missing or close_match) whose owner is a class in the repo, the
LLM writes the one member the test needs. Code then inserts it at the end of the class and
checks the result (``proposals/check.py``): nothing existing changes, the name and kind match
the use, and only existing names are used. Optionally the suite is collected in the sandbox
with the patched file. Findings go back to the model, at most ``proposals.max_repairs`` times.

The patch is never applied to the repo: it is returned as a diff for review.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from ticket2test.config import Settings
from ticket2test.generate.context import estimate_tokens
from ticket2test.generate.patch import FilePatch
from ticket2test.guides.inputs import class_outline
from ticket2test.index.indexer import IndexData
from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import StructuredOutputError, complete_structured
from ticket2test.models.gaps import GapVerdict
from ticket2test.models.proposal import Proposal, ProposalResponse
from ticket2test.prompts import PromptTemplate, load_prompt
from ticket2test.proposals.check import check_patched, insert_member
from ticket2test.sandbox.runner import SandboxError, collect_suite
from ticket2test.security.scrubber import scrub_code
from ticket2test.style.python import FormatError, format_python, target_syntax_error

_MAX_INHERITED = 60


def propose_gaps(
    gaps: list[GapVerdict],
    test_code: str,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    repo_root: Path,
) -> list[Proposal]:
    """A proposal for each class-owned gap, at most ``proposals.max_per_ticket``."""
    prompt = load_prompt(settings.proposals.prompt, settings.paths.prompts_dir)
    seen: set[tuple[str, str]] = set()
    picked: list[GapVerdict] = []
    for verdict in gaps:
        owner = verdict.owner_class
        key = (owner or "", verdict.piece.name)
        if verdict.status not in ("missing", "close_match") or owner is None or key in seen:
            continue
        if owner in index.catalog.classes:
            seen.add(key)
            picked.append(verdict)
    return [
        propose_one(
            v, use_kind(test_code, v.piece.name), index, settings, client, repo_root, prompt
        )
        for v in picked[: settings.proposals.max_per_ticket]
    ]


def use_kind(code: str, name: str) -> str | None:
    """How the test uses ``.name``: "method" when called, "property" when read or assigned,
    None when it doesn't appear (an investigator hint)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    called = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == name]
    if not uses:
        return None
    return "method" if any(id(n) in called for n in uses) else "property"


def propose_one(
    verdict: GapVerdict,
    kind: str | None,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    repo_root: Path,
    prompt: PromptTemplate,
) -> Proposal:
    cfg = settings.proposals
    qualname = verdict.owner_class or ""
    entry = index.catalog.classes[qualname]
    model = model_name(settings, "propose")
    proposal = Proposal(
        owner_class=qualname,
        member=verdict.piece.name,
        kind=kind,  # type: ignore[arg-type]
        file_path=entry.file_path,
        needed_for=verdict.piece.needed_for,
        prompt_version=prompt.version,
        model=model,
    )
    before = (repo_root / entry.file_path).read_text(encoding="utf-8")
    try:
        user = _user_text(prompt, verdict, kind, before, entry.file_path, index, settings)
    except (SyntaxError, ValueError) as exc:
        proposal.findings = [f"the class can't be read: {exc}"]
        return proposal
    messages = [Message(role="system", content=prompt.system), Message(role="user", content=user)]
    for _ in range(cfg.max_repairs + 1):
        request = LLMRequest(
            messages=tuple(messages),
            temperature=settings.llm.temperature,
            seed=settings.llm.seed,
            json_schema=strict_schema(ProposalResponse),
            model=model,
        )
        try:
            result = complete_structured(
                client, request, ProposalResponse, settings.llm.max_retries_on_bad_json
            )
        except StructuredOutputError as exc:
            proposal.attempts += exc.attempts
            proposal.findings = [f"no valid reply: {exc}"]
            return proposal
        except LLMError as exc:
            proposal.findings = [f"LLM call failed: {exc}"]
            return proposal
        proposal.attempts += result.attempts
        reply = result.value
        proposal.code, proposal.rationale = reply.code, reply.rationale
        proposal.kind = proposal.kind or reply.kind
        findings, after = _check(reply, proposal, before, entry.name, index, settings)
        if not findings and cfg.collect:
            findings = _collect(proposal, after, repo_root, settings)
        proposal.findings = findings
        if not findings:
            proposal.ok = True
            proposal.diff = FilePatch(entry.file_path, before, after).diff()
            return proposal
        messages += [
            Message(role="assistant", content=result.response.text),
            Message(
                role="user",
                content="The member fails these checks. Fix them and reply with the corrected "
                "JSON object only.\n" + "\n".join(f"- {f}" for f in findings),
            ),
        ]
    return proposal


def _check(
    reply: ProposalResponse,
    proposal: Proposal,
    before: str,
    class_name: str,
    index: IndexData,
    settings: Settings,
) -> tuple[list[str], str]:
    code = scrub_code(textwrap.dedent(reply.code).strip("\n")).text
    try:
        code = format_python(code + "\n", settings.style.python, []).rstrip("\n")
        after = insert_member(before, class_name, code)
    except (SyntaxError, ValueError, FormatError) as exc:
        return [f"the member does not parse on its own: {exc}"], before
    kind = proposal.kind or reply.kind
    findings = check_patched(
        before, after, class_name, proposal.member, kind, index.catalog, proposal.owner_class
    )
    target = settings.style.python.target_version
    problem = target_syntax_error(code, target)
    if problem:
        findings.append(f"the member uses syntax newer than Python {target} ({problem})")
    return findings, after


def _collect(proposal: Proposal, after: str, repo_root: Path, settings: Settings) -> list[str]:
    try:
        run = collect_suite(repo_root, settings, overlay={proposal.file_path: after})
    except SandboxError:  # no sandbox here: the checks passed, loading stays unconfirmed
        proposal.collect_ok = None
        return []
    proposal.collect_ok = run.exit_code == 0 and not run.timed_out
    if proposal.collect_ok:
        return []
    return [f"the suite no longer loads with the patch: {run.output_tail[-1500:]}"]


def _user_text(
    prompt: PromptTemplate,
    verdict: GapVerdict,
    kind: str | None,
    source: str,
    file_path: str,
    index: IndexData,
    settings: Settings,
) -> str:
    qualname = verdict.owner_class or ""
    class_name = index.catalog.classes[qualname].name
    tree = ast.parse(source)
    node = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None
    )
    if node is None:
        raise ValueError(f"{class_name} is not a top-level class of its file")
    class_code = ast.get_source_segment(source, node) or ""
    if estimate_tokens(class_code, settings.context.chars_per_token) > (
        settings.proposals.max_class_tokens
    ):
        class_code = class_outline(qualname, index, set())
    inherited = [
        f"- {name} ({member.kind}, from {owner.name})"
        for name, (owner, member) in sorted(index.catalog.members_of(qualname).items())
        if owner.qualname != qualname and not name.startswith("__")
    ]
    if len(inherited) > _MAX_INHERITED:
        rest = len(inherited) - _MAX_INHERITED
        inherited = [*inherited[:_MAX_INHERITED], f"- ... and {rest} more"]
    imports = [
        ast.get_source_segment(source, n) or ""
        for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom)
    ]
    return prompt.render_user(
        class_name=class_name,
        file_path=file_path,
        class_code=scrub_code(class_code).text,
        inherited="\n".join(inherited) or "(none)",
        imports="\n".join(imports) or "(none)",
        member=verdict.piece.name,
        kind=kind or "method or property: decide from where it is used",
        needed_for=verdict.piece.needed_for or "(not given)",
        close=", ".join(verdict.close) or "(none)",
    )
