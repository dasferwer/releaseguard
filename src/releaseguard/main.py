import hashlib
import hmac
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import RequestResponseEndpoint

from releaseguard.config import get_settings
from releaseguard.db import engine, get_session
from releaseguard.domain import CanaryDecision, ReleaseStatus, evaluate_canary
from releaseguard.metrics import (
    ACTIVE_RELEASES,
    CANARY_DECISIONS,
    HTTP_LATENCY,
    RELEASE_TRANSITIONS,
    RELEASES_CREATED,
    WEBHOOKS,
)
from releaseguard.models import (
    Application,
    CanaryObservation,
    Environment,
    GateResult,
    Release,
    ReleaseEvent,
    WebhookReceipt,
    utcnow,
)
from releaseguard.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApprovalCreate,
    DeployCreate,
    EnvironmentCreate,
    EnvironmentRead,
    GateWebhook,
    ObservationCreate,
    ReleaseCreate,
    ReleaseEventRead,
    ReleaseRead,
)
from releaseguard.service import (
    add_event,
    lock_environment,
    lock_release,
    recalculate_gate_status,
    transition,
)

settings = get_settings()
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(
    title="ReleaseGuard API",
    version="0.1.0",
    description="Policy-driven release gates, canary verification and automatic rollback.",
    lifespan=lifespan,
)


@app.middleware("http")
async def observe_http(request: Request, call_next: RequestResponseEndpoint) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    HTTP_LATENCY.labels(method=request.method, path=path).observe(time.perf_counter() - started)
    return response


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
async def ready(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/applications", response_model=ApplicationRead, status_code=201)
async def create_application(payload: ApplicationCreate, session: SessionDep) -> Application:
    application = Application(**payload.model_dump())
    session.add(application)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="application slug already exists") from exc
    await session.refresh(application)
    return application


@app.post(
    "/api/v1/applications/{application_id}/environments",
    response_model=EnvironmentRead,
    status_code=201,
)
async def create_environment(
    application_id: uuid.UUID, payload: EnvironmentCreate, session: SessionDep
) -> Environment:
    if await session.get(Application, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")
    environment = Environment(application_id=application_id, **payload.model_dump())
    session.add(environment)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="environment already exists") from exc
    await session.refresh(environment)
    return environment


@app.post(
    "/api/v1/environments/{environment_id}/releases",
    response_model=ReleaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_release(
    environment_id: uuid.UUID, payload: ReleaseCreate, session: SessionDep
) -> Release:
    existing = await session.scalar(
        select(Release).where(
            Release.environment_id == environment_id,
            Release.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.artifact_digest != payload.artifact_digest
            or existing.version != payload.version
        ):
            raise HTTPException(status_code=409, detail="idempotency key reused with new payload")
        return existing

    environment = await lock_environment(session, environment_id)
    if environment is None:
        raise HTTPException(status_code=404, detail="environment not found")
    if environment.active_release_id is not None:
        raise HTTPException(status_code=409, detail="environment already has an active release")

    release = Release(
        application_id=environment.application_id,
        environment_id=environment.id,
        version=payload.version,
        artifact_digest=payload.artifact_digest,
        idempotency_key=payload.idempotency_key,
        previous_release_id=environment.current_release_id,
    )
    session.add(release)
    await session.flush()
    environment.active_release_id = release.id
    add_event(
        session,
        release,
        "release.created",
        "api",
        {"version": release.version, "artifact_digest": release.artifact_digest},
    )
    await session.commit()
    await session.refresh(release)
    RELEASES_CREATED.inc()
    ACTIVE_RELEASES.inc()
    return release


@app.get("/api/v1/releases/{release_id}", response_model=ReleaseRead)
async def get_release(release_id: uuid.UUID, session: SessionDep) -> Release:
    release = await session.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    return release


def valid_signature(body: bytes, supplied: str | None) -> bool:
    expected = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return supplied is not None and hmac.compare_digest(supplied.removeprefix("sha256="), expected)


@app.post("/api/v1/webhooks/ci", response_model=ReleaseRead)
async def receive_gate_webhook(request: Request, session: SessionDep) -> Release:
    body = await request.body()
    if not valid_signature(body, request.headers.get("X-ReleaseGuard-Signature")):
        WEBHOOKS.labels(result="invalid_signature").inc()
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        payload = GateWebhook.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    payload_hash = hashlib.sha256(body).hexdigest()
    receipt = await session.get(WebhookReceipt, payload.event_id)
    if receipt is not None:
        if receipt.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="event_id reused with new payload")
        release = await session.get(Release, payload.release_id)
        if release is None:
            raise HTTPException(status_code=404, detail="release not found")
        WEBHOOKS.labels(result="duplicate").inc()
        return release

    release = await lock_release(session, payload.release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    if release.status != ReleaseStatus.evaluating:
        raise HTTPException(status_code=409, detail="release no longer accepts gate results")
    application = await session.get(Application, release.application_id)
    environment = await lock_environment(session, release.environment_id)
    if application is None or environment is None:
        raise HTTPException(status_code=409, detail="release dependencies are missing")
    if payload.gate not in application.required_gates:
        raise HTTPException(status_code=422, detail="gate is not required by application policy")

    gate = await session.scalar(
        select(GateResult).where(
            GateResult.release_id == release.id,
            GateResult.name == payload.gate,
        )
    )
    if gate is None:
        gate = GateResult(
            release_id=release.id,
            name=payload.gate,
            status=payload.status,
            details=payload.details,
        )
        session.add(gate)
    else:
        gate.status = payload.status
        gate.details = payload.details
    session.add(WebhookReceipt(event_id=payload.event_id, payload_hash=payload_hash))
    add_event(
        session,
        release,
        "gate.reported",
        "ci-webhook",
        {"gate": payload.gate, "status": payload.status.value},
    )
    await session.flush()
    target = await recalculate_gate_status(
        session,
        release=release,
        application=application,
        environment=environment,
    )
    await session.commit()
    await session.refresh(release)
    WEBHOOKS.labels(result="accepted").inc()
    if target != ReleaseStatus.evaluating:
        RELEASE_TRANSITIONS.labels(target=target.value).inc()
        if target == ReleaseStatus.blocked:
            ACTIVE_RELEASES.dec()
    return release


@app.post("/api/v1/releases/{release_id}/approve", response_model=ReleaseRead)
async def approve_release(
    release_id: uuid.UUID, payload: ApprovalCreate, session: SessionDep
) -> Release:
    release = await lock_release(session, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    try:
        transition(session, release, ReleaseStatus.approved, actor=payload.actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    release.approved_by = payload.actor
    await session.commit()
    await session.refresh(release)
    RELEASE_TRANSITIONS.labels(target="approved").inc()
    return release


@app.post("/api/v1/releases/{release_id}/deploy", response_model=ReleaseRead)
async def deploy_release(
    release_id: uuid.UUID, payload: DeployCreate, session: SessionDep
) -> Release:
    release = await lock_release(session, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    environment = await lock_environment(session, release.environment_id)
    if environment is None or environment.active_release_id != release.id:
        raise HTTPException(status_code=409, detail="release does not own environment lock")
    try:
        transition(session, release, ReleaseStatus.canary, actor=payload.actor)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    release.traffic_percent = payload.canary_percent
    release.canary_started_at = utcnow()
    await session.commit()
    await session.refresh(release)
    RELEASE_TRANSITIONS.labels(target="canary").inc()
    return release


@app.post("/api/v1/releases/{release_id}/observations", response_model=ReleaseRead)
async def observe_canary(
    release_id: uuid.UUID, payload: ObservationCreate, session: SessionDep
) -> Release:
    release = await lock_release(session, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    if release.status != ReleaseStatus.canary:
        raise HTTPException(status_code=409, detail="release is not in canary")
    environment = await lock_environment(session, release.environment_id)
    if environment is None:
        raise HTTPException(status_code=409, detail="environment is missing")

    decision = evaluate_canary(
        request_count=payload.request_count,
        error_rate=payload.error_rate,
        p95_ms=payload.p95_ms,
        min_requests=environment.min_requests,
        max_error_rate=environment.max_error_rate,
        max_p95_ms=environment.max_p95_ms,
    )
    session.add(
        CanaryObservation(release_id=release.id, decision=decision.value, **payload.model_dump())
    )
    add_event(
        session,
        release,
        "canary.observed",
        "metrics-gate",
        {**payload.model_dump(), "decision": decision.value},
    )
    if decision == CanaryDecision.promote:
        transition(session, release, ReleaseStatus.succeeded, actor="metrics-gate")
        release.traffic_percent = 100
        environment.current_release_id = release.id
        environment.active_release_id = None
        ACTIVE_RELEASES.dec()
        RELEASE_TRANSITIONS.labels(target="succeeded").inc()
    elif decision == CanaryDecision.rollback:
        transition(
            session,
            release,
            ReleaseStatus.rolled_back,
            actor="metrics-gate",
            reason="canary thresholds exceeded",
        )
        release.traffic_percent = 0
        environment.current_release_id = release.previous_release_id
        environment.active_release_id = None
        ACTIVE_RELEASES.dec()
        RELEASE_TRANSITIONS.labels(target="rolled_back").inc()
    await session.commit()
    await session.refresh(release)
    CANARY_DECISIONS.labels(decision=decision.value).inc()
    return release


@app.post("/api/v1/releases/{release_id}/rollback", response_model=ReleaseRead)
async def rollback_release(
    release_id: uuid.UUID, payload: ApprovalCreate, session: SessionDep
) -> Release:
    release = await lock_release(session, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    environment = await lock_environment(session, release.environment_id)
    if environment is None:
        raise HTTPException(status_code=409, detail="environment is missing")
    try:
        transition(
            session,
            release,
            ReleaseStatus.rolled_back,
            actor=payload.actor,
            reason="manual rollback",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    release.traffic_percent = 0
    environment.current_release_id = release.previous_release_id
    environment.active_release_id = None
    await session.commit()
    await session.refresh(release)
    RELEASE_TRANSITIONS.labels(target="rolled_back").inc()
    return release


@app.get("/api/v1/releases/{release_id}/events", response_model=list[ReleaseEventRead])
async def list_release_events(release_id: uuid.UUID, session: SessionDep) -> list[ReleaseEvent]:
    return list(
        (
            await session.scalars(
                select(ReleaseEvent)
                .where(ReleaseEvent.release_id == release_id)
                .order_by(ReleaseEvent.created_at)
            )
        ).all()
    )
