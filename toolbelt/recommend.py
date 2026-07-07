from __future__ import annotations

from pathlib import Path

from toolbelt.models import Evidence, MatchGroup, Recommendation, Tool


def _by_type(evidence: list[Evidence], etype: str) -> dict[str, Evidence]:
    return {e.key: e for e in evidence if e.type == etype}


def _first_glob(root: Path, patterns: tuple[str, ...], weight: int) -> Evidence | None:
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if matches:
            path = matches[0]
            return Evidence("file_glob", pattern, str(path.relative_to(root)), weight, str(path.relative_to(root)))
    return None


def _group_hit(group: MatchGroup, evidence: list[Evidence], root: Path) -> tuple[bool, list[Evidence]]:
    matched: list[Evidence] = []
    by_manifest_file = _by_type(evidence, "manifest_file")
    by_manifest_dep = _by_type(evidence, "manifest_dep")
    by_lang = _by_type(evidence, "lang_ext")
    by_infra = _by_type(evidence, "infra")
    by_brief = _by_type(evidence, "brief_keyword")

    if group.any_files:
        glob_ev = _first_glob(root, group.any_files, group.weight)
        if glob_ev is None:
            return False, []
        matched.append(glob_ev)
    if group.manifest_file:
        if group.manifest_deps:
            found = None
            for dep in group.manifest_deps:
                found = by_manifest_dep.get(f"{group.manifest_file}:{dep}")
                if found:
                    break
            if not found:
                return False, []
            matched.append(found)
        else:
            found = by_manifest_file.get(group.manifest_file)
            if not found:
                return False, []
            matched.append(found)
    for lang in group.langs:
        found = by_lang.get(lang)
        if not found:
            return False, []
        matched.append(found)
    for infra in group.infra:
        found = by_infra.get(infra)
        if not found:
            return False, []
        matched.append(found)
    if group.brief_keywords:
        found = None
        for keyword in group.brief_keywords:
            found = by_brief.get(f"brief:{keyword}")
            if found:
                break
        if not found:
            return False, []
        matched.append(found)
    return True, matched


def match_tool(tool: Tool, evidence: list[Evidence], root: Path) -> tuple[int, list[Evidence]]:
    confidence = 0
    matched: dict[tuple[str, str, str], Evidence] = {}
    for group in tool.match:
        hit, group_evidence = _group_hit(group, evidence, root)
        if hit:
            confidence += group.weight
            for item in group_evidence:
                matched[(item.type, item.key, item.detail)] = item
    return confidence, sorted(matched.values(), key=lambda e: (e.type, e.key, e.detail))


def recommend(
    catalog: list[Tool],
    evidence: list[Evidence],
    *,
    mode: str,
    root: Path,
    min_confidence: int = 2,
) -> list[Recommendation]:
    del mode, min_confidence
    recs: list[Recommendation] = []
    for tool in catalog:
        confidence, matched = match_tool(tool, evidence, root)
        if confidence >= 1:
            provisional = bool(matched) and all(e.type == "brief_keyword" for e in matched)
            recs.append(Recommendation(tool.id, confidence, tuple(matched), provisional))
    return sorted(recs, key=lambda r: (-r.confidence, r.tool_id))
