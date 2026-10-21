#!/usr/bin/env python3
"""In-container secondary guard + tool-call logger. The container mount is the real boundary.

pre : deny tool calls whose paths leave /work, and network/clone commands in Bash.
post: append {ts, tool, input digest} to /work/out/_log/tool_calls.jsonl (copied into provenance by the host).
"""
import datetime
import hashlib
import json
import os
import re
import sys

ROOT = "/work"
LOG = "/work/out/_log/tool_calls.jsonl"
NET = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|rsync|ftp|telnet|git\s+(clone|fetch|pull|remote)|pip\d*\s+install|npm\s+(i|install)|apt(-get)?\s+install)\b")


def paths(tool_input: dict):
    for k in ("file_path", "path", "notebook_path"):
        v = tool_input.get(k)
        if isinstance(v, str):
            yield v


def inside(p: str, cwd: str) -> bool:
    full = os.path.realpath(os.path.join(cwd, p))
    return full == ROOT or full.startswith(ROOT + "/")


def log(event: dict):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def main():
    phase = sys.argv[1]
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or ROOT
    if phase == "pre":
        reason = None
        for p in paths(ti):
            if not inside(p, cwd):
                reason = f"path outside /work: {p}"
        if tool == "Bash":
            cmd = ti.get("command", "")
            if NET.search(cmd):
                reason = "network or package commands are not allowed in the clean room"
            if re.search(r"(^|\s)(/(?!work\b)[A-Za-z]|\.\./)", cmd) and re.search(r"\b(cat|less|head|tail|cp|find|ls|grep|python3?)\b", cmd):
                reason = reason or "commands may only touch /work"
        if tool in ("WebFetch", "WebSearch") or tool.startswith("mcp__"):
            reason = f"{tool} is not allowed"
        log({"ts": datetime.datetime.utcnow().isoformat(), "phase": "pre", "tool": tool,
             "input_sha256": hashlib.sha256(json.dumps(ti, sort_keys=True).encode()).hexdigest(),
             "paths": list(paths(ti)), "command": ti.get("command"), "denied": reason})
        if reason:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                     "permissionDecision": "deny",
                                                     "permissionDecisionReason": reason}}))
        return 0
    log({"ts": datetime.datetime.utcnow().isoformat(), "phase": "post", "tool": tool, "paths": list(paths(ti))})
    return 0


if __name__ == "__main__":
    sys.exit(main())
