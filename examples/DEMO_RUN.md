# Cleanroom demo run on fake repositories

Upstream: `D:\plugins\demo\quillstack` (fake project "quillstack", GPL-3.0). Harness: `D:\plugins\demo\acme-books` (fake "acme-books").
Gate answers below are **demo fixtures** (synthetic repos; `config.synthetic_demo = true`). They are not a person's answers.
Test-writer and builder outputs are **stand-ins**: this machine has no Docker, so the pipeline refuses to run them for real (shown below).


## 0. Init

**Init**  
`python run_all.py init --upstream D:\plugins\demo\quillstack --languages python --test-command "python -m pytest -q" --synthetic-demo` -> exit 0

```text
initialized D:\plugins\demo\acme-books\.cleanroom
```

Demo config: `test_runner = host` (no Docker available; the report records where tests ran).

## 1. run-all refuses to proceed past unanswered gates

**run-all with no answers**  
`python run_all.py next --run` -> exit 20

```text
NEEDS YOUR ANSWER: [license] License gate closed: not decided. Run license_gate.py detect, explain, and ask the user.
```

**Try to prepare a builder sandbox directly (bypassing run-all)**  
`python sandbox_prepare.py prepare --module app-rows --role builder` -> exit 1

```text
REFUSED: license gate not open: not decided
```

## 2. License gate

**Detect license**  
`python license_gate.py detect` -> exit 0

```text
Detected license: GPL-3.0  (strong-copyleft)
  - LICENSE: GPL-3.0 [license text]
  - pyproject.toml: GPL-3.0-or-later [package metadata]
  - 1 file header(s): GPL-3.0-or-later [SPDX header]

This is a strong copyleft license. If you distribute software that includes this code (or, for AGPL, offer it as a network service), the whole combined work must be released under the same license. A clean-room rewrite is the usual way to remove that obligation.

Please confirm the license is correct before continuing.
```

**Record license decision (demo fixture)**  
`python license_gate.py record --license GPL-3.0 --confirmed yes --decision continue --source demo-fixture` -> exit 0

```text
{
  "confirmed_license": "GPL-3.0",
  "category": "strong-copyleft",
  "status": "open",
  "reason": "GPL-3.0 (strong-copyleft): user chose to continue"
}
```

## 3. Risk gates

**Patent scan of upstream**  
`python risk_gate.py scan-patents` -> exit 0

```text
[
  {
    "file": "LICENSE",
    "kind": "patent clause",
    "line": 8,
    "text": "11. Patents. Each contributor grants you a non-exclusive, worldwide, royalty-free patent license..."
  }
]
```

**Gate 'access' answered (demo fixture): 'yes'**  
`python risk_gate.py record --gate access --answer yes --source demo-fixture` -> exit 0

```text
{
  "status": "open",
  "reason": "source obtained legitimately",
  "reopened": []
}
```

**Gate 'agreements' answered (demo fixture): 'unsure'**  
`python risk_gate.py record --gate agreements --answer unsure --source demo-fixture` -> exit 1

```text
{
  "status": "closed",
  "reason": "extra agreements possible: type 'I accept this risk' to continue",
  "reopened": []
}
```

**run-all stops: agreements needs a typed override**  
`python run_all.py next --run` -> exit 20

```text
NEEDS YOUR ANSWER: [risks] Risk gate 'agreements' is closed (extra agreements possible: type 'I accept this risk' to continue). Ask the user: Did you agree to any terms beyond the open-source license (EULA, terms of service, NDA, employment or client contract) that cover this code?
```

**Gate 'agreements' answered (demo fixture): 'unsure' + override 'I accept this risk'**  
`python risk_gate.py record --gate agreements --answer unsure --source demo-fixture --override "I accept this risk"` -> exit 0

```text
{
  "status": "open",
  "reason": "risk accepted by typed override",
  "reopened": []
}
```

**Gate 'patents' answered (demo fixture): 'no'**  
`python risk_gate.py record --gate patents --answer no --source demo-fixture` -> exit 1

```text
{
  "status": "closed",
  "reason": "patent notices found in upstream: type 'I accept this risk' to continue",
  "reopened": [],
  "patent_findings": [
    {
      "file": "LICENSE",
      "kind": "patent clause",
      "line": 8,
      "text": "11. Patents. Each contributor grants you a non-exclusive, worldwide, royalty-free patent license..."
    }
  ]
... (1 more lines)
```

**Gate 'patents' answered (demo fixture): 'no' + override 'I accept this risk'**  
`python risk_gate.py record --gate patents --answer no --source demo-fixture --override "I accept this risk"` -> exit 0

```text
{
  "status": "open",
  "reason": "patent notices found in upstream; risk accepted by typed override",
  "reopened": [],
  "patent_findings": [
    {
      "file": "LICENSE",
      "kind": "patent clause",
      "line": 8,
      "text": "11. Patents. Each contributor grants you a non-exclusive, worldwide, royalty-free patent license..."
    }
  ]
... (1 more lines)
```

**Gate 'use' answered (demo fixture): 'no'**  
`python risk_gate.py record --gate use --answer no --source demo-fixture` -> exit 0

```text
{
  "status": "open",
  "reason": "internal use only",
  "reopened": []
}
```

**Gate 'name' answered (demo fixture): 'QuillStack2'**  
`python risk_gate.py record --gate name --answer QuillStack2 --source demo-fixture` -> exit 1

```text
{
  "status": "closed",
  "reason": "name 'QuillStack2' is too close to upstream 'quillstack' (similarity 1.00)",
  "reopened": []
}
```

**Gate 'name' answered (demo fixture): 'Brightledger'**  
`python risk_gate.py record --gate name --answer Brightledger --source demo-fixture` -> exit 0

```text
{
  "status": "open",
  "reason": "name differs from upstream (similarity 0.17)",
  "reopened": []
}
```

**Gate 'contamination' answered (demo fixture): 'yes'**  
`python risk_gate.py record --gate contamination --answer yes --source demo-fixture` -> exit 1

```text
{
  "status": "closed",
  "reason": "type exactly 'I understand'",
  "reopened": []
}
```

**run-all stops: contamination needs the exact text**  
`python run_all.py next --run` -> exit 20

```text
NEEDS YOUR ANSWER: [risks] Risk gate 'contamination' is closed (type exactly 'I understand'). Ask the user: The AI model may have seen the upstream code during training, and AI-run clean rooms have not been tested in court. The similarity scans are the mitigation, not a guarantee. Type 'I understand' to confirm you understand.
```

**Gate 'contamination' answered (demo fixture): 'I understand'**  
`python risk_gate.py record --gate contamination --answer "I understand" --source demo-fixture` -> exit 0

```text
{
  "status": "open",
  "reason": "user confirmed understanding",
  "reopened": []
}
```

**Gate 'use' answered (demo fixture): 'yes'**  
`python risk_gate.py record --gate use --answer yes --source demo-fixture` -> exit 0

```text
{
  "status": "open",
  "reason": "commercial/distributed use: license + patent check recommended",
  "reopened": [
    "patents",
    "license"
  ],
  "recommendation": [
    "Have the upstream license reviewed for distribution or network-use obligations (e.g. AGPL section 13).",
    "Run a patent search on the core techniques the upstream implements.",
    "Run a trademark search on your new project name in the markets you will sell in.",
    "Check your employment or client contracts for IP assignment clauses.",
... (3 more lines)
```

**Answer change re-opened related gates**  
`python risk_gate.py status` -> exit 1

```text
license      stale    GPL-3.0 (strong-copyleft): user chose to continue
access       open     source obtained legitimately
agreements   open     risk accepted by typed override
patents      stale    re-opened because answer to 'use' changed
use          open     commercial/distributed use: license + patent check recommended
name         open     name differs from upstream (similarity 0.17)
contamination open     user confirmed understanding
allowlist    closed
signoff      closed

GATES NOT SATISFIED: the build stage will not start
```

**Gate 'patents' answered (demo fixture): 'no' + override 'I accept this risk'**  
`python risk_gate.py record --gate patents --answer no --source demo-fixture --override "I accept this risk"` -> exit 0

```text
{
  "status": "open",
  "reason": "patent notices found in upstream; risk accepted by typed override",
  "reopened": [],
  "patent_findings": [
    {
      "file": "LICENSE",
      "kind": "patent clause",
      "line": 8,
      "text": "11. Patents. Each contributor grants you a non-exclusive, worldwide, royalty-free patent license..."
    }
  ]
... (1 more lines)
```

**License gate re-confirmed after use changed**  
`python license_gate.py record --license GPL-3.0 --confirmed yes --decision continue --source demo-fixture` -> exit 0

```text
{
  "confirmed_license": "GPL-3.0",
  "category": "strong-copyleft",
  "status": "open",
  "reason": "GPL-3.0 (strong-copyleft): user chose to continue"
}
```

**All gates**  
`python risk_gate.py status` -> exit 0

```text
license      open     GPL-3.0 (strong-copyleft): user chose to continue
access       open     source obtained legitimately
agreements   open     risk accepted by typed override
patents      open     patent notices found in upstream; risk accepted by typed override
use          open     commercial/distributed use: license + patent check recommended
name         open     name differs from upstream (similarity 0.17)
contamination open     user confirmed understanding
allowlist    closed
signoff      closed

ALL RISK GATES OPEN
```

## 4. Scan and partition (run-all runs them, then stops for the analyzer)

**Dry-run scan writes nothing**  
`python similarity_scan.py scan --dry-run` -> exit 0

```text
# Similarity scan: harness vs upstream

Generated 2026-10-20T21:05:16+00:00. Winnowing k=9 w=4.

| Rank | File | Token overlap | Worst function | Shared strings | Shared comments | Best upstream match |
|---|---|---|---|---|---|---|
| 1 | `vendor/quillstack/ledger.py` | 100% | split_ledger_line 100% | 2 | 6 | quillstack/ledger.py |
| 2 | `app/rows.py` | 100% | split_ledger_line 100% | 2 | 5 | quillstack/ledger.py |
| 3 | `conftest.py` | 0% | - | 0 | 0 | - |
| 4 | `app/__init__.py` | 0% | - | 0 | 0 | - |
| 5 | `app/report.py` | 0% | monthly_summary 0% | 0 | 0 | - |
| 6 | `tests/test_report.py` | 0% | test_summary 0% | 0 | 0 | - |

## Non-code findings

- Paths sharing upstream names: 3
- Package metadata matches: 1
- README passages shared: 30
- License/copyright header lines: 4 (2 name an upstream copyright holder)
- Shared config keys: 2
- Mentions of upstream name 'quillstack': 10

(dry run: nothing written)
```

**run-all**  
`python run_all.py next --run` -> exit 10

```text
== [scan] similarity_scan.py scan -> exit 0
# Similarity scan: harness vs upstream

Generated 2026-10-20T21:05:17+00:00. Winnowing k=9 w=4.

| Rank | File | Token overlap | Worst function | Shared strings | Shared comments | Best upstream match |
|---|---|---|---|---|---|---|
| 1 | `vendor/quillstack/ledger.py` | 100% | split_ledger_line 100% | 2 | 6 | quillstack/ledger.py |
| 2 | `app/rows.py` | 100% | split_ledger_line 100% | 2 | 5 | quillstack/ledger.py |
| 3 | `conftest.py` | 0% | - | 0 | 0 | - |
| 4 | `app/__init__.py` | 0% | - | 0 | 0 | - |
| 5 | `app/report.py` | 0% | monthly_summary 0% | 0 | 0 | - |
| 6 | `tests/test_report.py` | 0% | test_summary 0% | 0 | 0 | - |

## Non-code findings

- Paths sharing upstream names: 3
- Package metadata matches: 1
- README passages shared: 30
- License/copyright header lines: 4 (2 name an upstream copyright holder)
- Shared config keys: 2
- Mentions of upstream name 'quillstack': 10

== [partition] partition.py -> exit 0
original  app-init                       app/__init__.py
original  app-report                     app/report.py
tainted   app-rows                       app/rows.py
           - app/rows.py: token overlap 100% >= 30%; 2 copied non-trivial string(s); 5 copied comment(s)/comment block(s)
original  conftest                       conftest.py
original  tests-test-report              tests/test_report.py
vendored  vendor-quillstack-ledger       vendor/quillstack/ledger.py
           - vendor/quillstack/ledger.py: byte-identical copy of an upstream file

{'original': 4, 'mixed': 0, 'tainted': 1, 'vendored': 1}

NEEDS AGENT: [allowlist] Analyzer proposes allowlist.json: names needed for compatibility (public API, wire protocols, file formats).
```

## 5. Allowlist and spec (analyzer role; human approvals)

**run-all: allowlist needs approval**  
`python run_all.py next --run` -> exit 20

```text
NEEDS YOUR ANSWER: [allowlist] Show allowlist.json to the user; they must type 'approve allowlist'.
```

**Approve allowlist with the wrong text**  
`python risk_gate.py approve-allowlist --typed ok --source demo-fixture` -> exit 1

```text
approve-allowlist: closed
```

**Approve allowlist**  
`python risk_gate.py approve-allowlist --typed "approve allowlist" --source demo-fixture` -> exit 0

```text
approve-allowlist: open
```

**spec_filter on a deliberately bad first draft**  
`python spec_filter.py check --spec D:\plugins\demo\acme-books\.cleanroom\specs\app-rows.md --module app-rows` -> exit 1

```text
REJECTED: D:\plugins\demo\acme-books\.cleanroom\specs\app-rows.md has 13 violation(s):
  [code_fence] app-rows.md:3  code fences are not allowed in specs
  [code_line] app-rows.md:4  line looks like source code
  [upstream_identifier] app-rows.md:4  upstream identifier 'raw_line' not on allowlist
  [upstream_identifier] app-rows.md:4  upstream identifier 'delimiter_char' not on allowlist
  [code_fence] app-rows.md:5  code fences are not allowed in specs
  [long_literal] app-rows.md:8  literal of 45 chars (max 20)
  [upstream_identifier] app-rows.md:9  upstream identifier 'current' in code span
  [upstream_identifier] app-rows.md:9  upstream identifier 'QUOTE_MARK' not on allowlist
  [verbatim_text] app-rows.md:-  8-word run also in upstream: 'character and honour quoted sections of the ledger...'
  [verbatim_text] app-rows.md:-  8-word run also in upstream: 'def split ledger line raw line delimiter char...'
  [verbatim_text] app-rows.md:-  8-word run also in upstream: 'every character and honour quoted sections of the...'
  [verbatim_text] app-rows.md:-  8-word run also in upstream: 'walk every character and honour quoted sections of...'
  [upstream_name] app-rows.md:-  mentions the upstream project name
```

**Approval is refused while the spec fails the filter**  
`python risk_gate.py approve-spec --module app-rows --typed "approve spec" --source demo-fixture` -> exit 2

```text
ERROR: spec must exist and pass spec_filter (on its current content) before approval
```

**spec_filter on the revised spec**  
`python spec_filter.py check --spec D:\plugins\demo\acme-books\.cleanroom\specs\app-rows.md --module app-rows` -> exit 0

```text
PASS: D:\plugins\demo\acme-books\.cleanroom\specs\app-rows.md (spec) has no leaks
```

**spec_filter on the contract**  
`python spec_filter.py check --spec D:\plugins\demo\acme-books\.cleanroom\contracts\app-rows.md` -> exit 0

```text
PASS: D:\plugins\demo\acme-books\.cleanroom\contracts\app-rows.md (spec) has no leaks
```

**Human approves spec + contract**  
`python risk_gate.py approve-spec --module app-rows --typed "approve spec" --source demo-fixture` -> exit 0

```text
approve-spec: open
```

## 6. Tests: the real container path is refused (no Docker), then a stand-in is used

**run-all tries the test-writer container**  
`python run_all.py next --run` -> exit 30

```text
== [tests] sandbox_run.py run --module app-rows --role test-writer -> exit 2
REFUSED: docker is not installed or not on PATH. The builder only runs inside the isolated container.

STOPPED: [tests] sandbox_run.py failed (exit 2); stopping.
```

**Isolation probe**  
`python sandbox_run.py probe` -> exit 2

```text
CANNOT RUN PROBE: docker is not installed or not on PATH
```

**Prepare test-writer sandbox (attempt 1)**  
`python sandbox_prepare.py prepare --module app-rows --role test-writer --attempt 1` -> exit 0

```text
{
  "sandbox": "D:\\plugins\\demo\\acme-books\\.cleanroom\\sandbox\\app-rows-test-writer",
  "approved": "D:\\plugins\\demo\\acme-books\\.cleanroom\\manifests\\app-rows-test-writer.approved.json",
  "files": [
    "AGENT.md",
    "TASK.md",
    "contract.md",
    "spec.md"
  ]
}
```

Sandbox contents before the run: `['AGENT.md', 'TASK.md', 'contract.md', 'spec.md']`

**Manifest post-check (test-writer)** -> exit 0

```text
manifest post-check OK: 7 files
```

**Collect test-writer output**  
`python sandbox_prepare.py collect --module app-rows --role test-writer --attempt 1` -> exit 0

```text
{
  "tests": "D:\\plugins\\demo\\acme-books\\.cleanroom\\tests\\app-rows",
  "filter": {
    "passed": true,
    "violations": [],
    "tree_sha256": "b3bf055b21014e39df6771da6a93b7b138913557bca62dbee41076e4dbb9b78e"
  }
}
```

**run-all: captures behavioral fixtures from the OLD module, then tries the builder container**  
`python run_all.py next --run` -> exit 30

```text
== [tests] equivalence_run.py capture --module app-rows -> exit 0
captured 14 behavioral fixtures from app/rows.py

== [build] sandbox_run.py run --module app-rows --role builder --attempt 1 -> exit 2
REFUSED: docker is not installed or not on PATH. The builder only runs inside the isolated container.

STOPPED: [build] sandbox_run.py failed (exit 2); stopping.
```

Fixture sample (data only, exception type without message): `{"ok": false, "exc_type": "ValueError", "exc_bases": ["Exception", "BaseException", "object"]}`, `{"ok": true, "value": ["p", "q;r", "s"]}`

## 7. Build attempt 1 (stand-in that copies upstream) -> verify FAILS

**Prepare builder sandbox (attempt 1)**  
`python sandbox_prepare.py prepare --module app-rows --role builder --attempt 1` -> exit 0

```text
{
  "sandbox": "D:\\plugins\\demo\\acme-books\\.cleanroom\\sandbox\\app-rows-builder",
  "approved": "D:\\plugins\\demo\\acme-books\\.cleanroom\\manifests\\app-rows-builder.approved.json",
  "files": [
    "AGENT.md",
    "TASK.md",
    "contract.md",
    "spec.md",
    "style.md",
    "tests/test_rows.py"
  ]
}
```

Sandbox contents before the run: `['AGENT.md', 'TASK.md', 'contract.md', 'spec.md', 'style.md', 'tests/test_rows.py']`

**Manifest post-check (builder)** -> exit 0

```text
manifest post-check OK: 9 files
```

**Collect builder output**  
`python sandbox_prepare.py collect --module app-rows --role builder --attempt 1` -> exit 0

```text
{
  "build": "D:\\plugins\\demo\\acme-books\\.cleanroom\\builds\\app-rows\\attempt-1"
}
```

**run-all runs verify**  
`python run_all.py next --run` -> exit 10

```text
== [verify] verify_build.py --module app-rows --attempt 1 -> exit 1
tests        PASS  11 passed in 0.03s
equivalence  PASS  14/14 cases
winnowing    FAIL  app/rows.py: 93% (limit 15%), strings 2, comments 3, name 4
jplag        FAIL  max 100% (limit 30%)
VERIFY FAILED (attempt 1 of 3)

NEEDS AGENT: [verify/app-rows] Attempt 1 failed. Analyzer revises specs/app-rows.md (never pass code or diffs to the builder); then the user re-approves it for attempt 2.
```

Feedback handed to the builder for attempt 2 (file-level only):

```markdown
# Feedback for attempt 2 of module 'app-rows'

File-level results from the previous attempt. No source lines are shared by design.

- app/rows.py: too similar to upstream: score 0.93 (limit 0.15); 2 string literal(s) match upstream; write your own wording; 3 comment(s) match upstream; write your own comments; mentions a forbidden project name. Restructure this file (different decomposition, control flow and naming).
- Second similarity tool: module score 1.00 (limit 0.30). Restructure the module.
```

## 8. Spec revised by the analyzer, re-approved, attempt 2 -> verify PASSES

**run-all re-filters the revised spec, then needs re-approval**  
`python run_all.py next --run` -> exit 20

```text
== [spec] spec_filter.py check --spec D:\plugins\demo\acme-books\.cleanroom\specs\app-rows.md --module app-rows -> exit 0
PASS: D:\plugins\demo\acme-books\.cleanroom\specs\app-rows.md (spec) has no leaks

NEEDS YOUR ANSWER: [spec/app-rows] Spec review for 'app-rows': spec changed after approval (hash mismatch): approve again. Show the spec and contract; the user must type 'approve spec'.
```

**Human re-approves (approval is tied to attempt 2)**  
`python risk_gate.py approve-spec --module app-rows --typed "approve spec" --source demo-fixture` -> exit 0

```text
approve-spec: open
```

**run-all tries the builder container for attempt 2**  
`python run_all.py next --run` -> exit 30

```text
== [build] sandbox_run.py run --module app-rows --role builder --attempt 2 -> exit 2
REFUSED: docker is not installed or not on PATH. The builder only runs inside the isolated container.

STOPPED: [build] sandbox_run.py failed (exit 2); stopping.
```

**Prepare builder sandbox (attempt 2)**  
`python sandbox_prepare.py prepare --module app-rows --role builder --attempt 2` -> exit 0

```text
{
  "sandbox": "D:\\plugins\\demo\\acme-books\\.cleanroom\\sandbox\\app-rows-builder",
  "approved": "D:\\plugins\\demo\\acme-books\\.cleanroom\\manifests\\app-rows-builder.approved.json",
  "files": [
    "AGENT.md",
    "TASK.md",
    "contract.md",
    "feedback.md",
    "spec.md",
    "style.md",
    "tests/test_rows.py"
  ]
}
```

Sandbox contents before the run: `['AGENT.md', 'TASK.md', 'contract.md', 'feedback.md', 'spec.md', 'style.md', 'tests/test_rows.py']`

**Manifest post-check (builder)** -> exit 0

```text
manifest post-check OK: 11 files
```

**Collect builder output**  
`python sandbox_prepare.py collect --module app-rows --role builder --attempt 2` -> exit 0

```text
{
  "build": "D:\\plugins\\demo\\acme-books\\.cleanroom\\builds\\app-rows\\attempt-2"
}
```

**run-all: verify, then sign-off summary**  
`python run_all.py next --run` -> exit 20

```text
== [verify] verify_build.py --module app-rows --attempt 2 -> exit 0
tests        PASS  11 passed in 0.02s
equivalence  PASS  14/14 cases
winnowing    PASS  app/rows.py: 6% (limit 15%), strings 0, comments 0, name 0
jplag        PASS  max 0% (limit 30%)
VERIFY PASSED

== [signoff] run_all.py summary -> exit 0
summary written

NEEDS YOUR ANSWER: [signoff] Show reports/signoff_summary.md; the user must type 'approve swap'.
```

Sign-off summary shown to the human:

# Clean-room sign-off summary

**License:** GPL-3.0 (strong-copyleft), decision: continue

**Risk decisions**
- access: 'yes' -> open [demo-fixture]
- agreements: 'unsure' -> open OVERRIDE: "I accept this risk" [demo-fixture]
- patents: 'no' -> open OVERRIDE: "I accept this risk" [demo-fixture]
- use: 'yes' -> open [demo-fixture]
- name: 'Brightledger' -> open [demo-fixture]
- contamination: 'I understand' -> open [demo-fixture]

| Module | Before (winnowing) | After (winnowing) | After (JPlag) | Tests | Equivalence | Result |
|---|---|---|---|---|---|---|
| app-rows | 100% | 6% | 0% | pass | pass | PASSED (attempt 2) |

**WARNING: gates answered by demo fixture (synthetic test run, not a human):** access, agreements, patents, use, name, contamination

**WARNING: build produced by a demo stand-in, NOT the isolated builder:** app-rows

Next: swap replaces the modules, deletes tainted files, removes upstream remotes, vendored copies,
license headers and the upstream name, then runs leftover and ScanCode checks.
Git history will still contain upstream code (fresh history is a separate step).

Type exactly: **approve swap**


## 9. Final sign-off, swap, cleanup, leftover grep, ScanCode, report

**Swap is refused before sign-off**  
`python swap_and_clean.py swap --module app-rows` -> exit 1

```text
REFUSED: final sign-off not recorded: run /cleanroom:report summary, then type 'approve swap'
```

**Sign-off with the wrong text**  
`python risk_gate.py signoff --typed approve --source demo-fixture` -> exit 1

```text
signoff: closed
```

**Sign-off**  
`python risk_gate.py signoff --typed "approve swap" --source demo-fixture` -> exit 0

```text
signoff: open
```

**Swap dry run (changes nothing)**  
`python swap_and_clean.py swap --module app-rows --dry-run` -> exit 0

```text
[dry-run] backup app/rows.py -> .cleanroom/backup/20261020T210534+0000-app-rows/app/rows.py
[dry-run] write app/rows.py (from accepted build attempt 2)
```

**Clean dry run (changes nothing)**  
`python swap_and_clean.py clean --dry-run` -> exit 0

```text
[dry-run] git remote remove upstream  (D:\plugins\demo\quillstack)
[dry-run] delete vendored copy vendor/quillstack/ledger.py (identical to upstream quillstack/ledger.py)
[dry-run] remove 1 upstream license/copyright header line(s) from app/rows.py
[dry-run] remove 1 upstream license/copyright header line(s) from vendor/quillstack/ledger.py
[dry-run] rename upstream name (2x) in README.md
[dry-run] rename upstream name (3x) in app/rows.py
[dry-run] rename upstream name (4x) in vendor/quillstack/ledger.py
[dry-run] rename path vendor/quillstack -> brightledger
```

**run-all: swap, clean, then the leftover grep stops it**  
`python run_all.py next --run` -> exit 30

```text
== [swap] swap_and_clean.py swap --module app-rows -> exit 0
backup app/rows.py -> .cleanroom/backup/20261020T210535+0000-app-rows/app/rows.py
write app/rows.py (from accepted build attempt 2)

WARNING: git history still contains the upstream code. Run `fresh-history` (separate confirmed step) if you need a history without it.

== [swap] swap_and_clean.py clean -> exit 0
git remote remove upstream  (D:\plugins\demo\quillstack)
delete vendored copy vendor/quillstack/ledger.py (identical to upstream quillstack/ledger.py)
remove empty folder vendor/quillstack
remove empty folder vendor
rename upstream name (2x) in README.md

WARNING: git history still contains the upstream code. Run `fresh-history` (separate confirmed step) if you need a history without it.

== [swap] swap_and_clean.py leftovers -> exit 1
LEFTOVER docs        {"file": "README.md", "shared_8word_runs": 30}
LEFTOVER metadata    {"file": "pyproject.toml", "field": "description"}
LEFTOVER config_keys {"key": "amount_column", "files": ["settings.toml"]}
LEFTOVER config_keys {"key": "ledger_delimiter", "files": ["settings.toml"]}
UPSTREAM LEFTOVERS REMAIN

STOPPED: [swap] Upstream leftovers remain after clean (reports/leftovers.json). Fix them by hand or re-run the affected modules.
```

## 10. Human fixes what no tool should rewrite (copied README prose, package description, config keys)

Rewrote README.md, the pyproject description and the settings.toml keys by hand (simulated).

**Leftover grep again**  
`python swap_and_clean.py leftovers` -> exit 0

```text
NO UPSTREAM LEFTOVERS FOUND
Note: git history still contains the upstream code. See `fresh-history` (separate, confirmed step).
```

**run-all: ScanCode, report**  
`python run_all.py next --run` -> exit 0

```text
== [swap] final_license_scan.py -> exit 0
ScanCode 33.0.0rc1: 8 files scanned. PASS: no upstream license leftovers

== [report] report.py -> exit 0
wrote D:\plugins\demo\acme-books\CLEANROOM_REPORT.md

DONE: [done] Pipeline complete. Optional: fresh-history (separate confirmed step).
```

**Provenance chain**  
`python provenance_log.py verify` -> exit 0

```text
provenance chain OK
```

**Harness test suite after the swap**  
`python run_all.py status` -> exit 0

```text
license      open     GPL-3.0 (strong-copyleft): user chose to continue
access       open     source obtained legitimately
agreements   open     risk accepted by typed override
patents      open     patent notices found in upstream; risk accepted by typed override
use          open     commercial/distributed use: license + patent check recommended
name         open     name differs from upstream (similarity 0.17)
contamination open     user confirmed understanding
allowlist    open
signoff      open

ALL RISK GATES OPEN

next: [done] Pipeline complete. Optional: fresh-history (separate confirmed step).
provenance chain OK
```

**Harness's own tests after swap** (`python -m pytest -q` in acme-books) -> exit 0

```text
.                                                                        [100%]
1 passed in 0.02s
```

**Git state of the harness:** branch `cleanroom/2026-10-20`; remotes: `none`

```text
M README.md
 M app/rows.py
 M pyproject.toml
 M settings.toml
 D vendor/quillstack/ledger.py
?? CLEANROOM_REPORT.md
?? app/__pycache__/
```

**Swapped-in app/rows.py:**

```python
"""Record splitting and column sums for bookkeeping files."""


def split_ledger_line(text, sep=";"):
    """Break text into trimmed fields; double quotes protect separators."""
    if text.count('"') % 2:
        raise ValueError("odd number of double quotes")
    fields = [""]
    for position, segment in enumerate(text.split('"')):
        if position % 2:
            fields[-1] += segment
            continue
        head, *rest = segment.split(sep)
        fields[-1] += head
        fields.extend(rest)
    return [field.strip() for field in fields]


def _counted(text):
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith("#")


def column_total(lines, column=2, sep=";"):
    """Add up the whole number found in one field of every counted line."""
    sums = []
    for text in filter(_counted, lines):
        cells = split_ledger_line(text, sep)
        if not -len(cells) <= column < len(cells):
            raise ValueError(f"record has no field at position {column}")
        try:
            sums.append(int(cells[column]))
        except ValueError as exc:
            raise ValueError(f"field {column} is not a whole number") from exc
    return sum(sums)
```

## Result

All steps behaved as expected.
