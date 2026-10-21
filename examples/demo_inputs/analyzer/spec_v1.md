# Behavior: record splitting and column totals

## Purpose
Turns one line of a plain-text bookkeeping file into an ordered list of text fields, and adds up one
numeric field across many such lines.

## Inputs
- Split: one text line, plus an optional single separator character (default: semicolon).
- Total: a sequence of text lines, an optional zero-based field position (default: 2), and the same optional separator.

## Outputs
- Split returns a list of strings in left-to-right order. Every field has leading and trailing whitespace removed.
- A line without any separator gives exactly one field. An empty line gives one empty field.
- Two separators in a row produce an empty field between them.
- A double quote character starts or ends a protected region. Separators inside a protected region belong
  to the field. The double quote characters themselves never appear in the output.
- Total returns the integer sum of the chosen field over every line that is not blank and whose first
  non-space character is not a hash sign. Such skipped lines are ignored entirely.

## Error cases
- Split: an unclosed protected region (an odd count of double quotes) raises a value error.
- Total: a counted line that has too few fields, or whose chosen field is not a whole number, raises a value error.
- Errors from splitting a counted line propagate unchanged in category.

## Side effects
None. Both operations are pure functions of their arguments.

## Invariants
- Output order always matches field order in the input.
- Total of an empty sequence is zero.

## Performance limits
Linear in the length of the input; lines up to one megabyte must be handled.

## Examples
| Operation | Input | Result |
|---|---|---|
| split | a;b;c | three fields a, b, c |
| split | x ; y | two fields x and y |
| split | p;"q;r";s | three fields p, q;r and s |
| split | m;;n | three fields m, empty, n |
| split, comma separator | u,v | two fields u and v |
| total of field 2 | lines k;l;3 and k;l;4 plus a hash-sign line | 7 |
