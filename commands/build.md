---
description: Run the test-writer and builder inside the isolated Docker container (sandbox only, egress only to the model API), with SHA-256 manifest checks before and after.
argument-hint: "<module> [attempt]"
---

Preconditions (the scripts enforce them; you must not work around them):
- license and all six risk gates open (`risk_gate.py status` exits 0), allowlist approved, spec + contract approved.
- Docker with compose v2 running.
- A builder credential the user set in the environment **before starting Claude Code** (never ask them to paste it into chat):
  - subscription (default): `CLEANROOM_BUILDER_OAUTH_TOKEN`, printed by running `claude setup-token` in their own terminal.
    It is a separate token from their normal login. Usage counts against their plan's limits.
  - API key: `CLEANROOM_BUILDER_API_KEY`, different from the host's `ANTHROPIC_API_KEY`.

**You (this host session) must never write the module yourself, never read the builder's sandbox inputs into this
conversation to "help", and never pass upstream code, matching lines or diffs to the builder.**

Steps:
1. Once per machine/session: `python "${CLAUDE_PLUGIN_ROOT}/scripts/sandbox_run.py" --harness <H> probe`. All checks must PASS
   (only /work mounted, upstream canaries absent, GitHub unreachable directly and via proxy, external DNS blocked, model API reachable).
2. Tests (if `.cleanroom/tests/<module>/` is missing):
   `sandbox_run.py --harness <H> run --module <module> --role test-writer`, then
   `equivalence_run.py --harness <H> capture --module <module>` (fixtures from the OLD module, stored as data).
3. Build: `sandbox_run.py --harness <H> run --module <module> --role builder --attempt <N>` (N from `$ARGUMENTS`, default 1).
4. Report the manifest results and exit status. If anything was REFUSED, show the reason and stop.
5. `provenance_log.py commit --stage build`.
