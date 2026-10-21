#!/usr/bin/env python3
"""PreToolUse guard for host sessions (SECONDARY control; the container is the primary one).

Active only inside a project that has .cleanroom/config.json. Denies:
  - any write into the upstream repo (never modify upstream)
  - Write/Edit/shell edits of gate and evidence files (risk_decisions.json, provenance.jsonl,
    reports/, manifests/, accepted builds): only the plugin's scripts may write those
  - any tool call by the test-writer or builder agents on the host (they run only in the container)
  - analyzer writes outside specs/, contracts/, allowlist.json, style.md; analyzer web access
Every denial is appended to the provenance log.

Self-test:  python path_guard.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

PROTECTED = re.compile(r"(^|[\\/\s\"'=>])\.cleanroom[\\/](risk_decisions\.json|provenance\.jsonl|reports[\\/]|manifests[\\/]|builds[\\/][^\\/]+[\\/]accepted\.json|fixtures[\\/][^\\/]+(?<!\.inputs)\.json)", re.I)
ANALYZER_WRITABLE = re.compile(r"(^|[\\/])\.cleanroom[\\/](specs[\\/][^\\/]+\.md|contracts[\\/][^\\/]+\.md|allowlist\.json|style\.md)$", re.I)
SHELL_WRITE = re.compile(r"(>|>>|\btee\b|\bsed\s+-i|\brm\b|\bdel\b|\bmv\b|\bcp\b|Remove-Item|Set-Content|Add-Content|Out-File|Move-Item|Copy-Item|\bgit\s+(checkout|restore|reset)\b|truncate|python\S*\s+-c)", re.I)
OUR_SCRIPT = re.compile(r"cleanroom[\\/]+scripts[\\/]+\w+\.py|CLAUDE_PLUGIN_ROOT", re.I)


def tool_paths(tool_input: dict) -> list[str]:
    return [v for k in ("file_path", "path", "notebook_path") if isinstance(v := tool_input.get(k), str)]


def norm(p: str, cwd: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.join(cwd, p)))


def under(p: str, root: str | None) -> bool:
    if not root:
        return False
    root = os.path.normcase(os.path.abspath(root))
    return p == root or p.startswith(root.rstrip("\\/") + os.sep)


def decide(data: dict, cfg: dict) -> str | None:
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    agent = (data.get("agent_type") or "").lower()
    writes = tool in ("Write", "Edit", "MultiEdit", "NotebookEdit")
    paths = [norm(p, cwd) for p in tool_paths(ti)]
    upstream = cfg.get("upstream")

    if agent.endswith(("test-writer", "builder")):
        return f"the {agent} agent runs only inside the isolated container (sandbox_run.py), never on the host"
    if writes and any(under(p, upstream) for p in paths):
        return "the upstream repo is read-only for the clean room"
    if writes and any(PROTECTED.search(p) for p in paths):
        return "gate/evidence files are written only by the cleanroom scripts"
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command", "")
        if upstream and SHELL_WRITE.search(cmd) and os.path.normcase(upstream) in os.path.normcase(cmd).replace("/", os.sep) and not OUR_SCRIPT.search(cmd):
            return "shell command appears to modify the upstream repo"
        if PROTECTED.search(cmd) and SHELL_WRITE.search(cmd) and not OUR_SCRIPT.search(cmd):
            return "shell command appears to modify gate/evidence files; use the cleanroom scripts"
    if agent.endswith("analyzer"):
        if tool in ("WebFetch", "WebSearch") or tool.startswith("mcp__"):
            return "the analyzer works only from local files"
        if writes and not all(ANALYZER_WRITABLE.search(p) for p in paths):
            return "the analyzer may write only .cleanroom/specs/*.md, contracts/*.md, allowlist.json and style.md"
    return None


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        cfg = {"upstream": os.path.abspath("up")}
        assert decide({"tool_name": "Write", "tool_input": {"file_path": "up/x.py"}, "cwd": "."}, cfg)
        assert decide({"tool_name": "Edit", "tool_input": {"file_path": ".cleanroom/risk_decisions.json"}, "cwd": "."}, cfg)
        assert decide({"tool_name": "Read", "tool_input": {"file_path": "a.py"}, "agent_type": "cleanroom:builder", "cwd": "."}, cfg)
        assert decide({"tool_name": "Write", "tool_input": {"file_path": "src/a.py"}, "agent_type": "cleanroom:analyzer", "cwd": "."}, cfg)
        assert not decide({"tool_name": "Write", "tool_input": {"file_path": ".cleanroom/specs/m.md"}, "agent_type": "cleanroom:analyzer", "cwd": "."}, cfg)
        assert not decide({"tool_name": "Read", "tool_input": {"file_path": "up/x.py"}, "agent_type": "cleanroom:analyzer", "cwd": "."}, cfg)
        print("path_guard self-test OK")
        return 0
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    from _common import find_state_dir, load_config
    state = find_state_dir(Path(data.get("cwd") or os.getcwd()))
    if not (state / "config.json").exists():
        return 0
    reason = decide(data, load_config(state))
    if reason:
        import provenance_log
        provenance_log.append(state, "guard", data.get("agent_type") or "main",
                              decision={"denied": data.get("tool_name"), "reason": reason, "paths": tool_paths(data.get("tool_input") or {})})
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": f"cleanroom: {reason}"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
