---
description: Generate CLEANROOM_REPORT.md with license decision, before/after overlap (both tools), replacements, tests, ScanCode, full human decisions and linked residual risks.
---

1. `python "${CLAUDE_PLUGIN_ROOT}/scripts/provenance_log.py" --harness <H> verify` must print `provenance chain OK`. If not, stop and tell the user the log was altered.
2. `python "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" --harness <H>`
3. Summarize the report for the user: modules replaced, before/after scores, anything that failed or was not run, and the residual risks.
   Do not describe the result as legally safe or immune. It is evidence of process.
4. `provenance_log.py commit --stage report`.
