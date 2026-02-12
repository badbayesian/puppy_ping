from puppyping.email_utils import (
    is_valid_email,
    parse_email_list,
    sanitize_email,
    sanitize_emails,
)


def test_sanitize_email_normalizes_value():
    assert sanitize_email("  USER+one@Example.com ") == "user+one@example.com"


def test_sanitize_email_rejects_invalid_and_injected_values():
    assert sanitize_email("Name <user@example.com>") is None
    assert sanitize_email("user@example.com\r\nbcc:bad@example.com") is None
    assert sanitize_email("bad@@example.com") is None
    assert is_valid_email("user@example.com") is True
    assert is_valid_email("invalid") is False


def test_sanitize_emails_filters_and_dedupes():
    candidates = [
        "A@Example.com",
        "a@example.com ",
        "bad@@example.com",
        "Name <x@example.com>",
        "b@example.com",
    ]
    assert sanitize_emails(candidates) == ["a@example.com", "b@example.com"]


def test_parse_email_list_splits_common_delimiters():
    raw = "a@example.com; b@example.com,\nc@example.com"
    assert parse_email_list(raw) == ["a@example.com", "b@example.com", "c@example.com"]
