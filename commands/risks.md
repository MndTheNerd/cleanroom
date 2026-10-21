---
description: Ask (or re-ask) the six human risk-gate questions one at a time and record the answers in risk_decisions.json.
argument-hint: "[gate-id to re-ask, e.g. use]"
---

Gate store: `.cleanroom/risk_decisions.json`, written ONLY by `python "${CLAUDE_PLUGIN_ROOT}/scripts/risk_gate.py"`.

Rules:
- One question per message. Plain language, plus the "why it matters" text from `risk_gate.py questions`. Then stop and wait.
- **Never answer for the user. No defaults.** A skipped question leaves the gate closed. Say so.
- Record with `risk_gate.py record --gate <id> --answer "<answer>" [--override "I accept this risk"] --source chat --user-quote "<verbatim reply>"`.
- If `$ARGUMENTS` names a gate, ask only that one (an answer change re-opens related gates automatically; tell the user which).

Order and handling:
1. **access**: "Did you get the upstream source legitimately (public repo or licensed to you)?" If no or unsure: the script records a HARD STOP. Tell the user the process cannot continue. Stop.
2. **agreements**: "Did you agree to any terms beyond the open-source license (EULA, terms of service, NDA, employment or client contract) that cover this code?" If yes or unsure: explain the risk, and continue only if the user types exactly `I accept this risk` (pass it as `--override`).
3. **patents**: first run `risk_gate.py scan-patents` and show every finding. Then ask: "Do you know of any patents on the upstream project or the techniques it uses?" If they say yes or unsure, OR the scan found anything: require the typed override.
4. **use**: "Will this be sold, distributed, or offered as a service to others?" If yes: show the recommendation list the script prints (license + patent check, trademark search, contract review). It does not block. Record their choice.
5. **name**: "What is the new project name?" The script refuses names that match or closely resemble the upstream name. If refused, explain and ask again.
6. **contamination**: explain that the model may have seen upstream during training, that AI-run clean rooms have not been tested in court, and that the two similarity scans are the mitigation, not a guarantee. Ask them to type exactly `I understand`.

End with `risk_gate.py status`.
