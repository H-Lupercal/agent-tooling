from __future__ import annotations

from toolbelt.catalog import load_catalog_v2
from toolbelt.policy import recommend
from toolbelt.schemas import CapabilitySnapshot, EvidenceV2


def evidence(type: str, key: str, *, strength: str = "strong") -> EvidenceV2:
    return EvidenceV2(
        type=type,
        key=key,
        detail=f"{type}:{key}",
        source="pyproject.toml",
        strength=strength,
    )


def capabilities(
    *,
    existing: set[str] | None = None,
    managed: set[str] | None = None,
    native: set[str] | None = None,
    status: str = "known",
) -> CapabilitySnapshot:
    installed = tuple(sorted(existing or set()))
    return CapabilitySnapshot(
        schema_version=2,
        provider="combined",
        status=status,
        native=tuple(sorted(native or set())),
        installed=installed,
        managed=tuple(sorted(managed or set())),
        errors=("provider inventory unavailable",) if status == "unknown" else (),
    )


def python_evidence() -> list[EvidenceV2]:
    return [
        evidence("lang", "python", strength="weak"),
        evidence("test", "pytest"),
    ]


def repo_evidence() -> list[EvidenceV2]:
    return [
        evidence("infra", "repository"),
        evidence("infra", "git_repository"),
    ]


def test_existing_unmanaged_tool_is_never_reinstalled():
    recs = recommend(load_catalog_v2(), python_evidence(), capabilities(existing={"ruff"}))
    ruff = next(item for item in recs if item.tool_id == "ruff")

    assert ruff.allowed_operations == ("adopt", "leave_unmanaged", "replace")
    assert "install" not in ruff.allowed_operations
    assert "unmanaged" in ruff.why.lower()


def test_language_extension_cannot_authorize_user_global_install():
    recs = recommend(
        load_catalog_v2(),
        [evidence("lang", "python", strength="weak")],
        capabilities(),
        allow_network=True,
        allow_user_scope=True,
    )

    assert recs
    assert all(not item.actionable for item in recs)
    assert all("install" not in item.allowed_operations for item in recs)


def test_weak_tag_on_strong_catalog_key_remains_non_actionable():
    ruff = next(
        item
        for item in recommend(
            load_catalog_v2(),
            [evidence("test", "pytest", strength="weak")],
            capabilities(),
            allow_network=True,
        )
        if item.tool_id == "ruff"
    )

    assert ruff.actionable is False
    assert ruff.allowed_operations == ()


def test_native_filesystem_and_git_capabilities_suppress_redundant_mcp():
    catalog = load_catalog_v2()
    without_native = {
        item.tool_id
        for item in recommend(
            catalog,
            repo_evidence(),
            capabilities(),
            allow_network=True,
        )
    }
    with_native = {
        item.tool_id
        for item in recommend(
            catalog,
            repo_evidence(),
            capabilities(native={"filesystem", "git"}),
            allow_network=True,
        )
    }

    assert {"mcp-filesystem", "mcp-git"}.issubset(without_native)
    assert "mcp-filesystem" not in with_native
    assert "mcp-git" not in with_native


def test_user_scope_and_network_require_independent_flags():
    catalog = load_catalog_v2()
    signal = [evidence("config", "pyright")]

    neither = next(
        item for item in recommend(catalog, signal, capabilities()) if item.tool_id == "pyright"
    )
    network_only = next(
        item
        for item in recommend(
            catalog,
            signal,
            capabilities(),
            allow_network=True,
        )
        if item.tool_id == "pyright"
    )
    both = next(
        item
        for item in recommend(
            catalog,
            signal,
            capabilities(),
            allow_network=True,
            allow_user_scope=True,
        )
        if item.tool_id == "pyright"
    )

    assert neither.missing_requirements == (
        "network_approval",
        "user_scope_approval",
    )
    assert network_only.missing_requirements == ("user_scope_approval",)
    assert both.actionable is True
    assert both.allowed_operations == ("install",)


def test_unknown_capability_inventory_blocks_mutating_recommendations():
    ruff = next(
        item
        for item in recommend(
            load_catalog_v2(),
            python_evidence(),
            capabilities(status="unknown"),
            allow_network=True,
        )
        if item.tool_id == "ruff"
    )

    assert ruff.actionable is False
    assert ruff.allowed_operations == ()
    assert "capability_inventory_unknown" in ruff.missing_requirements


def test_recommendations_expose_explanation_evidence_and_stable_order():
    recs = recommend(
        load_catalog_v2(),
        python_evidence() + repo_evidence(),
        capabilities(),
        allow_network=True,
    )

    assert [item.tool_id for item in recs] == sorted(item.tool_id for item in recs)
    assert all(item.why for item in recs)
    assert all(isinstance(item.evidence, tuple) for item in recs)
    assert all(isinstance(item.missing_requirements, tuple) for item in recs)
    assert all(isinstance(item.allowed_operations, tuple) for item in recs)
