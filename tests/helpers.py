import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "hooks"))

UPSTREAM_CODE = '''"""Tokenize ledger lines for the Quillstack engine."""
# Copyright (c) 2021 Quillstack Authors
# SPDX-License-Identifier: GPL-3.0-or-later


def split_ledger_line(raw_line, delimiter_char=";"):
    # walk every character and honour quoted sections of the ledger
    fields, current, quoted = [], [], False
    for ch in raw_line:
        if ch == '"':
            quoted = not quoted
        elif ch == delimiter_char and not quoted:
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    fields.append("".join(current).strip())
    if quoted:
        raise ValueError("Quillstack: unterminated quote in ledger line")
    return fields
'''

ORIGINAL_CODE = '''def greet(person):
    return "hello " + person


class Counter:
    def __init__(self):
        self.n = 0

    def bump(self):
        self.n += 1
        return self.n
'''


class TempRepos(unittest.TestCase):
    """Creates upstream/ and harness/ with one copied (tainted) and one original module."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cleanroom-test-"))
        self.up = self.tmp / "quillstack"
        self.h = self.tmp / "harness"
        (self.up / "quillstack").mkdir(parents=True)
        (self.h / "app").mkdir(parents=True)
        (self.up / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE\n   Version 3, 29 June 2007\n... patent license ...\n", encoding="utf-8")
        (self.up / "quillstack" / "ledger.py").write_text(UPSTREAM_CODE, encoding="utf-8")
        copied = UPSTREAM_CODE.replace("split_ledger_line", "split_row").replace("raw_line", "line")
        (self.h / "app" / "rows.py").write_text(copied, encoding="utf-8")
        (self.h / "app" / "hello.py").write_text(ORIGINAL_CODE, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def init_state(self, demo=True):
        import run_all
        return run_all.init(self.h, self.up, ["python"], "pytest -q", "quillstack", "opus", "sonnet", synthetic_demo=demo)

    def open_all_gates(self, state):
        import _gates
        import license_gate
        license_gate.record(state, "GPL-3.0", "yes", "continue", "demo-fixture", None, {"detected": "GPL-3.0"})
        ctx = {"patent_findings": [], "upstream_name": "quillstack"}
        _gates.record(state, "access", "yes", None, "demo-fixture", ctx=ctx)
        _gates.record(state, "agreements", "no", None, "demo-fixture", ctx=ctx)
        _gates.record(state, "patents", "no", None, "demo-fixture", ctx=ctx)
        _gates.record(state, "use", "no", None, "demo-fixture", ctx=ctx)
        _gates.record(state, "name", "Brightledger", None, "demo-fixture", ctx=ctx)
        _gates.record(state, "contamination", "I understand", None, "demo-fixture", ctx=ctx)


def jdump(p, o):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(o), encoding="utf-8")
