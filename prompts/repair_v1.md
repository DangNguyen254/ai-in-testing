<!-- Prompt: validator errors on a generated test -> corrected reply. Version: repair_v1. Sent as a follow-up turn in the generation conversation; the generation prompt's system text stays in force. -->

# System

You fix a generated test so that it passes the suite's validators. Keep everything that is correct; change only what the errors require.

# User

The test you returned fails the suite's validators. Fix every error below and reply with the complete corrected JSON object in the same schema as before (module_name, code, entries, review_checklist, notes).

Rules for the fix:
- Change only what the errors require. Keep the scaffold, markers, page-object usage, and entry plans that are not mentioned.
- Use only names that appear in the context you were given; an error about a missing member means that name does not exist, so use the existing member the context shows instead.
- If an error can't be fixed with what exists, keep the closest valid code and explain it in notes.

Validator errors:
{{errors}}

Reviewer warnings (fix them only if the fix is clear from the context; they don't block):
{{warnings}}
