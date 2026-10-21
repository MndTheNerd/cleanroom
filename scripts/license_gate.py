#!/usr/bin/env python3
"""License gate: detect the upstream license, explain it in plain language, record the decision.

  license_gate.py detect --upstream PATH [--json]
  license_gate.py record --license SPDX --confirmed yes --decision continue|stop \
      --source chat|tty --user-quote "..."

Permissive licenses (MIT/Apache/BSD/ISC/Zlib): attribution may be enough, so the user is asked
whether to continue anyway. Copyleft/unknown/none: the clean room continues.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_state_dir, now, read_json  # noqa: E402
import _gates  # noqa: E402
import provenance_log  # noqa: E402

SIGNATURES = [
    ("AGPL-3.0", r"GNU AFFERO GENERAL PUBLIC LICENSE"),
    ("LGPL-3.0", r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 3"),
    ("LGPL-2.1", r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 2\.1|GNU LIBRARY GENERAL PUBLIC LICENSE"),
    ("GPL-3.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 3"),
    ("GPL-2.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 2"),
    ("MPL-2.0", r"Mozilla Public License,?\s+(?:v\.|version)\s*2\.0"),
    ("EPL-2.0", r"Eclipse Public License\s*-?\s*v\s*2\.0"),
    ("Apache-2.0", r"Apache License,?\s+Version 2\.0"),
    ("BSD-3-Clause", r"Redistribution and use in source and binary forms[\s\S]{0,1500}Neither the name"),
    ("BSD-2-Clause", r"Redistribution and use in source and binary forms"),
    ("MIT", r"Permission is hereby granted, free of charge, to any person obtaining a copy"),
    ("ISC", r"Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee"),
    ("Zlib", r"This software is provided 'as-is', without any express or implied\s+warranty"),
    ("Unlicense", r"This is free and unencumbered software released into the public domain"),
    ("SSPL-1.0", r"Server Side Public License"),
    ("BUSL-1.1", r"Business Source License"),
]

PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "Unlicense", "0BSD"}
WEAK_COPYLEFT = {"LGPL-2.1", "LGPL-3.0", "MPL-2.0", "EPL-2.0"}
STRONG_COPYLEFT = {"GPL-2.0", "GPL-3.0", "AGPL-3.0"}
SOURCE_AVAILABLE = {"SSPL-1.0", "BUSL-1.1"}

EXPLAIN = {
    "permissive": "This is a permissive license. You may usually keep the upstream code if you keep its "
                  "copyright notice and license text (Apache-2.0 also asks you to keep NOTICE files and mark changes). "
                  "A clean-room rewrite may be unnecessary: attribution alone may be enough. Do you want to continue anyway?",
    "weak-copyleft": "This is a weak copyleft license. Changes to the licensed files themselves must stay under the "
                     "same license, but your own separate files can use any license. A clean room removes the "
                     "licensed files from your project.",
    "strong-copyleft": "This is a strong copyleft license. If you distribute software that includes this code "
                       "(or, for AGPL, offer it as a network service), the whole combined work must be released "
                       "under the same license. A clean-room rewrite is the usual way to remove that obligation.",
    "source-available": "This is a source-available license, not an open-source one. It may restrict commercial or "
                        "service use. Read its terms carefully: some forbid building competing products even from "
                        "knowledge of the code.",
    "unknown": "No recognizable license was found. By default nobody may copy, change or distribute code "
               "without a license, so you have no permission to reuse it. The clean room continues; "
               "consider asking the authors.",
}


def classify(spdx: str | None) -> str:
    if not spdx:
        return "unknown"
    base = spdx.split(" ")[0].replace("-only", "").replace("-or-later", "").rstrip("+")
    if base in PERMISSIVE:
        return "permissive"
    if base in WEAK_COPYLEFT:
        return "weak-copyleft"
    if base in STRONG_COPYLEFT:
        return "strong-copyleft"
    if base in SOURCE_AVAILABLE:
        return "source-available"
    return "unknown"


def detect(upstream: Path) -> dict:
    upstream = Path(upstream)
    evidence = []
    for p in sorted(upstream.iterdir()) if upstream.exists() else []:
        if p.is_file() and re.match(r"(?i)^(licen[cs]e|copying|unlicense)", p.name):
            text = p.read_text(encoding="utf-8", errors="replace")
            for spdx, sig in SIGNATURES:
                if re.search(sig, text, re.I):
                    evidence.append({"source": p.name, "spdx": spdx, "how": "license text"})
                    break
            else:
                m = re.search(r"SPDX-License-Identifier:\s*([\w.\-+ ()]+)", text)
                evidence.append({"source": p.name, "spdx": m.group(1).strip() if m else None, "how": "spdx tag" if m else "unrecognized text"})
    pj = upstream / "package.json"
    if pj.exists():
        try:
            lic = json.loads(pj.read_text(encoding="utf-8")).get("license")
            if lic:
                evidence.append({"source": "package.json", "spdx": lic, "how": "package metadata"})
        except json.JSONDecodeError:
            pass
    for meta in ("pyproject.toml", "setup.cfg", "setup.py", "Cargo.toml"):
        mp = upstream / meta
        if mp.exists():
            m = re.search(r"""license\s*[=:]\s*(?:\{\s*text\s*=\s*)?["']([^"']+)["']""", mp.read_text(encoding="utf-8", errors="replace"))
            if m:
                evidence.append({"source": meta, "spdx": m.group(1), "how": "package metadata"})
    spdx_headers = {}
    for p in upstream.rglob("*"):
        if ".git" in p.parts or not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:2000]
        except OSError:
            continue
        for m in re.finditer(r"SPDX-License-Identifier:\s*([\w.\-+]+(?:\s+(?:OR|AND|WITH)\s+[\w.\-+]+)*)", head):
            spdx_headers[m.group(1)] = spdx_headers.get(m.group(1), 0) + 1
    for spdx, count in spdx_headers.items():
        evidence.append({"source": f"{count} file header(s)", "spdx": spdx, "how": "SPDX header"})
    ids = [e["spdx"] for e in evidence if e["spdx"]]
    distinct = sorted(set(ids))
    primary = ids[0] if ids else None
    category = classify(primary)
    return {
        "detected": primary,
        "all_detected": distinct,
        "conflicting": len({classify(i) for i in distinct}) > 1,
        "category": category,
        "explanation": EXPLAIN[category],
        "evidence": evidence,
    }


def record(state: Path, license_id: str, confirmed: str, decision: str, source: str, user_quote: str | None, detected: dict) -> dict:
    _gates._check_source(state, source, user_quote)
    category = classify(license_id)
    if confirmed.lower() != "yes":
        status, reason = "closed", "license not confirmed by user"
    elif decision == "stop":
        status, reason = "stopped", "user chose to stop (attribution may be enough)" if category == "permissive" else "user chose to stop"
    elif decision == "continue":
        status, reason = "open", f"{license_id} ({category}): user chose to continue"
    else:
        status, reason = "closed", "decision must be continue or stop"
    d = _gates.load(state)
    prev = d.get("license")
    d["license"] = {
        "detected": detected.get("detected"), "evidence": detected.get("evidence"), "confirmed_license": license_id,
        "category": category, "explanation": EXPLAIN[category], "confirmed": confirmed, "decision": decision,
        "status": status, "reason": reason, "source": source, "user_quote": user_quote, "ts": now(),
        "history": ((prev or {}).get("history", []) + [{k: prev.get(k) for k in ("confirmed_license", "decision", "status", "ts")}]) if prev else [],
    }
    _gates.save(state, d)
    provenance_log.append(state, "license", "human" if source != "demo-fixture" else "demo-fixture",
                          decision={"gate": "license", "license": license_id, "category": category,
                                    "decision": decision, "status": status, "source": source, "user_quote": user_quote},
                          writes=[_gates.path(state)])
    provenance_log.commit(state, "license")
    return d["license"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect", help="detect and explain the upstream license (read-only)")
    d.add_argument("--upstream")
    d.add_argument("--json", action="store_true")
    r = sub.add_parser("record", help="record the user's license decision")
    r.add_argument("--license", required=True, help="SPDX id the user confirmed")
    r.add_argument("--confirmed", required=True, choices=["yes", "no"])
    r.add_argument("--decision", required=True, choices=["continue", "stop"])
    r.add_argument("--source", required=True, choices=_gates.VALID_SOURCES)
    r.add_argument("--user-quote")
    args = ap.parse_args(argv)
    state = find_state_dir(Path(args.harness) if args.harness else None)
    cfg = read_json(state / "config.json", {}) or {}
    upstream = Path(getattr(args, "upstream", None) or cfg.get("upstream") or "")
    if not upstream or not upstream.exists():
        print("ERROR: upstream path unknown; pass --upstream or run init", file=sys.stderr)
        return 2
    info = detect(upstream)
    if args.cmd == "detect":
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(f"Detected license: {info['detected'] or 'NONE FOUND'}  ({info['category']})")
            if info["conflicting"]:
                print(f"WARNING: conflicting license signals: {', '.join(info['all_detected'])}")
            for e in info["evidence"]:
                print(f"  - {e['source']}: {e['spdx']} [{e['how']}]")
            print()
            print(info["explanation"])
            print("\nPlease confirm the license is correct before continuing.")
        if state.exists():
            provenance_log.append(state, "license", "script", note="license detected",
                                  decision={"detected": info["detected"], "category": info["category"]})
        return 0
    out = record(state, args.license, args.confirmed, args.decision, args.source, args.user_quote, info)
    print(json.dumps({k: out[k] for k in ("confirmed_license", "category", "status", "reason")}, indent=2))
    return 0 if out["status"] == "open" else 1


if __name__ == "__main__":
    sys.exit(main())
