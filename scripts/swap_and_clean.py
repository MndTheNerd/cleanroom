#!/usr/bin/env python3
"""Swap verified modules into the harness and remove upstream leftovers.

  swap_and_clean.py swap  --module M [--dry-run]   back up, replace module files with the accepted build
  swap_and_clean.py clean [--dry-run]              remove upstream remotes, vendored copies, upstream
                                                   license headers, and rename the upstream project name
  swap_and_clean.py leftovers                      grep the repo for upstream identifiers/strings/name (exit 1 if any)
  swap_and_clean.py fresh-history --mode orphan|new-repo [--dry-run]
                                                   optional: start history without upstream commits
                                                   (needs the 'rewrite history' gate; never deletes old history)

swap and clean refuse unless the final sign-off ("approve swap") is recorded and current.
--dry-run prints every action and changes nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (CODE_EXTS, TEXT_EXTS, find_state_dir, iter_files, load_config, now, read_json, run,  # noqa: E402
                     sha256_file, write_json)
from _similarity import GENERIC, code_shaped, facts, name_variants, word_shingles  # noqa: E402
import _gates  # noqa: E402
import provenance_log  # noqa: E402
import similarity_scan  # noqa: E402
import spec_filter  # noqa: E402
import sandbox_prepare  # noqa: E402

PROTECTED_BRANCHES = {"main", "master", "trunk", "develop"}


class Refused(Exception):
    pass


def require_signoff(state: Path):
    d = _gates.load(state)
    s = d.get("signoff") or {}
    if s.get("status") != "open":
        raise Refused("final sign-off not recorded: run /cleanroom:report summary, then type 'approve swap'")
    summ = state / "reports" / "signoff_summary.md"
    if not summ.exists() or sha256_file(summ) != s.get("summary_sha256"):
        raise Refused("results changed after sign-off: regenerate the summary and sign off again")


def require_branch(harness: Path):
    r = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=harness)
    if r.returncode != 0:
        return "not a git repo"
    b = r.stdout.strip()
    if b in PROTECTED_BRANCHES:
        raise Refused(f"on protected branch '{b}': work on a cleanroom/* branch (init creates one)")
    return b


def case_map(old: str, new: str) -> list[tuple[str, str]]:
    """Map each spelling variant of the old name to the same variant of the new name."""
    def variants(n):
        parts = [p for p in re.split(r"[\s_\-.]+|(?<=[a-z])(?=[A-Z])", n) if p]
        low = [p.lower() for p in parts]
        return {"kebab": "-".join(low), "snake": "_".join(low), "flat": "".join(low), "space": " ".join(low),
                "pascal": "".join(p.capitalize() for p in low), "upper": "_".join(low).upper(), "title": " ".join(p.capitalize() for p in low)}
    o, n = variants(old), variants(new)
    pairs = {(o[k], n[k]) for k in o if len(o[k]) >= 3}
    return sorted(pairs, key=lambda p: -len(p[0]))


def do_swap(state: Path, module: str, dry: bool) -> list[str]:
    cfg = load_config(state)
    harness = Path(cfg.get("harness") or state.parent)
    require_signoff(state)
    acc = read_json(state / "builds" / module / "accepted.json")
    if not acc:
        raise Refused(f"module '{module}' has no accepted (verified) build")
    branch = require_branch(harness)
    build = state / "builds" / module / f"attempt-{acc['attempt']}"
    for rel_path, h in acc["hashes"].items():
        if sha256_file(build / rel_path) != h:
            raise Refused(f"accepted build changed after verify: {rel_path}")
    targets = sandbox_prepare.module_targets(state, cfg, module)
    part = read_json(state / "reports" / "partition.json", {})
    old_files = list(part["modules"][module]["files"]) if module in part.get("modules", {}) else targets
    new_files = [p.relative_to(build).as_posix() for p in build.rglob("*")
                 if p.is_file() and p.relative_to(build).parts[0] not in ("tests", "_log")
                 and not set(p.relative_to(build).parts) & set(cfg["exclude"])
                 and p.name not in ("BUILD_NOTES.md", "QUESTIONS.md")]
    actions = []
    stamp = now().replace(":", "").replace("-", "")
    backup = state / "backup" / f"{stamp}-{module}"
    for f in sorted(set(old_files) | set(new_files)):
        if (harness / f).exists():
            actions.append(f"backup {f} -> {backup.relative_to(harness).as_posix()}/{f}")
            if not dry:
                (backup / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(harness / f, backup / f)
    for f in new_files:
        actions.append(f"write {f} (from accepted build attempt {acc['attempt']})")
        if not dry:
            (harness / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(build / f, harness / f)
    for f in old_files:
        if f not in new_files and (harness / f).exists():
            actions.append(f"delete tainted file {f}")
            if not dry:
                (harness / f).unlink()
    if not dry:
        provenance_log.append(state, "swap", "script", reads=[build / f for f in new_files], writes=[harness / f for f in new_files],
                              commands=[f"swap_and_clean.py swap --module {module}"],
                              decision={"module": module, "branch": branch, "backup": str(backup), "deleted": [f for f in old_files if f not in new_files]})
    return actions


def upstream_file_hashes(upstream: Path, exclude) -> dict:
    return {sha256_file(p): p.relative_to(upstream).as_posix() for p in iter_files(upstream, exclude, None)}


def do_clean(state: Path, dry: bool) -> list[str]:
    cfg = load_config(state)
    harness = Path(cfg.get("harness") or state.parent)
    upstream = Path(cfg["upstream"])
    require_signoff(state)
    require_branch(harness)
    actions = []
    # 1. upstream git remotes
    r = run(["git", "remote", "-v"], cwd=harness)
    up_name = (cfg.get("upstream_name") or "").lower()
    up_remote_urls = set()
    ur = run(["git", "remote", "-v"], cwd=upstream)
    if ur.returncode == 0:
        up_remote_urls = {l.split()[1] for l in ur.stdout.splitlines() if len(l.split()) >= 2}
    removed = set()
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        parts = line.split()
        if len(parts) < 2 or parts[0] in removed:
            continue
        name, url = parts[0], parts[1]
        is_local = not url.startswith(("http", "git@", "ssh", "git:"))
        points_at_upstream = (url in up_remote_urls
                              or (is_local and Path(url).resolve() == upstream.resolve())
                              or bool(up_name and up_name in url.lower())
                              or name == "upstream")
        if points_at_upstream:
            actions.append(f"git remote remove {name}  ({url})")
            removed.add(name)
            if not dry:
                run(["git", "remote", "remove", name], cwd=harness)
    # 2. vendored copies: any harness file byte-identical to an upstream file
    up_hashes = upstream_file_hashes(upstream, cfg["exclude"])
    for p in iter_files(harness, cfg["exclude"], None):
        h = sha256_file(p)
        if h in up_hashes and p.stat().st_size > 0:
            actions.append(f"delete vendored copy {p.relative_to(harness).as_posix()} (identical to upstream {up_hashes[h]})")
            if not dry:
                p.unlink()
                parent = p.parent
                while parent != harness and not any(parent.iterdir()):
                    actions.append(f"remove empty folder {parent.relative_to(harness).as_posix()}")
                    parent.rmdir()
                    parent = parent.parent
    # 3. license headers naming upstream holders / the upstream project
    scan = read_json(state / "reports" / "scan.json", {}) or {}
    holders = [h for h in scan.get("upstream_copyright_holders", []) if len(h) >= 3]
    name_res = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", re.I) for v in name_variants(cfg.get("upstream_name") or "") if len(v) >= 3]
    hdr = re.compile(r"copyright|spdx-license-identifier|licensed under|all rights reserved|permission is hereby granted", re.I)
    for p in iter_files(harness, cfg["exclude"], TEXT_EXTS):
        if dry is False and not p.exists():
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        keep, dropped = [], 0
        for i, l in enumerate(lines):
            if i < 40 and hdr.search(l) and (any(h.lower() in l.lower() for h in holders) or any(rx.search(l) for rx in name_res)):
                dropped += 1
                continue
            keep.append(l)
        if dropped:
            actions.append(f"remove {dropped} upstream license/copyright header line(s) from {p.relative_to(harness).as_posix()}")
            if not dry:
                p.write_text("".join(keep), encoding="utf-8")
    # 4. rename upstream project name -> new project name in code, docs and metadata
    new = cfg.get("project_name")
    if cfg.get("upstream_name") and new:
        pairs = case_map(cfg["upstream_name"], new)
        for p in iter_files(harness, cfg["exclude"], TEXT_EXTS):
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            out, n = text, 0
            for o, nn in pairs:
                out, k = re.subn(r"(?<![A-Za-z0-9])" + re.escape(o) + r"(?![A-Za-z0-9])", nn, out)
                n += k
            if n:
                actions.append(f"rename upstream name ({n}x) in {p.relative_to(harness).as_posix()}")
                if not dry:
                    p.write_text(out, encoding="utf-8")
        for p in sorted(harness.rglob("*"), key=lambda x: -len(x.parts)):
            if any(part in cfg["exclude"] for part in p.relative_to(harness).parts):
                continue
            for o, nn in pairs:
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(o) + r"(?![A-Za-z0-9])", p.name):
                    target = p.with_name(re.sub(re.escape(o), nn, p.name))
                    actions.append(f"rename path {p.relative_to(harness).as_posix()} -> {target.name}")
                    if not dry:
                        p.rename(target)
                    break
    elif not new:
        actions.append("WARNING: no project_name recorded (name gate); upstream name not replaced")
    if not dry:
        provenance_log.append(state, "swap", "script", commands=["swap_and_clean.py clean"], decision={"actions": len(actions)}, note="; ".join(actions)[:4000])
    return actions


def leftovers(state: Path) -> dict:
    cfg = load_config(state)
    harness = Path(cfg.get("harness") or state.parent)
    upstream = Path(cfg["upstream"])
    allow = spec_filter.approved_allowlist(state)
    up_idents, up_strings = set(), set()
    for p in iter_files(upstream, cfg["exclude"], CODE_EXTS):
        f = facts(p, upstream)
        up_idents |= {i for i in f.identifiers if code_shaped(i) and len(i) >= 4}
        up_strings |= {s for s, _ in f.strings if len(s) >= cfg["thresholds"]["nontrivial_string_len"] and re.search(r"[A-Za-z]{3}", s)}
    up_idents -= allow
    res = {"identifiers": [], "strings": [], "name": []}
    name_res = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", re.I) for v in name_variants(cfg.get("upstream_name") or "") if len(v) >= 3]
    for p in iter_files(harness, cfg["exclude"], TEXT_EXTS):
        r = p.relative_to(harness).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        if p.suffix.lower() in CODE_EXTS:
            f = facts(p, harness)
            for i in sorted(f.identifiers & up_idents):
                res["identifiers"].append({"file": r, "identifier": i})
            for s, line in f.strings:
                if s in up_strings:
                    res["strings"].append({"file": r, "line": line, "length": len(s)})
        for n, l in enumerate(text.splitlines(), 1):
            if any(rx.search(l) for rx in name_res):
                res["name"].append({"file": r, "line": n})
        if any(rx.search(r) for rx in name_res):
            res["name"].append({"file": r, "line": 0})
    # Copied prose, package metadata and config keys: renaming the project does not make them clean.
    text_exts = {".md", ".rst", ".txt"}
    up_text = [p for p in iter_files(upstream, cfg["exclude"], TEXT_EXTS) if p.suffix.lower() in text_exts or p.name.upper().startswith("README")]
    up_sh = set().union(*[word_shingles(p.read_text(encoding="utf-8", errors="replace"), 8) for p in up_text]) if up_text else set()
    up_sh_noname = {_strip_names(s, cfg) for s in up_sh}
    res["docs"] = []
    for p in iter_files(harness, cfg["exclude"], TEXT_EXTS):
        if p.suffix.lower() in text_exts or p.name.upper().startswith("README"):
            shared = {s for s in word_shingles(p.read_text(encoding="utf-8", errors="replace"), 8) if _strip_names(s, cfg) in up_sh_noname}
            if shared:
                res["docs"].append({"file": p.relative_to(harness).as_posix(), "shared_8word_runs": len(shared)})
    res["metadata"] = []
    for name in ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml"):
        hp, upp = harness / name, upstream / name
        if hp.exists() and upp.exists():
            hv, uv = similarity_scan._meta_fields(hp), similarity_scan._meta_fields(upp)
            for k in sorted(set(hv) & set(uv) - {"name"}):
                if hv[k] == uv[k] or word_shingles(hv[k], 5) & word_shingles(uv[k], 5):
                    res["metadata"].append({"file": name, "field": k})
    h_text = list(iter_files(harness, cfg["exclude"], TEXT_EXTS))
    hk = similarity_scan._config_keys(harness, h_text)
    uk = similarity_scan._config_keys(upstream, list(iter_files(upstream, cfg["exclude"], TEXT_EXTS)))
    res["config_keys"] = [{"key": k, "files": hk[k]} for k in sorted(set(hk) & set(uk)) if k not in allow and k.lower() not in GENERIC and len(k) >= 4]
    res["clean"] = not any(res[k] for k in ("identifiers", "strings", "name", "docs", "metadata", "config_keys"))
    return res


def _strip_names(shingle: str, cfg: dict) -> str:
    """Compare prose with project names masked, so renaming the project doesn't hide copied text."""
    out = shingle
    for n in (cfg.get("upstream_name"), cfg.get("project_name")):
        for v in name_variants(n or ""):
            if len(v) >= 3:
                out = re.sub(r"(?<![a-z0-9])" + re.escape(v.lower()) + r"(?![a-z0-9])", "<name>", out)
    return out


def fresh_history(state: Path, mode: str, dry: bool) -> list[str]:
    d = _gates.load(state)
    if (d.get("fresh_history") or {}).get("status") != "open":
        raise Refused(f"fresh history needs its own confirmation: type '{_gates.FRESH_HISTORY}'")
    harness = state.parent
    actions = []
    if mode == "orphan":
        actions += ["git checkout --orphan cleanroom-fresh", "git add -A", "git commit -m 'Fresh history after clean-room rewrite'",
                    "(old branches and history are left untouched; delete or keep them yourself)"]
        if not dry:
            for cmd in (["git", "checkout", "--orphan", "cleanroom-fresh"], ["git", "add", "-A"],
                        ["git", "commit", "-q", "-m", "Fresh history after clean-room rewrite"]):
                r = run(cmd, cwd=harness)
                if r.returncode != 0:
                    raise Refused(f"{' '.join(cmd)} failed: {r.stderr.strip()}")
    else:
        dst = harness.parent / f"{harness.name}-fresh"
        actions += [f"copy working tree (no .git) to {dst}", f"git init {dst}", "initial commit"]
        if not dry:
            if dst.exists():
                raise Refused(f"{dst} already exists")
            shutil.copytree(harness, dst, ignore=shutil.ignore_patterns(".git", "backup", "sandbox"))
            run(["git", "init", "-q"], cwd=dst)
            run(["git", "add", "-A"], cwd=dst)
            run(["git", "commit", "-q", "-m", "Initial commit after clean-room rewrite"], cwd=dst)
    if not dry:
        provenance_log.append(state, "swap", "script", decision={"fresh_history": mode}, commands=actions)
    return actions


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("swap")
    s.add_argument("--module", required=True)
    s.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("clean")
    c.add_argument("--dry-run", action="store_true")
    sub.add_parser("leftovers")
    f = sub.add_parser("fresh-history")
    f.add_argument("--mode", choices=["orphan", "new-repo"], required=True)
    f.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    try:
        if args.cmd == "swap":
            acts = do_swap(state, args.module, args.dry_run)
        elif args.cmd == "clean":
            acts = do_clean(state, args.dry_run)
        elif args.cmd == "fresh-history":
            acts = fresh_history(state, args.mode, args.dry_run)
        else:
            res = leftovers(state)
            write_json(state / "reports" / "leftovers.json", res)
            provenance_log.append(state, "swap", "script", commands=["swap_and_clean.py leftovers"],
                                  decision={"clean": res["clean"], **{k: len(res[k]) for k in ("identifiers", "strings", "name", "docs", "metadata", "config_keys")}})
            for k in ("identifiers", "strings", "name", "docs", "metadata", "config_keys"):
                for x in res[k][:50]:
                    print(f"LEFTOVER {k:<11} {json.dumps(x)}")
            print("NO UPSTREAM LEFTOVERS FOUND" if res["clean"] else "UPSTREAM LEFTOVERS REMAIN")
            if res["clean"]:
                print("Note: git history still contains the upstream code. See `fresh-history` (separate, confirmed step).")
            return 0 if res["clean"] else 1
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    for a in acts:
        print(("[dry-run] " if getattr(args, "dry_run", False) else "") + a)
    if args.cmd in ("swap", "clean") and not getattr(args, "dry_run", False):
        print("\nWARNING: git history still contains the upstream code. Run `fresh-history` (separate confirmed step) if you need a history without it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
