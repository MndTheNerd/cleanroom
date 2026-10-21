---
description: Have the analyzer write behavioral specs + interface contracts for tainted modules, filter them, and get the user's approval (mandatory human gate).
argument-hint: "[module]"
---

Modules to specify: `$ARGUMENTS`, or every `tainted` module in `.cleanroom/reports/partition.json`.

1. **Allowlist first** (once): delegate to the `cleanroom:analyzer` subagent to propose `.cleanroom/allowlist.json`: only names needed
   for compatibility (public API, wire protocols, file formats), each with a reason. Show it to the user. They must type exactly
   `approve allowlist`; record with `risk_gate.py approve-allowlist --typed "<their text>" --source chat --user-quote "<verbatim>"`.
2. For each module, delegate to `cleanroom:analyzer` with: the module name, its files and interface/dependents from partition.json,
   and the instruction to write `.cleanroom/specs/<module>.md` and `.cleanroom/contracts/<module>.md` per its rules.
   Give the analyzer ONLY this module's context. Never paste upstream code into the conversation yourself.
3. `python "${CLAUDE_PLUGIN_ROOT}/scripts/spec_filter.py" --harness <H> check --spec .cleanroom/specs/<module>.md --module <module>`.
   Also run it on the contract (without `--module`). If rejected, send the violation list (rule + line) back to the analyzer and repeat.
4. **Human gate.** Show the user the full spec and contract. Ask them to review. They must type exactly `approve spec`. Record:
   `risk_gate.py approve-spec --module <module> --typed "<their text>" --source chat --user-quote "<verbatim>"`.
   Any later edit to the spec or contract invalidates the approval (hash check).
5. `provenance_log.py commit --stage spec`.
