#!/usr/bin/env python3
"""Verify one build attempt. PASS requires ALL of:
  1. spec-derived tests green
  2. behavioral equivalence with the old module's fixtures
  3. built-in winnowing: max token overlap <= verify_max_overlap, zero shared strings/comments,
     zero mentions of the upstream name
  4. JPlag (independent tool): max similarity < jplag_max_similarity. If JPlag can't run, verify FAILS.

On failure it writes builds/M/feedback_attempt{N+1}.md containing FILE-LEVEL SCORES ONLY
(never matching lines, never upstream text) and stops after max_build_attempts.

  verify_build.py --module M --attempt N [--host-tests]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CODE_EXTS, find_state_dir, iter_files, load_config, read_json, sha256_file, tools_dirs, write_json  # noqa: E402
import provenance_log  # noqa: E402
import similarity_scan  # noqa: E402

JPLAG_LANG = {".py": "python3", ".js": "javascript", ".mjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
              ".java": "java", ".c": "cpp", ".cc": "cpp", ".cpp": "cpp", ".h": "cpp", ".hpp": "cpp", ".go": "go",
              ".rs": "rust", ".cs": "csharp", ".kt": "kotlin", ".swift": "swift", ".scala": "scala"}
NON_IMPL = ("tests", "_log")


def find_tools(cfg: dict) -> tuple[str | None, str | None]:
    jar = cfg.get("jplag_jar") or os.environ.get("CLEANROOM_JPLAG_JAR")
    java = cfg.get("java") or os.environ.get("CLEANROOM_JAVA")
    for r in tools_dirs(cfg):
        if not jar and (r / "jplag.jar").exists():
            jar = str(r / "jplag.jar")
        if not java and (r / "jdk").exists():
            for exe in sorted((r / "jdk").glob("*/bin/java*")):
                if exe.stem == "java":
                    java = str(exe)
    java = java or shutil.which("java")
    return java, jar


def impl_files(build: Path, exclude: list[str]) -> list[Path]:
    return [p for p in iter_files(build, exclude + list(NON_IMPL), CODE_EXTS)]


def run_jplag(build: Path, upstream: Path, cfg: dict, work: Path) -> dict:
    java, jar = find_tools(cfg)
    if not java or not jar:
        return {"ran": False, "ok": False, "reason": "JPlag or Java not found (enable the JPlag add-on: /cleanroom:addons install jplag, or set jplag_jar and java in config)"}
    files = impl_files(build, cfg["exclude"])
    exts = {p.suffix.lower() for p in files}
    langs = {JPLAG_LANG[e] for e in exts if e in JPLAG_LANG}
    if len(langs) != 1:
        return {"ran": False, "ok": False, "reason": f"cannot pick one JPlag language for {sorted(exts)}"}
    lang = langs.pop()
    new_root, old_root = work / "new", work / "old"
    for p in files:
        dst = new_root / "candidate" / p.relative_to(build)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
    suffixes = sorted(e for e, l in JPLAG_LANG.items() if l == lang)
    n_up = 0
    for p in iter_files(upstream, cfg["exclude"], set(suffixes)):
        dst = old_root / "upstream" / p.relative_to(upstream)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        n_up += 1
    if not n_up:
        return {"ran": False, "ok": False, "reason": f"upstream has no {lang} files to compare"}
    result = work / "result"
    cmd = [java, "-jar", jar, "-l", lang, "-M", "RUN", "--old", str(old_root), "-r", str(result),
           "--csv-export", "--overwrite", "-t", str(cfg["thresholds"].get("jplag_min_tokens", 9)), "--cluster-skip", str(new_root)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    sims = []
    for csv_path in list(work.rglob("*.csv")):
        sims += _parse_csv(csv_path.read_text(encoding="utf-8", errors="replace"))
    zp = result.with_suffix(".jplag") if result.suffix != ".jplag" else result
    if not sims and zp.exists():
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if n.endswith(".csv"):
                    sims += _parse_csv(z.read(n).decode("utf-8", "replace"))
                elif n.endswith("overview.json") or n.endswith("topComparisons.json"):
                    sims += _parse_overview(json.loads(z.read(n)))
    if r.returncode != 0 and not sims:
        return {"ran": False, "ok": False, "reason": f"JPlag failed: {(r.stderr or r.stdout)[-600:]}"}
    best = max(sims, default=0.0)
    limit = cfg["thresholds"]["jplag_max_similarity"]
    return {"ran": True, "ok": best < limit, "max_similarity": round(best, 3), "limit": limit, "language": lang,
            "command": " ".join(cmd[:3] + ["..."])}


def _parse_csv(text: str) -> list[float]:
    out = []
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return out
    hdr = [h.strip().lower() for h in rows[0]]
    idx = [i for i, h in enumerate(hdr) if "similarity" in h and ("max" in h or "average" in h or h == "similarity")]
    for row in rows[1:]:
        for i in idx:
            try:
                v = float(row[i])
                out.append(v / 100 if v > 1 else v)
            except (ValueError, IndexError):
                pass
    return out


def _parse_overview(o) -> list[float]:
    out = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, (int, float)) and k.upper() in ("MAX", "AVG", "MAXIMUM_SIMILARITY"):
                    out.append(v / 100 if v > 1 else v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(o)
    return out


def run_tests(build: Path, cfg: dict, module: str, host: bool) -> dict:
    cmd = ((cfg.get("modules") or {}).get(module) or {}).get("test_command") or cfg.get("module_test_command") or f"{sys.executable} -m pytest -q tests"
    if not (build / "tests").is_dir():
        return {"ok": False, "reason": "build has no tests/ directory", "command": cmd}
    if not host:
        import sandbox_run
        ok, info = sandbox_run.docker_ok()
        if not ok:
            return {"ok": False, "reason": f"container test runner unavailable ({info}); rerun with --host-tests to accept running builder code on this machine", "command": cmd}
        box = build.parents[2] / "sandbox" / f"{module}-tests"
        if box.exists():
            shutil.rmtree(box)
        shutil.copytree(build, box, ignore=shutil.ignore_patterns(*cfg["exclude"]))
        ccmd = ((cfg.get("modules") or {}).get(module) or {}).get("test_command") or cfg.get("module_test_command") or "python3 -m pytest -q tests"
        r = sandbox_run.compose({"CLEANROOM_SANDBOX": str(box.resolve()), "CLEANROOM_TEST_CMD": ccmd}, "run", "--rm", "-e", "CLEANROOM_TEST_CMD", "builder", "run-tests", timeout=900)
        tail = r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else []
        return {"ok": r.returncode == 0, "exit_code": r.returncode, "summary": tail[0] if tail else "", "command": ccmd, "where": "container"}
    # Run on a throwaway copy so caches and test artifacts never land in the accepted build.
    with tempfile.TemporaryDirectory(prefix="cleanroom-tests-") as tmp:
        work = Path(tmp) / "build"
        shutil.copytree(build, work)
        r = subprocess.run(cmd, shell=True, cwd=work, capture_output=True, text=True, timeout=900,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    text = r.stdout.strip() or r.stderr.strip()
    tail = text.splitlines()[-1:] if text else []
    return {"ok": r.returncode == 0, "exit_code": r.returncode, "summary": tail[0] if tail else "", "command": cmd, "where": "host"}


def baseline(state: Path, cfg: dict, module: str, upstream: Path) -> dict:
    """'Before' scores of the OLD module from both tools, computed once, for the report."""
    out = state / "reports" / f"baseline_{module}.json"
    if out.exists():
        return read_json(out)
    harness = Path(cfg.get("harness") or state.parent)
    part = read_json(state / "reports" / "partition.json", {}) or {}
    files = list((part.get("modules", {}).get(module) or {}).get("files", {}))
    with tempfile.TemporaryDirectory(prefix="cleanroom-base-") as tmp:
        old = Path(tmp) / "old"
        for f in files:
            if (harness / f).exists():
                (old / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(harness / f, old / f)
        if not old.exists():
            return {}
        sim = similarity_scan.compare_target(old, upstream, cfg)
        jw = Path(tmp) / "jp"
        jw.mkdir()
        jp = run_jplag(old, upstream, cfg, jw)
    res = {"module": module, "winnowing_max": max((s["token_overlap"] for s in sim), default=0.0),
           "jplag_max": jp.get("max_similarity"), "jplag_ran": jp.get("ran"), "files": sim}
    write_json(out, res)
    return res


def feedback(module: str, attempt: int, sim: list[dict], jp: dict, tests: dict, eq: dict, limit: float) -> str:
    L = [f"# Feedback for attempt {attempt + 1} of module '{module}'", "",
         "File-level results from the previous attempt. No source lines are shared by design.", ""]
    for s in sim:
        flags = []
        if s["token_overlap"] > limit:
            flags.append(f"too similar to upstream: score {s['token_overlap']:.2f} (limit {limit:.2f})")
        if s["shared_strings"]:
            flags.append(f"{s['shared_strings']} string literal(s) match upstream; write your own wording")
        if s["shared_comments"]:
            flags.append(f"{s['shared_comments']} comment(s) match upstream; write your own comments")
        if s["upstream_name_mentions"]:
            flags.append("mentions a forbidden project name")
        if flags:
            L.append(f"- {s['file']}: " + "; ".join(flags) + ". Restructure this file (different decomposition, control flow and naming).")
    if jp.get("ran") and not jp.get("ok"):
        L.append(f"- Second similarity tool: module score {jp['max_similarity']:.2f} (limit {jp['limit']:.2f}). Restructure the module.")
    if not tests.get("ok"):
        L.append(f"- Tests: not all passing ({tests.get('summary') or tests.get('reason', '')}).")
    if eq and not eq.get("passed"):
        L.append(f"- Behavior: {eq.get('mismatches')} of {eq.get('cases')} probe cases differ from the expected behavior. "
                 "The spec may be revised to clarify; re-read spec.md.")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    ap.add_argument("--module", required=True)
    ap.add_argument("--attempt", type=int, required=True)
    ap.add_argument("--host-tests", action="store_true", help="run the builder's tests on this machine (no container)")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = load_config(state)
    t = cfg["thresholds"]
    build = state / "builds" / args.module / f"attempt-{args.attempt}"
    if not build.is_dir():
        print(f"ERROR: no build at {build}", file=sys.stderr)
        return 2
    upstream = Path(cfg["upstream"])

    tests = run_tests(build, cfg, args.module, args.host_tests or cfg.get("test_runner") == "host")
    eq_cmd = subprocess.run([sys.executable, str(Path(__file__).parent / "equivalence_run.py"), "--harness", str(state.parent),
                             "compare", "--module", args.module, "--attempt", str(args.attempt)], capture_output=True, text=True)
    eq = read_json(state / "reports" / f"equivalence_{args.module}_attempt{args.attempt}.json", {}) or {"passed": False, "reason": eq_cmd.stderr.strip()}
    impl_dir = Path(tempfile.mkdtemp(prefix="cleanroom-impl-"))
    try:
        for p in impl_files(build, cfg["exclude"]):
            dst = impl_dir / p.relative_to(build)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
        sim = similarity_scan.compare_target(impl_dir, upstream, cfg)
    finally:
        shutil.rmtree(impl_dir, ignore_errors=True)
    builtin_ok = bool(sim) and all(s["token_overlap"] <= t["verify_max_overlap"] and s["max_function_overlap"] <= max(t["verify_max_overlap"] * 2, 0.3)
                                   and not s["shared_strings"] and not s["shared_comments"] and not s["upstream_name_mentions"] for s in sim)
    with tempfile.TemporaryDirectory(prefix="cleanroom-jplag-") as w:
        jp = run_jplag(build, upstream, cfg, Path(w))
    baseline(state, cfg, args.module, upstream)
    passed = tests["ok"] and eq.get("passed", False) and builtin_ok and jp["ok"]
    rep = {"module": args.module, "attempt": args.attempt, "passed": passed,
           "tests": tests, "equivalence": {k: eq.get(k) for k in ("passed", "cases", "mismatches", "reason") if k in eq},
           "builtin_similarity": {"ok": builtin_ok, "limit": t["verify_max_overlap"], "files": sim},
           "jplag": jp,
           "build_hashes": {p.relative_to(build).as_posix(): sha256_file(p) for p in build.rglob("*") if p.is_file()}}
    out = state / "reports" / f"verify_{args.module}_attempt{args.attempt}.json"
    write_json(out, rep)
    if passed:
        write_json(state / "builds" / args.module / "accepted.json", {"attempt": args.attempt, "report": str(out), "hashes": rep["build_hashes"]})
    else:
        fb = state / "builds" / args.module / f"feedback_attempt{args.attempt + 1}.md"
        fb.write_text(feedback(args.module, args.attempt, sim, jp, tests, eq, t["verify_max_overlap"]), encoding="utf-8")
    provenance_log.append(state, "verify", "script", reads=[{"path": str(build), "sha256": None}], writes=[out],
                          commands=["verify_build.py", tests.get("command", "")],
                          decision={"module": args.module, "attempt": args.attempt, "passed": passed, "tests": tests["ok"],
                                    "equivalence": eq.get("passed"), "builtin_ok": builtin_ok,
                                    "builtin_max_overlap": max((s["token_overlap"] for s in sim), default=None),
                                    "jplag_ok": jp["ok"], "jplag_max": jp.get("max_similarity"), "jplag_reason": jp.get("reason")})
    print(f"tests        {'PASS' if tests['ok'] else 'FAIL'}  {tests.get('summary') or tests.get('reason', '')}")
    print(f"equivalence  {'PASS' if eq.get('passed') else 'FAIL'}  {eq.get('cases', 0) - (eq.get('mismatches') or 0)}/{eq.get('cases', 0)} cases")
    for s in sim:
        print(f"winnowing    {'PASS' if s['token_overlap'] <= t['verify_max_overlap'] else 'FAIL'}  {s['file']}: {s['token_overlap']:.0%} (limit {t['verify_max_overlap']:.0%}), "
              f"strings {s['shared_strings']}, comments {s['shared_comments']}, name {s['upstream_name_mentions']}")
    print(f"jplag        {'PASS' if jp['ok'] else 'FAIL'}  " + (f"max {jp['max_similarity']:.0%} (limit {jp['limit']:.0%})" if jp.get("ran") else jp.get("reason", "")))
    print("VERIFY PASSED" if passed else f"VERIFY FAILED (attempt {args.attempt} of {cfg['max_build_attempts']})")
    if not passed and args.attempt >= cfg["max_build_attempts"]:
        print("Maximum attempts reached: stop and report. Do not build again without revising the spec and resetting attempts.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
