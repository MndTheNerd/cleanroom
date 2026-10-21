#!/usr/bin/env python3
"""Append-only, hash-chained provenance log (.cleanroom/provenance.jsonl).

Each entry records: timestamp, stage, agent, model, files read/written with SHA-256,
commands run, thresholds, gate decisions, prev_hash and entry_hash. Tampering with any
earlier line breaks the chain, which `verify` detects.

Usage:
  provenance_log.py append --stage scan --agent script --command "similarity_scan.py ..." \
      --read path --write path [--decision JSON] [--note TEXT]
  provenance_log.py verify
  provenance_log.py commit --stage scan       # git add + commit .cleanroom state in the harness
  provenance_log.py tail [-n 10]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_state_dir, now, run, sha256_file, sha256_text, load_config  # noqa: E402

GENESIS = "0" * 64
LOG_NAME = "provenance.jsonl"


def _canonical(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _last_hash(log: Path) -> str:
    if not log.exists() or log.stat().st_size == 0:
        return GENESIS
    with open(log, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        back = min(size, 1 << 20)
        f.seek(size - back)
        lines = f.read().splitlines()
    for raw in reversed(lines):
        if raw.strip():
            return json.loads(raw)["entry_hash"]
    return GENESIS


class _Lock:
    """Cross-platform exclusive lock using O_EXCL on a sidecar file."""

    def __init__(self, path: Path):
        self.path = Path(str(path) + ".lock")

    def __enter__(self):
        deadline = time.time() + 15
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    # stale lock: older than 60s
                    if time.time() - self.path.stat().st_mtime > 60:
                        os.unlink(self.path)
                        continue
                    raise TimeoutError(f"provenance lock busy: {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        os.close(self.fd)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def file_record(path: str | Path) -> dict:
    p = Path(path)
    if p.is_file():
        return {"path": str(p), "sha256": sha256_file(p)}
    return {"path": str(p), "sha256": None}


def append(state: Path, stage: str, agent: str, model: str | None = None, reads=(), writes=(),
           commands=(), thresholds=None, decision=None, note=None, extra=None) -> dict:
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    log = state / LOG_NAME
    if thresholds is None and (state / "config.json").exists():
        thresholds = load_config(state)["thresholds"]
    with _Lock(log):
        entry = {
            "ts": now(),
            "stage": stage,
            "agent": agent,
            "model": model,
            "reads": [file_record(r) if not isinstance(r, dict) else r for r in reads],
            "writes": [file_record(w) if not isinstance(w, dict) else w for w in writes],
            "commands": list(commands),
            "thresholds": thresholds,
            "decision": decision,
            "note": note,
            "prev_hash": _last_hash(log),
        }
        if extra:
            entry["extra"] = extra
        entry["entry_hash"] = sha256_text(_canonical(entry))
        with open(log, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def verify(state: Path) -> tuple[bool, list[str]]:
    log = Path(state) / LOG_NAME
    problems: list[str] = []
    if not log.exists():
        return True, []
    prev = GENESIS
    with open(log, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                problems.append(f"line {n}: not valid JSON")
                break
            if e.get("prev_hash") != prev:
                problems.append(f"line {n}: prev_hash does not match previous entry (chain broken)")
            if sha256_text(_canonical(e)) != e.get("entry_hash"):
                problems.append(f"line {n}: entry_hash mismatch (entry modified)")
            prev = e.get("entry_hash")
    return not problems, problems


def commit(state: Path, stage: str) -> str:
    """Commit .cleanroom state to git in the harness. Returns a short status string."""
    harness = Path(state).parent
    if run(["git", "rev-parse", "--is-inside-work-tree"], cwd=harness).returncode != 0:
        return "not a git repo: skipped commit"
    run(["git", "add", "-f", "--", ".cleanroom"], cwd=harness)
    # never commit sandboxes or builder secrets
    run(["git", "reset", "-q", "--", ".cleanroom/sandbox", ".cleanroom/backup"], cwd=harness)
    r = run(["git", "commit", "-q", "-m", f"cleanroom: {stage} provenance checkpoint", "--", ".cleanroom"], cwd=harness)
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        return f"commit failed: {r.stderr.strip() or r.stdout.strip()}"
    return "committed" if r.returncode == 0 else "nothing to commit"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness", help="harness repo (default: search upward from cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append", help="append an entry")
    a.add_argument("--stage", required=True)
    a.add_argument("--agent", default="script")
    a.add_argument("--model")
    a.add_argument("--read", action="append", default=[])
    a.add_argument("--write", action="append", default=[])
    a.add_argument("--command", action="append", default=[])
    a.add_argument("--decision", help="JSON value")
    a.add_argument("--note")
    sub.add_parser("verify", help="check the hash chain; exit 1 if broken")
    c = sub.add_parser("commit", help="git-commit .cleanroom state")
    c.add_argument("--stage", required=True)
    t = sub.add_parser("tail", help="print the last N entries")
    t.add_argument("-n", type=int, default=10)
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)

    if args.cmd == "append":
        e = append(state, args.stage, args.agent, args.model, args.read, args.write, args.command,
                   decision=json.loads(args.decision) if args.decision else None, note=args.note)
        print(e["entry_hash"])
    elif args.cmd == "verify":
        ok, problems = verify(state)
        print("provenance chain OK" if ok else "\n".join(problems))
        return 0 if ok else 1
    elif args.cmd == "commit":
        append(state, args.stage, "script", note="stage checkpoint commit")
        print(commit(state, args.stage))
    elif args.cmd == "tail":
        log = state / LOG_NAME
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        for l in lines[-args.n:]:
            e = json.loads(l)
            print(f"{e['ts']}  {e['stage']:<10} {e['agent']:<12} {e.get('note') or ''} {json.dumps(e.get('decision')) if e.get('decision') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
