import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import ROOT, UPSTREAM_CODE, TempRepos, jdump

import _gates
import _similarity as S
import license_gate
import manifest_check
import partition
import path_guard
import provenance_log
import run_all
import sandbox_prepare
import similarity_scan
import spec_filter
import swap_and_clean
from _common import load_config, sha256_file


class TestSimilarity(unittest.TestCase):
    def test_comments_stripped_and_strings_kept(self):
        lx = S.lex('x = "a # not comment"  # real comment\n', ".py")
        self.assertEqual([c for c, _ in lx.comments], ["real comment"])
        self.assertEqual([s for s, _ in lx.strings], ["a # not comment"])

    def test_renamed_copy_is_detected(self):
        renamed = UPSTREAM_CODE.replace("split_ledger_line", "f").replace("fields", "out").replace("current", "buf")
        a = S.winnow(S.normalize(S.lex(UPSTREAM_CODE, ".py").tokens))
        b = S.winnow(S.normalize(S.lex(renamed, ".py").tokens))
        shared = len({h for h, _ in a} & {h for h, _ in b}) / len({h for h, _ in b})
        self.assertGreater(shared, 0.9)

    def test_unrelated_code_low_overlap(self):
        other = "def area(w, h):\n    if w < 0 or h < 0:\n        return None\n    total = w * h\n    return total\n"
        a = {h for h, _ in S.winnow(S.normalize(S.lex(UPSTREAM_CODE, ".py").tokens))}
        b = {h for h, _ in S.winnow(S.normalize(S.lex(other, ".py").tokens))}
        self.assertLess(len(a & b) / len(b), 0.3)

    def test_c_style_comments(self):
        lx = S.lex("int a = 1; // one\n/* block\n * two */ int b;", ".c")
        self.assertEqual(len(lx.comments), 2)
        self.assertNotIn("one", [t for _, t, _ in lx.tokens])

    def test_name_similarity(self):
        self.assertGreaterEqual(S.similar_name("QuillStack", "quill-stack"), 0.75)
        self.assertGreaterEqual(S.similar_name("Quillstax", "quillstack"), 0.75)
        self.assertLess(S.similar_name("Brightledger", "quillstack"), 0.5)


class TestProvenance(TempRepos):
    def test_chain_and_tamper_detection(self):
        state = self.init_state()
        provenance_log.append(state, "scan", "script", note="a")
        provenance_log.append(state, "scan", "script", note="b")
        ok, _ = provenance_log.verify(state)
        self.assertTrue(ok)
        log = state / "provenance.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        e = json.loads(lines[1])
        e["note"] = "forged"
        lines[1] = json.dumps(e)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, problems = provenance_log.verify(state)
        self.assertFalse(ok)
        self.assertIn("entry_hash mismatch", problems[0])

    def test_deleted_entry_breaks_chain(self):
        state = self.init_state()
        for n in "abc":
            provenance_log.append(state, "x", "script", note=n)
        log = state / "provenance.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        del lines[1]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertFalse(provenance_log.verify(state)[0])


class TestGates(TempRepos):
    def test_rules(self):
        ev = _gates.evaluate
        self.assertEqual(ev("access", "no", None, {})[0], "stopped")
        self.assertEqual(ev("access", "unsure", None, {})[0], "stopped")
        self.assertEqual(ev("access", None, None, {})[0], "closed")
        self.assertEqual(ev("agreements", "yes", None, {})[0], "closed")
        self.assertEqual(ev("agreements", "yes", "i accept this risk", {})[0], "closed")  # must be exact
        self.assertEqual(ev("agreements", "unsure", "I accept this risk", {})[0], "open")
        self.assertEqual(ev("patents", "no", None, {"patent_findings": [{"file": "LICENSE"}]})[0], "closed")
        self.assertEqual(ev("patents", "no", None, {"patent_findings": []})[0], "open")
        self.assertEqual(ev("use", "yes", None, {})[0], "open")
        self.assertEqual(ev("name", "Quill-Stack", None, {"upstream_name": "quillstack"})[0], "closed")
        self.assertEqual(ev("name", "quillstack2", None, {"upstream_name": "quillstack"})[0], "closed")
        self.assertEqual(ev("name", "Brightledger", None, {"upstream_name": "quillstack"})[0], "open")
        self.assertEqual(ev("contamination", "yes", None, {})[0], "closed")
        self.assertEqual(ev("contamination", "I understand", None, {})[0], "open")

    def test_chat_needs_verbatim_quote_and_demo_needs_demo_mode(self):
        state = self.init_state(demo=False)
        with self.assertRaises(ValueError):
            _gates.record(state, "access", "yes", None, "chat", None)
        with self.assertRaises(ValueError):
            _gates.record(state, "access", "yes", None, "demo-fixture", None)
        e = _gates.record(state, "access", "yes", None, "chat", "yes, I cloned it from the public repo")
        self.assertEqual(e["status"], "open")

    def test_changed_answer_reopens_related(self):
        state = self.init_state()
        self.open_all_gates(state)
        e = _gates.record(state, "use", "yes", None, "demo-fixture", ctx={"patent_findings": []})
        self.assertIn("patents", e["reopened"])
        self.assertIn("license", e["reopened"])
        st = _gates.risk_status(state)
        self.assertEqual(st["gates"]["patents"]["status"], "stale")
        self.assertFalse(st["all_risk_open"])

    def test_patent_scan_finds_license_clause(self):
        self.assertTrue(_gates.scan_patents(self.up))


class TestLicense(TempRepos):
    def test_detect(self):
        info = license_gate.detect(self.up)
        self.assertEqual(info["detected"], "GPL-3.0")
        self.assertEqual(info["category"], "strong-copyleft")
        (self.up / "LICENSE").write_text("Permission is hereby granted, free of charge, to any person obtaining a copy", encoding="utf-8")
        self.assertEqual(license_gate.detect(self.up)["category"], "permissive")
        (self.up / "LICENSE").unlink()
        # still found through the SPDX header in the source file
        self.assertEqual(license_gate.detect(self.up)["detected"], "GPL-3.0-or-later")
        (self.up / "quillstack" / "ledger.py").unlink()
        self.assertEqual(license_gate.detect(self.up)["category"], "unknown")

    def test_record_stop(self):
        state = self.init_state()
        d = license_gate.record(state, "MIT", "yes", "stop", "demo-fixture", None, {})
        self.assertEqual(d["status"], "stopped")
        self.assertEqual(run_all.next_step(state)["code"], run_all.STOP)


class TestScanPartition(TempRepos):
    def test_scan_labels_copied_module_tainted(self):
        state = self.init_state()
        cfg = load_config(state)
        rep = similarity_scan.scan(self.h, self.up, cfg)
        by = {r["path"]: r for r in rep["files"]}
        self.assertGreater(by["app/rows.py"]["token_overlap"], 0.8)
        self.assertLess(by["app/hello.py"]["token_overlap"], 0.1)
        self.assertTrue(by["app/rows.py"]["comments"])
        self.assertTrue(rep["upstream_name_hits"])
        self.assertTrue(any(h["mentions_upstream_holder"] for h in rep["license_headers"]))
        jdump(state / "reports" / "scan.json", rep)
        part = partition.partition(state, cfg)
        labels = {m: i["label"] for m, i in part["modules"].items()}
        self.assertEqual(labels["app-rows"], "tainted")
        self.assertEqual(labels["app-hello"], "original")
        self.assertIn("split_row", part["modules"]["app-rows"]["interface"])

    def test_dry_run_writes_nothing(self):
        state = self.init_state()
        before = sorted(p.name for p in state.rglob("*"))
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "similarity_scan.py"), "--harness", str(self.h), "scan", "--dry-run"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, sorted(p.name for p in state.rglob("*")))


class TestSpecFilter(TempRepos):
    def facts(self, state):
        cfg = load_config(state)
        return spec_filter.UpstreamFacts(self.up, cfg["exclude"], 8), cfg

    def test_rejections(self):
        state = self.init_state()
        up, cfg = self.facts(state)
        bad = ("# Spec\n```python\nx = 1\n```\nCall split_ledger_line with delimiter_char.\n"
               'Error text is "unterminated quote in ledger line here".\n'
               "walk every character and honour quoted sections of the ledger\n")
        rules = {v["rule"] for v in spec_filter.check(bad, up, set(), cfg)}
        self.assertTrue({"code_fence", "upstream_identifier", "long_literal", "verbatim_text"} <= rules, rules)

    def test_clean_spec_passes_and_allowlist(self):
        state = self.init_state()
        up, cfg = self.facts(state)
        good = ("# Purpose\nSplits one text record into fields.\n\n## Inputs\n- a text record\n- a single separator character, default semicolon\n"
                "\n## Errors\n- an unbalanced double quote raises a value error\n\nPublic name: split_row\n")
        self.assertEqual(spec_filter.check(good, up, set(), cfg), [])
        v = spec_filter.check(good + "Compatible alias: split_ledger_line\n", up, set(), cfg)
        self.assertTrue(v)
        self.assertEqual(spec_filter.check(good + "Compatible alias: split_ledger_line\n", up, {"split_ledger_line"}, cfg), [])

    def test_tests_kind_flags_upstream_strings(self):
        state = self.init_state()
        up, cfg = self.facts(state)
        t = 'def test_x():\n    assert msg == "Quillstack: unterminated quote in ledger line"\n'
        rules = {v["rule"] for v in spec_filter.check(t, up, set(), cfg, "tests")}
        self.assertIn("upstream_string", rules)


class TestManifest(TempRepos):
    def test_pre_post(self):
        box = self.tmp / "box"
        (box / "out").mkdir(parents=True)
        (box / "spec.md").write_text("s", encoding="utf-8")
        files, _ = manifest_check.snapshot(box)
        approved = {"files": files}
        self.assertTrue(manifest_check.check(box, approved, "pre")["ok"])
        (box / "intruder.py").write_text("x", encoding="utf-8")
        r = manifest_check.check(box, approved, "pre")
        self.assertFalse(r["ok"])
        self.assertIn("file not on approved list: intruder.py", r["problems"])
        (box / "intruder.py").unlink()
        (box / "out" / "new.py").write_text("y", encoding="utf-8")
        self.assertTrue(manifest_check.check(box, approved, "post")["ok"])
        self.assertFalse(manifest_check.check(box, approved, "pre")["ok"])
        (box / "spec.md").write_text("changed", encoding="utf-8")
        self.assertIn("approved file changed: spec.md", manifest_check.check(box, approved, "post")["problems"])

    def test_symlink_rejected(self):
        box = self.tmp / "box2"
        (box / "out").mkdir(parents=True)
        try:
            os.symlink(self.up / "LICENSE", box / "link")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted on this machine")
        _, problems = manifest_check.snapshot(box)
        self.assertTrue(any("symlink" in p for p in problems))


class TestPipelineGates(TempRepos):
    def test_run_all_stops_at_each_unanswered_gate(self):
        state = self.init_state()
        s = run_all.next_step(state)
        self.assertEqual((s["code"], s["stage"]), (run_all.HUMAN, "license"))
        license_gate.record(state, "GPL-3.0", "yes", "continue", "demo-fixture", None, {})
        ctx = {"patent_findings": []}
        for gid, ans in [("access", "yes"), ("agreements", "no"), ("patents", "no"), ("use", "no"), ("name", "Brightledger")]:
            s = run_all.next_step(state)
            self.assertEqual((s["code"], s["stage"], s["gate"]), (run_all.HUMAN, "risks", gid))
            _gates.record(state, gid, ans, None, "demo-fixture", ctx=ctx)
        s = run_all.next_step(state)
        self.assertEqual((s["code"], s.get("gate")), (run_all.HUMAN, "contamination"))
        _gates.record(state, "contamination", "", None, "demo-fixture")  # skipped
        self.assertEqual(run_all.next_step(state)["code"], run_all.HUMAN)

    def test_hard_stop(self):
        state = self.init_state()
        license_gate.record(state, "GPL-3.0", "yes", "continue", "demo-fixture", None, {})
        _gates.record(state, "access", "unsure", None, "demo-fixture")
        s = run_all.next_step(state)
        self.assertEqual(s["code"], run_all.STOP)

    def test_cli_next_run_refuses_past_unanswered_gate(self):
        state = self.init_state()
        self.open_all_gates(state)
        _gates.record(state, "agreements", "yes", None, "demo-fixture")  # now needs an override
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_all.py"), "--harness", str(self.h), "next", "--run"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 20, r.stdout + r.stderr)
        self.assertIn("agreements", r.stdout)
        self.assertFalse((state / "reports" / "scan.json").exists())
        self.assertFalse((state / "sandbox").exists())

    def test_sandbox_prepare_refuses_without_gates_and_spec(self):
        state = self.init_state()
        with self.assertRaises(sandbox_prepare.Refused):
            sandbox_prepare.prepare(state, "app-rows", "builder")
        self.open_all_gates(state)
        with self.assertRaises(sandbox_prepare.Refused) as cm:
            sandbox_prepare.prepare(state, "app-rows", "builder")
        self.assertIn("allowlist", str(cm.exception))


class TestSandboxPrepare(TempRepos):
    def ready(self):
        state = self.init_state()
        self.open_all_gates(state)
        cfg = load_config(state)
        jdump(state / "reports" / "scan.json", similarity_scan.scan(self.h, self.up, cfg))
        jdump(state / "reports" / "partition.json", partition.partition(state, cfg))
        jdump(state / "allowlist.json", {"names": ["split_row"]})
        _gates.typed_approval(state, "allowlist", "approve allowlist", _gates.ALLOWLIST_APPROVE, "demo-fixture", None,
                              {"sha256": sha256_file(state / "allowlist.json")})
        (state / "specs").mkdir()
        (state / "contracts").mkdir()
        (state / "specs" / "app-rows.md").write_text("# Purpose\nSplits a record into fields.\n", encoding="utf-8")
        (state / "contracts" / "app-rows.md").write_text("# Interface\n- split_row(text, sep) returns a list of strings\n", encoding="utf-8")
        _gates.typed_approval(state, "spec_approvals", "approve spec", _gates.SPEC_APPROVE, "demo-fixture", None,
                              {"sha256": sha256_file(state / "specs" / "app-rows.md"),
                               "contract_sha256": sha256_file(state / "contracts" / "app-rows.md"), "for_attempt": 1}, module="app-rows")
        return state

    def test_test_writer_sandbox_contains_only_approved_inputs(self):
        state = self.ready()
        res = sandbox_prepare.prepare(state, "app-rows", "test-writer")
        self.assertEqual(sorted(res["files"]), ["AGENT.md", "TASK.md", "contract.md", "spec.md"])
        box = Path(res["sandbox"])
        everything = "".join(p.read_text(encoding="utf-8") for p in box.rglob("*") if p.is_file())
        self.assertNotIn("delimiter_char", everything)
        self.assertNotIn("Quillstack", everything)
        self.assertTrue(manifest_check.check(box, json.loads(Path(res["approved"]).read_text()), "pre")["ok"])

    def test_spec_edit_after_approval_refused(self):
        state = self.ready()
        (state / "specs" / "app-rows.md").write_text("# Purpose\nchanged\n", encoding="utf-8")
        with self.assertRaises(sandbox_prepare.Refused) as cm:
            sandbox_prepare.prepare(state, "app-rows", "test-writer")
        self.assertIn("hash mismatch", str(cm.exception))

    def test_builder_needs_filtered_tests(self):
        state = self.ready()
        with self.assertRaises(sandbox_prepare.Refused):
            sandbox_prepare.prepare(state, "app-rows", "builder")


class TestSwap(TempRepos):
    def test_refuses_without_signoff_and_case_map(self):
        state = self.init_state()
        with self.assertRaises(swap_and_clean.Refused):
            swap_and_clean.do_swap(state, "app-rows", dry=True)
        pairs = dict(swap_and_clean.case_map("quill-stack", "bright-ledger"))
        self.assertEqual(pairs["QuillStack"], "BrightLedger")
        self.assertEqual(pairs["quill_stack"], "bright_ledger")
        self.assertEqual(pairs["QUILL_STACK"], "BRIGHT_LEDGER")


class TestDemoFindings(TempRepos):
    def test_vendored_copy_labelled_and_empty_files_ignored(self):
        state = self.init_state()
        (self.up / "quillstack" / "__init__.py").write_text("", encoding="utf-8")
        (self.h / "app" / "__init__.py").write_text("", encoding="utf-8")
        (self.h / "vendor").mkdir()
        (self.h / "vendor" / "ledger.py").write_text(UPSTREAM_CODE, encoding="utf-8")
        cfg = load_config(state)
        jdump(state / "reports" / "scan.json", similarity_scan.scan(self.h, self.up, cfg))
        part = partition.partition(state, cfg)
        labels = {m: i["label"] for m, i in part["modules"].items()}
        self.assertEqual(labels["vendor-ledger"], "vendored")
        self.assertEqual(labels["app-init"], "original")
        jdump(state / "reports" / "partition.json", part)
        self.assertEqual(run_all.modules_to_replace(state, cfg), ["app-rows"])

    def test_leftovers_catch_prose_metadata_and_config_keys(self):
        state = self.init_state()
        prose = "Quillstack is a tiny double-entry ledger toolkit for plain text books and teams.\n"
        (self.up / "README.md").write_text(prose, encoding="utf-8")
        (self.h / "README.md").write_text(prose.replace("Quillstack", "Brightledger"), encoding="utf-8")
        (self.up / "quill.toml").write_text("ledger_delimiter = 1\n", encoding="utf-8")
        (self.h / "settings.toml").write_text("ledger_delimiter = 1\n", encoding="utf-8")
        (self.h / "app" / "rows.py").unlink()
        cfg_path = state / "config.json"
        c = json.loads(cfg_path.read_text())
        c["project_name"] = "Brightledger"
        cfg_path.write_text(json.dumps(c))
        res = swap_and_clean.leftovers(state)
        self.assertTrue(res["docs"], "renamed but copied README prose must still be flagged")
        self.assertEqual([k["key"] for k in res["config_keys"]], ["ledger_delimiter"])
        self.assertFalse(res["clean"])

    def test_feedback_is_file_level_only(self):
        import verify_build
        sim = [{"file": "app/rows.py", "token_overlap": 0.9, "max_function_overlap": 1.0, "shared_strings": 2,
                "shared_comments": 1, "shared_identifiers": 3, "upstream_name_mentions": 1}]
        fb = verify_build.feedback("m", 1, sim, {"ran": True, "ok": False, "max_similarity": 0.8, "limit": 0.3},
                                   {"ok": False, "summary": "1 failed"}, {"passed": False, "mismatches": 2, "cases": 9}, 0.15)
        for leak in ("split_ledger_line", "unterminated", "quoted", "def ", "Quillstack"):
            self.assertNotIn(leak, fb)
        self.assertIn("app/rows.py", fb)
        self.assertIn("0.90", fb)

    def test_equivalence_roundtrip(self):
        import equivalence_run
        cases = [{"function": "split_row", "args": ['a;"b;c"']}, {"function": "split_row", "args": ['x;"y']}]
        old = equivalence_run.execute(self.h / "app" / "rows.py", cases, [str(self.h)], None)
        self.assertEqual(old[0], {"ok": True, "value": ["a", "b;c"]})
        self.assertEqual(old[1]["exc_type"], "ValueError")
        self.assertNotIn("unterminated", json.dumps(old))
        self.assertTrue(all(equivalence_run.same(a, a) for a in old))
        self.assertFalse(equivalence_run.same(old[0], {"ok": True, "value": ["a", "b", "c"]}))


class TestAddons(TempRepos):
    def run_tools(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_OPTION_")}
        e.update(env or {})
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "install_tools.py"), "--dest", str(self.tmp / "tools"), *args],
                              capture_output=True, text=True, env=e)

    def test_status_and_opt_out(self):
        r = self.run_tools("--status")
        st = json.loads(r.stdout)
        self.assertFalse(st["jplag"])
        self.assertFalse(st["scancode"])
        # Both add-ons deselected at install time: the hook does nothing and starts no download.
        r = self.run_tools("--from-plugin-options", "--background",
                           env={"CLAUDE_PLUGIN_OPTION_INSTALL_JPLAG": "false", "CLAUDE_PLUGIN_OPTION_INSTALL_SCANCODE": "false"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertFalse((self.tmp / "tools" / "install.log").exists())

    def test_already_installed_is_noop(self):
        tools = self.tmp / "tools"
        (tools / "jdk" / "jre" / "bin").mkdir(parents=True)
        (tools / "jdk" / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")).write_text("", encoding="utf-8")
        (tools / "jplag.jar").write_text("", encoding="utf-8")
        r = self.run_tools("--from-plugin-options", "--background",
                           env={"CLAUDE_PLUGIN_OPTION_INSTALL_JPLAG": "true", "CLAUDE_PLUGIN_OPTION_INSTALL_SCANCODE": "false"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_tools_dir_from_config_searched_first_and_models_must_differ(self):
        from _common import tools_dirs
        self.assertEqual(tools_dirs({"tools_dir": str(self.tmp / "x")})[0], self.tmp / "x")
        with self.assertRaises(SystemExit):
            run_all.init(self.h, self.up, ["python"], "pytest", "quillstack", "opus", "opus")


class TestBuilderCredential(unittest.TestCase):
    def test_rules(self):
        import sandbox_run
        pick = sandbox_run.builder_credential
        self.assertEqual(pick({}, {"CLEANROOM_BUILDER_OAUTH_TOKEN": "t1"}), ("subscription", {"CLEANROOM_BUILDER_OAUTH_TOKEN": "t1"}))
        self.assertEqual(pick({}, {"CLEANROOM_BUILDER_API_KEY": "k1"})[0], "api_key")
        both = {"CLEANROOM_BUILDER_OAUTH_TOKEN": "t1", "CLEANROOM_BUILDER_API_KEY": "k1"}
        self.assertEqual(pick({}, both)[0], "subscription")
        self.assertEqual(pick({"builder_auth": "api_key"}, both)[0], "api_key")
        with self.assertRaises(ValueError):  # the host's own token must not be reused
            pick({}, {"CLEANROOM_BUILDER_OAUTH_TOKEN": "t1", "CLAUDE_CODE_OAUTH_TOKEN": "t1"})
        with self.assertRaises(ValueError):
            pick({}, {"CLEANROOM_BUILDER_API_KEY": "k1", "ANTHROPIC_API_KEY": "k1"})
        with self.assertRaises(ValueError) as cm:
            pick({}, {})
        self.assertIn("claude setup-token", str(cm.exception))


class TestPathGuard(unittest.TestCase):
    def test_decisions(self):
        cfg = {"upstream": os.path.abspath("up")}
        d = path_guard.decide
        self.assertTrue(d({"tool_name": "Write", "tool_input": {"file_path": "up/a.py"}, "cwd": "."}, cfg))
        self.assertTrue(d({"tool_name": "Bash", "tool_input": {"command": "echo x > .cleanroom/risk_decisions.json"}, "cwd": "."}, cfg))
        self.assertIsNone(d({"tool_name": "Bash", "tool_input": {"command": "python cleanroom/scripts/risk_gate.py status"}, "cwd": "."}, cfg))
        self.assertTrue(d({"tool_name": "Read", "tool_input": {"file_path": "x"}, "agent_type": "cleanroom:test-writer", "cwd": "."}, cfg))
        self.assertTrue(d({"tool_name": "WebFetch", "tool_input": {"url": "https://github.com"}, "agent_type": "cleanroom:analyzer", "cwd": "."}, cfg))
        self.assertIsNone(d({"tool_name": "Write", "tool_input": {"file_path": ".cleanroom/contracts/m.md"}, "agent_type": "cleanroom:analyzer", "cwd": "."}, cfg))


class TestCliHelp(unittest.TestCase):
    def test_every_script_has_help(self):
        for p in sorted((ROOT / "scripts").glob("*.py")):
            if p.name.startswith("_"):
                continue
            r = subprocess.run([sys.executable, str(p), "--help"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{p.name}: {r.stderr}")
            self.assertIn("usage", r.stdout.lower(), p.name)


if __name__ == "__main__":
    unittest.main()
