from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable public process exit codes."""

    SUCCESS = 0
    USAGE = 2
    VALIDATION = 3
    UNSUPPORTED_CAPABILITY = 4
    POLICY_DENIAL = 5
    DEGRADED_RUNTIME = 6
    STATE = 7
    INSTALLATION_CONFLICT = 8
    INTERNAL = 70


class ConductorError(Exception):
    exit_code = ExitCode.INTERNAL


class UsageError(ConductorError):
    exit_code = ExitCode.USAGE


class ConfigError(ConductorError):
    exit_code = ExitCode.VALIDATION


class ContractValidationError(ConductorError):
    exit_code = ExitCode.VALIDATION


class UnsupportedCapabilityError(ConductorError):
    exit_code = ExitCode.UNSUPPORTED_CAPABILITY


class PolicyDenialError(ConductorError):
    exit_code = ExitCode.POLICY_DENIAL


class DegradedRuntimeError(ConductorError):
    exit_code = ExitCode.DEGRADED_RUNTIME


class StateError(ConductorError):
    exit_code = ExitCode.STATE


class StoreBusyError(StateError):
    pass


class InstallationConflictError(ConductorError):
    exit_code = ExitCode.INSTALLATION_CONFLICT


class InternalError(ConductorError):
    exit_code = ExitCode.INTERNAL
