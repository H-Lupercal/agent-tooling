# Security policy

## Supported versions

Security fixes are provided for the latest published major version.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting feature. Do not open a
public issue containing exploit details, credentials, transcripts, or provider
payloads. Include the affected version, operating system, reproduction steps,
and impact. Maintainers will acknowledge a report within five business days.

Codex Conductor is a policy and accounting guardrail, not a sandbox or billing
authority. Provider hooks and payloads remain inside the provider's trust
boundary. Governed operations fail closed when Conductor cannot establish the
identity, capability contract, or state needed to enforce them.

Codex hook trust remains provider-managed. Review and persist trust for the
installed hashes in a trusted interactive session; never treat
`--dangerously-bypass-hook-trust` as a production setup step.
