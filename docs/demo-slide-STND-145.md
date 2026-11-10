# Demo slide: STND-145 on the stand-in suite

- **Repo:** [DangNguyen254/ai-in-testing](https://github.com/DangNguyen254/ai-in-testing), folder `standin/` (public, MIT; a synthetic web-app test suite with invented names, no company data)
- **Ticket:** STND-145, a synthetic ticket in [`standin/tickets/export.json`](https://github.com/DangNguyen254/ai-in-testing/blob/design-step/standin/tickets/export.json) (its URL points to `jira.example.com`, which doesn't exist)
- **Run:** 2026-11-10, `claude_code_cli` with `claude-sonnet-5-5`, branch `design-step`
- **Commands:**
  ```bash
  uv run ticket2test run STND-145 --jira-export standin/tickets/export.json --repo standin
  uv run ticket2test run STND-145 --jira-export standin/tickets/export.json --repo standin --continue
  ```

## 1. Input ticket

*Caption: The ticket, normalized from a Jira export*

```json
{
  "id": "STND-145",
  "title": "The browser tab on the Exceptions page is titled Rules",
  "description": "The page heading is right, but the browser tab still shows the title of the Rules page. ...",
  "steps_to_reproduce": [
    "Open Exceptions",
    "Look at the title of the browser tab"
  ],
  "expected": "The browser tab is titled Exceptions.",
  "actual": "The browser tab is titled Rules.",
  ...
}
```

## 2. Draft test case (for review)

*Caption: Readable draft a QE approves before code*

```markdown
## 1. Main test: Verify that the browser tab on the Exceptions page is titled Exceptions instead of Rules.
| Priority | p3 |
| Component | exceptions |
| Test type | User interface |
...
| Ticket has explicit steps to reproduce | yes |
| Draft words found in the ticket | 100% |
...
1. Open Exceptions.
2. Look at the title of the browser tab.

**Expected result:** The browser tab is titled Exceptions, not Rules.
```

## 3. Structured test plan

(Line breaks inside the JSON are joined to fit; the values are unchanged.)

*Caption: The same draft as validated JSON*

```json
{
  "intent": "Verify that the browser tab on the Exceptions page is titled Exceptions instead of Rules.",
  "markers": { "priority": "p3", "component": "exceptions", "suite": "regression" },
  "test_kind": "ui",
  "deployment_type": "both",
  "steps": ["Open Exceptions.", "Look at the title of the browser tab."],
  "expected_outcome": "The browser tab is titled Exceptions, not Rules.",
  "variants": [],
  "support": { "explicit_steps": true, "explicit_expected": true, ... "grounding": 1.0, ... }
}
```

## 4. Generated test, with flagged parts

*Caption: New method in an existing class, gap flagged*

```diff
+++ b/tests/exceptions/test_exceptions_expiry.py
...
+   @pytest.mark.priority("p3")
+   @pytest.mark.suite("regression")
+   def test_exceptions_tab_title(self):
+      exceptions = self.go_to("exceptions.list")
+      self.check.assertEqual("Exceptions", exceptions.page_title)

Validation: ok after 0 repair round(s), 0 error(s), 0 warning(s)
  missing piece nav.exceptions.list.tab_title: close_match (close: ExceptionListPage.TITLE)
Review checklist (needs a real run):
  - Confirm ExceptionListPage.page_title reads the browser tab title (document title), not the on-page h1 heading.
  ...
```

**What the reviewer still needs to check:** the suite has no member for the browser tab title, so the test uses `page_title` instead. The reviewer has to confirm that it reads the tab title and not the h1 heading. Until a `tab_title` member exists, the test doesn't fully test the ticket.
