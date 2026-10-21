#!/usr/bin/env python3
"""Reject specs (or spec-derived tests) that leak upstream code or text.

Spec rules (kind=spec):
  code_fence           any ``` or ~~~ fence
  code_line            a line that looks like source code
  upstream_identifier  a code-shaped word (snake_case, camelCase, digits...) that exists in upstream
                       and is not on the approved allowlist; also any upstream identifier in `backticks`
  long_literal         a quoted or backticked literal longer than spec_max_literal_len (20) characters
  verbatim_text        a run of spec_verbatim_words (8) words that also appears in upstream text
  upstream_name        the upstream project name, unless allowlisted

Test rules (kind=tests): upstream_identifier, verbatim_text, upstream_name, plus any string
literal that also appears in upstream (long_literal is replaced by upstream_string).

  spec_filter.py check --spec FILE [--module M] [--kind spec|tests]   exit 1 on any violation
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import TEXT_EXTS, find_state_dir, iter_files, load_config, read_json, sha256_file, write_json  # noqa: E402
from _similarity import KEYWORDS, code_shaped, facts, lex, name_variants, word_shingles  # noqa: E402
from _common import CODE_EXTS  # noqa: E402
import provenance_log  # noqa: E402

CODE_LINE = re.compile(
    r"^\s*(def |class |function |fn |func |import |from \S+ import|#include|public |private |return\b|const |let |var )"
    r"|[;{]\s*$|^\s*\}|=>|\)\s*\{|^\s{4,}\S+\s*=\s*\S+\(|\b\w+\([^)]*\)\s*;\s*$")
LITERAL = re.compile(r'"([^"\n]*)"|“([^”\n]*)”|`([^`\n]*)`|(?<![A-Za-z])\'([^\'\n]{3,})\'(?![A-Za-z])')
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class UpstreamFacts:
    def __init__(self, upstream: Path, exclude: list[str], verbatim_n: int):
        self.idents: set[str] = set()
        self.strings: set[str] = set()
        self.shingles: set[str] = set()
        for p in iter_files(upstream, exclude, TEXT_EXTS):
            text = p.read_text(encoding="utf-8", errors="replace")
            self.shingles |= word_shingles(text, verbatim_n)
            if p.suffix.lower() in CODE_EXTS:
                f = facts(p, upstream)
                self.idents |= f.identifiers
                self.strings |= {s for s, _ in f.strings if len(s) >= 6}


def check(text: str, up: UpstreamFacts, allow: set[str], cfg: dict, kind: str = "spec") -> list[dict]:
    t = cfg["thresholds"]
    v = []
    allow_low = {a.lower() for a in allow}
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if kind == "spec":
            if re.match(r"^\s*(```|~~~)", line):
                v.append({"rule": "code_fence", "line": i, "detail": "code fences are not allowed in specs"})
                in_fence = not in_fence
                continue
            if CODE_LINE.search(line) and not re.match(r"^\s*([-*+]|\d+\.)\s", line):
                v.append({"rule": "code_line", "line": i, "detail": "line looks like source code"})
            for m in LITERAL.finditer(line):
                lit = next(g for g in m.groups() if g is not None)
                if len(lit) > t["spec_max_literal_len"] and lit not in allow:
                    v.append({"rule": "long_literal", "line": i, "detail": f"literal of {len(lit)} chars (max {t['spec_max_literal_len']})"})
            for m in re.finditer(r"`([^`\n]+)`", line):
                for w in WORD.findall(m.group(1)):
                    if w in up.idents and w not in allow and w not in KEYWORDS and len(w) > 2:
                        v.append({"rule": "upstream_identifier", "line": i, "detail": f"upstream identifier '{w}' in code span"})
        for w in set(WORD.findall(line)):
            if w in up.idents and code_shaped(w) and w not in allow:
                v.append({"rule": "upstream_identifier", "line": i, "detail": f"upstream identifier '{w}' not on allowlist"})
        if kind == "tests":
            for s, _ in lex(line, ".py").strings:
                if len(s) >= 6 and s in up.strings and s not in allow:
                    v.append({"rule": "upstream_string", "line": i, "detail": f"string literal also present in upstream ({len(s)} chars)"})
    for sh in sorted(word_shingles(text, t["spec_verbatim_words"]) & up.shingles):
        # Allowlisted phrases (e.g. a protocol name) don't count.
        if not any(a in sh for a in allow_low if " " in a):
            v.append({"rule": "verbatim_text", "line": None, "detail": f"{t['spec_verbatim_words']}-word run also in upstream: '{sh[:60]}...'"})
    name = cfg.get("upstream_name")
    if name and name.lower() not in allow_low:
        for vname in name_variants(name):
            if len(vname) >= 3 and re.search(r"(?<![A-Za-z0-9])" + re.escape(vname) + r"(?![A-Za-z0-9])", text, re.I):
                v.append({"rule": "upstream_name", "line": None, "detail": "mentions the upstream project name"})
                break
    # de-duplicate
    seen, out = set(), []
    for x in v:
        key = (x["rule"], x["line"], x["detail"])
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def approved_allowlist(state: Path) -> set[str]:
    d = read_json(state / "risk_decisions.json", {}) or {}
    a = d.get("allowlist") or {}
    al = state / "allowlist.json"
    if a.get("status") != "open" or not al.exists() or a.get("sha256") != sha256_file(al):
        return set()
    return set(read_json(al, {}).get("names", []))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--spec", required=True, help="file to check (spec .md, or a test file/dir with --kind tests)")
    c.add_argument("--module", help="module name; writes reports/spec_filter_<module>.json")
    c.add_argument("--kind", choices=["spec", "tests"], default="spec")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = load_config(state)
    up = UpstreamFacts(Path(cfg["upstream"]), cfg["exclude"], cfg["thresholds"]["spec_verbatim_words"])
    allow = approved_allowlist(state)
    target = Path(args.spec)
    files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
    all_v = []
    for f in files:
        for x in check(f.read_text(encoding="utf-8", errors="replace"), up, allow, cfg, args.kind):
            all_v.append({"file": f.name if target.is_file() else f.relative_to(target).as_posix(), **x})
    passed = not all_v
    report = {"target": str(target), "kind": args.kind, "passed": passed, "violations": all_v,
              "sha256": sha256_file(target) if target.is_file() else None, "allowlist_size": len(allow)}
    if args.module:
        suffix = "" if args.kind == "spec" else "_tests"
        out = state / "reports" / f"spec_filter_{args.module}{suffix}.json"
        write_json(out, report)
        provenance_log.append(state, "spec" if args.kind == "spec" else "tests", "script", reads=[target] if target.is_file() else [],
                              writes=[out], commands=[f"spec_filter.py check --kind {args.kind}"],
                              decision={"module": args.module, "passed": passed, "violations": len(all_v)})
    if passed:
        print(f"PASS: {target} ({args.kind}) has no leaks")
        return 0
    print(f"REJECTED: {target} has {len(all_v)} violation(s):")
    for x in all_v:
        print(f"  [{x['rule']}] {x['file']}:{x['line'] or '-'}  {x['detail']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
