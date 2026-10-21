#!/usr/bin/env python3
"""Generate CLEANROOM_REPORT.md in the harness root.

Sections: license decision; before/after overlap per module from both similarity tools; what was
replaced; tests and equivalence; ScanCode results; Human decisions (full risk_decisions.json);
residual risks, each linked to the human decision recorded for it; provenance chain status.

  report.py [--harness H]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_state_dir, load_config, now, read_json  # noqa: E402
import _gates  # noqa: E402
import provenance_log  # noqa: E402

RESIDUAL = [
    ("Training-data contamination", "contamination",
     "The model may have seen upstream during training. Isolation stops it reading upstream now, not what it already learned. "
     "Mitigation: both similarity checks on every replaced module."),
    ("Patents", "patents", "A rewrite avoids copying text but can still practice a patented technique."),
    ("Trademarks", "name", "The upstream name was removed and a new name chosen; trademark searches are outside this tool."),
    ("Trade secrets", "access", "If the source was not obtained legitimately, no rewrite cures it."),
    ("Reverse-engineering / contract terms", "agreements", "EULAs, terms of service, NDAs or employment/client contracts may restrict this work."),
    ("Spec leakage", "spec", "Specs were written by an agent that read upstream. spec_filter and your review are the controls; they are not perfect."),
    ("Untested legal status", "contamination", "AI-run clean rooms have not been tested in court. This report is evidence of process, not legal immunity."),
    ("Distribution obligations", "use", "Selling or distributing raises the stakes of every risk above."),
]


def pct(x):
    return "-" if x is None else f"{x:.0%}"


def build(state: Path) -> str:
    cfg = load_config(state)
    d = _gates.load(state)
    rep = state / "reports"
    part = read_json(rep / "partition.json", {}) or {}
    import run_all  # local import to avoid a cycle at module load
    mods = run_all.modules_to_replace(state, cfg)
    L = [f"# Clean-room report: {cfg.get('project_name') or '(unnamed project)'}", "",
         f"Generated {now()}. This report documents a process. It is **not** a legal opinion and does not grant legal immunity.", ""]
    if cfg.get("synthetic_demo"):
        L += ["> **SYNTHETIC DEMO RUN.** Gate answers marked `demo-fixture` were scripted for fake repositories, not given by a person.", ""]
    lic = d.get("license") or {}
    L += ["## 1. License decision", "",
          f"- Detected: {lic.get('detected')}; confirmed by user: {lic.get('confirmed_license')} ({lic.get('category')})",
          f"- Decision: **{lic.get('decision')}** at {lic.get('ts')} (source: {lic.get('source')})",
          f"- What it means: {lic.get('explanation')}", ""]
    L += ["## 2. Overlap per module, before and after", "",
          "| Module | Before: winnowing | Before: JPlag | After: winnowing | After: JPlag | Attempts | Verified |", "|---|---|---|---|---|---|---|"]
    for m in mods:
        b = read_json(rep / f"baseline_{m}.json", {}) or {}
        n = run_all.latest_attempt(state, m)
        v = read_json(rep / f"verify_{m}_attempt{n}.json", {}) or {}
        after_w = max((f["token_overlap"] for f in (v.get("builtin_similarity") or {}).get("files", [])), default=None)
        jp = v.get("jplag") or {}
        L.append(f"| {m} | {pct(b.get('winnowing_max'))} | {pct(b.get('jplag_max'))} | {pct(after_w)} | "
                 f"{pct(jp.get('max_similarity')) if jp.get('ran') else 'not run'} | {n} | {'yes' if v.get('passed') else 'NO'} |")
    L += ["", "All modules and labels (from the scan):", "", "| Module | Label | Files |", "|---|---|---|"]
    for m, info in sorted(part.get("modules", {}).items()):
        L.append(f"| {m} | {info['label']} | {', '.join(info['files'])} |")
    L += ["", "## 3. What was replaced", ""]
    for m in mods:
        s = read_json(rep / f"swapped_{m}.json")
        L.append(f"- **{m}**: " + ("swapped at " + s["ts"] if s else "NOT swapped"))
        if s:
            L += [f"  - {line}" for line in s["output"].splitlines() if line.startswith(("write", "delete", "backup"))][:30]
        stand = state / "builds" / m / f"attempt-{run_all.latest_attempt(state, m)}" / "_log" / "STANDIN"
        if stand.exists():
            L.append("  - **WARNING: this build came from a demo stand-in, not the isolated builder container.**")
    c = read_json(rep / "clean_done.json")
    if c:
        L += ["", "Cleanup actions:", ""] + [f"- {l}" for l in c["output"].splitlines() if l and not l.startswith(("WARNING", "Note"))][:60]
    L += ["", "## 4. Tests and equivalence", "", "| Module | Tests | Where | Equivalence |", "|---|---|---|---|"]
    for m in mods:
        n = run_all.latest_attempt(state, m)
        v = read_json(rep / f"verify_{m}_attempt{n}.json", {}) or {}
        t, e = v.get("tests") or {}, v.get("equivalence") or {}
        L.append(f"| {m} | {'pass' if t.get('ok') else 'FAIL'} ({t.get('summary', '')}) | {t.get('where', '-')} | "
                 f"{(e.get('cases') or 0) - (e.get('mismatches') or 0)}/{e.get('cases', 0)} cases match |")
    lo = read_json(rep / "leftovers.json", {}) or {}
    fl = read_json(rep / "final_license_scan.json", {}) or {}
    L += ["", "## 5. Leftover and ScanCode results", "",
          f"- Leftover grep (identifiers, strings, upstream name): {'clean' if lo.get('clean') else 'NOT CLEAN or not run'}",
          f"- ScanCode Toolkit {fl.get('scancode_version') or ''}: {'PASS' if fl.get('passed') else 'FAIL or not run'}"
          f" ({fl.get('files_scanned', 0)} files; {len(fl.get('issues', []))} issue(s)) {fl.get('reason') or ''}"]
    for i in fl.get("issues", [])[:30]:
        L.append(f"  - {i['kind']}: {i['file']}: {i['text']}")
    probe = read_json(rep / "isolation_probe.json")
    L += ["", "## 6. Builder isolation", "",
          f"- Isolation probe: {'PASSED' if probe and probe.get('ok') else 'NOT PASSED / NOT RUN'}"]
    if probe:
        L += [f"  - {'PASS' if c['ok'] else 'FAIL'} {c['check']}" for c in probe.get("checks", [])]
    ok, problems = provenance_log.verify(state)
    entries = sum(1 for _ in open(state / "provenance.jsonl", encoding="utf-8")) if (state / "provenance.jsonl").exists() else 0
    L += [f"- Provenance log: {entries} entries, hash chain {'intact' if ok else 'BROKEN: ' + '; '.join(problems)}", ""]
    L += ["## 7. Residual risks", "", "| Risk | Linked human decision | Note |", "|---|---|---|"]
    for title, gid, note in RESIDUAL:
        if gid == "spec":
            link = "; ".join(f"{m}: {a.get('status')} at {a.get('ts')} ({a.get('source')})" for m, a in d["spec_approvals"].items()) or "none"
        else:
            g = d["gates"].get(gid) or {}
            link = f"[{gid}](#human-decisions): answer {g.get('answer')!r}, status {g.get('status')}" + (f", override \"{g['override']}\"" if g.get("override") else "")
        L.append(f"| {title} | {link} | {note} |")
    L += ["", "Git history: unless you ran the fresh-history step, the repository history still contains upstream code.", "",
          "## Human decisions", "", "Full contents of `.cleanroom/risk_decisions.json`:", "", "```json",
          json.dumps(d, indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = load_config(state)
    out = Path(cfg.get("harness") or state.parent) / "CLEANROOM_REPORT.md"
    out.write_text(build(state), encoding="utf-8")
    provenance_log.append(state, "report", "script", writes=[out], commands=["report.py"])
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
