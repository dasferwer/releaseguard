import pytest
from pydantic import ValidationError

from releaseguard.schemas import (
    ApplicationCreate,
    EnvironmentCreate,
    ObservationCreate,
    ReleaseCreate,
)


def test_required_gates_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="повторяться"):
        ApplicationCreate(name="API", slug="api", required_gates=["tests", "tests"])


def test_artifact_must_be_content_addressed() -> None:
    with pytest.raises(ValidationError):
        ReleaseCreate(version="1.0", artifact_digest="latest", idempotency_key="release-001")


def test_empty_policy_and_nonfinite_metrics_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ApplicationCreate(name="API", slug="api", required_gates=[])
    with pytest.raises(ValidationError):
        EnvironmentCreate(name="production", max_error_rate=float("nan"))
    with pytest.raises(ValidationError):
        ObservationCreate(request_count=500, error_rate=float("nan"), p95_ms=100)
