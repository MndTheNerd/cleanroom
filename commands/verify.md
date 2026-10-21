---
description: Verify a build. Tests, behavioral equivalence, built-in winnowing and JPlag must all pass. On failure, revise the spec (never hand the builder a diff) and rebuild, max 3 attempts.
argument-hint: "<module> <attempt>"
---

1. `python "${CLAUDE_PLUGIN_ROOT}/scripts/verify_build.py" --harness <H> --module <module> --attempt <N>`
   (tests run inside the container; only add `--host-tests` if the user explicitly agrees to run builder code on this machine).
2. Show the four results. PASS requires all four.
3. On FAIL:
   - The script wrote `.cleanroom/builds/<module>/feedback_attempt<N+1>.md`. It contains file-level scores only. Never add lines, code or upstream text to it.
   - Delegate to `cleanroom:analyzer` to revise the spec using the verify report.
   - Re-run spec_filter, then the human must re-approve the spec (`approve spec`). The approval records it is for attempt N+1.
   - Then `/cleanroom:build <module> <N+1>`.
   - After attempt 3 (config `max_build_attempts`) fails: STOP and report. Do not keep trying.
4. `provenance_log.py commit --stage verify`.
