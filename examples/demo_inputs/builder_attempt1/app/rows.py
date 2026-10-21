"""Row splitting."""
# DEMO STAND-IN for a FAILED attempt: deliberately reproduces upstream structure, comments and messages,
# to show that verify catches it and that the feedback to the builder carries file-level scores only.


def split_ledger_line(line, sep=";"):
    """Split one ledger line into trimmed fields, honouring double-quoted sections."""
    # walk every character and honour quoted sections of the ledger
    out, cur, inq = [], [], False
    for c in line:
        if c == '"':
            inq = not inq
        elif c == sep and not inq:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    out.append("".join(cur).strip())
    if inq:
        raise ValueError("Quillstack: unterminated quote in ledger line")
    return out


def column_total(lines, column=2, sep=";"):
    """Sum the integer amount column of many ledger lines, skipping blank lines and comments."""
    total = 0
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = split_ledger_line(line, sep)
        try:
            total += int(parts[column])
        except (IndexError, ValueError):
            raise ValueError("Quillstack: bad amount column in ledger line")
    return total
