"""The suite's vocabulary: the tracker-to-suite glossary (``docs/knowledge-plan.md``)."""

from ticket2test.knowledge.glossary import (
    Glossary,
    GlossaryError,
    Term,
    load_glossary,
    match_terms,
    record_unmapped,
    unknown_words,
    unmapped_log_path,
)

__all__ = [
    "Glossary",
    "GlossaryError",
    "Term",
    "load_glossary",
    "match_terms",
    "record_unmapped",
    "unknown_words",
    "unmapped_log_path",
]
