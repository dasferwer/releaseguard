"""Create ReleaseGuard schema.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

release_status = postgresql.ENUM(
    "evaluating",
    "blocked",
    "awaiting_approval",
    "approved",
    "canary",
    "succeeded",
    "rolled_back",
    name="release_status",
    create_type=False,
)
gate_status = postgresql.ENUM("passed", "failed", name="gate_status", create_type=False)


def upgrade() -> None:
    postgresql.ENUM(
        "evaluating",
        "blocked",
        "awaiting_approval",
        "approved",
        "canary",
        "succeeded",
        "rolled_back",
        name="release_status",
    ).create(op.get_bind())
    postgresql.ENUM("passed", "failed", name="gate_status").create(op.get_bind())
    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("required_gates", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_applications_slug", "applications", ["slug"], unique=True)
    op.create_table(
        "environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("min_requests", sa.Integer(), nullable=False),
        sa.Column("max_error_rate", sa.Float(), nullable=False),
        sa.Column("max_p95_ms", sa.Integer(), nullable=False),
        sa.Column("current_release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("application_id", "name"),
    )
    op.create_index("ix_environments_application_id", "environments", ["application_id"])
    op.create_table(
        "releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "environment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("environments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("artifact_digest", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("status", release_status, nullable=False),
        sa.Column(
            "previous_release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("traffic_percent", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(160), nullable=True),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("canary_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("environment_id", "idempotency_key"),
    )
    op.create_index("ix_releases_application_id", "releases", ["application_id"])
    op.create_index("ix_releases_environment_id", "releases", ["environment_id"])
    op.create_index("ix_releases_status", "releases", ["status"])
    op.create_index("ix_releases_status_updated", "releases", ["status", "updated_at"])
    op.create_table(
        "gate_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("status", gate_status, nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_id", "name"),
    )
    op.create_index("ix_gate_results_release_id", "gate_results", ["release_id"])
    op.create_table(
        "webhook_receipts",
        sa.Column("event_id", sa.String(160), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "canary_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("error_rate", sa.Float(), nullable=False),
        sa.Column("p95_ms", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_canary_observations_release_id", "canary_observations", ["release_id"])
    op.create_table(
        "release_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor", sa.String(160), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_release_events_release_id", "release_events", ["release_id"])


def downgrade() -> None:
    op.drop_table("release_events")
    op.drop_table("canary_observations")
    op.drop_table("webhook_receipts")
    op.drop_table("gate_results")
    op.drop_table("releases")
    op.drop_table("environments")
    op.drop_table("applications")
    postgresql.ENUM(name="gate_status").drop(op.get_bind())
    postgresql.ENUM(name="release_status").drop(op.get_bind())
