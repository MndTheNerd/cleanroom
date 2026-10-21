---
description: Final sign-off ("approve swap"), then replace verified modules, delete tainted files, remove upstream remotes/vendored copies/headers/name, grep for leftovers and run ScanCode.
argument-hint: "[--dry-run]"
---

1. `python "${CLAUDE_PLUGIN_ROOT}/scripts/run_all.py" --harness <H> summary` and show `.cleanroom/reports/signoff_summary.md` to the user in full.
2. **Human gate:** the user must type exactly `approve swap`. Record with
   `risk_gate.py signoff --typed "<their text>" --source chat --user-quote "<verbatim>"`. Never type it for them.
3. Dry run first and show the actions: `swap_and_clean.py swap --module <m> --dry-run` for each module, then `swap_and_clean.py clean --dry-run`.
   If `$ARGUMENTS` has `--dry-run`, stop here.
4. Apply: `swap_and_clean.py swap --module <m>` for each verified module, then `swap_and_clean.py clean`.
5. `swap_and_clean.py leftovers` must print NO UPSTREAM LEFTOVERS FOUND.
6. `final_license_scan.py` must PASS (ScanCode Toolkit). If ScanCode isn't installed it FAILS; offer `/cleanroom:addons install scancode`.
7. Warn the user: **git history still contains upstream code.** Offer the fresh-history option as a separate step. It needs its own typed
   confirmation `rewrite history` (`risk_gate.py approve-fresh-history ...`), then `swap_and_clean.py fresh-history --mode orphan|new-repo`.
   Never run it without that confirmation.
8. `provenance_log.py commit --stage swap`.
