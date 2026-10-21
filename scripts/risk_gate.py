#!/usr/bin/env python3
"""Human confirmation gates. Answers live in .cleanroom/risk_decisions.json and the provenance log.

  risk_gate.py questions                       print the six questions and why they matter
  risk_gate.py ask                             interactive: the HUMAN types each answer in a terminal (source=tty)
  risk_gate.py record --gate ID --answer A [--override "I accept this risk"] --source chat --user-quote "..."
  risk_gate.py status [--json]                 exit 0 only if every risk gate and the license gate are open
  risk_gate.py scan-patents [--upstream PATH]  show patent notices found in upstream
  risk_gate.py approve-allowlist --typed "approve allowlist" --source ... [--user-quote ...]
  risk_gate.py approve-spec --module M --typed "approve spec" --source ... [--user-quote ...]
  risk_gate.py signoff --typed "approve swap" --source ... [--user-quote ...]
  risk_gate.py approve-fresh-history --typed "rewrite history" --source ... [--user-quote ...]

No default answers exist. A skipped question leaves its gate closed. Claude must never fill in an
answer for the user: with --source chat it must pass the user's verbatim reply in --user-quote.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_state_dir, load_config, read_json, sha256_file  # noqa: E402
import _gates  # noqa: E402


def _ctx(state: Path, upstream: str | None = None) -> dict:
    cfg = load_config(state)
    up = upstream or cfg.get("upstream")
    return {"patent_findings": _gates.scan_patents(Path(up)) if up and Path(up).exists() else [],
            "upstream_name": cfg.get("upstream_name")}


def cmd_ask(state: Path) -> int:
    if not sys.stdin.isatty():
        print("ERROR: 'ask' needs an interactive terminal so a human types the answers. "
              "Run it yourself in a terminal, or answer in chat.", file=sys.stderr)
        return 2
    ctx = _ctx(state)
    for gid in _gates.ORDER:
        q = _gates.QUESTIONS[gid]
        print(f"\n[{gid}] {q['q']}\n  Why it matters: {q['why']}")
        if gid == "patents" and ctx["patent_findings"]:
            print("  Patent notices found in upstream:")
            for f in ctx["patent_findings"]:
                print(f"   - {f['file']}:{f['line'] or ''} {f['text'][:120]}")
        if q["answers"]:
            print(f"  Answer ({'/'.join(q['answers'])}), or press Enter to skip:")
        ans = input("> ").strip() or None
        override = None
        status, reason = _gates.evaluate(gid, ans, None, ctx)
        if status == "closed" and ans and gid in ("agreements", "patents"):
            print(f"  RISK: {reason}\n  Type exactly '{_gates.OVERRIDE}' to continue, or Enter to leave the gate closed:")
            override = input("> ").strip() or None
        e = _gates.record(state, gid, ans, override, "tty", None, ctx)
        print(f"  -> {e['status']}: {e['reason']}")
        if e.get("recommendation"):
            print("  Recommended before release (not blocking):")
            for r in e["recommendation"]:
                print(f"   - {r}")
        if e["status"] == "stopped":
            print("\nHARD STOP. The clean room cannot continue.")
            return 1
    return 0


def print_status(state: Path, as_json: bool) -> int:
    st = _gates.risk_status(state)
    ok = st["all_risk_open"] and st["license"]["status"] == "open"
    if as_json:
        print(json.dumps({**st, "ok": ok}, indent=2))
    else:
        print(f"license      {st['license']['status']:<8} {st['license']['reason']}")
        for gid, g in st["gates"].items():
            print(f"{gid:<12} {g['status']:<8} {g['reason']}")
        print(f"allowlist    {st['allowlist']}")
        print(f"signoff      {st['signoff']}")
        print("\nALL RISK GATES OPEN" if ok else "\nGATES NOT SATISFIED: the build stage will not start")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("questions")
    sub.add_parser("ask")
    r = sub.add_parser("record")
    r.add_argument("--gate", required=True, choices=_gates.ORDER)
    r.add_argument("--answer")
    r.add_argument("--override")
    r.add_argument("--source", required=True, choices=_gates.VALID_SOURCES)
    r.add_argument("--user-quote")
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    p = sub.add_parser("scan-patents")
    p.add_argument("--upstream")
    for name in ("approve-allowlist", "approve-spec", "signoff", "approve-fresh-history"):
        x = sub.add_parser(name)
        x.add_argument("--typed", required=True)
        x.add_argument("--source", required=True, choices=_gates.VALID_SOURCES)
        x.add_argument("--user-quote")
        if name == "approve-spec":
            x.add_argument("--module", required=True)
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)

    try:
        if args.cmd == "questions":
            for gid in _gates.ORDER:
                q = _gates.QUESTIONS[gid]
                print(f"[{gid}] {q['q']}\n    why: {q['why']}\n")
            return 0
        if args.cmd == "ask":
            return cmd_ask(state)
        if args.cmd == "record":
            e = _gates.record(state, args.gate, args.answer, args.override, args.source, args.user_quote, _ctx(state))
            print(json.dumps({k: e.get(k) for k in ("status", "reason", "reopened", "recommendation", "patent_findings") if e.get(k) is not None}, indent=2))
            return 0 if e["status"] == "open" else 1
        if args.cmd == "status":
            return print_status(state, args.json)
        if args.cmd == "scan-patents":
            f = _ctx(state, args.upstream)["patent_findings"]
            print(json.dumps(f, indent=2) if f else "No patent notices found in upstream.")
            return 0
        if args.cmd == "approve-allowlist":
            al = state / "allowlist.json"
            if not al.exists():
                print("ERROR: no allowlist.json to approve", file=sys.stderr)
                return 2
            e = _gates.typed_approval(state, "allowlist", args.typed, _gates.ALLOWLIST_APPROVE, args.source, args.user_quote,
                                      {"sha256": sha256_file(al), "names": read_json(al, {}).get("names", [])})
        elif args.cmd == "approve-spec":
            spec = state / "specs" / f"{args.module}.md"
            filt = read_json(state / "reports" / f"spec_filter_{args.module}.json", {})
            if not spec.exists() or not filt or not filt.get("passed") or filt.get("sha256") != sha256_file(spec):
                print("ERROR: spec must exist and pass spec_filter (on its current content) before approval", file=sys.stderr)
                return 2
            contract = state / "contracts" / f"{args.module}.md"
            if not contract.exists():
                print("ERROR: contract missing: approve the spec and its interface contract together", file=sys.stderr)
                return 2
            builds = state / "builds" / args.module
            last = max((int(p.name.split("-")[1]) for p in builds.glob("attempt-*")), default=0) if builds.exists() else 0
            e = _gates.typed_approval(state, "spec_approvals", args.typed, _gates.SPEC_APPROVE, args.source, args.user_quote,
                                      {"sha256": sha256_file(spec), "contract_sha256": sha256_file(contract), "for_attempt": last + 1},
                                      module=args.module)
        elif args.cmd == "signoff":
            summ = state / "reports" / "signoff_summary.md"
            if not summ.exists():
                print("ERROR: generate the summary first: run_all.py summary", file=sys.stderr)
                return 2
            e = _gates.typed_approval(state, "signoff", args.typed, _gates.SIGNOFF, args.source, args.user_quote,
                                      {"summary_sha256": sha256_file(summ)})
        else:
            e = _gates.typed_approval(state, "fresh_history", args.typed, _gates.FRESH_HISTORY, args.source, args.user_quote)
        print(f"{args.cmd}: {e['status']}")
        return 0 if e["status"] == "open" else 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
