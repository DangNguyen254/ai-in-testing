"""Secret scrubber. Fake secrets are built by concatenation so the repo scan stays clean."""

from __future__ import annotations

import pytest

from ticket2test.security import scrub, scrub_text

AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB = "ghp_" + "a1B2" * 9
ANTHROPIC = "sk-ant-" + "api03-" + "x" * 30
OPENAI_STYLE = "sk-" + "proj-" + "Y" * 30
GOOGLE = "AIza" + "S" * 35
SLACK = "xoxb-" + "1234567890-abcdef"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0In0" + "." + "c2lnbmF0dXJlLXZhbHVl"
BEARER = "Q" * 24


@pytest.mark.parametrize(
    ("text", "kind", "secret"),
    [
        (f"aws key {AWS} here", "aws_access_key", AWS),
        (f"token {GITHUB}", "github_token", GITHUB),
        (f"ANTHROPIC={ANTHROPIC}", "anthropic_key", ANTHROPIC),
        (f"key: {OPENAI_STYLE}", "api_key", OPENAI_STYLE),
        (f"maps key {GOOGLE}", "google_api_key", GOOGLE),
        (f"slack {SLACK}", "slack_token", SLACK),
        (f"jwt {JWT}", "jwt", JWT),
    ],
)
def test_api_key_like_strings(text: str, kind: str, secret: str) -> None:
    result = scrub(text)
    assert secret not in result.text
    assert f"[REDACTED:{kind}]" in result.text
    assert result.counts[kind] == 1


def test_bearer_token_keeps_prefix() -> None:
    result = scrub(f"Authorization: Bearer {BEARER}")
    assert result.text == "Authorization: Bearer [REDACTED:bearer_token]"


def test_basic_auth_header() -> None:
    encoded = "dXNlcjpwYXNz" + "d29yZA=="
    assert scrub_text(f"Authorization: Basic {encoded}") == (
        "Authorization: Basic [REDACTED:basic_auth]"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://alice:" + "s3cr3t" + "@example.com/path",
            "https://alice:" + "[REDACTED:password_in_url]" + "@example.com/path",
        ),
        (
            "postgres://app:" + "pw123" + "@db.example.com:5432/main",
            "postgres://app:" + "[REDACTED:password_in_url]" + "@db.example.com:5432/main",
        ),
        (
            "http://proxy-user:" + "p%40ss" + "@proxy.example.com:3128",
            "http://proxy-user:" + "[REDACTED:password_in_url]" + "@proxy.example.com:3128",
        ),
    ],
)
def test_password_in_url(url: str, expected: str) -> None:
    assert scrub_text(url) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("password=" + "hunter22", "password=[REDACTED:credential_assignment]"),
        ('"api_key": "' + "abcd1234" + '"', '"api_key": "[REDACTED:credential_assignment]"'),
        (
            "Server=db;User Id=app;Password=" + "Pa55word" + ";",
            "Server=db;User Id=app;Password=[REDACTED:credential_assignment];",
        ),
        ("CLIENT_SECRET: " + "zzzz9999", "CLIENT_SECRET: [REDACTED:credential_assignment]"),
    ],
)
def test_credential_assignments_and_connection_strings(text: str, expected: str) -> None:
    assert scrub_text(text) == expected


def test_private_key_block() -> None:
    block = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA " + "PRIVATE KEY-----"
    assert scrub_text(f"key:\n{block}\nafter") == "key:\n[REDACTED:private_key]\nafter"


@pytest.mark.parametrize(
    "text",
    [
        "token = get_token()",
        "def __init__(self, **kwargs): pass",
        "client = httpx.Client(base_url='https://example.org/some/path')",
        'WWW-Authenticate: Digest realm="server", nonce="4f3b1a0c93d39d1c"',
        "https://github.com/encode/httpx/issues/1407",
        "password = ''",  # too short to be a secret
        "Bearer short",
    ],
)
def test_ordinary_text_is_untouched(text: str) -> None:
    result = scrub(text)
    assert result.text == text
    assert result.redacted == 0


def test_scrubbing_is_idempotent() -> None:
    once = scrub_text(f"Bearer {BEARER} and {AWS}")
    assert scrub_text(once) == once
