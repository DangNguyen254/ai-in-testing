<!-- Prompt: validator findings on a generated test -> corrected reply. Version: repair_v2. Sent as a follow-up turn in the generation conversation; the generation prompt's system text stays in force. v2: a round may be started by warnings alone (repair.warning_checks), e.g. an expected outcome no check covers. -->

# System

You fix a generated test so that it passes the suite's validators and checks what the draft expects. Keep everything that is correct; change only what the findings require.

# User

The validators found problems in the test you returned. Fix every error below, and every finding listed under "Findings to address". Reply with the complete corrected JSON object in the same schema as before (module_name, code, entries, review_checklist, notes).

Rules for the fix:
- Change only what the findings require. Keep the scaffold, markers, page-object usage, and entry plans that are not mentioned.
- Use only names that appear in the context you were given; an error about a missing member means that name does not exist, so use the existing member the context shows instead.
- An expected outcome that no check covers: add the check the suite uses for it, a helper or page-object member from the context (the template test and its class show which helpers check what). Data the new check reads goes into the entry; data no check reads comes out.
- If a finding can't be fixed with what exists, keep the closest valid code and explain it in notes and in review_checklist. Never add a check you can't ground in the context.

Validator errors:
{{errors}}

Findings to address (they started this round; fix them when the context shows how):
{{required}}

Other reviewer warnings (fix them only if the fix is clear from the context; they don't block):
{{warnings}}
