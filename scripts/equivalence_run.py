#!/usr/bin/env python3
"""Behavioral fixtures: run the OLD module on spec-derived inputs, store outputs as data, compare NEW.

  equivalence_run.py capture --module M                 old module -> fixtures/M.json
  equivalence_run.py compare --module M --attempt N     new build  -> reports/equivalence_M_attemptN.json

Inputs come from fixtures/M.inputs.json (written by the test-writer from the spec):
  [{"function": "name", "args": [...], "kwargs": {...}}, ...]
Outputs record return values (JSON) or the exception TYPE only. Exception messages are not stored,
because they may be upstream text. Fixtures are data, never code, and never enter the sandbox.

Python modules run in a subprocess via a built-in driver. Other languages: set config
modules.M.driver to a command that reads one JSON case on stdin and prints one JSON result.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_state_dir, load_config, read_json, write_json  # noqa: E402
import provenance_log  # noqa: E402
import sandbox_prepare  # noqa: E402

PY_DRIVER = r"""
import importlib.util, json, sys, os
path, roots = sys.argv[1], sys.argv[2:]
for r in roots:
    sys.path.insert(0, r)
spec = importlib.util.spec_from_file_location("cleanroom_module_under_test", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cases = json.load(sys.stdin)
out = []
def enc(v):
    try:
        json.dumps(v); return v
    except TypeError:
        if isinstance(v, (set, frozenset)): return sorted(enc(x) for x in v)
        if isinstance(v, tuple): return [enc(x) for x in v]
        if hasattr(v, "__dict__"): return {"__type__": type(v).__name__, **{k: enc(x) for k, x in vars(v).items() if not k.startswith("_")}}
        return repr(v)
for c in cases:
    try:
        fn = getattr(mod, c["function"])
        v = fn(*c.get("args", []), **c.get("kwargs", {}))
        if hasattr(v, "__iter__") and not isinstance(v, (str, bytes, dict, list, tuple, set, frozenset)):
            v = list(v)
        out.append({"ok": True, "value": enc(v)})
    except Exception as e:
        out.append({"ok": False, "exc_type": type(e).__name__, "exc_bases": [b.__name__ for b in type(e).__mro__[1:4]]})
print(json.dumps(out))
"""


def execute(module_file: Path, cases: list, roots: list[str], driver: str | None) -> list:
    if driver:
        results = []
        for c in cases:
            r = subprocess.run(shlex.split(driver) + [str(module_file)], input=json.dumps(c), capture_output=True, text=True, timeout=60)
            try:
                results.append(json.loads(r.stdout))
            except json.JSONDecodeError:
                results.append({"ok": False, "exc_type": "DriverError"})
        return results
    r = subprocess.run([sys.executable, "-I", "-c", PY_DRIVER, str(module_file), *roots], input=json.dumps(cases),
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"driver failed: {r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def same(a: dict, b: dict) -> bool:
    if a.get("ok") != b.get("ok"):
        return False
    if a.get("ok"):
        return a.get("value") == b.get("value")
    # Exceptions match when the type matches or both derive from the same builtin base.
    return a.get("exc_type") == b.get("exc_type") or bool(set(a.get("exc_bases", [])[:1]) & set(b.get("exc_bases", [])[:1]) - {"Exception", "object"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--module", required=True)
    m = sub.add_parser("compare")
    m.add_argument("--module", required=True)
    m.add_argument("--attempt", type=int, required=True)
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = load_config(state)
    harness = Path(cfg.get("harness") or state.parent)
    inputs = read_json(state / "fixtures" / f"{args.module}.inputs.json")
    if not inputs:
        print("ERROR: no probe inputs (fixtures/<module>.inputs.json); run the test-writer first", file=sys.stderr)
        return 2
    driver = ((cfg.get("modules") or {}).get(args.module) or {}).get("driver")
    targets = sandbox_prepare.module_targets(state, cfg, args.module)
    entry = targets[0]
    if args.cmd == "capture":
        old = harness / entry
        res = execute(old, inputs, [str(harness), str(old.parent)], driver)
        fx = state / "fixtures" / f"{args.module}.json"
        write_json(fx, {"module": args.module, "source": entry, "cases": inputs, "results": res})
        provenance_log.append(state, "tests", "script", reads=[old], writes=[fx], commands=["equivalence_run.py capture"],
                              decision={"module": args.module, "cases": len(inputs)})
        print(f"captured {len(res)} behavioral fixtures from {entry}")
        return 0
    fx = read_json(state / "fixtures" / f"{args.module}.json")
    if not fx:
        print("ERROR: no fixtures captured for this module", file=sys.stderr)
        return 2
    build = state / "builds" / args.module / f"attempt-{args.attempt}"
    new = build / entry
    if not new.exists():
        print(f"ERROR: build output missing: {new}", file=sys.stderr)
        return 2
    res = execute(new, fx["cases"], [str(build), str(new.parent)], driver)
    mism = [i for i, (a, b) in enumerate(zip(fx["results"], res)) if not same(a, b)]
    rep = {"module": args.module, "attempt": args.attempt, "cases": len(res), "mismatches": len(mism),
           "mismatch_cases": [{"case": fx["cases"][i], "expected": fx["results"][i], "got": res[i]} for i in mism],
           "passed": not mism}
    out = state / "reports" / f"equivalence_{args.module}_attempt{args.attempt}.json"
    write_json(out, rep)
    provenance_log.append(state, "verify", "script", reads=[new], writes=[out], commands=["equivalence_run.py compare"],
                          decision={"module": args.module, "attempt": args.attempt, "passed": rep["passed"], "mismatches": len(mism)})
    print(f"equivalence: {len(res) - len(mism)}/{len(res)} cases match")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
