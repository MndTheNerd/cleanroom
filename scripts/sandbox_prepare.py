#!/usr/bin/env python3
"""Create a clean sandbox folder holding ONLY approved inputs, and its approved SHA-256 manifest.

  sandbox_prepare.py prepare --module M --role test-writer|builder [--attempt N]
  sandbox_prepare.py collect --module M --role test-writer|builder [--attempt N]

prepare refuses unless: license + all risk gates are open, the allowlist is approved, the
spec is approved (hash unchanged), and every input passes spec_filter. Files are COPIED, never
linked. The approved manifest is written OUTSIDE the sandbox (.cleanroom/manifests/).

test-writer inputs: AGENT.md, TASK.md, spec.md, contract.md
builder inputs    : AGENT.md, TASK.md, spec.md, contract.md, style.md (optional),
                    tests/ (spec-derived), feedback.md (attempt > 1, file-level scores only)

collect copies results out of a finished sandbox: test-writer -> .cleanroom/tests/M and
fixtures/M.inputs.json (after the tests pass spec_filter --kind tests); builder ->
.cleanroom/builds/M/attempt-N/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PLUGIN_ROOT, find_state_dir, load_config, now, read_json, sha256_file, write_json  # noqa: E402
import _gates  # noqa: E402
import provenance_log  # noqa: E402
import spec_filter  # noqa: E402
from manifest_check import snapshot  # noqa: E402


class Refused(Exception):
    pass


def agent_body(role: str) -> str:
    text = (PLUGIN_ROOT / "agents" / f"{role}.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip() + "\n"


def module_targets(state: Path, cfg: dict, module: str) -> list[str]:
    m = (cfg.get("modules") or {}).get(module)
    if m and m.get("target"):
        return list(m["target"]) if isinstance(m["target"], list) else [m["target"]]
    part = read_json(state / "reports" / "partition.json", {}) or {}
    pm = part.get("modules", {}).get(module)
    if not pm:
        raise Refused(f"module '{module}' not found in partition.json")
    return list(pm["files"])


def task_text(role: str, module: str, cfg: dict, targets: list[str], attempt: int, has_feedback: bool) -> str:
    langs = ", ".join(cfg.get("languages") or []) or "the language named in contract.md"
    if role == "test-writer":
        return (f"# Task: black-box tests for module '{module}'\n\n"
                f"Language: {langs}. Read spec.md and contract.md only.\n\n"
                f"1. Write black-box tests into out/tests/ that check only the behavior in spec.md, "
                f"through the public interface in contract.md. The module under test will be importable "
                f"from the files listed below, relative to the sandbox root.\n"
                f"2. Write out/inputs.json: a JSON list of probe cases, each "
                f'{{"function": NAME, "args": [...], "kwargs": {{}}}}, covering normal, edge and error cases from spec.md. '
                f"These are used to compare old and new behavior.\n"
                f"3. Do not invent behavior that spec.md does not state.\n\n"
                f"Module files the tests will import: {', '.join(targets)}\n")
    fb = "\nfeedback.md lists which files were rejected in the previous attempt and why (scores only). Rewrite them with a different structure.\n" if has_feedback else ""
    return (f"# Task: implement module '{module}' (attempt {attempt})\n\n"
            f"Language: {langs}. Inputs: spec.md (behavior), contract.md (interface you must provide), "
            f"style.md (house style, if present), tests/ (black-box tests).\n\n"
            f"Write the implementation under out/, at these paths: {', '.join('out/' + t for t in targets)}.\n"
            f"Copy tests/ to out/tests/ unchanged and run them; iterate until they pass.\n"
            f"Write out/BUILD_NOTES.md: design decisions, anything in spec.md you found ambiguous.\n"
            f"{fb}")


def _clean_dir(p: Path):
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)


def _copy(src: Path, dst: Path):
    if src.is_symlink():
        raise Refused(f"refusing to copy symlink {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)  # copies content; never links


def prepare(state: Path, module: str, role: str, attempt: int = 1) -> dict:
    cfg = load_config(state)
    st = _gates.risk_status(state)
    if st["license"]["status"] != "open":
        raise Refused(f"license gate not open: {st['license']['reason']}")
    if not st["all_risk_open"]:
        closed = {g: v["status"] for g, v in st["gates"].items() if v["status"] != "open"}
        raise Refused(f"risk gates not open: {closed}")
    if st["allowlist"] != "open":
        raise Refused("allowlist not approved")
    spec = state / "specs" / f"{module}.md"
    ok, why = _gates.spec_approved(state, module, spec)
    if not ok:
        raise Refused(f"spec for '{module}': {why}")
    contract = state / "contracts" / f"{module}.md"
    if not contract.exists():
        raise Refused(f"interface contract missing: {contract}")
    style = state / "style.md"
    targets = module_targets(state, cfg, module)

    up = spec_filter.UpstreamFacts(Path(cfg["upstream"]), cfg["exclude"], cfg["thresholds"]["spec_verbatim_words"])
    allow = spec_filter.approved_allowlist(state)
    inputs = {"spec.md": spec, "contract.md": contract}
    if role == "builder" and style.exists():
        inputs["style.md"] = style
    for name, src in inputs.items():
        v = spec_filter.check(src.read_text(encoding="utf-8"), up, allow, cfg, "spec")
        if v:
            raise Refused(f"{name} fails spec_filter ({len(v)} violations); fix it before building")

    feedback = state / "builds" / module / f"feedback_attempt{attempt}.md"
    if role == "builder":
        tests = state / "tests" / module
        rep = read_json(state / "reports" / f"spec_filter_{module}_tests.json", {}) or {}
        if not tests.is_dir() or not any(tests.rglob("*")):
            raise Refused(f"no spec-derived tests in {tests}; run the test-writer first")
        if not rep.get("passed") or rep.get("tree_sha256") != tree_hash(tests):
            raise Refused("tests have not passed spec_filter --kind tests in their current form")
        for p in sorted(tests.rglob("*")):
            if p.is_file():
                inputs[f"tests/{p.relative_to(tests).as_posix()}"] = p
        if attempt > 1:
            if not feedback.exists():
                raise Refused(f"attempt {attempt} needs {feedback.name} from verify")
            v = spec_filter.check(feedback.read_text(encoding="utf-8"), up, allow, cfg, "spec")
            if v:
                raise Refused("feedback.md would leak upstream content; refusing")
            inputs["feedback.md"] = feedback

    sandbox = state / "sandbox" / f"{module}-{role}"
    _clean_dir(sandbox)
    (sandbox / "AGENT.md").write_text(agent_body(role), encoding="utf-8")
    (sandbox / "TASK.md").write_text(task_text(role, module, cfg, targets, attempt, "feedback.md" in inputs), encoding="utf-8")
    for name, src in inputs.items():
        _copy(src, sandbox / name)
    (sandbox / "out").mkdir()
    files, problems = snapshot(sandbox)
    if problems:
        raise Refused(f"sandbox problems: {problems}")
    approved = {"module": module, "role": role, "attempt": attempt, "created": now(), "files": files,
                "sources": {k: str(v) for k, v in inputs.items()}}
    mpath = state / "manifests" / f"{module}-{role}.approved.json"
    write_json(mpath, approved)
    provenance_log.append(state, "build" if role == "builder" else "tests", "script",
                          reads=[{"path": str(v), "sha256": sha256_file(v)} for v in inputs.values()],
                          writes=[mpath], commands=[f"sandbox_prepare.py prepare --module {module} --role {role} --attempt {attempt}"],
                          decision={"sandbox": str(sandbox), "files": len(files)})
    return {"sandbox": str(sandbox), "approved": str(mpath), "files": sorted(files)}


def tree_hash(root: Path) -> str:
    files, _ = snapshot(root)
    return provenance_log.sha256_text(json.dumps(files, sort_keys=True))


def collect(state: Path, module: str, role: str, attempt: int = 1) -> dict:
    sandbox = state / "sandbox" / f"{module}-{role}"
    out = sandbox / "out"
    if not out.is_dir():
        raise Refused("sandbox has no out/ directory")
    if role == "test-writer":
        dst = state / "tests" / module
        _clean_dir(dst)
        src_tests = out / "tests"
        if not src_tests.is_dir():
            raise Refused("test-writer produced no out/tests/")
        for p in src_tests.rglob("*"):
            if p.is_file():
                _copy(p, dst / p.relative_to(src_tests))
        if (out / "inputs.json").exists():
            _copy(out / "inputs.json", state / "fixtures" / f"{module}.inputs.json")
        cfg = load_config(state)
        up = spec_filter.UpstreamFacts(Path(cfg["upstream"]), cfg["exclude"], cfg["thresholds"]["spec_verbatim_words"])
        allow = spec_filter.approved_allowlist(state)
        viol = []
        for p in sorted(dst.rglob("*")):
            if p.is_file():
                viol += [{"file": p.relative_to(dst).as_posix(), **x} for x in spec_filter.check(p.read_text(encoding="utf-8", errors="replace"), up, allow, cfg, "tests")]
        rep = {"passed": not viol, "violations": viol, "tree_sha256": tree_hash(dst)}
        write_json(state / "reports" / f"spec_filter_{module}_tests.json", rep)
        provenance_log.append(state, "tests", "script", writes=[dst], decision={"module": module, "tests_filter_passed": rep["passed"], "violations": len(viol)})
        return {"tests": str(dst), "filter": rep}
    dst = state / "builds" / module / f"attempt-{attempt}"
    _clean_dir(dst)
    for p in out.rglob("*"):
        if p.is_file():
            _copy(p, dst / p.relative_to(out))
    provenance_log.append(state, "build", "script", writes=[{"path": str(dst), "sha256": tree_hash(dst)}],
                          decision={"module": module, "attempt": attempt, "collected": True})
    return {"build": str(dst)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("prepare", "collect"):
        p = sub.add_parser(n)
        p.add_argument("--module", required=True)
        p.add_argument("--role", required=True, choices=["test-writer", "builder"])
        p.add_argument("--attempt", type=int, default=1)
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    try:
        res = (prepare if args.cmd == "prepare" else collect)(state, args.module, args.role, args.attempt)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        provenance_log.append(state, "build" if args.role == "builder" else "tests", "script",
                              decision={"refused": str(e), "module": args.module, "role": args.role})
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
