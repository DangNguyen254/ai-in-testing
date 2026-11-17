# Prompt: audit the validators against the team's own tests

`check-suite` runs every validator over the real suite's own tests (2026-11-17): 60 of 171
files pass, 1,459 errors remain where the October calibration stopped. The repair loop makes
every generated test pass these checks, so a rule the team doesn't follow pushes generated
tests away from the team's way. This asks a session that reads the suite which rules are
wrong for this team and which errors are the suite's own inconsistency.

For a Claude Code session (Sonnet or Haiku) in the shared workspace. Paste everything between
the lines, unchanged.

---

```text
You are auditing a tool's validation rules against the test suite they are meant to fit.
Work read-only, except for the two report files named below. Don't run anything, don't call
a model, don't open the network.

The workspace: ai-prj (the tool), the real test suite (the folder t2t-private/company.yaml
names as the repo; called <repo> below), and t2t-private (the tool's private config and its
reports).

Inputs:
- t2t-private/output/check-suite/check-suite-20261117T085449.json: the tool's validators run
  over <repo>'s own tests. "by_check" lists, per check, the error count, the files, the
  common messages ("patterns") and real examples ("pattern_examples"). "deviations" lists
  style and data-file differences by area. "warnings_by_check" counts warnings.
- ai-prj/src/ticket2test/validate/validator.py: each check is a function named check_<name>;
  read what it enforces. ai-prj/CLAUDE.md, "Target test-suite patterns" and the guardrails,
  says why each rule exists. t2t-private/company.yaml holds the tool's settings for <repo>.

For each check with errors (assertions, data_keys, ids, names, data_shape, page_objects,
base_class), and for the style deviations:
1. Read what the check enforces.
2. Sample 10 errors from at least 4 different files (fewer if the check has fewer), open
   each in <repo>, and classify it:
   - rule wrong: the team does this on purpose, widely; the rule should change.
   - config: the rule is right, a setting in company.yaml is wrong or missing.
   - tool gap: the code is fine, the tool can't follow it (a pattern it doesn't understand).
   - team inconsistent: most of the suite follows the rule, these files don't.
   - real defect: the test is actually broken or dead (unread data, a wrong id).
3. Say which change you would make, if any (a rule, a setting, nothing), in general words.

Then, overall: which checks, if they stayed as they are, would make a generated test look
LESS like the team's tests? Rank them.

Write:
1. t2t-private/output/validator-audit.json, exactly this shape:
   {"checks": [{"check": "<name>", "sampled": N, "rule_wrong": N, "config": N,
     "tool_gap": N, "team_inconsistent": N, "real_defect": N,
     "change": "rule" | "setting" | "nothing" | "split"}],
    "harms_style": ["<check names, most harmful first>"]}
2. t2t-private/output/validator-audit.md: the same with examples, files and reasons.

Then reply in the chat with ONLY: one line per check with its counts and the change, and the
ranked list of checks that harm style. No names of classes, helpers, files, keys, values,
tickets or features, and no quotes from the code (check names and config key names of the
tool are fine).
```

---

## When the reply comes

Each "rule wrong" or "config" becomes one change, made on the stand-in first, then
`check-suite` again; the share of clean files is the measure. Rules are not loosened for
"team inconsistent" or "real defect".
