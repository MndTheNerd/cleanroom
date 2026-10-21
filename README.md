# cleanroom: a Claude Code plugin for clean-room rewrites

`cleanroom` finds code in your project that still matches an upstream open-source project, has it
rewritten from a **behavioral description** by a builder that has **never seen** the upstream code,
proves the result is different (two independent similarity tools) and behaves the same (tests plus recorded
behavior), and then removes every trace of the upstream: files, remotes, headers, names, copied prose and config keys.

Every decision a tool can't make is put to you as a plain-language question, recorded with your exact
words, and the pipeline refuses to continue until you answer. Everything that happens is written to a
tamper-evident (hash-chained) log.

> **This is not legal advice and gives no legal immunity.** It produces evidence that you followed a careful
> process. AI-run clean rooms have not been tested in court, and the model may have seen the upstream code
> during training. See [What this can't enforce](#what-this-cant-enforce).

---

## How it works, in plain language

Think of two rooms with a wall between them.

1. **The dirty room (your normal Claude Code session plus the `analyzer` agent).** It may look at the upstream code
   and your project. It writes a *spec*: what a module must do (inputs, outputs, errors, side effects, limits),
   never how the upstream does it. No code, no upstream names, no copied comments or messages.
2. **The wall.** A filter (`spec_filter`) rejects any spec that leaks code, upstream identifiers, long quotes or
   copied sentences. **You** then read and approve every spec.
3. **The clean room (a Docker container).** The `test-writer` and `builder` agents run in a container that can see
   **only** a sandbox folder holding the approved spec, your interface contract, your house style notes and the
   spec-derived tests. The network allows only the model API (through an allowlist proxy). It uses its own credential (a separate subscription token or API key),
   a different model, no memory, no CLAUDE.md, no MCP servers, no web tools. Before the container starts, the
   sandbox is checked file by file against a SHA-256 manifest. After it exits, it is checked again.
4. **Inspection.** The new module must pass the tests, behave like the old one on recorded inputs, and score
   below the thresholds on **two independent similarity checks** (built-in winnowing and JPlag). If it fails, the
   builder only hears *"file X too similar, score N"*, never which lines. The spec is revised, you re-approve it,
   and the builder tries again (3 attempts max).
5. **Swap and sweep.** After you type `approve swap`, the plugin backs up, swaps the module in, deletes tainted
   and vendored files, removes upstream remotes, license headers and the upstream name, then greps the whole repo for
   leftovers and runs ScanCode. Anything left over stops the pipeline for you to fix by hand.
6. **Report.** `CLEANROOM_REPORT.md` records the license decision, before/after similarity per module, test
   results, ScanCode results, every human decision verbatim, and the risks that remain, each linked to your decision about it.

## Quick start

```text
/plugin marketplace add MndTheNerd/cleanroom
/plugin install cleanroom@cleanroom
```

Then, in the project you want to clean:

```text
/cleanroom:init
/cleanroom:run-all
```

Step-by-step guide: **https://mndthenerd.github.io/cleanroom/**

## Requirements

| Need | Why | How |
|---|---|---|
| Claude Code with plugin support | runs the commands, agents and hooks | [install Claude Code](https://code.claude.com/docs/en/setup) |
| Python 3.10+ | all scripts (standard library only) | python.org |
| **Docker** with compose v2 | builder isolation; **without it the build stage refuses to run** | Docker Desktop (Windows: admin rights + WSL2) or Docker Engine |
| A **separate builder credential** | the builder's own session, never your main login | **Subscription (default):** run `claude setup-token`, set `CLEANROOM_BUILDER_OAUTH_TOKEN`. **Or API key:** set `CLEANROOM_BUILDER_API_KEY`. |
| JPlag + Java 25 | second, independent similarity check | add-on, chosen at install |
| ScanCode Toolkit | final license scan | add-on, chosen at install |
| pytest (for Python projects) | runs spec-derived tests | `pip install pytest` |

### Using your Claude subscription (no API key needed)

The whole pipeline can run on a Claude Pro, Max, Team or Enterprise plan:

- **Your session** (the analyzer side) uses your normal Claude Code login.
- **The builder container** needs its own credential. In your own terminal, run:

  ```bash
  claude setup-token
  ```

  Approve in the browser, then set the printed token **before** starting Claude Code (never paste it into chat):

  ```bash
  export CLEANROOM_BUILDER_OAUTH_TOKEN=...        # macOS / Linux
  $env:CLEANROOM_BUILDER_OAUTH_TOKEN = "..."      # Windows PowerShell
  ```

Builder runs count against your plan's usage limits. The token is valid for a year and can only make model requests.
In subscription mode the container can't use Claude Code's `--bare` flag (it ignores this token), so the same isolation
comes from an empty home folder, no loaded settings, no MCP servers and the sandbox manifest check. The isolation probe
verifies it.

## Install the plugin

```text
/plugin marketplace add MndTheNerd/cleanroom
/plugin install cleanroom@cleanroom
```

When you enable the plugin, Claude Code asks you to choose:

| Option | Default | What it does |
|---|---|---|
| Add-on: JPlag similarity checker | on | Downloads JPlag 6.3.0 and a portable Java 25 runtime (~150 MB). Needed by `/cleanroom:verify`, which requires two independent similarity checks. |
| Add-on: ScanCode Toolkit license scanner | on | Installs ScanCode Toolkit in its own virtualenv (~130 MB). Needed by the final license scan. |
| ScanCode offline source | empty | A ScanCode source `.zip`, `.whl` or folder you already downloaded; installs from it instead of PyPI (useful on slow connections). |
| Builder credential | subscription | `subscription` (token from `claude setup-token`) or `api_key`. |
| Analyzer model | opus | Model that reads upstream and writes specs. |
| Builder / test-writer model | sonnet | Model inside the container. Must differ from the analyzer. |

Selected add-ons install **in the background** when a Claude Code session starts, once, into the plugin's data folder.
Check or install later with `/cleanroom:addons`. Change your choices any time in `/plugin` or `/config`.
If you turn an add-on off, the stage that needs it **fails closed** rather than being skipped; point config `jplag_jar` +
`java` or `scancode` in `.cleanroom/config.json` at your own installs instead.

**Docker is not an add-on**: it needs admin rights (and WSL2 on Windows), so install it yourself, then run
`/cleanroom:build`'s isolation probe once to confirm the container is sealed.

To try it without installing: clone the repo and run `claude --plugin-dir ./cleanroom` (no options prompt; add-ons default to on).

## Commands

| Command | What it does |
|---|---|
| `/cleanroom:init [harness] [upstream]` | Asks for missing inputs **one at a time**, creates `.cleanroom/`, switches to a `cleanroom/<date>` branch, runs the license gate, then the risk gates. |
| `/cleanroom:risks [gate]` | Asks (or re-asks) the six risk questions. Answers go to `risk_decisions.json` and the provenance log. |
| `/cleanroom:scan [--dry-run]` | Similarity scan + partition into original / mixed / tainted / vendored. |
| `/cleanroom:spec [module]` | Allowlist proposal → your approval; analyzer writes spec + contract → filter → **your approval**. |
| `/cleanroom:build <module> [attempt]` | Isolation probe, test-writer and builder in the container, manifest checks. |
| `/cleanroom:verify <module> <attempt>` | Tests, equivalence, winnowing, JPlag. On failure: file-level feedback, spec revision, re-approval. |
| `/cleanroom:swap [--dry-run]` | One-screen summary → **you type `approve swap`** → swap, clean, leftover grep, ScanCode. Offers fresh git history as a separate confirmed step. |
| `/cleanroom:report` | Writes `CLEANROOM_REPORT.md`. |
| `/cleanroom:addons [status\|install …]` | Shows add-on status, or installs JPlag / ScanCode (optionally from a local zip or wheel). |
| `/cleanroom:run-all` | Runs everything in order and **stops** at every unanswered gate, every agent step and every failure. |

You can answer the risk questions in your own terminal instead of in chat (strongest evidence, recorded as `source: tty`):

```bash
python /path/to/cleanroom/scripts/risk_gate.py --harness /path/to/your/project ask
```

## The human gates

| Gate | When | What unlocks it |
|---|---|---|
| License | init | You confirm the detected license and choose continue/stop. For MIT/Apache/BSD you're told attribution may be enough. |
| 1. Access | init | "yes". **No/unsure is a hard stop**, the only one. |
| 2. Agreements | init | "no", or typing `I accept this risk`. |
| 3. Patents | init | "no" with no patent notices found in upstream, or typing `I accept this risk`. The upstream is scanned for PATENTS files and patent clauses, and you're shown what was found. |
| 4. Use | init | Any answer. "yes" shows a pre-release checklist but doesn't block. |
| 5. Name | init | A new name that isn't the upstream's or close to it. |
| 6. Contamination | init | Typing `I understand`. |
| Allowlist | spec | Typing `approve allowlist`. These are names kept for compatibility (public API, protocols, file formats). |
| Spec + contract | spec, and again after each failed build | Typing `approve spec`. Any later edit invalidates it (hash check). |
| Final sign-off | swap | Typing `approve swap` on the current summary. A later change invalidates it. |
| Fresh history | optional | Typing `rewrite history`. |

A skipped question leaves its gate closed. Changing an answer later re-opens the related gates (e.g. switching
"use" to *yes* re-opens the patent and license gates). There are no defaults. Claude is instructed never to
answer for you, and every chat answer is stored with your verbatim reply (`user_quote`).

## Files it creates in your project

```text
.cleanroom/
  config.json            paths, languages, models, thresholds (edit thresholds here)
  risk_decisions.json    every human decision, with history (written only by the scripts)
  provenance.jsonl       append-only, hash-chained log of every stage and tool call
  allowlist.json         names approved for compatibility
  specs/  contracts/     behavioral specs and interface contracts
  style.md               your house style, derived from your original modules
  tests/  fixtures/      spec-derived tests; recorded old-module behavior (data only)
  sandbox/               the only folder the container sees (git-ignored)
  manifests/             approved SHA-256 manifests and pre/post check results
  builds/<module>/       attempt-N outputs, feedback_attemptN.md, accepted.json
  reports/               scan, partition, filter, verify, leftovers, ScanCode, sign-off summary
  backup/                copies of replaced files (git-ignored)
CLEANROOM_REPORT.md
```

## Thresholds (defaults, in `.cleanroom/config.json`)

| Setting | Default | Meaning |
|---|---|---|
| `k`, `window` | 9, 4 | Winnowing k-gram size (normalized tokens) and window. 9 matches JPlag's default minimum match. With 5, common idioms collide in independently written code: on the demo, an independent rewrite scored 23% at k=5 and 6% at k=9, while copies scored 93–100% at both. |
| `tainted_token_overlap` | 0.30 | Module is *tainted* at or above this, or with any copied non-trivial string or comment block. |
| `mixed_token_overlap` | 0.10 | *Mixed* (flagged for your review, not replaced unless `replace_mixed: true`). |
| `verify_max_overlap` | 0.15 | Max winnowing overlap of a new module, per file. |
| `jplag_max_similarity` | 0.30 | Max JPlag similarity of a new module. |
| `nontrivial_string_len` | 12 | Shortest string literal that counts as "copied". |
| `spec_max_literal_len` | 20 | Longest quoted literal allowed in a spec. |
| `spec_verbatim_words` | 8 | A run of this many words shared with upstream text is rejected in specs. |
| `max_build_attempts` | 3 | Then the pipeline stops and reports. |

## Running the tests and the demo

```bash
cd cleanroom/tests && python -m unittest -v test_core
python cleanroom/examples/run_demo.py --dest ./demo
```

The demo builds a fake GPL project ("quillstack") and a fake harness ("acme-books") containing every kind of leftover,
then runs the whole pipeline and writes `examples/DEMO_RUN.md`. On a machine without Docker the pipeline refuses to
start the test-writer and builder (that refusal is part of the demo), and labelled stand-in outputs are used instead.
Gate answers in the demo come from a script and are labelled `demo-fixture`. They are accepted only when the
project was initialised with the hidden `--synthetic-demo` flag.

## What this can't enforce

See [LIMITATIONS.md](LIMITATIONS.md). Short version: it cannot erase what the model learned in training, cannot
stop *you* from copying code by hand, cannot see through every possible spec leak, cannot prove a container is
isolated on your machine until you run `sandbox_run.py probe`, and does not clean git history unless you choose the
fresh-history step.
