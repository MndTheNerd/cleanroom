#!/usr/bin/env python3
"""Run the test-writer or builder inside the isolated container, with manifest checks around it.

  sandbox_run.py probe                                   isolation self-test (no model call)
  sandbox_run.py run --module M --role test-writer|builder [--attempt N]

Requires: Docker with compose v2; a builder credential that is NOT the host's own, either
  CLEANROOM_BUILDER_OAUTH_TOKEN  a Claude subscription token from `claude setup-token` (Pro/Max/Team/Enterprise), or
  CLEANROOM_BUILDER_API_KEY      an Anthropic API key;
and a builder model that differs from the analyzer model (config: builder_model / analyzer_model).
Config "builder_auth" ("subscription" or "api_key") picks one when both are set.

Sequence for run: sandbox_prepare (copy approved inputs) -> manifest pre-check -> docker compose run
-> manifest post-check -> collect outputs -> provenance (tool-call log + hashes).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CODE_EXTS, PLUGIN_ROOT, find_state_dir, iter_files, load_config, read_json, run, write_json  # noqa: E402
import manifest_check  # noqa: E402
import provenance_log  # noqa: E402
import sandbox_prepare  # noqa: E402

COMPOSE = PLUGIN_ROOT / "docker" / "compose.yaml"


def docker_ok() -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "docker is not installed or not on PATH"
    r = run(["docker", "compose", "version"])
    if r.returncode != 0:
        return False, "docker compose v2 is not available: " + (r.stderr or r.stdout).strip()
    r = run(["docker", "info", "--format", "{{.ServerVersion}}"])
    if r.returncode != 0:
        return False, "docker daemon is not running: " + (r.stderr or r.stdout).strip()[:200]
    return True, r.stdout.strip()


def canaries(upstream: Path, exclude: list[str], n: int = 12) -> list[str]:
    """Distinctive lines taken from upstream files: if any appears inside the container, isolation failed."""
    lines = []
    for p in iter_files(upstream, exclude, CODE_EXTS):
        for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = l.strip()
            if 30 <= len(s) <= 120 and sum(c.isalpha() for c in s) > 15:
                lines.append(s)
    random.Random(7).shuffle(lines)
    return lines[:n]


def compose(env_extra: dict, *args, timeout: int = 3600):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "HOME",
                                                         "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "APPDATA", "LOCALAPPDATA",
                                                         "ProgramData", "ProgramFiles", "COMSPEC", "PATHEXT")}
    env.update(env_extra)
    return run(["docker", "compose", "-f", str(COMPOSE), *args], env=env, timeout=timeout)


def teardown(env: dict) -> str:
    """Capture the egress proxy's log (what it allowed/denied), then stop and remove the containers."""
    log = compose(env, "logs", "--no-color", "--tail", "60", "proxy", timeout=120)
    compose(env, "down", "--remove-orphans", timeout=300)
    return (log.stdout + log.stderr)[-4000:]


def probe(state: Path) -> int:
    ok, info = docker_ok()
    if not ok:
        print(f"CANNOT RUN PROBE: {info}", file=sys.stderr)
        provenance_log.append(state, "probe", "script", decision={"ok": False, "reason": info})
        return 2
    cfg = load_config(state)
    sandbox = state / "sandbox" / "_probe"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    (sandbox / "out").mkdir(parents=True)
    (sandbox / "README.txt").write_text("isolation probe sandbox\n", encoding="utf-8")
    cans = canaries(Path(cfg["upstream"]), cfg["exclude"])
    env = {"CLEANROOM_SANDBOX": str(sandbox.resolve()), "CLEANROOM_CANARIES": "\n".join(cans)}
    try:
        r = compose(env, "run", "--rm", "--build", "builder", "probe", timeout=1800)
    finally:
        proxy_log = teardown(env)
    checks = [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")]
    result = {"ok": r.returncode == 0 and bool(checks) and all(c["ok"] for c in checks), "checks": checks,
              "docker": info, "stderr_tail": r.stderr[-1500:], "proxy_log_tail": proxy_log}
    write_json(state / "reports" / "isolation_probe.json", result)
    provenance_log.append(state, "probe", "script", commands=["docker compose run --rm builder probe"],
                          decision={"ok": result["ok"], "failed": [c["check"] for c in checks if not c["ok"]]})
    for c in checks:
        print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['check']:<26} {c['detail']}")
    print("ISOLATION OK" if result["ok"] else "ISOLATION FAILED")
    return 0 if result["ok"] else 1


def builder_credential(cfg: dict, env: dict | None = None) -> tuple[str, dict]:
    """Pick the builder's credential. Returns (mode, env vars for compose). Never the host's own credential."""
    env = os.environ if env is None else env
    token, key = env.get("CLEANROOM_BUILDER_OAUTH_TOKEN"), env.get("CLEANROOM_BUILDER_API_KEY")
    pref = cfg.get("builder_auth") or "subscription"
    if pref not in ("subscription", "api_key"):
        raise ValueError("config builder_auth must be 'subscription' or 'api_key'")
    if token and (pref == "subscription" or not key):
        if token == env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            raise ValueError("CLEANROOM_BUILDER_OAUTH_TOKEN must be a separate token from the host's CLAUDE_CODE_OAUTH_TOKEN; "
                             "run `claude setup-token` again to mint one for the builder")
        return "subscription", {"CLEANROOM_BUILDER_OAUTH_TOKEN": token}
    if key:
        if key == env.get("ANTHROPIC_API_KEY"):
            raise ValueError("CLEANROOM_BUILDER_API_KEY must differ from the host's ANTHROPIC_API_KEY")
        return "api_key", {"CLEANROOM_BUILDER_API_KEY": key}
    raise ValueError("no builder credential. With a Claude subscription: run `claude setup-token` and set "
                     "CLEANROOM_BUILDER_OAUTH_TOKEN to the printed token. Or set CLEANROOM_BUILDER_API_KEY to an API key.")


def run_role(state: Path, module: str, role: str, attempt: int) -> int:
    cfg = load_config(state)
    ok, info = docker_ok()
    if not ok:
        print(f"REFUSED: {info}. The builder only runs inside the isolated container.", file=sys.stderr)
        provenance_log.append(state, "build", "script", decision={"refused": info, "module": module, "role": role})
        return 2
    try:
        auth_mode, cred_env = builder_credential(cfg)
    except ValueError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    model = cfg["builder_model"] if role == "builder" else cfg["test_writer_model"]
    if model == cfg["analyzer_model"] and not cfg.get("allow_same_model"):
        print(f"REFUSED: {role} model '{model}' equals the analyzer model; set a different one in config", file=sys.stderr)
        return 2
    prep = sandbox_prepare.prepare(state, module, role, attempt)
    sandbox, approved_path = Path(prep["sandbox"]), Path(prep["approved"])
    approved = read_json(approved_path)
    pre = manifest_check.check(sandbox, approved, "pre")
    write_json(state / "manifests" / f"{module}-{role}.pre.json", pre)
    if not pre["ok"]:
        print("ABORT: manifest pre-check failed:\n  " + "\n  ".join(pre["problems"]), file=sys.stderr)
        provenance_log.append(state, "build", "script", decision={"abort": "manifest pre-check", "problems": pre["problems"]})
        return 1
    run_env = {"CLEANROOM_SANDBOX": str(sandbox.resolve()), "CLEANROOM_MODEL": model, **cred_env}
    try:
        r = compose(run_env, "run", "--rm", "--build", "builder", role)
    finally:
        proxy_log = teardown({k: v for k, v in run_env.items() if k == "CLEANROOM_SANDBOX"})
    write_json(state / "reports" / f"proxy_{module}_{role}.json", {"proxy_log_tail": proxy_log})
    post = manifest_check.check(sandbox, approved, "post")
    write_json(state / "manifests" / f"{module}-{role}.post.json", post)
    tool_log = sandbox / "out" / "_log" / "tool_calls.jsonl"
    calls = [json.loads(l) for l in tool_log.read_text(encoding="utf-8").splitlines()] if tool_log.exists() else []
    image = compose({"CLEANROOM_SANDBOX": str(sandbox.resolve())}, "images", "--format", "json").stdout[:2000]
    provenance_log.append(state, "build" if role == "builder" else "tests", role, model,
                          reads=[{"path": f"sandbox:{k}", "sha256": v} for k, v in approved["files"].items()],
                          writes=[{"path": f"sandbox:{k}", "sha256": v} for k, v in post["manifest"].items() if k.startswith("out/")],
                          commands=[f"docker compose run --rm builder {role}"] + [c.get("command") for c in calls if c.get("command")],
                          decision={"module": module, "attempt": attempt, "exit_code": r.returncode, "auth_mode": auth_mode,
                                    "manifest_post_ok": post["ok"], "denied_tool_calls": [c for c in calls if c.get("denied")],
                                    "tool_calls": len(calls)},
                          extra={"images": image})
    if not post["ok"]:
        print("ABORT: manifest post-check failed (inputs changed or files outside out/):\n  " + "\n  ".join(post["problems"]), file=sys.stderr)
        return 1
    if r.returncode != 0:
        print(f"{role} container exited {r.returncode}\n{r.stderr[-2000:]}", file=sys.stderr)
        return 1
    res = sandbox_prepare.collect(state, module, role, attempt)
    print(json.dumps(res, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    sub.add_parser("check-docker")
    r = sub.add_parser("run")
    r.add_argument("--module", required=True)
    r.add_argument("--role", required=True, choices=["test-writer", "builder"])
    r.add_argument("--attempt", type=int, default=1)
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    if args.cmd == "check-docker":
        ok, info = docker_ok()
        print(("OK " if ok else "NOT AVAILABLE: ") + info)
        return 0 if ok else 1
    if args.cmd == "probe":
        return probe(state)
    try:
        return run_role(state, args.module, args.role, args.attempt)
    except sandbox_prepare.Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
