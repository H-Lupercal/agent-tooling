from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from toolbelt.models import Evidence, SKIP_DIRS, Tool


SOURCE_EXTS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".tf",
        ".sql",
        ".sh",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".kt",
        ".swift",
        ".php",
        ".scala",
        ".clj",
    }
)
BRIEF_LANG_KEYWORDS = {
    "python": "python",
    "typescript": "typescript",
    "javascript": "javascript",
    "node": "javascript",
    "react": "typescript",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "java": "java",
    "ruby": "ruby",
    "terraform": "terraform",
}


def is_greenfield(root: Path) -> bool:
    root = Path(root)
    skip = SKIP_DIRS | {"docs"}
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in skip for part in rel.parts):
            continue
        if not path.is_file():
            continue
        name = path.name
        if name.startswith(".") or name.endswith(".md") or name.startswith("LICENSE"):
            continue
        if path.suffix in SOURCE_EXTS:
            return False
    return True


def find_brief(root: Path) -> Path | None:
    path = Path(root) / ".toolbelt" / "brief.md"
    return path if path.exists() else None


def parse_brief(path: Path, catalog: list[Tool]) -> list[Evidence]:
    text = path.read_text(encoding="utf-8").lower()
    out: dict[str, Evidence] = {}
    for tool in catalog:
        for group in tool.match:
            for keyword in group.brief_keywords:
                kw = keyword.lower()
                if kw in text:
                    key = f"brief:{kw}"
                    out[key] = Evidence("brief_keyword", key, kw, 1, "brief")
    return sorted(out.values(), key=lambda e: (e.type, e.key, e.detail))


def brief_stack(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").lower()
    langs = {
        lang
        for kw, lang in BRIEF_LANG_KEYWORDS.items()
        if re.search(rf"\b{re.escape(kw)}\b", text)
    }
    return sorted(langs)


def brief_goals(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if line.strip().lower() == "## goals":
            goals: list[str] = []
            for candidate in lines[idx + 1 :]:
                stripped = candidate.strip()
                if stripped.startswith("## "):
                    break
                if stripped.startswith("- "):
                    goals.append(stripped[2:].strip())
            return goals
    paragraph: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    return [" ".join(paragraph)] if paragraph else []


def copy_brief(src: Path, root: Path) -> Path:
    dst = Path(root) / ".toolbelt" / "brief.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
