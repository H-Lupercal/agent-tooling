from install_rehearsal.redaction import build_child_environment, redact_argv, redact_text


def test_environment_drops_credentials_and_sorts_keys() -> None:
    result = build_child_environment(
        {"PATH": "/bin", "OPENAI_API_KEY": "secret", "LANG": "C.UTF-8", "RANDOM": "drop"},
        {"HOME": "/tmp/profile"},
    )

    assert result == {"HOME": "/tmp/profile", "LANG": "C.UTF-8", "PATH": "/bin"}
    assert list(result) == ["HOME", "LANG", "PATH"]


def test_redact_text_masks_secret_assignments_and_bearer_tokens() -> None:
    assert redact_text("TOKEN=abc123") == "TOKEN=[REDACTED]"
    assert redact_text("Authorization: Bearer abc.def") == "Authorization: Bearer [REDACTED]"


def test_redact_argv_masks_inline_and_following_secret_values() -> None:
    assert redact_argv(("tool", "--token", "abc", "--password=hunter2", "ok")) == (
        "tool",
        "--token",
        "[REDACTED]",
        "--password=[REDACTED]",
        "ok",
    )
