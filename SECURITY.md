# Security policy

## Supported versions

Security fixes are provided for the latest published 2.x release of each package. The
v1 prototypes are unsupported.

## Report a vulnerability

Use GitHub private vulnerability reporting for
[`H-Lupercal/agent-tooling`](https://github.com/H-Lupercal/agent-tooling/security/advisories/new).
Do not open a public issue containing exploit details, credentials, private repository
data, provider transcripts, or unredacted command output.

Include the affected package and version, operating system, minimal reproduction,
impact, and whether the issue crosses a documented trust boundary. Maintainers aim to
acknowledge reports within five business days and will coordinate validation,
remediation, advisory publication, and reporter credit.

## Scope

High-priority Toolbelt areas include path or symlink escape, plan-binding bypass,
catalog command injection, rollback corruption, and unsafe executable discovery.
High-priority Conductor areas include identity spoofing, reservation or budget bypass,
lifecycle mis-correlation, unsafe hook payload parsing, pricing errors, installer
ownership bypass, and state corruption. Release workflow compromise and artifact
substitution affect both projects.

Toolbelt and Conductor are guardrails, not sandboxes. Approved commands and provider
hooks retain the invoking user's operating-system authority. See each project's
security policy for its detailed trust boundaries.
