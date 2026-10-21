---
description: Run the whole clean-room pipeline, stopping at every unanswered human gate, every agent step that needs dispatching, and every failure.
---

Loop:

1. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/run_all.py" --harness <H> next --run`. It executes every deterministic stage it can
   (scan, partition, spec filter, sandboxed test-writer/builder, fixtures, verify, summary, swap, cleanup, ScanCode, report),
   commits the provenance log after each, and stops with one of:
   - `NEEDS YOUR ANSWER` (exit 20): a human gate. Ask the user that ONE question exactly as `/cleanroom:risks`, `/cleanroom:spec`
     or `/cleanroom:swap` describe, then **end your turn and wait**. Record only what they actually typed. Never answer for them.
   - `NEEDS AGENT` (exit 10): delegate to `cleanroom:analyzer` with the detail shown (spec, contract, allowlist, or spec revision). Then loop.
   - `STOPPED` (exit 30): a failed or refused stage (HARD STOP, verify failed 3 times, leftovers, ScanCode, provenance tampering,
     Docker missing, etc.). Report it plainly and stop. Do not work around it.
   - `DONE` (exit 0): show the report summary.
2. The build stage cannot start until the license gate and all six risk gates are open. Swap and report cannot run until
   the user has typed `approve swap` on the current summary. The scripts enforce both; do not try to bypass them.
3. Never write module code yourself in this session, and never pass upstream code or matching lines to the builder.
