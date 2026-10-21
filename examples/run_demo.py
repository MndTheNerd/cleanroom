#!/usr/bin/env python3
"""End-to-end run of the cleanroom pipeline on FAKE repos, with a transcript (DEMO_RUN.md).

What is real: every gate, scan, partition, spec_filter, sandbox_prepare, manifest check, fixture
capture, verify (tests + equivalence + winnowing + JPlag), swap/clean, leftover grep, ScanCode, report,
and the provenance hash chain.

What is NOT real, and labelled as such everywhere:
  - gate answers come from a script (source=demo-fixture, accepted only because config.synthetic_demo=true)
  - the test-writer and builder outputs are pre-written stand-ins dropped into the prepared sandbox's out/
    folder, because they must run inside the Docker container and this machine has no Docker.
    The pipeline's own attempt to run them is shown first, and is refused.

  run_demo.py [--dest DIR]      (default: a 'demo' folder next to the plugin)
"""
import argparse
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCRIPTS = PLUGIN / "scripts"
INPUTS = HERE / "demo_inputs"
MOD = "app-rows"

log: list[str] = []
failures: list[str] = []


def say(md: str):
    print(md)
    log.append(md)


def sh(title: str, script: str, *args, expect=None, show=40):
    cmd = [sys.executable, str(SCRIPTS / script), "--harness", str(H), *args] if script != "make_demo.py" else [sys.executable, str(HERE / script), *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
    lines = out.splitlines()
    if len(lines) > show:
        lines = lines[:show] + [f"... ({len(out.splitlines()) - show} more lines)"]
    ok = expect is None or (r.returncode in expect if isinstance(expect, (list, tuple)) else r.returncode == expect)
    mark = "" if ok else f"  **UNEXPECTED (wanted {expect})**"
    pretty = " ".join(["python", script] + [a if " " not in a else json.dumps(a) for a in args])
    say(f"\n**{title}**  \n`{pretty}` -> exit {r.returncode}{mark}\n\n```text\n" + "\n".join(lines) + "\n```")
    if not ok:
        failures.append(f"{title}: exit {r.returncode}, wanted {expect}")
        (HERE / "DEMO_RUN.md").write_text("\n".join(log) + "\n", encoding="utf-8")
        raise SystemExit(f"demo stopped at unexpected result: {failures[-1]}")
    return r


def answer(gate, ans, override=None, expect=0):
    args = ["record", "--gate", gate, "--answer", ans, "--source", "demo-fixture"]
    if override:
        args += ["--override", override]
    return sh(f"Gate '{gate}' answered (demo fixture): {ans!r}" + (f" + override {override!r}" if override else ""), "risk_gate.py", *args, expect=expect, show=12)


def standin(role: str, attempt: int, src: Path):
    """Real prepare -> stand-in output into out/ -> real manifest post-check -> real collect."""
    state = H / ".cleanroom"
    sh(f"Prepare {role} sandbox (attempt {attempt})", "sandbox_prepare.py", "prepare", "--module", MOD, "--role", role, "--attempt", str(attempt), expect=0, show=20)
    box = state / "sandbox" / f"{MOD}-{role}"
    say(f"\nSandbox contents before the run: `{sorted(p.relative_to(box).as_posix() for p in box.rglob('*') if p.is_file())}`")
    out = box / "out"
    for p in src.rglob("*"):
        if p.is_file():
            (out / p.relative_to(src)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, out / p.relative_to(src))
    if role == "builder":
        shutil.copytree(box / "tests", out / "tests", dirs_exist_ok=True)
    (out / "_log").mkdir(exist_ok=True)
    (out / "_log" / "STANDIN").write_text("Demo stand-in output. NOT produced by the isolated builder container.\n", encoding="utf-8")
    sys.path.insert(0, str(SCRIPTS))
    import provenance_log
    provenance_log.append(state, "build" if role == "builder" else "tests", "demo-standin", None,
                          decision={"module": MOD, "role": role, "attempt": attempt, "isolation": "NONE: demo stand-in, Docker unavailable"})
    r = subprocess.run([sys.executable, str(SCRIPTS / "manifest_check.py"), "--sandbox", str(box), "--approved",
                        str(state / "manifests" / f"{MOD}-{role}.approved.json"), "--phase", "post"], capture_output=True, text=True)
    say(f"\n**Manifest post-check ({role})** -> exit {r.returncode}\n\n```text\n{r.stdout.strip()}\n```")
    if r.returncode:
        failures.append(f"manifest post {role}")
    sh(f"Collect {role} output", "sandbox_prepare.py", "collect", "--module", MOD, "--role", role, "--attempt", str(attempt), expect=0, show=12)


def copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def main():
    global H
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", default=str(PLUGIN.parent / "demo"))
    args = ap.parse_args()
    dest = Path(args.dest)
    H = dest / "acme-books"
    U = dest / "quillstack"
    st = H / ".cleanroom"

    say("# Cleanroom demo run on fake repositories\n")
    say(textwrap.dedent(f"""\
        Upstream: `{U}` (fake project "quillstack", GPL-3.0). Harness: `{H}` (fake "acme-books").
        Gate answers below are **demo fixtures** (synthetic repos; `config.synthetic_demo = true`). They are not a person's answers.
        Test-writer and builder outputs are **stand-ins**: this machine has no Docker, so the pipeline refuses to run them for real (shown below).
        """))
    subprocess.run([sys.executable, str(HERE / "make_demo.py"), "--dest", str(dest)], check=True)

    say("\n## 0. Init")
    sh("Init", "run_all.py", "init", "--upstream", str(U), "--languages", "python", "--test-command", "python -m pytest -q", "--synthetic-demo", expect=0)
    cfg = json.loads((st / "config.json").read_text(encoding="utf-8"))
    cfg["test_runner"] = "host"  # no Docker here: run the builder's tests on the host (recorded in the report)
    (st / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    say("\nDemo config: `test_runner = host` (no Docker available; the report records where tests ran).")

    say("\n## 1. run-all refuses to proceed past unanswered gates")
    sh("run-all with no answers", "run_all.py", "next", "--run", expect=20)
    sh("Try to prepare a builder sandbox directly (bypassing run-all)", "sandbox_prepare.py", "prepare", "--module", MOD, "--role", "builder", expect=1)

    say("\n## 2. License gate")
    sh("Detect license", "license_gate.py", "detect", expect=0)
    sh("Record license decision (demo fixture)", "license_gate.py", "record", "--license", "GPL-3.0", "--confirmed", "yes", "--decision", "continue", "--source", "demo-fixture", expect=0)

    say("\n## 3. Risk gates")
    sh("Patent scan of upstream", "risk_gate.py", "scan-patents", expect=0)
    answer("access", "yes")
    answer("agreements", "unsure", expect=1)
    sh("run-all stops: agreements needs a typed override", "run_all.py", "next", "--run", expect=20)
    answer("agreements", "unsure", override="I accept this risk")
    answer("patents", "no", expect=1)
    answer("patents", "no", override="I accept this risk")
    answer("use", "no")
    answer("name", "QuillStack2", expect=1)
    answer("name", "Brightledger")
    answer("contamination", "yes", expect=1)
    sh("run-all stops: contamination needs the exact text", "run_all.py", "next", "--run", expect=20)
    answer("contamination", "I understand")
    answer("use", "yes")
    sh("Answer change re-opened related gates", "risk_gate.py", "status", expect=1)
    answer("patents", "no", override="I accept this risk")
    sh("License gate re-confirmed after use changed", "license_gate.py", "record", "--license", "GPL-3.0", "--confirmed", "yes", "--decision", "continue", "--source", "demo-fixture", expect=0)
    sh("All gates", "risk_gate.py", "status", expect=0)

    say("\n## 4. Scan and partition (run-all runs them, then stops for the analyzer)")
    sh("Dry-run scan writes nothing", "similarity_scan.py", "scan", "--dry-run", expect=0, show=25)
    sh("run-all", "run_all.py", "next", "--run", expect=10, show=80)

    say("\n## 5. Allowlist and spec (analyzer role; human approvals)")
    copy(INPUTS / "analyzer" / "allowlist.json", st / "allowlist.json")
    sh("run-all: allowlist needs approval", "run_all.py", "next", "--run", expect=20)
    sh("Approve allowlist with the wrong text", "risk_gate.py", "approve-allowlist", "--typed", "ok", "--source", "demo-fixture", expect=1)
    sh("Approve allowlist", "risk_gate.py", "approve-allowlist", "--typed", "approve allowlist", "--source", "demo-fixture", expect=0)
    copy(INPUTS / "analyzer" / "spec_bad.md", st / "specs" / f"{MOD}.md")
    copy(INPUTS / "analyzer" / "contract.md", st / "contracts" / f"{MOD}.md")
    copy(INPUTS / "analyzer" / "style.md", st / "style.md")
    sh("spec_filter on a deliberately bad first draft", "spec_filter.py", "check", "--spec", str(st / "specs" / f"{MOD}.md"), "--module", MOD, expect=1)
    sh("Approval is refused while the spec fails the filter", "risk_gate.py", "approve-spec", "--module", MOD, "--typed", "approve spec", "--source", "demo-fixture", expect=2)
    copy(INPUTS / "analyzer" / "spec_v1.md", st / "specs" / f"{MOD}.md")
    sh("spec_filter on the revised spec", "spec_filter.py", "check", "--spec", str(st / "specs" / f"{MOD}.md"), "--module", MOD, expect=0)
    sh("spec_filter on the contract", "spec_filter.py", "check", "--spec", str(st / "contracts" / f"{MOD}.md"), expect=0)
    sh("Human approves spec + contract", "risk_gate.py", "approve-spec", "--module", MOD, "--typed", "approve spec", "--source", "demo-fixture", expect=0)

    say("\n## 6. Tests: the real container path is refused (no Docker), then a stand-in is used")
    sh("run-all tries the test-writer container", "run_all.py", "next", "--run", expect=30)
    # No Docker: the probe can't run (exit 2). With Docker it must pass (exit 0); a failing probe is never accepted.
    sh("Isolation probe", "sandbox_run.py", "probe", expect=[0, 2], show=20)
    standin("test-writer", 1, INPUTS / "test_writer")
    sh("run-all: captures behavioral fixtures from the OLD module, then tries the builder container", "run_all.py", "next", "--run", expect=30, show=30)
    fx = json.loads((st / "fixtures" / f"{MOD}.json").read_text(encoding="utf-8"))
    say(f"\nFixture sample (data only, exception type without message): `{json.dumps(fx['results'][7])}`, `{json.dumps(fx['results'][2])}`")

    say("\n## 7. Build attempt 1 (stand-in that copies upstream) -> verify FAILS")
    standin("builder", 1, INPUTS / "builder_attempt1")
    sh("run-all runs verify", "run_all.py", "next", "--run", expect=10, show=40)
    fb = st / "builds" / MOD / "feedback_attempt2.md"
    say(f"\nFeedback handed to the builder for attempt 2 (file-level only):\n\n```markdown\n{fb.read_text(encoding='utf-8').strip()}\n```")

    say("\n## 8. Spec revised by the analyzer, re-approved, attempt 2 -> verify PASSES")
    copy(INPUTS / "analyzer" / "spec_v2.md", st / "specs" / f"{MOD}.md")
    sh("run-all re-filters the revised spec, then needs re-approval", "run_all.py", "next", "--run", expect=20)
    sh("Human re-approves (approval is tied to attempt 2)", "risk_gate.py", "approve-spec", "--module", MOD, "--typed", "approve spec", "--source", "demo-fixture", expect=0)
    sh("run-all tries the builder container for attempt 2", "run_all.py", "next", "--run", expect=30)
    standin("builder", 2, INPUTS / "builder_attempt2")
    sh("run-all: verify, then sign-off summary", "run_all.py", "next", "--run", expect=20, show=60)
    say("\nSign-off summary shown to the human:\n\n" + (st / "reports" / "signoff_summary.md").read_text(encoding="utf-8"))

    say("\n## 9. Final sign-off, swap, cleanup, leftover grep, ScanCode, report")
    sh("Swap is refused before sign-off", "swap_and_clean.py", "swap", "--module", MOD, expect=1)
    sh("Sign-off with the wrong text", "risk_gate.py", "signoff", "--typed", "approve", "--source", "demo-fixture", expect=1)
    sh("Sign-off", "risk_gate.py", "signoff", "--typed", "approve swap", "--source", "demo-fixture", expect=0)
    sh("Swap dry run (changes nothing)", "swap_and_clean.py", "swap", "--module", MOD, "--dry-run", expect=0)
    sh("Clean dry run (changes nothing)", "swap_and_clean.py", "clean", "--dry-run", expect=0)
    sh("run-all: swap, clean, then the leftover grep stops it", "run_all.py", "next", "--run", expect=30, show=120)

    say("\n## 10. Human fixes what no tool should rewrite (copied README prose, package description, config keys)")
    (H / "README.md").write_text("# Brightledger\n\nOur internal bookkeeping tool. It turns plain-text records into fields and totals,\nso the books live next to the code.\n", encoding="utf-8")
    (H / "pyproject.toml").write_text('[project]\nname = "brightledger"\ndescription = "Internal bookkeeping helpers for Acme"\n', encoding="utf-8")
    (H / "settings.toml").write_text('field_separator = ";"\nsum_field = 2\nreport_title = "Acme"\n', encoding="utf-8")
    say("\nRewrote README.md, the pyproject description and the settings.toml keys by hand (simulated).")
    sh("Leftover grep again", "swap_and_clean.py", "leftovers", expect=0)
    sh("run-all: ScanCode, report", "run_all.py", "next", "--run", expect=[0, 30], show=60)
    sh("Provenance chain", "provenance_log.py", "verify", expect=0)
    sh("Harness test suite after the swap", "run_all.py", "status", expect=0, show=20)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=H, capture_output=True, text=True)
    say(f"\n**Harness's own tests after swap** (`python -m pytest -q` in acme-books) -> exit {r.returncode}\n\n```text\n{r.stdout.strip()[-800:]}\n```")
    g = subprocess.run(["git", "status", "--short"], cwd=H, capture_output=True, text=True).stdout
    rem = subprocess.run(["git", "remote", "-v"], cwd=H, capture_output=True, text=True).stdout
    br = subprocess.run(["git", "branch", "--show-current"], cwd=H, capture_output=True, text=True).stdout
    say(f"\n**Git state of the harness:** branch `{br.strip()}`; remotes: `{rem.strip() or 'none'}`\n\n```text\n{g.strip()}\n```")
    rep = H / "CLEANROOM_REPORT.md"
    if rep.exists():
        (HERE / "sample_output").mkdir(exist_ok=True)
        shutil.copyfile(rep, HERE / "sample_output" / "CLEANROOM_REPORT.md")
    for p in ("rows.py",):
        say(f"\n**Swapped-in app/rows.py:**\n\n```python\n{(H / 'app' / p).read_text(encoding='utf-8').strip()}\n```")

    say("\n## Result\n")
    say("All steps behaved as expected." if not failures else "UNEXPECTED RESULTS:\n" + "\n".join(f"- {f}" for f in failures))
    (HERE / "DEMO_RUN.md").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
