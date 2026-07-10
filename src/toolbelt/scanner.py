from __future__ import annotations

import fnmatch
import json
import os
import re
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import islice
from pathlib import Path, PurePosixPath
from typing import Literal, overload

from toolbelt.ignore import IgnoreRules
from toolbelt.schemas import EvidenceStrength, EvidenceV2

_MANIFEST_FILES = frozenset(
    {
        "Cargo.toml",
        "Gemfile",
        "go.mod",
        "package.json",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
    }
)
_LANGUAGE_EXTENSIONS = {
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".sql": "sql",
    ".tf": "terraform",
    ".ts": "typescript",
    ".tsx": "typescript",
}


@dataclass(frozen=True, slots=True)
class ScanLimits:
    max_files: int = 25_000
    max_depth: int = 20
    max_bytes: int = 32 * 1024 * 1024
    max_warnings: int = 100

    def __post_init__(self) -> None:
        for field_name in ("max_files", "max_depth", "max_bytes", "max_warnings"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must not be negative")


@dataclass(frozen=True, slots=True, order=True)
class ScanWarning:
    code: str
    source: str
    message: str


@dataclass(frozen=True, slots=True)
class ScanResult(Sequence[EvidenceV2]):
    evidence: tuple[EvidenceV2, ...]
    warnings: tuple[ScanWarning, ...]
    files_scanned: int
    bytes_scanned: int

    def __iter__(self) -> Iterator[EvidenceV2]:
        return iter(self.evidence)

    def __len__(self) -> int:
        return len(self.evidence)

    @overload
    def __getitem__(self, index: int) -> EvidenceV2: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[EvidenceV2, ...]: ...

    def __getitem__(self, index: int | slice) -> EvidenceV2 | tuple[EvidenceV2, ...]:
        return self.evidence[index]


@dataclass(frozen=True, slots=True)
class _FileRecord:
    path: Path
    source: str
    size: int


class _Warnings:
    def __init__(self, maximum: int):
        self._maximum = max(0, maximum)
        self._items: list[ScanWarning] = []
        self._seen: set[tuple[str, str, str]] = set()

    def add(self, code: str, source: str, message: str) -> None:
        item = ScanWarning(code, source, message)
        identity = (item.code, item.source, item.message)
        if identity in self._seen or len(self._items) >= self._maximum:
            return
        self._seen.add(identity)
        self._items.append(item)

    def result(self) -> tuple[ScanWarning, ...]:
        return tuple(sorted(self._items))


def scan_repository(
    root: str | Path,
    *,
    limits: ScanLimits | None = None,
    include_fixtures: bool = False,
) -> ScanResult:
    """Collect repository evidence without importing code or writing state."""

    selected_root = Path(root)
    if selected_root.is_symlink():
        raise ValueError("repository root must not be a symlink")
    try:
        resolved_root = selected_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("repository root does not exist") from exc
    if not resolved_root.is_dir():
        raise ValueError("repository root must be a directory")

    active_limits = limits or ScanLimits()
    warnings = _Warnings(active_limits.max_warnings)
    rules = IgnoreRules.from_root(
        resolved_root,
        include_fixtures=include_fixtures,
    )
    for warning in rules.warnings:
        warnings.add("ignore_error", warning.source, warning.message)

    records, bytes_scanned = _collect_files(
        resolved_root,
        rules,
        active_limits,
        warnings,
    )
    evidence = _collect_evidence(resolved_root, records, warnings)
    ordered = tuple(
        sorted(
            evidence.values(),
            key=lambda item: (item.type, item.key, item.source, item.detail),
        )
    )
    return ScanResult(ordered, warnings.result(), len(records), bytes_scanned)


def _collect_files(
    root: Path,
    root_rules: IgnoreRules,
    limits: ScanLimits,
    warnings: _Warnings,
) -> tuple[tuple[_FileRecord, ...], int]:
    records: list[_FileRecord] = []
    bytes_scanned = 0
    entries_seen = 0
    stopped = False
    stack: list[tuple[Path, PurePosixPath, IgnoreRules]] = [(root, PurePosixPath("."), root_rules)]

    while stack and not stopped:
        directory, relative_directory, rules = stack.pop()
        remaining = max(0, limits.max_files - entries_seen)
        try:
            with os.scandir(directory) as iterator:
                entries = list(islice(iterator, remaining + 1))
        except OSError as exc:
            warnings.add(
                "traversal_error",
                relative_directory.as_posix(),
                _safe_os_error("could not read directory", exc),
            )
            continue

        has_more_entries = len(entries) > remaining
        if has_more_entries:
            entries = entries[:remaining]
        entries.sort(key=lambda entry: entry.name)
        child_directories: list[tuple[Path, PurePosixPath, IgnoreRules]] = []

        for entry in entries:
            entries_seen += 1
            relative = _join_relative(relative_directory, entry.name)
            source = relative.as_posix()
            try:
                if entry.is_symlink():
                    warnings.add(
                        "symlink_skipped",
                        source,
                        "symbolic links are not traversed",
                    )
                    continue
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                warnings.add(
                    "traversal_error",
                    source,
                    _safe_os_error("could not inspect entry", exc),
                )
                continue

            if rules.is_ignored(relative, is_directory=is_directory):
                continue

            depth = len(relative.parts)
            if is_directory:
                if depth >= limits.max_depth:
                    warnings.add(
                        "depth_limit",
                        source,
                        f"maximum scan depth {limits.max_depth} reached",
                    )
                    continue
                child_rules = rules.with_directory(Path(entry.path), relative)
                for warning in child_rules.warnings[len(rules.warnings) :]:
                    warnings.add("ignore_error", warning.source, warning.message)
                child_directories.append((Path(entry.path), relative, child_rules))
                continue
            if depth > limits.max_depth:
                warnings.add(
                    "depth_limit",
                    source,
                    f"maximum scan depth {limits.max_depth} reached",
                )
                continue

            try:
                is_file = entry.is_file(follow_symlinks=False)
                size = max(0, int(entry.stat(follow_symlinks=False).st_size))
            except OSError as exc:
                warnings.add(
                    "traversal_error",
                    source,
                    _safe_os_error("could not inspect file", exc),
                )
                continue
            if not is_file:
                continue
            if bytes_scanned + size > limits.max_bytes:
                warnings.add(
                    "byte_limit",
                    source,
                    f"maximum scan bytes {limits.max_bytes} reached",
                )
                stopped = True
                break
            bytes_scanned += size
            records.append(_FileRecord(Path(entry.path), source, size))

        if has_more_entries:
            warnings.add(
                "file_limit",
                relative_directory.as_posix(),
                f"maximum scan entries {limits.max_files} reached",
            )
            stopped = True
        if not stopped:
            stack.extend(reversed(child_directories))

    return tuple(sorted(records, key=lambda record: record.source)), bytes_scanned


def _collect_evidence(
    root: Path,
    records: tuple[_FileRecord, ...],
    warnings: _Warnings,
) -> dict[tuple[str, str, str, str], EvidenceV2]:
    evidence: dict[tuple[str, str, str, str], EvidenceV2] = {}
    language_counts: dict[str, int] = {}
    language_sources: dict[str, str] = {}

    for record in records:
        path = PurePosixPath(record.source)
        suffix = path.suffix.lower()
        language = _LANGUAGE_EXTENSIONS.get(suffix)
        if language is not None:
            language_counts[language] = language_counts.get(language, 0) + 1
            language_sources.setdefault(language, record.source)

        if _is_manifest(path.name):
            _add_evidence(
                evidence,
                type="manifest",
                key=_safe_identifier(path.name),
                detail="project manifest",
                source=record.source,
                strength="strong",
            )
            _parse_manifest(root, record, evidence, warnings)

        _detect_infrastructure(root, record, evidence, warnings)
        _detect_test_configuration(record, evidence)

    for language, count in language_counts.items():
        _add_evidence(
            evidence,
            type="lang",
            key=language,
            detail=f"{count} files",
            source=language_sources[language],
            strength="weak",
        )
    return evidence


def _is_manifest(filename: str) -> bool:
    return filename in _MANIFEST_FILES or filename.endswith(".csproj")


def _parse_manifest(
    root: Path,
    record: _FileRecord,
    evidence: dict[tuple[str, str, str, str], EvidenceV2],
    warnings: _Warnings,
) -> None:
    name = PurePosixPath(record.source).name
    if name not in {
        "Cargo.toml",
        "go.mod",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
    }:
        return
    text = _read_text(root, record, warnings)
    if text is None:
        return
    try:
        if name == "package.json":
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("package manifest must be an object")
            for section in ("dependencies", "devDependencies"):
                dependencies = data.get(section) or {}
                if not isinstance(dependencies, dict):
                    raise ValueError("dependency section must be an object")
                for dependency, spec in dependencies.items():
                    _add_dependency(evidence, dependency, spec, record.source)
        elif name == "pyproject.toml":
            data = tomllib.loads(text)
            project = data.get("project") or {}
            if not isinstance(project, dict):
                raise ValueError("project table must be an object")
            dependencies = project.get("dependencies") or []
            if not isinstance(dependencies, list):
                raise ValueError("project dependencies must be a list")
            for spec in dependencies:
                dependency = _dependency_name(str(spec))
                if dependency:
                    _add_dependency(evidence, dependency, spec, record.source)
            tool = data.get("tool") or {}
            if not isinstance(tool, dict):
                raise ValueError("tool table must be an object")
            poetry = tool.get("poetry") or {}
            if not isinstance(poetry, dict):
                raise ValueError("poetry table must be an object")
            poetry_dependencies = poetry.get("dependencies") or {}
            if not isinstance(poetry_dependencies, dict):
                raise ValueError("poetry dependencies must be an object")
            for dependency, spec in poetry_dependencies.items():
                if str(dependency).lower() != "python":
                    _add_dependency(evidence, dependency, spec, record.source)
            pytest_config = tool.get("pytest") or {}
            if isinstance(pytest_config, dict) and "ini_options" in pytest_config:
                _add_evidence(
                    evidence,
                    type="test",
                    key="pytest",
                    detail="pytest configured in pyproject.toml",
                    source=record.source,
                    strength="strong",
                )
        elif name == "requirements.txt":
            for line in text.splitlines():
                spec = line.strip()
                if spec and not spec.startswith(("#", "-")):
                    dependency = _dependency_name(spec)
                    if dependency:
                        _add_dependency(evidence, dependency, spec, record.source)
        elif name == "Cargo.toml":
            data = tomllib.loads(text)
            dependencies = data.get("dependencies") or {}
            if not isinstance(dependencies, dict):
                raise ValueError("Cargo dependencies must be an object")
            for dependency, spec in dependencies.items():
                _add_dependency(evidence, dependency, spec, record.source)
        elif name == "go.mod":
            _parse_go_dependencies(text, record.source, evidence)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError):
        warnings.add(
            "parse_error",
            record.source,
            f"could not parse {name} as data",
        )


def _parse_go_dependencies(
    text: str,
    source: str,
    evidence: dict[tuple[str, str, str, str], EvidenceV2],
) -> None:
    in_require_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "require (":
            in_require_block = True
            continue
        if in_require_block and stripped == ")":
            in_require_block = False
            continue
        if stripped.startswith("require "):
            fields = stripped.split()
            if len(fields) >= 2:
                _add_dependency(evidence, fields[1], stripped, source)
        elif in_require_block and stripped and not stripped.startswith("//"):
            _add_dependency(evidence, stripped.split()[0], stripped, source)


def _detect_infrastructure(
    root: Path,
    record: _FileRecord,
    evidence: dict[tuple[str, str, str, str], EvidenceV2],
    warnings: _Warnings,
) -> None:
    path = PurePosixPath(record.source)
    filename = path.name
    lower = filename.lower()
    keys: list[str] = []
    if filename == "Dockerfile" or lower.endswith(".dockerfile"):
        keys.append("dockerfile")
    if fnmatch.fnmatch(lower, "docker-compose*.yml") or fnmatch.fnmatch(
        lower, "docker-compose*.yaml"
    ):
        keys.append("compose")
        text = _read_text(root, record, warnings)
        if text is not None and re.search(r"image:\s*[\"']?postgres(?:[:\"'\s]|$)", text, re.I):
            keys.append("postgres")
    if path.suffix.lower() == ".tf":
        keys.append("terraform")
    if record.source.startswith(".github/workflows/") and path.suffix.lower() in {
        ".yml",
        ".yaml",
    }:
        keys.append("github_actions")
    if filename == "Makefile":
        keys.append("make")
    for key in keys:
        _add_evidence(
            evidence,
            type="infra",
            key=key,
            detail=f"{key} configuration",
            source=record.source,
            strength="strong",
        )


def _detect_test_configuration(
    record: _FileRecord,
    evidence: dict[tuple[str, str, str, str], EvidenceV2],
) -> None:
    filename = PurePosixPath(record.source).name
    patterns = (
        ("playwright.config.*", "playwright"),
        ("cypress.config.*", "cypress"),
        ("jest.config.*", "jest"),
        ("vitest.config.*", "vitest"),
    )
    for pattern, key in patterns:
        if fnmatch.fnmatch(filename, pattern):
            _add_evidence(
                evidence,
                type="test",
                key=key,
                detail=f"{key} configured",
                source=record.source,
                strength="strong",
            )
    if filename == "pytest.ini":
        _add_evidence(
            evidence,
            type="test",
            key="pytest",
            detail="pytest configured",
            source=record.source,
            strength="strong",
        )


def _read_text(
    root: Path,
    record: _FileRecord,
    warnings: _Warnings,
) -> str | None:
    try:
        if record.path.is_symlink():
            warnings.add(
                "symlink_skipped",
                record.source,
                "file changed to a symbolic link during scanning",
            )
            return None
        resolved = record.path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            warnings.add(
                "path_escape",
                record.source,
                "file resolved outside the repository",
            )
            return None
        with record.path.open("rb") as handle:
            raw = handle.read(record.size + 1)
        if len(raw) > record.size:
            warnings.add(
                "file_changed",
                record.source,
                "file size changed during scanning",
            )
            return None
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        warnings.add("decode_error", record.source, "file is not valid UTF-8")
    except OSError as exc:
        warnings.add(
            "read_error",
            record.source,
            _safe_os_error("could not read file", exc),
        )
    return None


def _add_dependency(
    evidence: dict[tuple[str, str, str, str], EvidenceV2],
    dependency: object,
    specification: object,
    source: str,
) -> None:
    _add_evidence(
        evidence,
        type="dependency",
        key=_safe_identifier(str(dependency)),
        detail=str(specification)[:2048],
        source=source,
        strength="strong",
    )


def _add_evidence(
    evidence: dict[tuple[str, str, str, str], EvidenceV2],
    *,
    type: str,
    key: str,
    detail: str,
    source: str,
    strength: Literal["weak", "strong", "required"],
) -> None:
    item = EvidenceV2(
        type=type,
        key=key,
        detail=detail[:2048],
        source=source,
        strength=EvidenceStrength(strength),
    )
    evidence[(item.type, item.key, item.source, item.detail)] = item


def _dependency_name(specification: str) -> str:
    return re.split(r"[ <>=!~\[;(\n]", specification.strip(), maxsplit=1)[0]


def _safe_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    if not normalized:
        return "unknown"
    if not normalized[0].isalnum():
        normalized = f"item-{normalized}"
    return normalized[:128]


def _join_relative(directory: PurePosixPath, name: str) -> PurePosixPath:
    if directory == PurePosixPath("."):
        return PurePosixPath(name)
    return directory / name


def _safe_os_error(prefix: str, error: OSError) -> str:
    detail = error.strerror or type(error).__name__
    return f"{prefix}: {detail}"


__all__ = ["ScanLimits", "ScanResult", "ScanWarning", "scan_repository"]
