import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from releaseguard.domain import GateStatus, ReleaseStatus


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    required_gates: list[str] = Field(default_factory=lambda: ["tests", "security", "signature"])

    @field_validator("required_gates")
    @classmethod
    def unique_gates(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("required_gates must be unique")
        return normalized


class ApplicationRead(ApplicationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    requires_approval: bool = True
    min_requests: int = Field(default=100, ge=1, le=1_000_000)
    max_error_rate: float = Field(default=0.02, ge=0, le=1)
    max_p95_ms: int = Field(default=800, ge=1, le=120_000)


class EnvironmentRead(EnvironmentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    current_release_id: uuid.UUID | None
    active_release_id: uuid.UUID | None
    created_at: datetime


class ReleaseCreate(BaseModel):
    version: str = Field(min_length=1, max_length=100)
    artifact_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=120)


class ReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    environment_id: uuid.UUID
    version: str
    artifact_digest: str
    idempotency_key: str
    status: ReleaseStatus
    previous_release_id: uuid.UUID | None
    traffic_percent: int
    approved_by: str | None
    state_reason: str | None
    canary_started_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GateWebhook(BaseModel):
    event_id: str = Field(min_length=8, max_length=160)
    release_id: uuid.UUID
    gate: str = Field(min_length=2, max_length=80)
    status: GateStatus
    details: dict[str, object] = Field(default_factory=dict)


class ApprovalCreate(BaseModel):
    actor: str = Field(min_length=3, max_length=160)


class DeployCreate(BaseModel):
    actor: str = Field(min_length=3, max_length=160)
    canary_percent: int = Field(default=10, ge=1, le=50)


class ObservationCreate(BaseModel):
    request_count: int = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    p95_ms: int = Field(ge=0, le=120_000)


class ReleaseEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    event_type: str
    actor: str
    payload: dict[str, object]
    created_at: datetime
