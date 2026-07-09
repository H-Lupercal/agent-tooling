from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)


TASK_CLASSES = (
    "architecture",
    "high_risk",
    "integration",
    "review_gate",
    "implementation",
    "refactor",
    "debug",
    "cross_module_change",
    "tests",
    "docs",
    "mechanical_edit",
    "rename",
    "config_change",
    "search",
    "summarize",
    "boilerplate",
    "formatting",
    "data_extraction",
)

HIGH_RISK_TRIGGERS = (
    "authentication/authorization",
    "cryptography",
    "payments/billing",
    "database schema migration",
    "deleting or rewriting more than 200 lines",
    "public API contract change",
    "concurrency/locking",
    "build or release pipeline change",
    "security-sensitive input parsing",
    "secrets handling",
    "production configuration",
)


Identifier = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]
Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
BoundedString = Annotated[StrictStr, StringConstraints(min_length=1, max_length=256)]
BoundedMessage = Annotated[StrictStr, StringConstraints(min_length=1, max_length=4096)]
FiniteNonNegativeFloat = Annotated[
    StrictFloat,
    Field(ge=0.0, allow_inf_nan=False),
]
FinitePositiveFloat = Annotated[
    StrictFloat,
    Field(gt=0.0, allow_inf_nan=False),
]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


class Provider(str, Enum):
    CODEX = "codex"
    CLAUDE = "claude"


class OperatingMode(str, Enum):
    ROUTING = "routing"
    ADMISSION = "admission"
    OBSERVE = "observe"
    UNSUPPORTED = "unsupported"


class OperationName(str, Enum):
    SPAWN = "spawn"
    ASSIGN = "assign"
    FOLLOWUP = "followup"
    MESSAGE = "message"
    OTHER = "other"


class ReservationState(str, Enum):
    APPROVED = "approved"
    STARTED = "started"
    STOPPED = "stopped"
    COSTED = "costed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class LifecycleKind(str, Enum):
    START = "start"
    STOP = "stop"
    COST = "cost"
    CANCEL = "cancel"
    FAIL = "fail"


class Pricing(StrictModel):
    input_usd_per_mtok: FiniteNonNegativeFloat
    cache_read_usd_per_mtok: FiniteNonNegativeFloat
    cache_write_usd_per_mtok: FiniteNonNegativeFloat
    output_usd_per_mtok: FiniteNonNegativeFloat


class BudgetConfig(StrictModel):
    run_usd_cap: FinitePositiveFloat
    warn_at_fraction: Annotated[
        StrictFloat,
        Field(gt=0.0, le=1.0, allow_inf_nan=False),
    ]
    enforce: StrictBool


class PolicyConfig(StrictModel):
    max_depth: Annotated[StrictInt, Field(ge=0, le=32)]
    require_strictly_cheaper: StrictBool
    same_tier_spawns_from_root_max: Annotated[StrictInt, Field(ge=0, le=1000)]
    minimum_mode: OperatingMode = OperatingMode.ADMISSION
    unknown_identity: Literal["deny", "observe", "degraded"] = "deny"
    unknown_model: Literal["deny", "observe", "degraded"] = "deny"
    reservation_ttl_seconds: Annotated[StrictInt, Field(ge=1, le=86400)] = 300
    busy_timeout_ms: Annotated[StrictInt, Field(ge=1, le=30000)] = 1000

    @field_validator("minimum_mode")
    @classmethod
    def minimum_mode_must_be_enforceable(cls, value: OperatingMode) -> OperatingMode:
        if value is OperatingMode.UNSUPPORTED:
            raise ValueError("minimum_mode cannot be unsupported")
        return value


class TierConfig(StrictModel):
    name: Identifier
    model: BoundedString
    reasoning_effort: Literal["low", "medium", "high"]
    enabled: Literal["always", "auto", "never"]
    pricing: Pricing
    relative_cost_weight: PositiveInt
    est_task_usd: FiniteNonNegativeFloat
    max_concurrent: Annotated[StrictInt, Field(ge=1, le=10000)]
    may_spawn: StrictBool
    task_classes: Annotated[
        tuple[BoundedString, ...], Field(min_length=1, max_length=64)
    ]

    @field_validator("task_classes")
    @classmethod
    def task_classes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("task_classes must not contain duplicates")
        return value

    @property
    def input_usd_per_mtok(self) -> float:
        return self.pricing.input_usd_per_mtok

    @property
    def cached_input_usd_per_mtok(self) -> float:
        return self.pricing.cache_read_usd_per_mtok

    @property
    def cache_write_usd_per_mtok(self) -> float:
        return self.pricing.cache_write_usd_per_mtok

    @property
    def output_usd_per_mtok(self) -> float:
        return self.pricing.output_usd_per_mtok


class ConductorConfig(StrictModel):
    schema_version: Literal[2]
    budget: BudgetConfig
    policy: PolicyConfig
    tiers: Annotated[tuple[TierConfig, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def validate_integrity(self) -> ConductorConfig:
        names = [tier.name for tier in self.tiers]
        if len(names) != len(set(names)):
            raise ValueError("tiers must have unique tier names")

        models = [tier.model for tier in self.tiers]
        if len(models) != len(set(models)):
            raise ValueError("tiers must have unique models")

        for stronger, weaker in zip(self.tiers, self.tiers[1:]):
            if weaker.relative_cost_weight >= stronger.relative_cost_weight:
                raise ValueError(
                    "tier relative_cost_weight must be strictly decreasing"
                )

        owners: dict[str, list[str]] = {}
        for tier in self.tiers:
            for task_class in tier.task_classes:
                owners.setdefault(task_class, []).append(tier.name)
        expected = set(TASK_CLASSES)
        actual = set(owners)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        duplicated = sorted(name for name, tiers in owners.items() if len(tiers) != 1)
        if missing or unknown or duplicated:
            raise ValueError(
                "task class ownership must form exact partition "
                f"(missing={missing}, unknown={unknown}, duplicated={duplicated})"
            )

        if not any(tier.enabled != "never" for tier in self.tiers):
            raise ValueError("at least one tier must be enabled")
        return self

    def tier_index_for_model(self, model: str) -> int | None:
        for index, tier in enumerate(self.tiers):
            if tier.model == model:
                return index
        return None

    def tier_for_model(self, model: str) -> TierConfig | None:
        index = self.tier_index_for_model(model)
        return None if index is None else self.tiers[index]

    def tier_for_class(self, task_class: str) -> TierConfig | None:
        for tier in self.tiers:
            if task_class in tier.task_classes:
                return tier
        return None


class CliVersionRange(StrictModel):
    minimum: BoundedString
    maximum_exclusive: BoundedString | None = None


class ToolContract(StrictModel):
    canonical_name: OperationName
    names: Annotated[tuple[BoundedString, ...], Field(min_length=1, max_length=64)]
    input_schema: dict[str, Any]


class CorrelationFields(StrictModel):
    run_id: Annotated[tuple[BoundedString, ...], Field(max_length=16)] = ()
    caller_id: Annotated[tuple[BoundedString, ...], Field(max_length=16)] = ()
    child_id: Annotated[tuple[BoundedString, ...], Field(max_length=16)] = ()
    task_id: Annotated[tuple[BoundedString, ...], Field(max_length=16)] = ()
    lifecycle_id: Annotated[tuple[BoundedString, ...], Field(max_length=16)] = ()


class CapabilityContract(StrictModel):
    schema_version: Literal[1]
    contract_name: Identifier
    provider: Provider
    cli_version_range: CliVersionRange
    hook_events: Annotated[tuple[BoundedString, ...], Field(max_length=64)]
    tools: Annotated[tuple[ToolContract, ...], Field(max_length=64)]
    model_selector_path: BoundedString | None
    correlation_fields: CorrelationFields
    usage_fields: Annotated[tuple[BoundedString, ...], Field(max_length=64)]
    decision_response_schema: dict[str, Any]
    trust_visibility: StrictBool
    can_block: StrictBool

    @model_validator(mode="after")
    def tools_are_unique(self) -> CapabilityContract:
        names = [tool.canonical_name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("canonical tool names must be unique")
        aliases = [alias for tool in self.tools for alias in tool.names]
        if len(aliases) != len(set(aliases)):
            raise ValueError("tool aliases must be unique")
        return self


class RunContext(StrictModel):
    schema_version: Literal[1] = 1
    provider: Provider
    run_id: Identifier
    thread_id: Identifier
    root_model: BoundedString
    model_source: Literal["session", "transcript", "provider", "operator"]
    provider_contract: Identifier
    contract_digest: Digest
    mode: OperatingMode
    generation: PositiveInt
    started_at: datetime
    heartbeat_at: datetime
    config_digest: Digest

    @field_validator("started_at", "heartbeat_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def heartbeat_follows_start(self) -> RunContext:
        if self.heartbeat_at < self.started_at:
            raise ValueError("heartbeat_at must not precede started_at")
        return self


class TaskEnvelopeV2(StrictModel):
    schema_version: Literal[1]
    task_name: Identifier
    task_class: BoundedString
    risk_triggers: Annotated[tuple[BoundedString, ...], Field(max_length=32)]
    owned_paths: Annotated[tuple[BoundedString, ...], Field(max_length=64)]
    acceptance_checks: Annotated[
        tuple[
            Annotated[StrictStr, StringConstraints(min_length=1, max_length=1024)], ...
        ],
        Field(max_length=64),
    ]
    new_task: StrictBool
    operation_intent: OperationName | None = None

    @field_validator("task_class")
    @classmethod
    def task_class_is_known(cls, value: str) -> str:
        if value not in TASK_CLASSES:
            raise ValueError(f"unknown task class: {value}")
        return value

    @field_validator("risk_triggers")
    @classmethod
    def risk_triggers_are_known(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(HIGH_RISK_TRIGGERS))
        if unknown:
            raise ValueError(f"unknown risk triggers: {unknown}")
        if len(value) != len(set(value)):
            raise ValueError("risk_triggers must not contain duplicates")
        return value

    @field_validator("owned_paths")
    @classmethod
    def owned_paths_are_normalized(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for raw in value:
            if "\\" in raw or "\x00" in raw:
                raise ValueError("owned paths must use normalized POSIX separators")
            path = PurePosixPath(raw)
            if path.is_absolute() or raw in {"", "."} or ".." in path.parts:
                raise ValueError("owned paths must be normalized relative paths")
            clean = str(path)
            if clean != raw or "." in path.parts:
                raise ValueError("owned paths must be normalized relative paths")
            normalized.append(clean)
        if len(normalized) != len(set(normalized)):
            raise ValueError("owned_paths must not contain duplicates")
        return tuple(normalized)


class NormalizedOperation(StrictModel):
    schema_version: Literal[1] = 1
    provider: Provider
    operation: OperationName
    raw_tool_name: BoundedString
    payload: dict[str, Any]
    envelope: TaskEnvelopeV2 | None
    is_new_work: StrictBool
    correlation_id: Identifier | None = None


class Decision(StrictModel):
    schema_version: Literal[1] = 1
    decision_id: Identifier
    allowed: StrictBool
    rule: Identifier
    message: BoundedMessage
    mode: OperatingMode
    operation: OperationName
    selected_model: BoundedString | None
    reservation_estimate_usd: FiniteNonNegativeFloat
    savings_eligible: StrictBool
    reservation_id: Identifier | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class Reservation(StrictModel):
    schema_version: Literal[1] = 1
    reservation_id: Identifier
    run_id: Identifier
    task_id: Identifier
    operation: OperationName
    tier: Identifier | None
    model: BoundedString | None
    estimated_usd: FiniteNonNegativeFloat
    state: ReservationState
    correlation_id: Identifier | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @field_validator("created_at", "updated_at", "expires_at")
    @classmethod
    def reservation_timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reservation timestamp must be timezone-aware")
        return value


class RawUsage(StrictModel):
    schema_version: Literal[1] = 1
    source_event_id: Identifier
    provider: Provider
    parser_version: BoundedString
    model: BoundedString
    input_tokens: NonNegativeInt
    cache_read_tokens: NonNegativeInt
    cache_write_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    reasoning_tokens: NonNegativeInt
    measured: StrictBool
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def usage_timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class LifecycleEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: Identifier
    provider: Provider
    run_id: Identifier
    correlation_id: Identifier
    kind: LifecycleKind
    occurred_at: datetime
    status: BoundedString | None = None
    usage: RawUsage | None = None

    @field_validator("occurred_at")
    @classmethod
    def lifecycle_timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class ReportRow(StrictModel):
    schema_version: Literal[1] = 1
    run_id: Identifier
    tier: Identifier
    mode: OperatingMode
    reservations: NonNegativeInt
    completed: NonNegativeInt
    failed: NonNegativeInt
    measured_usd: FiniteNonNegativeFloat
    estimated_usd: FiniteNonNegativeFloat
