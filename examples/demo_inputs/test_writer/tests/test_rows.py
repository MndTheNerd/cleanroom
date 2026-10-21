import pytest

from app.rows import column_total, split_ledger_line


def test_plain_fields():
    assert split_ledger_line("a;b;c") == ["a", "b", "c"]


def test_whitespace_trimmed():
    assert split_ledger_line("  x ; y ") == ["x", "y"]


def test_protected_region_keeps_separator():
    assert split_ledger_line('p;"q;r";s') == ["p", "q;r", "s"]


def test_empty_between_separators():
    assert split_ledger_line("m;;n") == ["m", "", "n"]


def test_no_separator_and_empty_line():
    assert split_ledger_line("solo") == ["solo"]
    assert split_ledger_line("") == [""]


def test_other_separator():
    assert split_ledger_line("u,v", ",") == ["u", "v"]


def test_unclosed_region_is_value_error():
    with pytest.raises(ValueError):
        split_ledger_line('a;"b')


def test_total_skips_blank_and_hash_lines():
    assert column_total(["k;l;3", "   ", "# skip me", "k;l;4"]) == 7


def test_total_of_nothing_is_zero():
    assert column_total([]) == 0


def test_total_missing_field_is_value_error():
    with pytest.raises(ValueError):
        column_total(["k;l"])


def test_total_non_number_is_value_error():
    with pytest.raises(ValueError):
        column_total(["k;l;many"])
