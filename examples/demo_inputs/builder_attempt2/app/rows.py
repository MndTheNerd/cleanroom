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
