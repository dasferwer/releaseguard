import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from releaseguard.domain import ReleaseStatus, evaluate_gates, require_transition
from releaseguard.models import Application, Environment, GateResult, Release, ReleaseEvent


def add_event(
    session: AsyncSession,
    release: Release,
    event_type: str,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        ReleaseEvent(
            release_id=release.id,
            event_type=event_type,
            actor=actor,
            payload=payload or {},
        )
    )


def transition(
    session: AsyncSession,
    release: Release,
    target: ReleaseStatus,
    *,
    actor: str,
    reason: str | None = None,
) -> None:
    previous = release.status
    require_transition(previous, target)
    release.status = target
    release.state_reason = reason
    add_event(
        session,
        release,
        "release.status_changed",
        actor,
        {"from": previous.value, "to": target.value, "reason": reason},
    )


async def recalculate_gate_status(
    session: AsyncSession,
    *,
    release: Release,
    application: Application,
    environment: Environment,
) -> ReleaseStatus:
    results = {
        result.name: result.status
        for result in (
            await session.scalars(select(GateResult).where(GateResult.release_id == release.id))
        ).all()
    }
    target = evaluate_gates(
        application.required_gates,
        results,
        requires_approval=environment.requires_approval,
    )
    if target != release.status:
        transition(session, release, target, actor="policy-engine")
        if target == ReleaseStatus.blocked:
            environment.active_release_id = None
    return target


async def lock_release(session: AsyncSession, release_id: uuid.UUID) -> Release | None:
    return await session.scalar(select(Release).where(Release.id == release_id).with_for_update())


async def lock_environment(session: AsyncSession, environment_id: uuid.UUID) -> Environment | None:
    return await session.scalar(
        select(Environment).where(Environment.id == environment_id).with_for_update()
    )
