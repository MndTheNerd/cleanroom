#!/usr/bin/env python3
"""PostToolUse logger: every tool call in a cleanroom project becomes a hash-chained provenance entry
(stage, agent, model, files read/written with SHA-256, commands). Active only where .cleanroom/config.json exists."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    from _common import find_state_dir, load_config
    import provenance_log
    cwd = data.get("cwd") or os.getcwd()
    state = find_state_dir(Path(cwd))
    if not (state / "config.json").exists():
        return 0
    cfg = load_config(state)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    agent = data.get("agent_type") or "main"
    model = cfg.get("analyzer_model") if agent.lower().endswith("analyzer") else None
    paths = [os.path.abspath(os.path.join(cwd, ti[k])) for k in ("file_path", "path", "notebook_path") if isinstance(ti.get(k), str)]
    reads, writes, cmds = [], [], []
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        writes = paths
    elif tool in ("Read", "Grep", "Glob"):
        reads = [p for p in paths if Path(p).is_file()] or [{"path": p, "sha256": None} for p in paths]
        if tool != "Read":
            cmds = [f"{tool} {ti.get('pattern', '')}"]
    elif tool in ("Bash", "PowerShell"):
        cmds = [ti.get("command", "")]
    else:
        cmds = [f"{tool} {json.dumps(ti)[:300]}"]
    stage = (state / "current_stage").read_text(encoding="utf-8").strip() if (state / "current_stage").exists() else "interactive"
    provenance_log.append(state, stage, agent, model, reads=reads, writes=writes, commands=cmds,
                          extra={"tool": tool, "session_id": data.get("session_id"), "tool_use_id": data.get("tool_use_id")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
