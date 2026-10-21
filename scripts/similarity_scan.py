#!/usr/bin/env python3
"""Compare the harness against upstream and report overlap per file and per function.

Signals:
  - k-gram winnowing on normalized tokens (comments/whitespace stripped, identifiers -> placeholders)
  - shared distinctive identifiers, non-trivial string literals, comments / comment blocks
  - file and folder names, package metadata, README text, license headers, config keys
  - occurrences of the upstream project name

  similarity_scan.py scan    [--harness H] [--upstream U] [--dry-run]   -> reports/scan.json + scan_summary.md
  similarity_scan.py compare --target PATH [--upstream U] [--json]      -> file-level scores only (used by verify)

--dry-run prints the summary and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CODE_EXTS, TEXT_EXTS, find_state_dir, iter_files, load_config, now, write_json  # noqa: E402
from _similarity import (GENERIC, distinctive, facts, name_variants, norm_text, similar_name,  # noqa: E402
                         word_shingles)
import provenance_log  # noqa: E402

LICENSE_HDR = re.compile(r"copyright\s*(\(c\)|©|\d{4})|spdx-license-identifier|licensed under|all rights reserved", re.I)


class Index:
    """Fingerprints and auxiliary facts for one tree (usually upstream)."""

    def __init__(self, root: Path, exclude: list[str], k: int, w: int, str_len: int, cmt_len: int):
        self.root = Path(root)
        self.files = {}
        self.fp = defaultdict(set)          # hash -> {file}
        self.idents = Counter()
        self.strings = {}                   # text -> file
        self.comments = {}                  # normalized text -> file
        self.comment_shingles = {}          # 8-word shingle -> file
        for p in iter_files(root, exclude, CODE_EXTS):
            f = facts(p, root, k, w)
            self.files[f.path] = f
            for h, _ in f.fingerprints:
                self.fp[h].add(f.path)
            self.idents.update(i for i in f.identifiers if distinctive(i))
            for s, _ in f.strings:
                if nontrivial_string(s, str_len):
                    self.strings.setdefault(s, f.path)
            for c, _ in f.comments:
                n = norm_text(c)
                if len(n) >= cmt_len:
                    self.comments.setdefault(n, f.path)
                for sh in word_shingles(c, 8):
                    self.comment_shingles.setdefault(sh, f.path)


def nontrivial_string(s: str, min_len: int) -> bool:
    return len(s) >= min_len and bool(re.search(r"[A-Za-z]{3}", s))


def compare_file(f, idx: Index, thresholds: dict, name_res: list[re.Pattern]) -> dict:
    total = len(f.fingerprints) or 1
    per_up = Counter()
    matched_lines = set()
    hit = 0
    for h, line in f.fingerprints:
        ups = idx.fp.get(h)
        if ups:
            hit += 1
            matched_lines.add(line)
            per_up.update(ups)
    best = per_up.most_common(1)
    funcs = []
    for name, s, e in f.functions:
        fps = [(h, l) for h, l in f.fingerprints if s <= l <= e]
        if not fps:
            continue
        m = sum(1 for h, _ in fps if h in idx.fp)
        funcs.append({"name": name, "start": s, "end": e, "overlap": round(m / len(fps), 3), "fingerprints": len(fps)})
    shared_ids = sorted(i for i in f.identifiers if distinctive(i) and i in idx.idents)
    dist_ids = [i for i in f.identifiers if distinctive(i)]
    strings = [{"text": s, "line": l, "upstream_file": idx.strings[s]} for s, l in f.strings
               if nontrivial_string(s, thresholds["nontrivial_string_len"]) and s in idx.strings]
    comments = []
    for c, l in f.comments:
        n = norm_text(c)
        if len(n) >= thresholds["comment_block_len"] and n in idx.comments:
            comments.append({"text": c[:200], "line": l, "upstream_file": idx.comments[n], "kind": "exact"})
            continue
        shared = [sh for sh in word_shingles(c, 8) if sh in idx.comment_shingles]
        if shared:
            comments.append({"text": c[:200], "line": l, "upstream_file": idx.comment_shingles[shared[0]], "kind": "block"})
    return {
        "path": f.path,
        "token_overlap": round(hit / total, 3),
        "fingerprints": len(f.fingerprints),
        "best_match": {"file": best[0][0], "shared_fingerprints": best[0][1]} if best else None,
        "matched_line_ranges": _ranges(sorted(matched_lines)),
        "functions": sorted(funcs, key=lambda x: -x["overlap"]),
        "identifiers": {"shared": shared_ids, "ratio": round(len(shared_ids) / (len(dist_ids) or 1), 3)},
        "strings": strings,
        "comments": comments,
    }


def _ranges(lines: list[int]) -> list[list[int]]:
    out = []
    for l in lines:
        if out and l <= out[-1][1] + 2:
            out[-1][1] = l
        else:
            out.append([l, l])
    return out


def name_patterns(upstream_name: str | None) -> list[re.Pattern]:
    if not upstream_name:
        return []
    return [re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", re.I) for v in sorted(name_variants(upstream_name), key=len, reverse=True) if len(v) >= 3]


def text_scans(harness: Path, upstream: Path, exclude: list[str], upstream_name: str | None) -> dict:
    """Non-code signals: names in paths, package metadata, README, license headers, config keys, project name."""
    h_files = list(iter_files(harness, exclude, TEXT_EXTS))
    u_files = list(iter_files(upstream, exclude, TEXT_EXTS))
    rel_h = [p.relative_to(harness).as_posix() for p in h_files]
    rel_u = [p.relative_to(upstream).as_posix() for p in u_files]

    def comps(r):
        parts = r.split("/")
        return {re.sub(r"\.[^.]+$", "", x).lower() for x in parts}

    up_comps = set().union(*[comps(r) for r in rel_u]) if rel_u else set()
    paths = []
    for r in rel_h:
        shared = sorted(c for c in comps(r) if c in up_comps and c not in GENERIC and len(c) >= 4)
        if shared:
            paths.append({"path": r, "shared_components": shared})

    meta = []
    for name in ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml", "go.mod"):
        hp, up = harness / name, upstream / name
        if hp.exists() and up.exists():
            hv, uv = _meta_fields(hp), _meta_fields(up)
            for k in sorted(set(hv) & set(uv)):
                a, b = hv[k], uv[k]
                if a == b or (k == "name" and similar_name(a, b) >= 0.75) or (len(word_shingles(a, 5) & word_shingles(b, 5)) > 0):
                    meta.append({"file": name, "field": k, "harness": a[:200], "upstream": b[:200]})

    readme = []
    up_sh = set()
    for p in u_files:
        if p.name.upper().startswith("README") or p.suffix.lower() in (".md", ".rst"):
            up_sh |= word_shingles(p.read_text(encoding="utf-8", errors="replace"), 8)
    for p in h_files:
        if p.name.upper().startswith("README") or p.suffix.lower() in (".md", ".rst"):
            sh = word_shingles(p.read_text(encoding="utf-8", errors="replace"), 8)
            shared = sh & up_sh
            if shared:
                readme.append({"file": p.relative_to(harness).as_posix(), "shared_shingles": len(shared),
                               "ratio": round(len(shared) / (len(sh) or 1), 3), "samples": sorted(shared)[:3]})

    name_res = name_patterns(upstream_name)
    headers, name_hits = [], []
    up_holders = _copyright_holders(u_files)
    for p in h_files:
        r = p.relative_to(harness).as_posix()
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, l in enumerate(lines[:40], 1):
            if LICENSE_HDR.search(l):
                headers.append({"file": r, "line": i, "text": l.strip()[:200],
                                "mentions_upstream_holder": any(h.lower() in l.lower() for h in up_holders)})
        for i, l in enumerate(lines, 1):
            for rx in name_res:
                if rx.search(l):
                    name_hits.append({"file": r, "line": i, "text": l.strip()[:200]})
                    break
    for r in rel_h:
        if any(rx.search(r) for rx in name_res):
            name_hits.append({"file": r, "line": 0, "text": "(in path)"})

    hk, uk = _config_keys(harness, h_files), _config_keys(upstream, u_files)
    config_keys = sorted({k for k in hk if k in uk and k.lower() not in GENERIC and len(k) >= 4})
    return {"paths": paths, "package_metadata": meta, "readme": readme, "license_headers": headers,
            "upstream_name_hits": name_hits, "config_keys": [{"key": k, "harness_files": hk[k], "upstream_files": uk[k]} for k in config_keys],
            "upstream_copyright_holders": sorted(up_holders)}


def _copyright_holders(files) -> set[str]:
    holders = set()
    for p in files:
        try:
            head = p.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
        except OSError:
            continue
        for l in head:
            m = re.search(r"copyright\s*(?:\(c\)|©)?\s*(?:\d{4}(?:\s*[-,]\s*\d{4})*)?\s*,?\s*(?:by\s+)?([A-Z][\w .&'-]{2,60})", l, re.I)
            if m:
                h = m.group(1).strip(" .")
                if h.lower() not in ("the", "notice", "holders", "holder", "and", "owner") and not h.lower().startswith(("notice", "holder", "the copyright")):
                    holders.add(h)
    return holders


def _meta_fields(p: Path) -> dict:
    t = p.read_text(encoding="utf-8", errors="replace")
    out = {}
    if p.name == "package.json":
        try:
            j = json.loads(t)
        except json.JSONDecodeError:
            return out
        for k in ("name", "description", "author", "homepage", "repository", "keywords", "bugs", "bin"):
            if k in j:
                out[k] = j[k] if isinstance(j[k], str) else json.dumps(j[k], sort_keys=True)
        return out
    for k in ("name", "description", "authors", "author", "homepage", "repository", "keywords", "module"):
        m = re.search(rf"""^\s*{k}\s*[=:]\s*(.+)$""", t, re.M)
        if m:
            out[k] = m.group(1).strip().strip(",").strip("'\"")
    return out


def _config_keys(root: Path, files) -> dict:
    keys = defaultdict(list)
    for p in files:
        ext = p.suffix.lower()
        if p.name in ("package.json", "package-lock.json", "tsconfig.json") or ext not in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env") and p.name != ".env":
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        found = set()
        if ext == ".json":
            try:
                _walk_keys(json.loads(t), found)
            except json.JSONDecodeError:
                pass
        elif ext in (".yaml", ".yml"):
            found |= set(re.findall(r"^\s*-?\s*([A-Za-z_][\w.-]*)\s*:", t, re.M))
        else:
            found |= set(re.findall(r"^\s*([A-Za-z_][\w.-]*)\s*=", t, re.M))
        for k in found:
            keys[k].append(p.relative_to(root).as_posix())
    return keys


def _walk_keys(o, acc: set):
    if isinstance(o, dict):
        for k, v in o.items():
            acc.add(str(k))
            _walk_keys(v, acc)
    elif isinstance(o, list):
        for v in o:
            _walk_keys(v, acc)


def scan(harness: Path, upstream: Path, cfg: dict) -> dict:
    t = cfg["thresholds"]
    exclude = cfg["exclude"]
    idx = Index(upstream, exclude, t["k"], t["window"], t["nontrivial_string_len"], t["comment_block_len"])
    name_res = name_patterns(cfg.get("upstream_name"))
    files = []
    for p in iter_files(harness, exclude, CODE_EXTS):
        f = facts(p, harness, t["k"], t["window"])
        files.append(compare_file(f, idx, t, name_res))
    for r in files:
        r["score"] = round(max(r["token_overlap"], max((fn["overlap"] for fn in r["functions"]), default=0) * 0.8)
                           + 0.05 * len(r["strings"]) + 0.05 * len(r["comments"]), 3)
    files.sort(key=lambda r: -r["score"])
    return {"generated": now(), "harness": str(harness), "upstream": str(upstream), "upstream_name": cfg.get("upstream_name"),
            "thresholds": t, "files": files, **text_scans(harness, upstream, exclude, cfg.get("upstream_name"))}


def summary_md(rep: dict) -> str:
    t = rep["thresholds"]
    L = [f"# Similarity scan: harness vs upstream", "", f"Generated {rep['generated']}. Winnowing k={t['k']} w={t['window']}.", "",
         "| Rank | File | Token overlap | Worst function | Shared strings | Shared comments | Best upstream match |",
         "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rep["files"], 1):
        wf = r["functions"][0] if r["functions"] else None
        L.append(f"| {i} | `{r['path']}` | {r['token_overlap']:.0%} | {(wf['name'] + ' ' + format(wf['overlap'], '.0%')) if wf else '-'} | "
                 f"{len(r['strings'])} | {len(r['comments'])} | {r['best_match']['file'] if r['best_match'] else '-'} |")
    L += ["", "## Non-code findings", "",
          f"- Paths sharing upstream names: {len(rep['paths'])}",
          f"- Package metadata matches: {len(rep['package_metadata'])}",
          f"- README passages shared: {sum(x['shared_shingles'] for x in rep['readme'])}",
          f"- License/copyright header lines: {len(rep['license_headers'])} "
          f"({sum(1 for h in rep['license_headers'] if h['mentions_upstream_holder'])} name an upstream copyright holder)",
          f"- Shared config keys: {len(rep['config_keys'])}",
          f"- Mentions of upstream name '{rep.get('upstream_name')}': {len(rep['upstream_name_hits'])}"]
    return "\n".join(L) + "\n"


def compare_target(target: Path, upstream: Path, cfg: dict) -> list[dict]:
    """File-level scores only. Safe to turn into builder feedback (no lines, no text)."""
    t = cfg["thresholds"]
    idx = Index(upstream, cfg["exclude"], t["k"], t["window"], t["nontrivial_string_len"], t["comment_block_len"])
    root = target if target.is_dir() else target.parent
    files = [target] if target.is_file() else list(iter_files(target, cfg["exclude"], CODE_EXTS))
    name_res = name_patterns(cfg.get("upstream_name"))
    out = []
    for p in files:
        f = facts(p, root, t["k"], t["window"])
        r = compare_file(f, idx, t, name_res)
        text = p.read_text(encoding="utf-8", errors="replace")
        out.append({"file": r["path"], "token_overlap": r["token_overlap"],
                    "max_function_overlap": max((fn["overlap"] for fn in r["functions"]), default=0.0),
                    "shared_strings": len(r["strings"]), "shared_comments": len(r["comments"]),
                    "shared_identifiers": len(r["identifiers"]["shared"]),
                    "upstream_name_mentions": sum(1 for rx in name_res for _ in rx.finditer(text))})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--upstream")
    s.add_argument("--dry-run", action="store_true", help="print summary, write nothing")
    c = sub.add_parser("compare")
    c.add_argument("--target", required=True)
    c.add_argument("--upstream")
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = load_config(state)
    upstream = Path(args.upstream or cfg.get("upstream") or "")
    if not upstream.is_dir():
        print("ERROR: upstream directory not found", file=sys.stderr)
        return 2
    if args.cmd == "scan":
        harness = Path(args.harness or cfg.get("harness") or state.parent)
        rep = scan(harness, upstream, cfg)
        md = summary_md(rep)
        if args.dry_run:
            print(md)
            print("(dry run: nothing written)")
            return 0
        out = state / "reports"
        write_json(out / "scan.json", rep)
        (out / "scan_summary.md").write_text(md, encoding="utf-8")
        provenance_log.append(state, "scan", "script", reads=[], writes=[out / "scan.json", out / "scan_summary.md"],
                              commands=["similarity_scan.py scan"], note=f"{len(rep['files'])} code files scanned")
        print(md)
        return 0
    res = compare_target(Path(args.target), upstream, cfg)
    print(json.dumps(res, indent=2) if args.json else "\n".join(f"{r['file']}: overlap {r['token_overlap']:.0%}" for r in res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
