---
description: Compare harness vs upstream (winnowing + identifiers, strings, comments, paths, metadata, README, headers, config keys), then partition modules into original / mixed / tainted.
argument-hint: "[--dry-run]"
---

1. If `$ARGUMENTS` contains `--dry-run`, add `--dry-run` to both commands below; nothing is written.
2. `python "${CLAUDE_PLUGIN_ROOT}/scripts/similarity_scan.py" --harness <harness> scan`
3. `python "${CLAUDE_PLUGIN_ROOT}/scripts/partition.py" --harness <harness>`
4. Show the user `.cleanroom/reports/scan_summary.md` and the partition table. Explain each label briefly and which thresholds were used
   (from `.cleanroom/config.json`). Point out mixed modules: they are not replaced unless the user sets `"replace_mixed": true`.
5. `python "${CLAUDE_PLUGIN_ROOT}/scripts/provenance_log.py" --harness <harness> commit --stage scan`
