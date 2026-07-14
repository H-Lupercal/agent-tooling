"""Human and machine-readable receipt rendering and comparison."""

from __future__ import annotations

from install_rehearsal.models import FileDelta, Receipt, receipt_to_json


def render_receipt(receipt: Receipt, *, as_json: bool = False) -> str:
    if as_json:
        return receipt_to_json(receipt)
    run = receipt.run
    lines = [
        receipt.trust_label,
        f"Run: {receipt.run_id}",
        f"Installer: {run.termination_reason} (exit={run.exit_code})",
        f"Duration: {run.duration_seconds:.3f}s",
        f"Observed profile changes: {len(receipt.filesystem_delta)}",
    ]
    lines.extend(f"  {delta.change:12} {delta.path}" for delta in receipt.filesystem_delta)
    if receipt.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in receipt.warnings)
    return "\n".join(lines) + "\n"


def _delta_map(receipt: Receipt) -> dict[str, FileDelta]:
    return {delta.path: delta for delta in receipt.filesystem_delta}


def compare_receipts(first: Receipt, second: Receipt) -> tuple[str, ...]:
    """Compare installer semantics while ignoring run identity and timing noise."""
    differences: list[str] = []
    first_delta = _delta_map(first)
    second_delta = _delta_map(second)
    for path in sorted(first_delta.keys() | second_delta.keys()):
        previous = first_delta.get(path)
        current = second_delta.get(path)
        if previous is None:
            differences.append(f"{path}: created in second")
        elif current is None:
            differences.append(f"{path}: absent from second")
        elif previous != current:
            differences.append(f"{path}: observed change differs")

    comparable_fields = (
        ("platform", first.platform, second.platform),
        ("tool version", first.tool_version, second.tool_version),
        ("argv", first.argv, second.argv),
        ("executable digest", first.executable_sha256, second.executable_sha256),
        ("termination", first.run.termination_reason, second.run.termination_reason),
        ("exit code", first.run.exit_code, second.run.exit_code),
        ("stdout digest", first.run.stdout_sha256, second.run.stdout_sha256),
        ("stderr digest", first.run.stderr_sha256, second.run.stderr_sha256),
        ("warnings", first.warnings, second.warnings),
    )
    differences.extend(
        f"{label}: differs" for label, previous, current in comparable_fields if previous != current
    )
    return tuple(differences)


def render_comparison(first: Receipt, second: Receipt) -> tuple[str, bool]:
    differences = compare_receipts(first, second)
    if not differences:
        return "No semantic differences.\n", False
    lines = [f"Semantic differences: {first.run_id} -> {second.run_id}"]
    lines.extend(f"  - {difference}" for difference in differences)
    return "\n".join(lines) + "\n", True

