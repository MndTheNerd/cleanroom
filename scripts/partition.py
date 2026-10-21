#!/usr/bin/env python3
"""Label every harness module original / mixed / tainted, with interface boundaries.

Default rules (configurable in .cleanroom/config.json "thresholds"):
  tainted : token overlap >= tainted_token_overlap (0.30), OR any copied non-trivial string,
            OR any copied comment block
  mixed   : token overlap >= mixed_token_overlap (0.10), OR some function >= tainted threshold
  original: everything else
  vendored: byte-identical to an upstream file. Deleted by `clean`; rewritten only if harness code imports it.

A module is one file unless config "modules" groups files: {"name": {"files": [...]}}.
Each module records its public interface (names other code depends on) and its dependents,
so a tainted module can be replaced on its own.

  partition.py [--harness H] [--dry-run]     -> reports/partition.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CODE_EXTS, find_state_dir, iter_files, load_config, read_json, sha256_file, write_json  # noqa: E402
import provenance_log  # noqa: E402

RANK = {"original": 0, "mixed": 1, "tainted": 2, "vendored": 3}


def label_file(r: dict, t: dict) -> tuple[str, list[str]]:
    why = []
    if r["token_overlap"] >= t["tainted_token_overlap"]:
        why.append(f"token overlap {r['token_overlap']:.0%} >= {t['tainted_token_overlap']:.0%}")
    if r["strings"]:
        why.append(f"{len(r['strings'])} copied non-trivial string(s)")
    if r["comments"]:
        why.append(f"{len(r['comments'])} copied comment(s)/comment block(s)")
    if why:
        return "tainted", why
    if r["token_overlap"] >= t["mixed_token_overlap"]:
        why.append(f"token overlap {r['token_overlap']:.0%} >= {t['mixed_token_overlap']:.0%}")
    hot = [f for f in r["functions"] if f["overlap"] >= t["tainted_token_overlap"] and f["fingerprints"] >= 3]
    if hot:
        why.append("function(s) over threshold: " + ", ".join(f"{f['name']} {f['overlap']:.0%}" for f in hot[:5]))
    return ("mixed", why) if why else ("original", ["below all thresholds"])


def public_interface(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []
        names = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_"):
                names.append(n.name)
            elif isinstance(n, ast.Assign):
                for tgt in n.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "__all__" and isinstance(n.value, (ast.List, ast.Tuple)):
                        return [e.value for e in n.value.elts if isinstance(e, ast.Constant)]
                    if isinstance(tgt, ast.Name) and tgt.id.isupper():
                        names.append(tgt.id)
        return names
    names = re.findall(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", src)
    m = re.search(r"module\.exports\s*=\s*\{([^}]*)\}", src)
    if m:
        names += re.findall(r"([A-Za-z_$][\w$]*)\s*(?:[:,]|$)", m.group(1))
    names += re.findall(r"exports\.([A-Za-z_$][\w$]*)\s*=", src)
    return sorted(set(names))


def dependents(harness: Path, target_rel: str, exclude: list[str]) -> list[str]:
    stem = Path(target_rel).stem
    if stem in ("__init__", "index"):
        stem = Path(target_rel).parent.name
    rx = re.compile(rf"(?:import|from|require\()\s*[\"']?[\w./@-]*\b{re.escape(stem)}\b")
    out = []
    for p in iter_files(harness, exclude, CODE_EXTS):
        r = p.relative_to(harness).as_posix()
        if r != target_rel and rx.search(p.read_text(encoding="utf-8", errors="replace")):
            out.append(r)
    return out


def module_name(rel: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", re.sub(r"\.[^.]+$", "", rel)).strip("-").lower() or "module"
    name, i = base, 2
    while name in taken:
        name, i = f"{base}-{i}", i + 1
    taken.add(name)
    return name


def partition(state: Path, cfg: dict) -> dict:
    scan = read_json(state / "reports" / "scan.json")
    if not scan:
        raise SystemExit("ERROR: run the scan first (reports/scan.json missing)")
    harness = Path(cfg.get("harness") or state.parent)
    t = cfg["thresholds"]
    by_path = {r["path"]: r for r in scan["files"]}
    labels = {p: label_file(r, t) for p, r in by_path.items()}
    # Byte-identical copies of upstream files are 'vendored': deleted by clean, rewritten only if something imports them.
    upstream = Path(cfg["upstream"])
    up_hashes = {sha256_file(p) for p in iter_files(upstream, cfg["exclude"], CODE_EXTS) if p.stat().st_size}
    for p, r in by_path.items():
        trivial = r["fingerprints"] < 3
        if not trivial and (harness / p).exists() and sha256_file(harness / p) in up_hashes:
            labels[p] = ("vendored", ["byte-identical copy of an upstream file"])
    groups = {name: m["files"] for name, m in (cfg.get("modules") or {}).items()}
    grouped = {f for fs in groups.values() for f in fs}
    taken = set(groups)
    for p in sorted(by_path):
        if p not in grouped:
            groups[module_name(p, taken)] = [p]
    modules = {}
    for name, fs in sorted(groups.items()):
        file_labels = {f: labels.get(f, ("original", ["not scanned"])) for f in fs}
        worst = max((lab for lab, _ in file_labels.values()), key=lambda x: RANK[x])
        iface, deps = [], set()
        for f in fs:
            fp = harness / f
            if fp.exists():
                iface += public_interface(fp)
                deps |= set(dependents(harness, f, cfg["exclude"]))
        modules[name] = {
            "label": worst,
            "files": {f: {"label": l, "why": w, "token_overlap": by_path.get(f, {}).get("token_overlap")} for f, (l, w) in file_labels.items()},
            "interface": sorted(set(iface)),
            "dependents": sorted(deps - set(fs)),
            "contract": f".cleanroom/contracts/{name}.md",
        }
    counts = {k: sum(1 for m in modules.values() if m["label"] == k) for k in RANK}
    return {"thresholds": t, "modules": modules, "counts": counts,
            "non_code": {k: scan[k] for k in ("paths", "package_metadata", "readme", "license_headers", "config_keys", "upstream_name_hits")}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    ap.add_argument("--dry-run", action="store_true", help="print labels, write nothing")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = load_config(state)
    res = partition(state, cfg)
    for name, m in res["modules"].items():
        print(f"{m['label']:<9} {name:<30} {', '.join(m['files'])}")
        for f, info in m["files"].items():
            if info["label"] != "original":
                print(f"           - {f}: {'; '.join(info['why'])}")
    print(f"\n{res['counts']}")
    if args.dry_run:
        print("(dry run: nothing written)")
        return 0
    out = state / "reports" / "partition.json"
    write_json(out, res)
    provenance_log.append(state, "partition", "script", reads=[state / "reports" / "scan.json"], writes=[out],
                          commands=["partition.py"], decision=res["counts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
