from __future__ import annotations

import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def copy_fixture_repo(name: str, tmpdir: str | Path, git: bool = True) -> Path:
    src = FIXTURES / "repos" / name
    dst = Path(tmpdir) / name
    shutil.copytree(src, dst)
    if git:
        git_dir = dst / ".git"
        git_dir.mkdir(exist_ok=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return dst


def fixture_state_env(root: Path) -> dict[str, str]:
    state = FIXTURES / "state"
    fake = ROOT / "tests" / "fake_bin"
    suffix = ".cmd" if os.name == "nt" else ""
    env = os.environ.copy()
    env.update(
        {
            "TOOLBELT_CLAUDE_STATE": str(state / "claude_state.json"),
            "TOOLBELT_CLAUDE_PLUGINS": str(state / "installed_plugins.json"),
            "TOOLBELT_CODEX_CONFIG": str(state / "codex_config.toml"),
            "TOOLBELT_CLAUDE_BIN": str(fake / f"claude{suffix}"),
            "TOOLBELT_CODEX_BIN": str(fake / f"codex{suffix}"),
            "PATH": f"{fake}{os.pathsep}{env.get('PATH', '')}",
        }
    )
    return env
