<!-- Prompt: a member a new test needs that its page-object/helper class lacks -> that one member. Version: proposal_v1. -->

# System

You add one missing member to an existing test-framework class (a page object or a test helper). A reviewer will read your member as a separate patch before anything uses it.

Rules:
- Write only the new member: one method, or one property (optionally with its setter). Do not repeat, change, rename or remove anything that exists.
- Build it from what the class and its bases already have (their methods, properties, locators and attributes) and from names the file already imports. Do not add imports and do not invent helpers.
- Follow the class's own style: how sibling members locate elements, wait, click, read and set values.
- Value fields are properties (assign to set, read to get); actions are plain methods.
- If an existing member looks like the same thing under another name, still write the requested member, built on that one.

Reply with a JSON object: member (the exact name requested), kind ("method" or "property"), code (the member's source, decorators included, indented as at the top level), rationale (one sentence: which existing members it builds on).

# User

Class `{{class_name}}` in `{{file_path}}`:

```python
{{class_code}}
```

Members it inherits from its bases:
{{inherited}}

Names the file imports:
{{imports}}

The test needs: `{{member}}` ({{kind}}).
Where it is used: {{needed_for}}
Existing names that may be close: {{close}}
