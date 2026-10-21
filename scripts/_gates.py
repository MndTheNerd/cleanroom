"""Human gate store (.cleanroom/risk_decisions.json) and gate evaluation.

Gate status values:
  open     the gate is passed
  closed   unanswered, or answered in a way that needs a typed override
  stopped  hard stop (only the 'access' gate can produce this)
  stale    a related answer changed, so this gate must be answered again
"""
from __future__ import annotations

import re
from pathlib import Path

from _common import load_config, now, read_json, write_json, sha256_file
import provenance_log
from _similarity import similar_name

OVERRIDE = "I accept this risk"
UNDERSTAND = "I understand"
SIGNOFF = "approve swap"
SPEC_APPROVE = "approve spec"
ALLOWLIST_APPROVE = "approve allowlist"
FRESH_HISTORY = "rewrite history"
NAME_SIMILARITY_LIMIT = 0.75

VALID_SOURCES = ("tty", "chat", "demo-fixture")

QUESTIONS = {
    "access": {
        "q": "Did you get the upstream source legitimately (public repo or licensed to you)?",
        "why": "A clean room only helps if you were allowed to read the original. Code obtained "
               "without permission (leaked, stolen, under NDA) can't be fixed by rewriting it.",
        "answers": ["yes", "no", "unsure"],
    },
    "agreements": {
        "q": "Did you agree to any terms beyond the open-source license (EULA, terms of service, NDA, "
             "employment or client contract) that cover this code?",
        "why": "Contracts can forbid reverse engineering or claim ownership of derived work, and "
               "rewriting the code doesn't cancel a contract you signed.",
        "answers": ["yes", "no", "unsure"],
    },
    "patents": {
        "q": "Do you know of any patents on the upstream project or the techniques it uses?",
        "why": "Copyright covers the text of code; patents cover ideas. A clean-room rewrite avoids copying "
               "text but can still infringe a patent on the technique.",
        "answers": ["yes", "no", "unsure"],
    },
    "use": {
        "q": "Will this be sold, distributed, or offered as a service to others?",
        "why": "Distribution is what triggers most license obligations and makes infringement claims "
               "worth pursuing, so the stakes rise if you ship this to others.",
        "answers": ["yes", "no", "unsure"],
    },
    "name": {
        "q": "What is the new project name?",
        "why": "Names and logos are trademarks, and clean-room rewriting doesn't touch trademark law. "
               "A name close to the upstream's can cause trouble even if every line of code is new.",
        "answers": None,  # free text
    },
    "contamination": {
        "q": "The AI model may have seen the upstream code during training, and AI-run clean rooms "
             "have not been tested in court. The similarity scans are the mitigation, not a guarantee. "
             f"Type '{UNDERSTAND}' to confirm you understand.",
        "why": "Physical isolation stops the builder from reading upstream now, but it can't erase "
               "anything the model learned before. That risk is reduced, not removed.",
        "answers": None,
    },
}
ORDER = ["access", "agreements", "patents", "use", "name", "contamination"]

# When an answer changes, these other gates must be answered again.
RELATED = {
    "access": ["agreements", "patents", "use", "name", "contamination"],
    "use": ["patents"],
    "agreements": [],
    "patents": [],
    "name": [],
    "contamination": [],
}

USE_RECOMMENDATION = [
    "Have the upstream license reviewed for distribution or network-use obligations (e.g. AGPL section 13).",
    "Run a patent search on the core techniques the upstream implements.",
    "Run a trademark search on your new project name in the markets you will sell in.",
    "Check your employment or client contracts for IP assignment clauses.",
    "Keep CLEANROOM_REPORT.md and the provenance log with your release records.",
]


def path(state: Path) -> Path:
    return Path(state) / "risk_decisions.json"


def load(state: Path) -> dict:
    d = read_json(path(state), None) or {}
    d.setdefault("version", 1)
    d.setdefault("license", None)
    d.setdefault("gates", {})
    d.setdefault("allowlist", None)
    d.setdefault("spec_approvals", {})
    d.setdefault("signoff", None)
    d.setdefault("fresh_history", None)
    return d


def save(state: Path, d: dict) -> None:
    write_json(path(state), d)


def _check_source(state: Path, source: str, user_quote: str | None):
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}")
    if source == "chat" and not (user_quote and user_quote.strip()):
        raise ValueError("source=chat requires --user-quote with the user's verbatim reply")
    if source == "demo-fixture" and not load_config(state).get("synthetic_demo"):
        raise ValueError("demo-fixture answers are only accepted when config.synthetic_demo is true")


def evaluate(gate_id: str, answer: str | None, override: str | None, ctx: dict) -> tuple[str, str]:
    """Return (status, reason) for one gate answer. Pure function, unit-tested."""
    if answer is None or not str(answer).strip():
        return "closed", "not answered"
    a = str(answer).strip().lower()
    ov_ok = (override or "").strip() == OVERRIDE
    if gate_id == "access":
        if a == "yes":
            return "open", "source obtained legitimately"
        return "stopped", "HARD STOP: upstream access not confirmed as legitimate"
    if gate_id == "agreements":
        if a == "no":
            return "open", "no extra agreements"
        return ("open", "risk accepted by typed override") if ov_ok else ("closed", f"extra agreements possible: type '{OVERRIDE}' to continue")
    if gate_id == "patents":
        findings = ctx.get("patent_findings") or []
        if a == "no" and not findings:
            return "open", "no known patents and none found in upstream"
        why = "patent notices found in upstream" if findings else "patents possible"
        return ("open", f"{why}; risk accepted by typed override") if ov_ok else ("closed", f"{why}: type '{OVERRIDE}' to continue")
    if gate_id == "use":
        if a in ("yes", "no", "unsure"):
            return "open", ("commercial/distributed use: license + patent check recommended" if a != "no" else "internal use only")
        return "closed", "answer yes, no or unsure"
    if gate_id == "name":
        up = ctx.get("upstream_name") or ""
        if not up:
            return "closed", "upstream name unknown: set upstream_name in config first"
        score = similar_name(answer, up)
        if score >= NAME_SIMILARITY_LIMIT:
            return "closed", f"name '{answer}' is too close to upstream '{up}' (similarity {score:.2f})"
        return "open", f"name differs from upstream (similarity {score:.2f})"
    if gate_id == "contamination":
        if str(answer).strip() == UNDERSTAND:
            return "open", "user confirmed understanding"
        return "closed", f"type exactly '{UNDERSTAND}'"
    raise KeyError(gate_id)


def record(state: Path, gate_id: str, answer: str | None, override: str | None, source: str,
           user_quote: str | None = None, ctx: dict | None = None) -> dict:
    if gate_id not in QUESTIONS:
        raise KeyError(f"unknown gate {gate_id}")
    _check_source(state, source, user_quote)
    ctx = ctx or {}
    cfg = load_config(state)
    ctx.setdefault("upstream_name", cfg.get("upstream_name"))
    d = load(state)
    status, reason = evaluate(gate_id, answer, override, ctx)
    prev = d["gates"].get(gate_id)
    entry = {
        "question": QUESTIONS[gate_id]["q"],
        "answer": answer,
        "override": override or None,
        "status": status,
        "reason": reason,
        "source": source,
        "user_quote": user_quote,
        "ts": now(),
        "history": (prev or {}).get("history", []) + ([{k: prev[k] for k in ("answer", "override", "status", "ts", "source")}] if prev else []),
    }
    if gate_id == "patents":
        entry["patent_findings"] = ctx.get("patent_findings") or []
    if gate_id == "use" and str(answer).lower() != "no":
        entry["recommendation"] = USE_RECOMMENDATION
    reopened = []
    if prev and str(prev.get("answer")).strip().lower() != str(answer).strip().lower():
        for rel_id in RELATED.get(gate_id, []):
            g = d["gates"].get(rel_id)
            if g and g["status"] == "open":
                g["status"] = "stale"
                g["reason"] = f"re-opened because answer to '{gate_id}' changed"
                reopened.append(rel_id)
        if gate_id == "use" and d.get("license"):
            d["license"]["status"] = "stale"
            reopened.append("license")
        if d.get("signoff"):
            d["signoff"]["status"] = "stale"
            reopened.append("signoff")
    entry["reopened"] = reopened
    if gate_id == "name" and status == "open":
        cfg_path = Path(state) / "config.json"
        c = read_json(cfg_path, {})
        c["project_name"] = answer
        write_json(cfg_path, c)
    d["gates"][gate_id] = entry
    save(state, d)
    provenance_log.append(state, "risks", "human" if source != "demo-fixture" else "demo-fixture",
                          decision={"gate": gate_id, "answer": answer, "override": override,
                                    "status": status, "reason": reason, "source": source,
                                    "user_quote": user_quote, "reopened": reopened},
                          writes=[path(state)])
    provenance_log.commit(state, f"risks/{gate_id}")
    return entry


def risk_status(state: Path) -> dict:
    """Summary used by run_all: which gates block which stages."""
    d = load(state)
    out = {"gates": {}, "hard_stop": False, "all_risk_open": True}
    for gid in ORDER:
        g = d["gates"].get(gid)
        st = g["status"] if g else "closed"
        out["gates"][gid] = {"status": st, "reason": g["reason"] if g else "not answered"}
        if st == "stopped":
            out["hard_stop"] = True
        if st != "open":
            out["all_risk_open"] = False
    lic = d.get("license")
    out["license"] = {"status": lic["status"] if lic else "closed", "reason": (lic or {}).get("reason", "not decided")}
    out["allowlist"] = (d.get("allowlist") or {}).get("status", "closed")
    out["signoff"] = (d.get("signoff") or {}).get("status", "closed")
    return out


def typed_approval(state: Path, key: str, typed: str, expected: str, source: str, user_quote: str | None,
                   payload: dict | None = None, module: str | None = None) -> dict:
    _check_source(state, source, user_quote)
    status = "open" if (typed or "").strip() == expected else "closed"
    d = load(state)
    entry = {"status": status, "typed": typed, "expected": expected, "source": source,
             "user_quote": user_quote, "ts": now(), **(payload or {})}
    if key == "spec_approvals":
        d["spec_approvals"][module] = entry
    else:
        prev = d.get(key)
        if prev:
            entry["history"] = prev.get("history", []) + [{k: prev.get(k) for k in ("status", "ts", "typed")}]
        d[key] = entry
    save(state, d)
    provenance_log.append(state, key if key != "spec_approvals" else "spec", "human" if source != "demo-fixture" else "demo-fixture",
                          decision={"approval": key, "module": module, "status": status, "typed": typed,
                                    "source": source, "user_quote": user_quote, **(payload or {})},
                          writes=[path(state)])
    provenance_log.commit(state, key if key != "spec_approvals" else f"spec/{module}")
    return entry


def spec_approved(state: Path, module: str, spec_file: Path) -> tuple[bool, str]:
    d = load(state)
    a = d["spec_approvals"].get(module)
    if not a or a["status"] != "open":
        return False, "spec not approved"
    if not Path(spec_file).exists():
        return False, "spec file missing"
    if a.get("sha256") != sha256_file(spec_file):
        return False, "spec changed after approval (hash mismatch): approve again"
    contract = Path(spec_file).parent.parent / "contracts" / Path(spec_file).name
    if a.get("contract_sha256") and (not contract.exists() or a["contract_sha256"] != sha256_file(contract)):
        return False, "contract changed after approval (hash mismatch): approve again"
    return True, "approved"


def scan_patents(upstream: Path) -> list[dict]:
    """Look for patent notices: PATENTS files and patent clauses in license/notice files."""
    upstream = Path(upstream)
    found = []
    pat = re.compile(r"\bpatent(s|ed|ee)?\b|\bpatent\s+(grant|license|rights)\b", re.I)
    for p in upstream.rglob("*"):
        if ".git" in p.parts or not p.is_file():
            continue
        name = p.name.upper()
        if name.startswith("PATENT"):
            found.append({"file": p.relative_to(upstream).as_posix(), "kind": "PATENTS file", "line": None,
                          "text": p.read_text(encoding="utf-8", errors="replace")[:300]})
            continue
        if name.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")) or p.suffix.lower() in (".md", ".txt") and "LICEN" in name:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if pat.search(line):
                    found.append({"file": p.relative_to(upstream).as_posix(), "kind": "patent clause", "line": i,
                                  "text": line.strip()[:200]})
    return found
