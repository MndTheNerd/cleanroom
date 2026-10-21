# Build notes (demo stand-in)

- Quote handling: an odd quote count is rejected up front; the text is then cut at quotes, and only
  unquoted segments are cut at the separator.
- Field position check accepts negative positions, matching the spec's sequence-indexing rule.
