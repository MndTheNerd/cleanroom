---
description: Start a clean-room rewrite. Collects inputs, runs the license gate and the six human risk gates, one question at a time.
argument-hint: "[harness-path] [upstream-path]"
---

You are starting the **cleanroom** process. Scripts live in `${CLAUDE_PLUGIN_ROOT}/scripts/`; run them with `python`.

## Absolute rules for this command
- Ask **one question per message**, in plain language, with one or two sentences on why it matters. Then stop and wait.
- **Never answer a gate for the user and never assume a default.** If the user doesn't answer, the gate stays closed.
- Record every answer with `--source chat --user-quote "<the user's reply, verbatim>"`. Never paraphrase in `--user-quote`.
- Typed confirmations must match exactly ("I accept this risk", "I understand"). Do not accept near-misses; ask again.
- Never claim this process gives legal immunity.
- Tell the user they can instead answer the risk questions in their own terminal: `python "${CLAUDE_PLUGIN_ROOT}/scripts/risk_gate.py" --harness <harness> ask` (strongest evidence: source=tty).

## Steps
1. Inputs: ask, one at a time, for whatever is missing from `$ARGUMENTS`: harness path, upstream path, languages, how to run tests.
2. `python "${CLAUDE_PLUGIN_ROOT}/scripts/run_all.py" --harness <H> init --upstream <U> --languages <L> --test-command "<T>" --analyzer-model "${user_config.analyzer_model}" --builder-model "${user_config.builder_model}" --builder-auth "${user_config.builder_auth}" --tools-dir "${CLAUDE_PLUGIN_DATA}/tools"`.
   This creates `.cleanroom/`, works on a `cleanroom/<date>` branch, and detects the upstream name. Confirm the detected upstream name with the user.
   The models come from the plugin options the user chose when enabling the plugin; init refuses if they are the same.
3. Self-test the guard hook: `python "${CLAUDE_PLUGIN_ROOT}/hooks/path_guard.py" --self-test`.
   Check add-ons: `python "${CLAUDE_PLUGIN_ROOT}/scripts/install_tools.py" --dest "${CLAUDE_PLUGIN_DATA}/tools" --status`.
   Tell the user which are missing and what each is needed for (see `/cleanroom:addons`). Missing Docker means the build stage will refuse to run.
4. **License gate**: `python "${CLAUDE_PLUGIN_ROOT}/scripts/license_gate.py" --harness <H> detect`. Show the result and explanation. Ask the user to confirm the license.
   - MIT/Apache/BSD/ISC (permissive): say attribution may be enough, and ask whether to continue anyway.
   - GPL/AGPL/unknown/none: explain, then continue once confirmed.
   Record: `license_gate.py record --license <SPDX> --confirmed yes|no --decision continue|stop --source chat --user-quote "..."`.
5. **Risk gates**: run `/cleanroom:risks` (same rules; one question at a time, in order: access, agreements, patents, use, name, contamination).
6. Finish with `python "${CLAUDE_PLUGIN_ROOT}/scripts/risk_gate.py" --harness <H> status` and say what is still closed.
