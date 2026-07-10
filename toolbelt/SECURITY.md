# Security policy

## Supported versions

Security fixes are provided for the latest 2.x release. The v1 prototype is not
supported.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open a
public issue containing exploit details, credentials, private repository data, or
unredacted command output. Include the affected version, platform, minimal
reproduction, impact, and whether the issue crosses a documented trust boundary.

Maintainers should acknowledge a report within five business days and coordinate
validation, remediation, advisory publication, and credit with the reporter.

## Scope

High-priority areas include path containment or symlink escapes, plan-binding
bypass, catalog command injection, secret exposure, rollback/recovery corruption,
unsafe provider parsing, artifact substitution, and release workflow compromise.

Toolbelt is not a sandbox. Catalog commands run with the invoking user's OS
authority after explicit approval; a malicious trusted executable remains outside
Toolbelt's containment guarantees.
