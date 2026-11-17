# Prompt: the validators' tool gaps as invented examples, and the config fixes

Follows `docs/validator-audit-prompt.md`. Of 91 sampled rejections of the team's own tests, 35
were the tool not understanding a pattern the team uses, and 16 a setting in the private
config. The tool is built and tested on a synthetic stand-in with invented names, so each
pattern must come back as a small invented example the stand-in can reproduce. The settings
stay private: the session writes them as a proposed change for the human to apply.

For the same session that ran the audit (it has the samples in view), or a new one that reads
`t2t-private/output/validator-audit.md` first. Paste everything between the lines.

---

```text
Follow-up to the validator audit you wrote in t2t-private/output/validator-audit.md. Work
read-only, except for the two files named below. Don't run anything, don't call a model.

1. TOOL GAPS. Group the "tool gap" samples of every check into distinct patterns (one pattern
   = one way of writing code the tool doesn't follow). For each pattern:
   - which check rejects it, and how many of the audit's samples it covers;
   - how common it is in the suite: count files or tests that use it;
   - what the tool does wrong (read ai-prj/src/ticket2test/validate/ and index/ to say where,
     by function name);
   - a minimal example in Python that shows the pattern with INVENTED generic names only
     (pages like ItemsPage, helpers like open_items, values like "example"), 5 to 25 lines,
     written so it could be added to a synthetic test suite. Nothing from the real suite: no
     real names, strings, keys, paths, or structure that identifies it.
2. CONFIG. For every "config" sample, the setting in t2t-private/company.yaml that is wrong or
   missing and the value it should have, as a YAML snippet.

Write:
- t2t-private/output/tool-gaps.md: everything above, with the real examples you found next to
  each invented one, and the YAML snippets. Private.
- t2t-private/output/tool-gaps-public.md: ONLY the patterns, each with its check, its counts,
  where the tool fails (function names of ai-prj are fine) and its invented example. This file
  is pasted into the tool's public repository: before writing it, check it holds no name,
  string, key or path from the real suite.

Then reply in the chat with ONLY: the number of patterns per check, the count of config
settings to change, and "public file checked: yes/no".
```

---

## When the reply comes

The human reads `tool-gaps-public.md`, checks it has nothing of the real suite, and pastes it
here. Each pattern is added to `standin/`, its validator gap fixed with a test, one pattern at
a time; then `check-suite` on the real suite again, the share of clean files as the measure.
The YAML snippets go into the private config by the human.
