#!/usr/bin/env python3
"""Create a small FAKE upstream/harness pair for exercising the pipeline.

  make_demo.py --dest DIR      creates DIR/quillstack (upstream, GPL-3.0) and DIR/acme-books (harness)

The harness deliberately contains every kind of leftover the plugin must find:
  app/rows.py          copied from upstream with identifiers renamed (tainted)
  app/report.py        original code that depends on app/rows.py through its public function
  vendor/quillstack/   byte-identical vendored upstream file
  README.md            a paragraph copied from upstream's README and the upstream name
  pyproject.toml       description copied from upstream
  settings.toml        upstream config keys
  git remote 'upstream' pointing at the upstream repo
"""
import argparse
import os
import shutil
import stat
import subprocess
from pathlib import Path

UP_LEDGER = '''"""Ledger line tokenizer for Quillstack."""
# Copyright (c) 2021 Quillstack Authors
# SPDX-License-Identifier: GPL-3.0-or-later

QUOTE_MARK = '"'


def split_ledger_line(raw_line, delimiter_char=";"):
    """Split one ledger line into trimmed fields, honouring double-quoted sections."""
    # walk every character and honour quoted sections of the ledger
    fields, current, quoted = [], [], False
    for ch in raw_line:
        if ch == QUOTE_MARK:
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


def ledger_totals(lines, amount_column=2, delimiter_char=";"):
    """Sum the integer amount column of many ledger lines, skipping blank lines and comments."""
    total_amount = 0
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        parts = split_ledger_line(raw_line, delimiter_char)
        try:
            total_amount += int(parts[amount_column])
        except (IndexError, ValueError):
            raise ValueError("Quillstack: bad amount column in ledger line")
    return total_amount
'''

UP_README = """# Quillstack

Quillstack is a tiny double-entry ledger toolkit for plain text books.
It reads semicolon separated ledger lines, honours quoted sections, and
sums the amount column so that small teams can keep their books in git.

Configure it with `ledger_delimiter` and `amount_column` in quill.toml.
"""

HARNESS_REPORT = '''"""Monthly summary for Acme Books."""
from app.rows import split_ledger_line


def monthly_summary(text):
    """Return (row_count, first_names) for a block of records."""
    rows = [split_ledger_line(l) for l in text.splitlines() if l.strip()]
    return len(rows), [r[0] for r in rows if r]
'''

HARNESS_README = """# Acme Books

Acme Books is our internal bookkeeping tool, originally based on Quillstack.

Quillstack is a tiny double-entry ledger toolkit for plain text books.
It reads semicolon separated ledger lines, honours quoted sections, and
sums the amount column so that small teams can keep their books in git.
"""

HARNESS_TEST = '''from app.report import monthly_summary


def test_summary():
    assert monthly_summary("a;1\\nb;2\\n") == (2, ["a", "b"])
'''


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", required=True)
    args = ap.parse_args()
    dest = Path(args.dest)
    if dest.exists():
        # git marks object files read-only on Windows
        shutil.rmtree(dest, onexc=lambda fn, p, e: (os.chmod(p, stat.S_IWRITE), fn(p)))
    up, h = dest / "quillstack", dest / "acme-books"

    (up / "quillstack").mkdir(parents=True)
    (up / "LICENSE").write_text(
        "                    GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007\n\n"
        " Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>\n\n"
        "  [Full license text omitted in this fake fixture.]\n\n"
        "  11. Patents. Each contributor grants you a non-exclusive, worldwide, royalty-free patent license...\n",
        encoding="utf-8")
    (up / "README.md").write_text(UP_README, encoding="utf-8")
    (up / "pyproject.toml").write_text('[project]\nname = "quillstack"\ndescription = "A tiny double-entry ledger toolkit for plain text books"\nlicense = {text = "GPL-3.0-or-later"}\n', encoding="utf-8")
    (up / "quill.toml").write_text("ledger_delimiter = \";\"\namount_column = 2\n", encoding="utf-8")
    (up / "quillstack" / "__init__.py").write_text("", encoding="utf-8")
    (up / "quillstack" / "ledger.py").write_text(UP_LEDGER, encoding="utf-8")

    (h / "app").mkdir(parents=True)
    (h / "tests").mkdir()
    (h / "vendor" / "quillstack").mkdir(parents=True)
    copied = UP_LEDGER.replace("Ledger line tokenizer for Quillstack.", "Row splitting for Acme Books.") \
                      .replace("ledger_totals", "column_total").replace("total_amount", "acc")
    (h / "app" / "__init__.py").write_text("", encoding="utf-8")
    (h / "app" / "rows.py").write_text(copied, encoding="utf-8")
    (h / "app" / "report.py").write_text(HARNESS_REPORT, encoding="utf-8")
    (h / "vendor" / "quillstack" / "ledger.py").write_text(UP_LEDGER, encoding="utf-8")
    (h / "README.md").write_text(HARNESS_README, encoding="utf-8")
    (h / "pyproject.toml").write_text('[project]\nname = "acme-books"\ndescription = "A tiny double-entry ledger toolkit for plain text books"\n', encoding="utf-8")
    (h / "settings.toml").write_text("ledger_delimiter = \";\"\namount_column = 2\nreport_title = \"Acme\"\n", encoding="utf-8")
    (h / "tests" / "test_report.py").write_text(HARNESS_TEST, encoding="utf-8")
    (h / "conftest.py").write_text("", encoding="utf-8")

    for repo in (up, h):
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "demo@example.invalid")
        git(repo, "config", "user.name", "demo")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "initial")
    git(h, "remote", "add", "upstream", str(up))
    print(f"created {up} and {h}")


if __name__ == "__main__":
    main()
