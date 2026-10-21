#!/usr/bin/env python3
"""Pipeline orchestrator. Decides the next stage, runs deterministic stages, and STOPS at every
gate a human must answer, every step an agent must do, and every failure.

  run_all.py init --harness H --upstream U --languages python --test-command "pytest -q" [--upstream-name N]
  run_all.py status                 table of stages and gates
  run_all.py next [--run] [--json]  what happens next; with --run, execute script stages until blocked
  run_all.py summary                one-screen sign-off summary (reports/signoff_summary.md)

Exit codes for `next`: 0 all done | 10 needs an agent | 20 needs a human answer | 30 stopped/failed
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, STATE_DIRNAME, find_state_dir, load_config, now, read_json, run, sha256_file, write_json  # noqa: E402
import _gates  # noqa: E402
import provenance_log  # noqa: E402

HERE = Path(__file__).resolve().parent
DONE, AGENT, HUMAN, STOP = 0, 10, 20, 30


def sh(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)


# ---------------------------------------------------------------- init
def init(harness: Path, upstream: Path, languages: list[str], test_command: str, upstream_name: str | None,
         analyzer_model: str | None, builder_model: str | None, synthetic_demo: bool = False,
         tools_dir: str | None = None, builder_auth: str | None = None) -> Path:
    harness, upstream = harness.resolve(), upstream.resolve()
    if not harness.is_dir() or not upstream.is_dir():
        raise SystemExit("ERROR: harness and upstream must both be existing directories")
    if harness == upstream or harness in upstream.parents or upstream in harness.parents:
        raise SystemExit("ERROR: harness and upstream must not contain each other")
    state = harness / STATE_DIRNAME
    if (state / "config.json").exists():
        raise SystemExit(f"ERROR: already initialized ({state / 'config.json'})")
    name = upstream_name or _detect_name(upstream)
    cfg = {k: v for k, v in DEFAULT_CONFIG.items() if k != "thresholds"}
    cfg.update({"harness": str(harness), "upstream": str(upstream), "languages": languages, "test_command": test_command,
                "upstream_name": name, "thresholds": DEFAULT_CONFIG["thresholds"], "created": now(),
                "synthetic_demo": synthetic_demo})
    if analyzer_model:
        cfg["analyzer_model"] = analyzer_model
    if builder_model:
        cfg["builder_model"] = builder_model
        cfg["test_writer_model"] = builder_model
    if cfg["builder_model"] == cfg["analyzer_model"]:
        raise SystemExit(f"ERROR: analyzer and builder models must differ (both '{cfg['builder_model']}'); change them in the plugin options")
    if tools_dir and "${" not in tools_dir:
        cfg["tools_dir"] = tools_dir
    cfg["builder_auth"] = builder_auth if builder_auth in ("subscription", "api_key") else "subscription"
    write_json(state / "config.json", cfg)
    (state / ".gitignore").write_text("sandbox/\nbackup/\n*.lock\n*.tmp\n", encoding="utf-8")
    branch = None
    if run(["git", "rev-parse", "--is-inside-work-tree"], cwd=harness).returncode == 0:
        cur = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=harness).stdout.strip()
        if cur in ("main", "master", "trunk", "develop", "HEAD"):
            branch = f"cleanroom/{now()[:10]}"
            r = run(["git", "checkout", "-b", branch], cwd=harness)
            if r.returncode != 0:
                branch = f"(could not create branch: {r.stderr.strip()})"
        else:
            branch = cur
    provenance_log.append(state, "init", "script", reads=[], writes=[state / "config.json"],
                          commands=["run_all.py init"], decision={"harness": str(harness), "upstream": str(upstream),
                                                                  "upstream_name": name, "branch": branch, "synthetic_demo": synthetic_demo})
    return state


def _detect_name(upstream: Path) -> str:
    pj = upstream / "package.json"
    if pj.exists():
        try:
            n = json.loads(pj.read_text(encoding="utf-8")).get("name")
            if n:
                return n.split("/")[-1]
        except json.JSONDecodeError:
            pass
    for meta in ("pyproject.toml", "setup.cfg", "setup.py", "Cargo.toml"):
        p = upstream / meta
        if p.exists():
            m = re.search(r"""^\s*name\s*[=:]\s*["']?([\w.\-]+)""", p.read_text(encoding="utf-8", errors="replace"), re.M)
            if m:
                return m.group(1)
    return upstream.name


# ---------------------------------------------------------------- stage engine
def modules_to_replace(state: Path, cfg: dict) -> list[str]:
    part = read_json(state / "reports" / "partition.json", {}) or {}
    labels = ("tainted", "mixed") if cfg.get("replace_mixed") else ("tainted",)
    return sorted(m for m, info in part.get("modules", {}).items()
                  if info["label"] in labels or (info["label"] == "vendored" and info["dependents"]))


def latest_attempt(state: Path, m: str) -> int:
    d = state / "builds" / m
    nums = [int(p.name.split("-")[1]) for p in d.glob("attempt-*") if p.is_dir()] if d.exists() else []
    return max(nums, default=0)


def next_step(state: Path) -> dict:
    """Pure decision function: returns {code, stage, action, detail, [module], [run]}."""
    cfg = load_config(state)
    st = _gates.risk_status(state)
    d = _gates.load(state)
    rep = state / "reports"

    if st["license"]["status"] == "stopped":
        return {"code": STOP, "stage": "license", "detail": "You chose to stop at the license gate."}
    if st["license"]["status"] != "open":
        return {"code": HUMAN, "stage": "license", "action": "ask",
                "detail": f"License gate {st['license']['status']}: {st['license']['reason']}. Run license_gate.py detect, explain, and ask the user."}
    if st["hard_stop"]:
        return {"code": STOP, "stage": "risks", "detail": "HARD STOP: upstream access was not confirmed as legitimate."}
    for gid in _gates.ORDER:
        g = st["gates"][gid]
        if g["status"] != "open":
            return {"code": HUMAN, "stage": "risks", "action": "ask", "gate": gid,
                    "detail": f"Risk gate '{gid}' is {g['status']} ({g['reason']}). Ask the user: {_gates.QUESTIONS[gid]['q']}"}

    if not (rep / "scan.json").exists():
        return {"code": DONE, "stage": "scan", "run": ["similarity_scan.py", "scan"]}
    if not (rep / "partition.json").exists():
        return {"code": DONE, "stage": "partition", "run": ["partition.py"]}
    mods = modules_to_replace(state, cfg)
    if not (state / "allowlist.json").exists():
        return {"code": AGENT, "stage": "allowlist", "action": "agent:analyzer",
                "detail": "Analyzer proposes allowlist.json: names needed for compatibility (public API, wire protocols, file formats)."}
    if st["allowlist"] != "open" or (d.get("allowlist") or {}).get("sha256") != sha256_file(state / "allowlist.json"):
        return {"code": HUMAN, "stage": "allowlist", "action": "ask",
                "detail": f"Show allowlist.json to the user; they must type '{_gates.ALLOWLIST_APPROVE}'."}

    for m in mods:
        spec = state / "specs" / f"{m}.md"
        contract = state / "contracts" / f"{m}.md"
        if not spec.exists() or not contract.exists():
            return {"code": AGENT, "stage": "spec", "module": m, "action": "agent:analyzer",
                    "detail": f"Analyzer writes specs/{m}.md and contracts/{m}.md (behavior and interface only)."}
        fr = read_json(rep / f"spec_filter_{m}.json", {}) or {}
        if fr.get("sha256") != sha256_file(spec):
            return {"code": DONE, "stage": "spec", "module": m, "run": ["spec_filter.py", "check", "--spec", str(spec), "--module", m]}
        if not fr.get("passed"):
            return {"code": AGENT, "stage": "spec", "module": m, "action": "agent:analyzer",
                    "detail": f"spec_filter rejected specs/{m}.md ({len(fr.get('violations', []))} violations). Analyzer revises it."}
        ok, why = _gates.spec_approved(state, m, spec)
        if not ok:
            return {"code": HUMAN, "stage": "spec", "module": m, "action": "ask",
                    "detail": f"Spec review for '{m}': {why}. Show the spec and contract; the user must type '{_gates.SPEC_APPROVE}'."}

    for m in mods:
        tr = read_json(rep / f"spec_filter_{m}_tests.json", {}) or {}
        if not (state / "tests" / m).is_dir():
            return {"code": DONE, "stage": "tests", "module": m, "run": ["sandbox_run.py", "run", "--module", m, "--role", "test-writer"]}
        if not tr.get("passed"):
            return {"code": STOP, "stage": "tests", "module": m,
                    "detail": "Spec-derived tests leak upstream content (spec_filter --kind tests failed). Revise the spec, re-approve, and regenerate tests."}
        if not (state / "fixtures" / f"{m}.json").exists():
            return {"code": DONE, "stage": "tests", "module": m, "run": ["equivalence_run.py", "capture", "--module", m]}

    for m in mods:
        if (state / "builds" / m / "accepted.json").exists():
            continue
        n = latest_attempt(state, m)
        if n == 0:
            return {"code": DONE, "stage": "build", "module": m, "run": ["sandbox_run.py", "run", "--module", m, "--role", "builder", "--attempt", "1"]}
        vr = read_json(rep / f"verify_{m}_attempt{n}.json")
        if vr is None:
            return {"code": DONE, "stage": "verify", "module": m, "run": ["verify_build.py", "--module", m, "--attempt", str(n)]}
        if vr["passed"]:
            continue
        if n >= cfg["max_build_attempts"]:
            return {"code": STOP, "stage": "verify", "module": m,
                    "detail": f"Module '{m}' failed verification {n} times (max {cfg['max_build_attempts']}). Stopping. See reports/verify_{m}_attempt{n}.json."}
        # A rebuild needs a spec revised and re-approved after this failure (approval records its attempt).
        if d["spec_approvals"].get(m, {}).get("for_attempt") != n + 1:
            return {"code": AGENT, "stage": "verify", "module": m, "action": "agent:analyzer",
                    "detail": f"Attempt {n} failed. Analyzer revises specs/{m}.md (never pass code or diffs to the builder); "
                              f"then the user re-approves it for attempt {n + 1}."}
        return {"code": DONE, "stage": "build", "module": m,
                "run": ["sandbox_run.py", "run", "--module", m, "--role", "builder", "--attempt", str(n + 1)]}

    summ = rep / "signoff_summary.md"
    if not summ.exists() or (d.get("signoff") or {}).get("status") == "stale":
        return {"code": DONE, "stage": "signoff", "run": ["run_all.py", "summary"]}
    s = d.get("signoff") or {}
    if s.get("status") != "open" or s.get("summary_sha256") != sha256_file(summ):
        return {"code": HUMAN, "stage": "signoff", "action": "ask",
                "detail": f"Show reports/signoff_summary.md; the user must type '{_gates.SIGNOFF}'."}
    for m in mods:
        if not (state / "reports" / f"swapped_{m}.json").exists():
            return {"code": DONE, "stage": "swap", "module": m, "run": ["swap_and_clean.py", "swap", "--module", m]}
    if not (rep / "clean_done.json").exists():
        return {"code": DONE, "stage": "swap", "run": ["swap_and_clean.py", "clean"]}
    lo = read_json(rep / "leftovers.json")
    if lo is None:
        return {"code": DONE, "stage": "swap", "run": ["swap_and_clean.py", "leftovers"]}
    if not lo["clean"]:
        return {"code": STOP, "stage": "swap", "detail": "Upstream leftovers remain after clean (reports/leftovers.json). Fix them by hand or re-run the affected modules."}
    fl = read_json(rep / "final_license_scan.json")
    if fl is None:
        return {"code": DONE, "stage": "swap", "run": ["final_license_scan.py"]}
    if not fl.get("passed"):
        return {"code": STOP, "stage": "swap", "detail": f"Final license scan failed: {fl.get('reason') or str(len(fl.get('issues', []))) + ' issue(s)'}."}
    if not (Path(cfg["harness"]) / "CLEANROOM_REPORT.md").exists():
        return {"code": DONE, "stage": "report", "run": ["report.py"]}
    return {"code": DONE, "stage": "done", "detail": "Pipeline complete. Optional: fresh-history (separate confirmed step)."}


def execute(state: Path, step: dict) -> tuple[int, str]:
    script, *args = step["run"]
    if script == "run_all.py" and args == ["summary"]:
        write_summary(state)
        return 0, "summary written"
    r = sh(script, "--harness", str(state.parent), *args)
    out = (r.stdout + r.stderr).strip()
    if r.returncode == 0:
        if script == "swap_and_clean.py" and args[0] == "swap":
            write_json(state / "reports" / f"swapped_{args[2]}.json", {"ts": now(), "output": out[-4000:]})
        if script == "swap_and_clean.py" and args[0] == "clean":
            write_json(state / "reports" / "clean_done.json", {"ts": now(), "output": out[-8000:]})
    return r.returncode, out


# ---------------------------------------------------------------- summary
def write_summary(state: Path) -> Path:
    cfg = load_config(state)
    d = _gates.load(state)
    rep = state / "reports"
    part = read_json(rep / "partition.json", {}) or {}
    L = ["# Clean-room sign-off summary", ""]
    lic = d.get("license") or {}
    L.append(f"**License:** {lic.get('confirmed_license')} ({lic.get('category')}), decision: {lic.get('decision')}")
    L.append("")
    L.append("**Risk decisions**")
    for gid in _gates.ORDER:
        g = d["gates"].get(gid) or {}
        ov = f" OVERRIDE: \"{g['override']}\"" if g.get("override") else ""
        L.append(f"- {gid}: {g.get('answer')!r} -> {g.get('status')}{ov} [{g.get('source')}]")
    L += ["", "| Module | Before (winnowing) | After (winnowing) | After (JPlag) | Tests | Equivalence | Result |", "|---|---|---|---|---|---|---|"]
    for m in modules_to_replace(state, cfg):
        n = latest_attempt(state, m)
        v = read_json(rep / f"verify_{m}_attempt{n}.json", {}) or {}
        before = max((f["token_overlap"] or 0 for f in part["modules"][m]["files"].values()), default=0)
        after = max((f["token_overlap"] for f in (v.get("builtin_similarity") or {}).get("files", [])), default=None)
        jp = (v.get("jplag") or {})
        L.append(f"| {m} | {before:.0%} | {'-' if after is None else format(after, '.0%')} | "
                 f"{format(jp['max_similarity'], '.0%') if jp.get('ran') else 'not run'} | {'pass' if (v.get('tests') or {}).get('ok') else 'FAIL'} | "
                 f"{'pass' if (v.get('equivalence') or {}).get('passed') else 'FAIL'} | {'PASSED' if v.get('passed') else 'FAILED'} (attempt {n}) |")
    mixed = [m for m, i in part.get("modules", {}).items() if i["label"] == "mixed"]
    if mixed:
        L += ["", f"**Flagged as mixed (not replaced, needs your review):** {', '.join(mixed)}"]
    demo = [k for k, g in d["gates"].items() if g.get("source") == "demo-fixture"]
    if demo:
        L += ["", "**WARNING: gates answered by demo fixture (synthetic test run, not a human):** " + ", ".join(demo)]
    standin = [m for m in modules_to_replace(state, cfg) if (state / "builds" / m / f"attempt-{latest_attempt(state, m)}" / "_log" / "STANDIN").exists()]
    if standin:
        L += ["", "**WARNING: build produced by a demo stand-in, NOT the isolated builder:** " + ", ".join(standin)]
    L += ["", "Next: swap replaces the modules, deletes tainted files, removes upstream remotes, vendored copies,",
          "license headers and the upstream name, then runs leftover and ScanCode checks.",
          "Git history will still contain upstream code (fresh history is a separate step).", "",
          f"Type exactly: **{_gates.SIGNOFF}**"]
    p = rep / "signoff_summary.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    provenance_log.append(state, "signoff", "script", writes=[p], note="sign-off summary generated")
    return p


def status(state: Path) -> int:
    subprocess.run([sys.executable, str(HERE / "risk_gate.py"), "--harness", str(state.parent), "status"])
    step = next_step(state)
    print(f"\nnext: [{step['stage']}] {step.get('detail') or ' '.join(step.get('run', []))}")
    ok, problems = provenance_log.verify(state)
    print("provenance chain OK" if ok else "PROVENANCE CHAIN BROKEN: " + "; ".join(problems))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--upstream", required=True)
    i.add_argument("--languages", required=True, help="comma-separated, e.g. python,typescript")
    i.add_argument("--test-command", required=True)
    i.add_argument("--upstream-name")
    i.add_argument("--analyzer-model")
    i.add_argument("--builder-model")
    i.add_argument("--builder-auth", choices=["subscription", "api_key"], help="builder credential type (default subscription)")
    i.add_argument("--tools-dir", help="where the add-ons are installed (the plugin passes ${CLAUDE_PLUGIN_DATA}/tools)")
    i.add_argument("--synthetic-demo", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("status")
    n = sub.add_parser("next")
    n.add_argument("--run", action="store_true")
    n.add_argument("--json", action="store_true")
    n.add_argument("--max-steps", type=int, default=50)
    sub.add_parser("summary")
    args = ap.parse_args(argv)
    if args.cmd == "init":
        state = init(Path(args.harness or "."), Path(args.upstream), [x.strip() for x in args.languages.split(",") if x.strip()],
                     args.test_command, args.upstream_name, args.analyzer_model, args.builder_model, args.synthetic_demo,
                     args.tools_dir, args.builder_auth)
        print(f"initialized {state}")
        return 0
    state = find_state_dir(Path(args.harness) if args.harness else None)
    if not (state / "config.json").exists():
        print("ERROR: not initialized; run /cleanroom:init", file=sys.stderr)
        return 2
    ok, problems = provenance_log.verify(state)
    if not ok:
        print("STOP: provenance log tampered or corrupted:\n  " + "\n  ".join(problems), file=sys.stderr)
        return STOP
    if args.cmd == "status":
        return status(state)
    if args.cmd == "summary":
        print(write_summary(state).read_text(encoding="utf-8"))
        return 0
    steps = 0
    while True:
        step = next_step(state)
        if not (args.run and step["code"] == DONE and step.get("run")):
            break
        code, out = execute(state, step)
        print(f"== [{step['stage']}] {' '.join(step['run'])} -> exit {code}\n{out[-3000:]}\n")
        provenance_log.commit(state, step["stage"])
        steps += 1
        if code != 0:
            nxt = next_step(state)
            if nxt.get("run") == step["run"]:
                step = {"code": STOP, "stage": step["stage"], "detail": f"{step['run'][0]} failed (exit {code}); stopping.", "output": out[-3000:]}
                break
        if steps >= args.max_steps:
            break
    if args.json:
        print(json.dumps(step, indent=2))
    else:
        label = {DONE: "DONE" if not step.get("run") else "READY", AGENT: "NEEDS AGENT", HUMAN: "NEEDS YOUR ANSWER", STOP: "STOPPED"}[step["code"]]
        print(f"{label}: [{step['stage']}{'/' + step['module'] if step.get('module') else ''}] {step.get('detail') or ' '.join(step.get('run', []))}")
    return step["code"]


if __name__ == "__main__":
    sys.exit(main())
