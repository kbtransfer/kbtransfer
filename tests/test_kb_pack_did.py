"""Tests for kb_pack.did.did_to_safe_path."""

from __future__ import annotations

import pytest

from kb_pack import did_to_safe_path


@pytest.mark.parametrize(
    "did, expected",
    [
        ("did:web:example.com", "did-web-example.com"),
        ("did:web:gkhnfdn.github.io", "did-web-gkhnfdn.github.io"),
        ("did:web:example.com:ports:8080", "did-web-example.com-ports-8080"),
        ("did:web:example.com/user/alice", "did-web-example.com-user-alice"),
        ("did:key:z6Mk...xyz", "did-key-z6Mk...xyz"),
    ],
)
def test_encoding_matches_reference(did: str, expected: str) -> None:
    assert did_to_safe_path(did) == expected


def test_output_is_deterministic() -> None:
    a = did_to_safe_path("did:web:example.com:8443")
    b = did_to_safe_path("did:web:example.com:8443")
    assert a == b


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "web:example.com",
        "http://example.com",
        "DID:web:upper-case-scheme",
    ],
)
def test_non_did_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        did_to_safe_path(bad)


@pytest.mark.parametrize(
    "bad",
    [
        "did:web:bad\x00char",
        "did:web:bad\\slash",
        "did:web:bad\x1fcontrol",
    ],
)
def test_forbidden_characters_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        did_to_safe_path(bad)


def test_non_string_input_rejected() -> None:
    with pytest.raises(ValueError):
        did_to_safe_path(None)  # type: ignore[arg-type]


def test_output_has_no_path_separators() -> None:
    # The encoded name must be a single path component, never a path.
    encoded = did_to_safe_path("did:web:example.com:8080/a/b")
    assert "/" not in encoded
    assert ":" not in encoded
