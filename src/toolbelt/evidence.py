from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import tomllib
from pathlib import Path

from toolbelt.models import Evidence, SKIP_DIRS


MANIFEST_FILES = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    "composer.json",
]
EXT_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".tf": "terraform",
    ".sql": "sql",
    ".sh": "shell",
}


def _walk(root: Path):
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield path


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _dep_name(spec: str) -> str:
    return re.split(r"[ <>=!~\[;(\n]", spec.strip(), maxsplit=1)[0].lower()


def _manifest_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    paths: list[Path] = []
    for path in _walk(root):
        if path.is_file() and (path.name in MANIFEST_FILES or fnmatch.fnmatch(path.name, "*.csproj")):
            paths.append(path)
    return sorted(set(paths))


def detect_manifest_files(root: Path) -> list[Evidence]:
    return [
        Evidence("manifest_file", path.name, path.relative_to(root).as_posix(), 2, _rel(root, path))
        for path in _manifest_paths(root)
    ]


def detect_manifest_deps(root: Path) -> list[Evidence]:
    evidence: list[Evidence] = []
    for path in _manifest_paths(root):
        name = path.name
        try:
            if name == "package.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                for section in ("dependencies", "devDependencies"):
                    for dep, spec in (data.get(section) or {}).items():
                        evidence.append(Evidence("manifest_dep", f"{name}:{dep.lower()}", str(spec), 3, _rel(root, path)))
            elif name == "pyproject.toml":
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                for spec in (data.get("project") or {}).get("dependencies") or []:
                    dep = _dep_name(spec)
                    if dep:
                        evidence.append(Evidence("manifest_dep", f"{name}:{dep}", spec, 3, _rel(root, path)))
                poetry = (((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {})
                for dep, spec in poetry.items():
                    if dep.lower() != "python":
                        evidence.append(Evidence("manifest_dep", f"{name}:{dep.lower()}", str(spec), 3, _rel(root, path)))
            elif name == "requirements.txt":
                for line in path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        dep = _dep_name(stripped)
                        if dep:
                            evidence.append(Evidence("manifest_dep", f"{name}:{dep}", stripped, 3, _rel(root, path)))
            elif name == "go.mod":
                in_block = False
                for line in path.read_text(encoding="utf-8").splitlines():
                    s = line.strip()
                    if s.startswith("require ("):
                        in_block = True
                        continue
                    if in_block and s == ")":
                        in_block = False
                        continue
                    if s.startswith("require "):
                        dep = s.split()[1]
                        evidence.append(Evidence("manifest_dep", f"{name}:{dep}", s, 3, _rel(root, path)))
                    elif in_block and s:
                        dep = s.split()[0]
                        evidence.append(Evidence("manifest_dep", f"{name}:{dep}", s, 3, _rel(root, path)))
            elif name == "Cargo.toml":
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                for dep, spec in (data.get("dependencies") or {}).items():
                    evidence.append(Evidence("manifest_dep", f"{name}:{dep.lower()}", str(spec), 3, _rel(root, path)))
        except (json.JSONDecodeError, tomllib.TOMLDecodeError, OSError, IndexError):
            continue
    return evidence


def detect_lang_ext(root: Path) -> list[Evidence]:
    counts: dict[str, int] = {}
    first: dict[str, Path] = {}
    for path in _walk(root):
        if path.is_file() and path.suffix in EXT_LANG:
            lang = EXT_LANG[path.suffix]
            counts[lang] = counts.get(lang, 0) + 1
            first.setdefault(lang, path)
    return [
        Evidence("lang_ext", lang, f"{count} files", 1, _rel(root, first[lang]))
        for lang, count in sorted(counts.items())
    ]


def detect_infra(root: Path) -> list[Evidence]:
    out: list[Evidence] = []
    for path in _walk(root):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        lower = path.name.lower()
        keys: list[str] = []
        if path.name == "Dockerfile" or lower.endswith(".dockerfile"):
            keys.append("dockerfile")
        if fnmatch.fnmatch(lower, "docker-compose*.yml") or fnmatch.fnmatch(lower, "docker-compose*.yaml"):
            keys.append("compose")
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if "image: postgres" in text or 'image: "postgres' in text:
                keys.append("postgres")
        if path.suffix == ".tf":
            keys.append("terraform")
        if fnmatch.fnmatch(rel, ".github/workflows/*.yml") or fnmatch.fnmatch(rel, ".github/workflows/*.yaml"):
            keys.append("github_actions")
        if path.name == "Makefile":
            keys.append("make")
        for key in keys:
            out.append(Evidence("infra", key, rel, 2, _rel(root, path)))
    return out


def detect_test_setup(root: Path) -> list[Evidence]:
    out: list[Evidence] = []
    for pattern, key in (
        ("playwright.config.*", "playwright"),
        ("cypress.config.*", "cypress"),
        ("jest.config.*", "jest"),
        ("vitest.config.*", "vitest"),
    ):
        matches = sorted(root.glob(pattern))
        if matches:
            path = matches[0]
            out.append(Evidence("test_setup", key, path.relative_to(root).as_posix(), 3, _rel(root, path)))
    if (root / "cypress").is_dir():
        out.append(Evidence("test_setup", "cypress", "cypress", 3, _rel(root, root / "cypress")))
    if (root / "pytest.ini").exists():
        out.append(Evidence("test_setup", "pytest", "pytest.ini", 3, _rel(root, root / "pytest.ini")))
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            if (((data.get("tool") or {}).get("pytest") or {}).get("ini_options")) is not None:
                out.append(Evidence("test_setup", "pytest", "pyproject.toml", 3, _rel(root, pyproject)))
        except tomllib.TOMLDecodeError:
            pass
    return out


def detect_existing_tools(root: Path) -> list[Evidence]:
    out: list[Evidence] = []
    project = root / ".mcp.json"
    if project.exists():
        try:
            data = json.loads(project.read_text(encoding="utf-8"))
            for name in sorted((data.get("mcpServers") or {}).keys()):
                out.append(Evidence("existing_tool", f"claude_mcp:{name}", ".mcp.json", 0, _rel(root, project)))
        except json.JSONDecodeError:
            pass
    from toolbelt import harness

    for name in harness.codex_mcp_servers():
        out.append(Evidence("existing_tool", f"codex_mcp:{name}", "codex config", 0, "codex config"))
    for plugin in harness.claude_plugins():
        out.append(Evidence("existing_tool", f"claude_plugin:{plugin}", "claude plugins", 0, "claude plugins"))
    return out


def scan(root: Path) -> list[Evidence]:
    root = Path(root)
    all_evidence: dict[tuple[str, str, str], Evidence] = {}
    for detector in (
        detect_manifest_files,
        detect_manifest_deps,
        detect_lang_ext,
        detect_infra,
        detect_test_setup,
        detect_existing_tools,
    ):
        for item in detector(root):
            all_evidence[(item.type, item.key, item.detail)] = item
    return sorted(all_evidence.values(), key=lambda e: (e.type, e.key, e.detail))


def evidence_sha256(evidence: list[Evidence]) -> str:
    lines = sorted(f"{e.type}|{e.key}|{e.detail}" for e in evidence)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def scan_v2(root: str | Path, **kwargs):
    """Bridge to the pure v2 scanner during the staged package replacement."""

    from toolbelt.scanner import scan_repository

    return scan_repository(root, **kwargs)
