# Clean-room report: Brightledger

Generated 2026-10-20T21:05:47+00:00. This report documents a process. It is **not** a legal opinion and does not grant legal immunity.

> **SYNTHETIC DEMO RUN.** Gate answers marked `demo-fixture` were scripted for fake repositories, not given by a person.

## 1. License decision

- Detected: GPL-3.0; confirmed by user: GPL-3.0 (strong-copyleft)
- Decision: **continue** at 2026-10-20T21:05:16+00:00 (source: demo-fixture)
- What it means: This is a strong copyleft license. If you distribute software that includes this code (or, for AGPL, offer it as a network service), the whole combined work must be released under the same license. A clean-room rewrite is the usual way to remove that obligation.

## 2. Overlap per module, before and after

| Module | Before: winnowing | Before: JPlag | After: winnowing | After: JPlag | Attempts | Verified |
|---|---|---|---|---|---|---|
| app-rows | 100% | 100% | 6% | 0% | 2 | yes |

All modules and labels (from the scan):

| Module | Label | Files |
|---|---|---|
| app-init | original | app/__init__.py |
| app-report | original | app/report.py |
| app-rows | tainted | app/rows.py |
| conftest | original | conftest.py |
| tests-test-report | original | tests/test_report.py |
| vendor-quillstack-ledger | vendored | vendor/quillstack/ledger.py |

## 3. What was replaced

- **app-rows**: swapped at 2026-10-20T21:05:35+00:00
  - backup app/rows.py -> .cleanroom/backup/20261020T210535+0000-app-rows/app/rows.py
  - write app/rows.py (from accepted build attempt 2)
  - **WARNING: this build came from a demo stand-in, not the isolated builder container.**

Cleanup actions:

- git remote remove upstream  (D:\plugins\demo\quillstack)
- delete vendored copy vendor/quillstack/ledger.py (identical to upstream quillstack/ledger.py)
- remove empty folder vendor/quillstack
- remove empty folder vendor
- rename upstream name (2x) in README.md

## 4. Tests and equivalence

| Module | Tests | Where | Equivalence |
|---|---|---|---|
| app-rows | pass (11 passed in 0.02s) | host | 14/14 cases match |

## 5. Leftover and ScanCode results

- Leftover grep (identifiers, strings, upstream name): clean
- ScanCode Toolkit 33.0.0rc1: PASS (8 files; 0 issue(s)) 

## 6. Builder isolation

- Isolation probe: NOT PASSED / NOT RUN
- Provenance log: 52 entries, hash chain intact

## 7. Residual risks

| Risk | Linked human decision | Note |
|---|---|---|
| Training-data contamination | [contamination](#human-decisions): answer 'I understand', status open | The model may have seen upstream during training. Isolation stops it reading upstream now, not what it already learned. Mitigation: both similarity checks on every replaced module. |
| Patents | [patents](#human-decisions): answer 'no', status open, override "I accept this risk" | A rewrite avoids copying text but can still practice a patented technique. |
| Trademarks | [name](#human-decisions): answer 'Brightledger', status open | The upstream name was removed and a new name chosen; trademark searches are outside this tool. |
| Trade secrets | [access](#human-decisions): answer 'yes', status open | If the source was not obtained legitimately, no rewrite cures it. |
| Reverse-engineering / contract terms | [agreements](#human-decisions): answer 'unsure', status open, override "I accept this risk" | EULAs, terms of service, NDAs or employment/client contracts may restrict this work. |
| Spec leakage | app-rows: open at 2026-10-20T21:05:28+00:00 (demo-fixture) | Specs were written by an agent that read upstream. spec_filter and your review are the controls; they are not perfect. |
| Untested legal status | [contamination](#human-decisions): answer 'I understand', status open | AI-run clean rooms have not been tested in court. This report is evidence of process, not legal immunity. |
| Distribution obligations | [use](#human-decisions): answer 'yes', status open | Selling or distributing raises the stakes of every risk above. |

Git history: unless you ran the fresh-history step, the repository history still contains upstream code.

## Human decisions

Full contents of `.cleanroom/risk_decisions.json`:

```json
{
  "version": 1,
  "license": {
    "detected": "GPL-3.0",
    "evidence": [
      {
        "source": "LICENSE",
        "spdx": "GPL-3.0",
        "how": "license text"
      },
      {
        "source": "pyproject.toml",
        "spdx": "GPL-3.0-or-later",
        "how": "package metadata"
      },
      {
        "source": "1 file header(s)",
        "spdx": "GPL-3.0-or-later",
        "how": "SPDX header"
      }
    ],
    "confirmed_license": "GPL-3.0",
    "category": "strong-copyleft",
    "explanation": "This is a strong copyleft license. If you distribute software that includes this code (or, for AGPL, offer it as a network service), the whole combined work must be released under the same license. A clean-room rewrite is the usual way to remove that obligation.",
    "confirmed": "yes",
    "decision": "continue",
    "status": "open",
    "reason": "GPL-3.0 (strong-copyleft): user chose to continue",
    "source": "demo-fixture",
    "user_quote": null,
    "ts": "2026-10-20T21:05:16+00:00",
    "history": [
      {
        "confirmed_license": "GPL-3.0",
        "decision": "continue",
        "status": "stale",
        "ts": "2026-10-20T21:05:11+00:00"
      }
    ]
  },
  "gates": {
    "access": {
      "question": "Did you get the upstream source legitimately (public repo or licensed to you)?",
      "answer": "yes",
      "override": null,
      "status": "open",
      "reason": "source obtained legitimately",
      "source": "demo-fixture",
      "user_quote": null,
      "ts": "2026-10-20T21:05:12+00:00",
      "history": [],
      "reopened": []
    },
    "agreements": {
      "question": "Did you agree to any terms beyond the open-source license (EULA, terms of service, NDA, employment or client contract) that cover this code?",
      "answer": "unsure",
      "override": "I accept this risk",
      "status": "open",
      "reason": "risk accepted by typed override",
      "source": "demo-fixture",
      "user_quote": null,
      "ts": "2026-10-20T21:05:12+00:00",
      "history": [
        {
          "answer": "unsure",
          "override": null,
          "status": "closed",
          "ts": "2026-10-20T21:05:12+00:00",
          "source": "demo-fixture"
        }
      ],
      "reopened": []
    },
    "patents": {
      "question": "Do you know of any patents on the upstream project or the techniques it uses?",
      "answer": "no",
      "override": "I accept this risk",
      "status": "open",
      "reason": "patent notices found in upstream; risk accepted by typed override",
      "source": "demo-fixture",
      "user_quote": null,
      "ts": "2026-10-20T21:05:16+00:00",
      "history": [
        {
          "answer": "no",
          "override": null,
          "status": "closed",
          "ts": "2026-10-20T21:05:13+00:00",
          "source": "demo-fixture"
        },
        {
          "answer": "no",
          "override": "I accept this risk",
          "status": "stale",
          "ts": "2026-10-20T21:05:13+00:00",
          "source": "demo-fixture"
        }
      ],
      "patent_findings": [
        {
          "file": "LICENSE",
          "kind": "patent clause",
          "line": 8,
          "text": "11. Patents. Each contributor grants you a non-exclusive, worldwide, royalty-free patent license..."
        }
      ],
      "reopened": []
    },
    "use": {
      "question": "Will this be sold, distributed, or offered as a service to others?",
      "answer": "yes",
      "override": null,
      "status": "open",
      "reason": "commercial/distributed use: license + patent check recommended",
      "source": "demo-fixture",
      "user_quote": null,
      "ts": "2026-10-20T21:05:15+00:00",
      "history": [
        {
          "answer": "no",
          "override": null,
          "status": "open",
          "ts": "2026-10-20T21:05:13+00:00",
          "source": "demo-fixture"
        }
      ],
      "recommendation": [
        "Have the upstream license reviewed for distribution or network-use obligations (e.g. AGPL section 13).",
        "Run a patent search on the core techniques the upstream implements.",
        "Run a trademark search on your new project name in the markets you will sell in.",
        "Check your employment or client contracts for IP assignment clauses.",
        "Keep CLEANROOM_REPORT.md and the provenance log with your release records."
      ],
      "reopened": [
        "patents",
        "license"
      ]
    },
    "name": {
      "question": "What is the new project name?",
      "answer": "Brightledger",
      "override": null,
      "status": "open",
      "reason": "name differs from upstream (similarity 0.17)",
      "source": "demo-fixture",
      "user_quote": null,
      "ts": "2026-10-20T21:05:14+00:00",
      "history": [
        {
          "answer": "QuillStack2",
          "override": null,
          "status": "closed",
          "ts": "2026-10-20T21:05:14+00:00",
          "source": "demo-fixture"
        }
      ],
      "reopened": []
    },
    "contamination": {
      "question": "The AI model may have seen the upstream code during training, and AI-run clean rooms have not been tested in court. The similarity scans are the mitigation, not a guarantee. Type 'I understand' to confirm you understand.",
      "answer": "I understand",
      "override": null,
      "status": "open",
      "reason": "user confirmed understanding",
      "source": "demo-fixture",
      "user_quote": null,
      "ts": "2026-10-20T21:05:15+00:00",
      "history": [
        {
          "answer": "yes",
          "override": null,
          "status": "closed",
          "ts": "2026-10-20T21:05:14+00:00",
          "source": "demo-fixture"
        }
      ],
      "reopened": []
    }
  },
  "allowlist": {
    "status": "open",
    "typed": "approve allowlist",
    "expected": "approve allowlist",
    "source": "demo-fixture",
    "user_quote": null,
    "ts": "2026-10-20T21:05:18+00:00",
    "sha256": "0289ef1fc46b7f925fdfd20a0485dac020c39ef0169831aa8039ba01a84f0d16",
    "names": [
      "split_ledger_line"
    ],
    "history": [
      {
        "status": "closed",
        "ts": "2026-10-20T21:05:18+00:00",
        "typed": "ok"
      }
    ]
  },
  "spec_approvals": {
    "app-rows": {
      "status": "open",
      "typed": "approve spec",
      "expected": "approve spec",
      "source": "demo-fixture",
      "user_quote": null,
      "ts": "2026-10-20T21:05:28+00:00",
      "sha256": "9335f405446cf6906c77f1fd0195d573f0c1e70f8202f52bdb993b1cf4e5c501",
      "contract_sha256": "8fa7862f8e2af84f31d53d4324edc517ce40de310f210ad56fb0e75494e33408",
      "for_attempt": 2
    }
  },
  "signoff": {
    "status": "open",
    "typed": "approve swap",
    "expected": "approve swap",
    "source": "demo-fixture",
    "user_quote": null,
    "ts": "2026-10-20T21:05:34+00:00",
    "summary_sha256": "6f7bb4fe96bb4e715d4de77771cbf1980cb53e1c0c3f00823ac9374c26011db4",
    "history": [
      {
        "status": "closed",
        "ts": "2026-10-20T21:05:33+00:00",
        "typed": "approve"
      }
    ]
  },
  "fresh_history": null
}
```
