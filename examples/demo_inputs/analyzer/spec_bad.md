# Spec for rows (first draft, deliberately bad)

```python
def split_ledger_line(raw_line, delimiter_char=";"):
```

The function will walk every character and honour quoted sections of the ledger.
When the quote is left open it raises "Quillstack: unterminated quote in ledger line".
It uses QUOTE_MARK and keeps a `current` buffer.
