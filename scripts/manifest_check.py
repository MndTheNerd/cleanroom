#!/usr/bin/env python3
"""Verify a sandbox folder against its approved SHA-256 manifest. Abort on anything unexpected.

  manifest_check.py --sandbox DIR --approved FILE.json --phase pre    before the container starts
  manifest_check.py --sandbox DIR --approved FILE.json --phase post   after it exits

pre : the sandbox must contain exactly the approved files (same hashes), plus an empty out/.
post: approved inputs must be unchanged; new files may appear only under out/.
Both: symlinks, junctions, hard-linked files, device files or '..' paths fail the check.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import now, read_json, sha256_file, write_json  # noqa: E402

OUTPUT_DIR = "out"


def _is_link(p: Path) -> bool:
    return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))


def snapshot(sandbox: Path) -> tuple[dict, list[str]]:
    files, problems = {}, []
    sandbox = Path(sandbox)
    for dirpath, dirnames, filenames in os.walk(sandbox, followlinks=False):
        for d in list(dirnames):
            dp = Path(dirpath) / d
            if _is_link(dp):
                problems.append(f"link/junction directory: {dp.relative_to(sandbox).as_posix()}")
                dirnames.remove(d)
        for name in filenames:
            p = Path(dirpath) / name
            r = p.relative_to(sandbox).as_posix()
            if ".." in r.split("/"):
                problems.append(f"path traversal: {r}")
                continue
            if _is_link(p):
                problems.append(f"symlink: {r}")
                continue
            st = p.lstat()
            if not stat.S_ISREG(st.st_mode):
                problems.append(f"not a regular file: {r}")
                continue
            if st.st_nlink > 1:
                problems.append(f"hard-linked file (must be a copy): {r}")
            files[r] = sha256_file(p)
    return files, problems


def check(sandbox: Path, approved: dict, phase: str) -> dict:
    files, problems = snapshot(sandbox)
    want = approved["files"]
    for r, h in want.items():
        if r not in files:
            problems.append(f"missing approved file: {r}")
        elif files[r] != h:
            problems.append(f"approved file changed: {r}")
    for r in files:
        if r in want:
            continue
        if phase == "post" and r.split("/")[0] == OUTPUT_DIR:
            continue
        problems.append(f"file not on approved list: {r}")
    if phase == "pre" and not (Path(sandbox) / OUTPUT_DIR).is_dir():
        problems.append("out/ directory missing")
    return {"phase": phase, "ts": now(), "ok": not problems, "problems": problems, "manifest": files}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sandbox", required=True)
    ap.add_argument("--approved", required=True)
    ap.add_argument("--phase", choices=["pre", "post"], required=True)
    ap.add_argument("--write", help="write the computed manifest/result JSON here")
    args = ap.parse_args(argv)
    approved = read_json(Path(args.approved))
    if not approved:
        print("ERROR: approved manifest missing", file=sys.stderr)
        return 2
    res = check(Path(args.sandbox), approved, args.phase)
    if args.write:
        write_json(Path(args.write), res)
    if res["ok"]:
        print(f"manifest {args.phase}-check OK: {len(res['manifest'])} files")
        return 0
    print(f"manifest {args.phase}-check FAILED:")
    for p in res["problems"]:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
