from __future__ import annotations

import pytest

from ticket2test.normalize.jira_markup import adf_to_markdown, wiki_to_markdown
from ticket2test.normalize.markdown import extract_urls, markdown_to_text, split_lines
from ticket2test.normalize.sections import extract_sections, heading_kind


def _sections(md: str):  # type: ignore[no-untyped-def]
    return extract_sections(split_lines(md))


# --- markdown_to_text ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("md", "text"),
    [
        ("## Title ##", "Title"),
        ("**bold** and *italic* and ~~gone~~", "bold and italic and gone"),
        ("call `client.get()` now", "call client.get() now"),
        ("see [docs](https://x.example/d)", "see docs (https://x.example/d)"),
        ("[https://a.example](https://a.example)", "https://a.example"),
        ("![shot](https://img.example/a.png)", "shot (https://img.example/a.png)"),
        ("<https://auto.example>", "https://auto.example"),
        ("> quoted", "quoted"),
        ("a<br>b", "a\nb"),
        ("<details><summary>Logs</summary>x</details>", "Logsx"),
        ("&lt;tag&gt; &amp;", "<tag> &"),
        ("before <!-- hidden\nmultiline --> after", "before  after"),
        ("---", ""),
    ],
)
def test_markdown_to_text(md: str, text: str) -> None:
    assert markdown_to_text(md) == text


def test_python_names_and_non_html_angle_text_survive() -> None:
    assert markdown_to_text("`__init__` and __init__ and **kwargs") == (
        "__init__ and __init__ and **kwargs"
    )
    assert markdown_to_text("returns `<Request('GET', 'x')>`") == "returns <Request('GET', 'x')>"
    assert markdown_to_text("returns <Request('GET', 'x')>") == "returns <Request('GET', 'x')>"


def test_code_blocks_are_verbatim() -> None:
    md = "Text **b**\n\n```python\n# not a heading\nx = **kwargs  # <!-- keep -->\n```\nafter"
    assert markdown_to_text(md) == (
        "Text b\n\n```python\n# not a heading\nx = **kwargs  # <!-- keep -->\n```\nafter"
    )


def test_unclosed_fence_treats_rest_as_code() -> None:
    assert markdown_to_text("```\n**raw**") == "```\n**raw**"


def test_crlf_and_blank_line_collapse() -> None:
    assert markdown_to_text("a\r\n\r\n\r\n\r\nb  ") == "a\n\nb"


def test_extract_urls_skips_code_and_dedupes() -> None:
    md = "see https://a.example/x. and https://a.example/x\n`https://inline.example`\n```\nhttps://code.example\n```"
    assert extract_urls(split_lines(md)) == ["https://a.example/x"]


# --- sections --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("heading", "kind"),
    [
        ("Steps to reproduce", "steps"),
        ("To Reproduce:", "steps"),
        ("How to reproduce", "steps"),
        ("Minimal reproducible example", "steps"),
        ("Expected behaviour", "expected"),
        ("Expected result(s)", "expected"),
        ("Actual Behavior", "actual"),
        ("Current behavior", "actual"),
        ("What happened?", "actual"),
        ("Environment", None),
        ("Describe the bug", None),
        ("Example", None),
        ("Current workaround", None),
        ("Expected that this would be a very long sentence and not a heading at all", None),
    ],
)
def test_heading_kind(heading: str, kind: str | None) -> None:
    assert heading_kind(heading) == kind


def test_heading_styles() -> None:
    md = (
        "**Steps to reproduce**\n1. one\n2. two\n\n"
        "Expected: it works\n\n"
        "**Actual:** it breaks\nbadly\n"
    )
    s = _sections(md)
    assert s.steps == ["one", "two"]
    assert s.expected == "it works"
    assert s.actual == "it breaks\nbadly"


def test_other_heading_ends_section_and_code_headings_are_ignored() -> None:
    md = "### To reproduce\n```\n# Expected: not a heading\n```\n### Environment\n- OS: x"
    s = _sections(md)
    assert s.steps == ["```\n# Expected: not a heading\n```"]
    assert s.expected is None


def test_list_items_with_continuation_and_nested_code() -> None:
    md = "## Steps\n1. Install it\n   with pip\n2. Run:\n   ```\n   tool --go\n   ```\n3. Done\n"
    assert _sections(md).steps == ["Install it\nwith pip", "Run:\n```\ntool --go\n```", "Done"]


def test_no_sections_found() -> None:
    s = _sections("Something is broken. Expected it to work, but it did not.")
    assert s.steps == [] and s.expected is None and s.actual is None


# --- Jira markup -----------------------------------------------------------------------------


def test_wiki_to_markdown() -> None:
    wiki = (
        "h3. Steps\n* a\n** nested\n# first\n"
        "{{code}} [x|https://e.example] [https://b.example]\n"
        "{noformat}\nraw *x*\n{noformat}\nbq. quote"
    )
    assert wiki_to_markdown(wiki) == (
        "### Steps\n- a\n  - nested\n1. first\n`code` [x](https://e.example) https://b.example\n"
        "```\nraw *x*\n```\n> quote"
    )


def test_wiki_inline_code_block_and_unclosed() -> None:
    assert wiki_to_markdown("{code:language=java}int x;{code}") == "```java\nint x;\n```"
    assert wiki_to_markdown("{code}\nopen") == "```\nopen\n```"


def test_adf_unknown_nodes_and_tables() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "panel",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "in panel"}]}
                ],
            },
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "a"}],
                                    }
                                ],
                            },
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "b"}],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            {"type": "mediaSingle", "content": [{"type": "media"}]},
            {"type": "someFutureNode", "text": "fallback"},
        ],
    }
    assert adf_to_markdown(doc) == "in panel\n\na | b\n\n[attachment]\n\nfallback"
