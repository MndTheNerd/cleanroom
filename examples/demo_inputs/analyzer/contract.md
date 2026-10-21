# Interface contract: app-rows

Module file: app/rows.py (Python 3). Other harness code imports it as a module of package app.

Public operations:
- split_ledger_line(line, sep) where sep defaults to a semicolon. Returns a list of strings.
  (Name kept for compatibility: app/report.py calls it with one positional argument.)
- column_total(lines, column, sep) where column defaults to 2 and sep to a semicolon. Returns an integer.

Both operations raise the built-in ValueError for every error case in spec.md.
No other public names are required.
