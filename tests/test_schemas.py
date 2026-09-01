import pytest
from pydantic import ValidationError

from releaseguard.schemas import ApplicationCreate, ReleaseCreate


def test_required_gates_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="unique"):
        ApplicationCreate(name="API", slug="api", required_gates=["tests", "tests"])


def test_artifact_must_be_content_addressed() -> None:
    with pytest.raises(ValidationError):
        ReleaseCreate(version="1.0", artifact_digest="latest", idempotency_key="release-001")
