#!/usr/bin/env python3
"""Final license scan of the harness with ScanCode Toolkit. Fails on any upstream leftover:
  - a copyright statement naming an upstream copyright holder
  - a license detection matching the upstream license (outside files you list as your own)
  - a file byte-identical to an upstream file (vendored copy)
  - a NOTICE/LICENSE/COPYING/PATENTS file that mentions the upstream project name

  final_license_scan.py [--harness H] [--scancode PATH]

If ScanCode is not installed the scan FAILS (it never passes silently). Install it with
scripts/install_tools.py or `pip install scancode-toolkit-mini`, or set config "scancode".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_state_dir, iter_files, load_config, read_json, sha256_file, tools_dirs, write_json  # noqa: E402
from _similarity import name_variants  # noqa: E402
import provenance_log  # noqa: E402


def find_scancode(cfg: dict, explicit: str | None) -> str | None:
    cands = [explicit, cfg.get("scancode"), os.environ.get("CLEANROOM_SCANCODE"), shutil.which("scancode")]
    for r in tools_dirs(cfg):
        cands += [str(r / "venv" / "Scripts" / "scancode.exe"), str(r / "venv" / "bin" / "scancode")]
    for c in cands:
        if c and Path(c).exists():
            return c
    return None


def run_scancode(exe: str, harness: Path, exclude: list[str]) -> dict:
    with tempfile.TemporaryDirectory(prefix="cleanroom-scancode-") as tmp:
        out = Path(tmp) / "scan.json"
        cmd = [exe, "--license", "--copyright", "--info", "--strip-root", "--quiet", "-n", "2", "--timeout", "120"]
        for e in exclude:
            cmd += ["--ignore", f"*/{e}/*", "--ignore", e]
        cmd += ["--json-pp", str(out), str(harness)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if not out.exists():
            raise RuntimeError(f"scancode failed (exit {r.returncode}): {(r.stderr or r.stdout)[-800:]}")
        return json.loads(out.read_text(encoding="utf-8"))


def evaluate(sc: dict, cfg: dict, harness: Path, upstream: Path, holders: list[str], upstream_license: str | None) -> dict:
    own = set(cfg.get("own_license_files") or [])
    issues = []
    lic_base = (upstream_license or "").lower().replace("-only", "").replace("-or-later", "")
    for f in sc.get("files", []):
        if f.get("type") != "file":
            continue
        path = f["path"]
        for c in f.get("copyrights", []) + f.get("holders", []):
            text = c.get("copyright") or c.get("holder") or c.get("value") or ""
            if any(h.lower() in text.lower() for h in holders):
                issues.append({"file": path, "kind": "upstream_copyright", "text": text[:200]})
        if path not in own and lic_base:
            for det in f.get("license_detections", []) or []:
                expr = (det.get("license_expression_spdx") or det.get("license_expression") or "").lower()
                if lic_base and lic_base.split("-")[0] in expr and lic_base in expr.replace("-only", "").replace("-or-later", ""):
                    issues.append({"file": path, "kind": "upstream_license", "text": expr})
    up_hashes = {sha256_file(p): p.relative_to(upstream).as_posix() for p in iter_files(upstream, cfg["exclude"], None) if p.stat().st_size}
    for p in iter_files(harness, cfg["exclude"], None):
        if p.stat().st_size and sha256_file(p) in up_hashes:
            issues.append({"file": p.relative_to(harness).as_posix(), "kind": "vendored_file", "text": f"identical to upstream {up_hashes[sha256_file(p)]}"})
    rx = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", re.I) for v in name_variants(cfg.get("upstream_name") or "") if len(v) >= 3]
    for p in harness.iterdir():
        if p.is_file() and re.match(r"(?i)^(notice|licen[cs]e|copying|patents|authors|credits)", p.name):
            if any(r.search(p.read_text(encoding="utf-8", errors="replace")) for r in rx):
                issues.append({"file": p.name, "kind": "upstream_notice", "text": "mentions the upstream project"})
    return {"passed": not issues, "issues": issues}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    ap.add_argument("--scancode")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = load_config(state)
    harness = Path(cfg.get("harness") or state.parent)
    upstream = Path(cfg["upstream"])
    exe = find_scancode(cfg, args.scancode)
    out = state / "reports" / "final_license_scan.json"
    if not exe:
        rep = {"passed": False, "ran": False, "reason": "ScanCode Toolkit not installed"}
        write_json(out, rep)
        provenance_log.append(state, "swap", "script", writes=[out], decision=rep)
        print("FAIL: ScanCode Toolkit not installed; the final license scan cannot pass without it. Run /cleanroom:addons install scancode, or set config 'scancode'.")
        return 1
    scan = read_json(state / "reports" / "scan.json", {}) or {}
    holders = scan.get("upstream_copyright_holders", [])
    lic = ((read_json(state / "risk_decisions.json", {}) or {}).get("license") or {}).get("confirmed_license")
    try:
        sc = run_scancode(exe, harness, cfg["exclude"])
    except Exception as e:  # noqa: BLE001
        rep = {"passed": False, "ran": False, "reason": str(e)}
        write_json(out, rep)
        provenance_log.append(state, "swap", "script", writes=[out], decision={"passed": False, "reason": str(e)[:300]})
        print(f"FAIL: {e}")
        return 1
    res = evaluate(sc, cfg, harness, upstream, holders, lic)
    rep = {"ran": True, "scancode": exe, "scancode_version": (sc.get("headers") or [{}])[0].get("tool_version"),
           "files_scanned": sum(1 for f in sc.get("files", []) if f.get("type") == "file"),
           "upstream_holders": holders, "upstream_license": lic, **res}
    write_json(out, rep)
    provenance_log.append(state, "swap", "script", writes=[out], commands=[f"{Path(exe).name} --license --copyright --info"],
                          decision={"passed": res["passed"], "issues": len(res["issues"])})
    for i in res["issues"]:
        print(f"LEFTOVER {i['kind']:<20} {i['file']}: {i['text']}")
    print(f"ScanCode {rep['scancode_version']}: {rep['files_scanned']} files scanned. " + ("PASS: no upstream license leftovers" if res["passed"] else "FAIL"))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
