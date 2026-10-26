"""Use accepted proposals for a second generation: in memory only, never on disk.

The catalog gets each proposed member (so the validators accept it), and the generator gets the
members' code as context (so it uses them instead of working around the gap). The repo and the
stored index are untouched; the reviewer applies the patch.
"""

from __future__ import annotations

from ticket2test.index.catalog import ChainEntry, Member
from ticket2test.index.indexer import IndexData
from ticket2test.models.proposal import Proposal


def with_proposals(index: IndexData, proposals: list[Proposal]) -> IndexData:
    """A copy of the index whose catalog has every accepted proposal's member."""
    catalog = index.catalog
    classes = dict(catalog.classes)
    chains = list(catalog.chains)
    for proposal in proposals:
        entry = classes.get(proposal.owner_class)
        if not proposal.ok or proposal.kind is None or entry is None:
            continue
        member = Member(name=proposal.member, kind=proposal.kind, line=entry.line)
        members = {**entry.members, proposal.member: member}
        classes[entry.qualname] = entry.model_copy(update={"members": members})
        chains += [
            ChainEntry(chain=f"{c.chain}.{proposal.member}", kind=proposal.kind, owner=c.type)
            for c in catalog.chains
            if c.type == entry.qualname
        ]
    patched = catalog.model_copy(update={"classes": classes, "chains": chains})
    return index.model_copy(update={"catalog": patched})


def proposal_context(proposals: list[Proposal]) -> str:
    """The accepted members, as text for the generator's context."""
    blocks = [
        f"`{p.owner_class.rsplit('.', 1)[-1]}.{p.member}` ({p.kind}), proposed for this ticket "
        f"and pending review. Use it where the test needs it:\n```python\n{p.code.strip()}\n```"
        for p in proposals
        if p.ok
    ]
    if not blocks:
        return ""
    return "New page-object/helper members (not in the suite yet):\n\n" + "\n\n".join(blocks)
