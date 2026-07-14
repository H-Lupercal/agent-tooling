from pathlib import Path

import pytest

from agent_harness.config import load_config


def _write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_config_rejects_capacity_below_root_roster(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "agent-harness.toml",
        """
[capacity]
max_participants = 1
max_dynamic_children = 0
max_children_per_parent = 0
max_spawn_depth = 0
max_simultaneous_speakers = 1
[budgets]
tokens = 1000
[room]
queue_size = 10
[[participants]]
id = "a"
adapter = "fake"
model = "offline"
roles = ["builder"]
context_limit = 1000
[[participants]]
id = "b"
adapter = "fake"
model = "offline"
roles = ["reviewer"]
context_limit = 1000
""",
    )

    with pytest.raises(ValueError, match="root roster"):
        load_config(config)


def test_config_rejects_unknown_root_key(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "agent-harness.toml", "surprise = true\n")

    with pytest.raises(ValueError, match="unknown root key"):
        load_config(config)


def test_config_rejects_duplicate_participant_ids(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "agent-harness.toml",
        """
[capacity]
max_participants = 2
max_dynamic_children = 0
max_children_per_parent = 0
max_spawn_depth = 0
max_simultaneous_speakers = 1
[budgets]
tokens = 1000
[room]
queue_size = 10
[[participants]]
id = "same"
adapter = "fake"
model = "offline"
roles = ["builder"]
context_limit = 1000
[[participants]]
id = "same"
adapter = "fake"
model = "offline"
roles = ["reviewer"]
context_limit = 1000
""",
    )

    with pytest.raises(ValueError, match="duplicate participant ID"):
        load_config(config)


def test_config_accepts_credential_environment_variable_name(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "agent-harness.toml",
        """
[capacity]
max_participants = 1
max_dynamic_children = 0
max_children_per_parent = 0
max_spawn_depth = 0
max_simultaneous_speakers = 1
[budgets]
tokens = 1000
[room]
queue_size = 10
[[participants]]
id = "api-agent"
adapter = "openai-compatible"
model = "specialist"
roles = ["builder"]
context_limit = 1000
credential_env = "SPECIALIST_API_KEY"
""",
    )

    parsed = load_config(config)

    assert parsed.credential_env == {"api-agent": "SPECIALIST_API_KEY"}
