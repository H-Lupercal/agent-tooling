from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pathspec.gitignore import GitIgnoreSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPatternError


_MAX_IGNORE_FILE_BYTES = 256 * 1024
_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".cache",
        ".mypy_cache",
        ".next",
        ".nox",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".toolbelt",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "env",
        "htmlcov",
        "node_modules",
        "out",
        "target",
        "third_party",
        "vendor",
        "venv",
    }
)
_FIXTURE_DIRECTORIES = frozenset(
    {"__fixtures__", "__snapshots__", "fixture", "fixtures", "testdata"}
)
_GENERATED_FILE_PATTERNS = (
    "*.generated.*",
    "*.min.css",
    "*.min.js",
    "*.min.mjs",
    "*.min.ts",
    "*.map",
    "*.pyc",
    "*.pyo",
    "*.sourcemap",
    "*_pb2.py",
    "coverage.xml",
)


@dataclass(frozen=True, slots=True)
class IgnoreRuleWarning:
    source: str
    message: str


@dataclass(frozen=True, slots=True)
class _RuleSet:
    base: PurePosixPath
    spec: GitIgnoreSpec


@dataclass(frozen=True, slots=True)
class IgnoreRules:
    """Immutable Git-compatible ignore rules for one traversal branch."""

    rules: tuple[_RuleSet, ...] = ()
    warnings: tuple[IgnoreRuleWarning, ...] = ()
    include_fixtures: bool = False

    @classmethod
    def from_root(cls, root: Path, *, include_fixtures: bool = False) -> IgnoreRules:
        return cls(include_fixtures=include_fixtures).with_directory(
            root, PurePosixPath(".")
        )

    def with_directory(
        self,
        directory: Path,
        relative_directory: PurePosixPath,
    ) -> IgnoreRules:
        rules = list(self.rules)
        warnings = list(self.warnings)
        for filename in (".gitignore", ".toolbeltignore"):
            loaded, warning = _load_ignore_file(
                directory / filename,
                _join_source(relative_directory, filename),
                relative_directory,
            )
            if loaded is not None:
                rules.append(loaded)
            if warning is not None:
                warnings.append(warning)
        return IgnoreRules(tuple(rules), tuple(warnings), self.include_fixtures)

    def is_ignored(self, relative_path: PurePosixPath, *, is_directory: bool) -> bool:
        parts = set(relative_path.parts)
        if parts & _EXCLUDED_DIRECTORIES:
            return True
        if not self.include_fixtures and parts & _FIXTURE_DIRECTORIES:
            return True
        if not is_directory and any(
            fnmatch.fnmatch(relative_path.name, pattern)
            for pattern in _GENERATED_FILE_PATTERNS
        ):
            return True

        ignored: bool | None = None
        for rule_set in self.rules:
            try:
                local = (
                    relative_path
                    if rule_set.base == PurePosixPath(".")
                    else relative_path.relative_to(rule_set.base)
                )
            except ValueError:
                continue
            candidate = local.as_posix()
            if is_directory:
                candidate += "/"
            matched = rule_set.spec.check_file(candidate).include
            if matched is not None:
                ignored = matched
        return ignored is True


def _join_source(directory: PurePosixPath, filename: str) -> str:
    if directory == PurePosixPath("."):
        return filename
    return (directory / filename).as_posix()


def _load_ignore_file(
    path: Path,
    source: str,
    base: PurePosixPath,
) -> tuple[_RuleSet | None, IgnoreRuleWarning | None]:
    if not path.exists():
        return None, None
    if path.is_symlink() or not path.is_file():
        return None, IgnoreRuleWarning(source, "ignore file is not a regular file")
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_IGNORE_FILE_BYTES + 1)
        if len(raw) > _MAX_IGNORE_FILE_BYTES:
            return None, IgnoreRuleWarning(source, "ignore file exceeds size limit")
        text = raw.decode("utf-8")
        spec = GitIgnoreSpec.from_lines(text.splitlines())
    except UnicodeDecodeError:
        return None, IgnoreRuleWarning(source, "ignore file is not valid UTF-8")
    except GitWildMatchPatternError as exc:
        return None, IgnoreRuleWarning(source, f"invalid ignore pattern: {exc}")
    except OSError as exc:
        return None, IgnoreRuleWarning(source, f"could not read ignore file: {exc}")
    return _RuleSet(base, spec), None


__all__ = ["IgnoreRuleWarning", "IgnoreRules"]
