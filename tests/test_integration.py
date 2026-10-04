# ruff: noqa: E402
import pytest

from releaseguard.test_safety import UnsafeTestEnvironment, ensure_test_environment

# Проверяем окружение раньше settings/engine и регистрации любых fixtures.
try:
    ensure_test_environment()
except UnsafeTestEnvironment as exc:
    raise pytest.UsageError(str(exc)) from None

import asyncio
import hashlib
import hmac
import json
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text

from releaseguard.db import engine, session_factory
from releaseguard.main import app, settings
from releaseguard.models import Environment, Release, utcnow
from releaseguard.reconciler import reconcile_batch

pytestmark = pytest.mark.asyncio(loop_scope="session")

KEYS = {
    "admin": "local-admin-key-change-me",
    "approver": "local-approver-key-change-me",
    "observer": "local-observer-key-change-me",
    "viewer": "local-viewer-key-change-me",
}


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def clean_test_database():
    if engine.url.database != "releaseguard_test":
        pytest.skip("Интеграционные тесты выполняются только в releaseguard_test")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE release_events, canary_observations, webhook_receipts, "
                "gate_results, releases, environments, applications CASCADE"
            )
        )
    yield


@pytest.fixture
def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def headers(role: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + KEYS[role]}


async def make_release(
    client: httpx.AsyncClient, environment_id: str | None = None, gates: list[str] | None = None
):
    if environment_id is None:
        suffix = uuid4().hex[:8]
        application_response = await client.post(
            "/api/v1/applications",
            headers=headers("admin"),
            json={
                "name": "Сервис заказов",
                "slug": "orders-" + suffix,
                "required_gates": gates or ["tests"],
            },
        )
        assert application_response.status_code == 201, application_response.text
        application = application_response.json()
        environment_response = await client.post(
            f"/api/v1/applications/{application['id']}/environments",
            headers=headers("admin"),
            json={"name": "production", "min_requests": 10},
        )
        assert environment_response.status_code == 201, environment_response.text
        environment_id = environment_response.json()["id"]
    payload = {
        "version": uuid4().hex[:8],
        "artifact_digest": "sha256:" + "a" * 64,
        "idempotency_key": "deploy-" + uuid4().hex,
    }
    response = await client.post(
        f"/api/v1/environments/{environment_id}/releases",
        headers=headers("admin"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return environment_id, response.json(), payload


async def send_gate(
    client: httpx.AsyncClient,
    release_id: str,
    event_id: str,
    status: str = "passed",
    gate: str = "tests",
):
    payload = {
        "event_id": event_id,
        "release_id": release_id,
        "gate": gate,
        "status": status,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return await client.post(
        "/api/v1/webhooks/ci",
        content=body,
        headers={"X-ReleaseGuard-Signature": "sha256=" + signature},
    )


async def advance_to_canary(client: httpx.AsyncClient, release_id: str):
    response = await send_gate(client, release_id, "event-" + uuid4().hex)
    assert response.status_code == 200, response.text
    response = await client.post(
        f"/api/v1/releases/{release_id}/approve",
        headers=headers("approver"),
        json={"actor": "подставной-пользователь"},
    )
    assert response.status_code == 200 and response.json()["approved_by"] == "local-approver"
    response = await client.post(
        f"/api/v1/releases/{release_id}/deploy",
        headers=headers("admin"),
        json={"actor": "подставной-пользователь", "canary_percent": 10},
    )
    assert response.status_code == 200 and response.json()["status"] == "canary"


async def test_roles_webhook_and_concurrent_idempotency(client):
    async with client:
        assert (await client.post("/api/v1/applications", json={})).status_code == 401
        assert (
            await client.post(
                "/api/v1/applications",
                headers=headers("viewer"),
                json={"name": "Чужое приложение", "slug": "not-allowed"},
            )
        ).status_code == 403
        environment_id, release, payload = await make_release(client)
        responses = await asyncio.gather(
            *[
                client.post(
                    f"/api/v1/environments/{environment_id}/releases",
                    headers=headers("admin"),
                    json=payload,
                )
                for _ in range(5)
            ]
        )
        assert all(response.status_code == 201 for response in responses)
        assert {response.json()["id"] for response in responses} == {release["id"]}
        assert (
            await client.post(f"/api/v1/releases/{release['id']}/approve", headers=headers("admin"))
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/webhooks/ci",
                content=b"{}",
                headers={"X-ReleaseGuard-Signature": "sha256=bad"},
            )
        ).status_code == 401
        event_id = "event-" + uuid4().hex
        webhooks = await asyncio.gather(
            send_gate(client, release["id"], event_id),
            send_gate(client, release["id"], event_id),
        )
        assert all(
            response.status_code == 200 and response.json()["status"] == "awaiting_approval"
            for response in webhooks
        )
        assert (await client.get(f"/api/v1/releases/{release['id']}/events")).status_code == 401
        events = await client.get(
            f"/api/v1/releases/{release['id']}/events", headers=headers("viewer")
        )
        assert events.status_code == 200 and len(events.json()) == 3
        await advance_existing_release(client, release["id"])
        audit = (
            await client.get(f"/api/v1/releases/{release['id']}/events", headers=headers("viewer"))
        ).json()
        assert {
            item["actor"] for item in audit if item["event_type"] == "release.status_changed"
        } == {
            "policy-engine",
            "local-approver",
            "local-admin",
        }
        assert (
            await client.post(
                f"/api/v1/releases/{release['id']}/observations",
                headers=headers("viewer"),
                json={"request_count": 50, "error_rate": 0, "p95_ms": 100},
            )
        ).status_code == 403


async def advance_existing_release(client: httpx.AsyncClient, release_id: str):
    response = await client.post(
        f"/api/v1/releases/{release_id}/approve",
        headers=headers("approver"),
        json={"actor": "подставной-пользователь"},
    )
    assert response.status_code == 200 and response.json()["approved_by"] == "local-approver"
    response = await client.post(
        f"/api/v1/releases/{release_id}/deploy",
        headers=headers("admin"),
        json={"actor": "подставной-пользователь", "canary_percent": 10},
    )
    assert response.status_code == 200


async def test_old_release_cannot_rollback_new_one(client):
    async with client:
        environment_id, first, _ = await make_release(client)
        await advance_to_canary(client, first["id"])
        promoted = await client.post(
            f"/api/v1/releases/{first['id']}/observations",
            headers=headers("observer"),
            json={"request_count": 50, "error_rate": 0.001, "p95_ms": 100},
        )
        assert promoted.status_code == 200 and promoted.json()["status"] == "succeeded"
        _, second, _ = await make_release(client, environment_id)
        await advance_to_canary(client, second["id"])
        promoted = await client.post(
            f"/api/v1/releases/{second['id']}/observations",
            headers=headers("observer"),
            json={"request_count": 50, "error_rate": 0.001, "p95_ms": 100},
        )
        assert promoted.status_code == 200 and promoted.json()["status"] == "succeeded"
        stale = await client.post(
            f"/api/v1/releases/{first['id']}/rollback", headers=headers("admin")
        )
        assert stale.status_code == 409
        async with session_factory() as session:
            environment = await session.get(Environment, UUID(environment_id))
            assert environment.current_release_id == UUID(second["id"])


async def test_reported_gate_cannot_be_overwritten(client):
    async with client:
        _, release, _ = await make_release(client, gates=["tests", "security"])
        first = await send_gate(client, release["id"], "event-" + uuid4().hex)
        assert first.status_code == 200 and first.json()["status"] == "evaluating"
        changed = await send_gate(client, release["id"], "event-" + uuid4().hex, "failed")
        assert changed.status_code == 409
        second = await send_gate(client, release["id"], "event-" + uuid4().hex, gate="security")
        assert second.status_code == 200 and second.json()["status"] == "awaiting_approval"


async def test_reconciler_rolls_back_only_own_canary(client):
    async with client:
        environment_id, release, _ = await make_release(client)
        await advance_to_canary(client, release["id"])
        async with session_factory.begin() as session:
            stored = await session.get(Release, UUID(release["id"]))
            stored.canary_started_at = utcnow() - timedelta(
                seconds=settings.canary_timeout_seconds + 1
            )
        assert await reconcile_batch() == 1
        current = await client.get(f"/api/v1/releases/{release['id']}", headers=headers("viewer"))
        assert current.status_code == 200 and current.json()["status"] == "rolled_back"
        async with session_factory() as session:
            environment = await session.get(Environment, UUID(environment_id))
            assert environment.active_release_id is None


@pytest.mark.parametrize("gate_status", [None, "passed", "failed"])
async def test_approval_cannot_bypass_missing_or_failed_gates(client, gate_status):
    async with client:
        _, release, _ = await make_release(client, gates=["tests", "security"])
        if gate_status is not None:
            gate = await send_gate(client, release["id"], "event-" + uuid4().hex, gate_status)
            assert gate.status_code == 200
        before = await client.get(
            f"/api/v1/releases/{release['id']}/events", headers=headers("viewer")
        )
        approved = await client.post(
            f"/api/v1/releases/{release['id']}/approve", headers=headers("approver")
        )
        assert approved.status_code == 409
        deployed = await client.post(
            f"/api/v1/releases/{release['id']}/deploy",
            headers=headers("admin"),
            json={"canary_percent": 10},
        )
        assert deployed.status_code == 409
        current = await client.get(f"/api/v1/releases/{release['id']}", headers=headers("viewer"))
        assert current.json()["status"] == ("blocked" if gate_status == "failed" else "evaluating")
        assert current.json()["approved_by"] is None
        after = await client.get(
            f"/api/v1/releases/{release['id']}/events", headers=headers("viewer")
        )
        assert after.json() == before.json()


@pytest.mark.parametrize("gate_status", [None, "passed", "failed"])
async def test_approval_rechecks_gates_even_with_inconsistent_status(client, gate_status):
    async with client:
        _, release, _ = await make_release(client, gates=["tests", "security"])
        if gate_status is not None:
            await send_gate(client, release["id"], "event-" + uuid4().hex, gate_status)
        # Имитация старых или вручную изменённых данных: одного статуса недостаточно.
        async with session_factory.begin() as session:
            await session.execute(
                text("UPDATE releases SET status='awaiting_approval' WHERE id=:id"),
                {"id": UUID(release["id"])},
            )
        approved = await client.post(
            f"/api/v1/releases/{release['id']}/approve", headers=headers("approver")
        )
        assert approved.status_code == 409
        current = await client.get(f"/api/v1/releases/{release['id']}", headers=headers("viewer"))
        assert current.json()["status"] == "awaiting_approval"
        assert current.json()["approved_by"] is None


async def test_last_gate_racing_approval_preserves_admission_and_audit(client):
    async with client:
        for _ in range(5):
            _, release, _ = await make_release(client, gates=["tests", "security"])
            await send_gate(client, release["id"], "event-" + uuid4().hex)
            gate, approved = await asyncio.gather(
                send_gate(client, release["id"], "event-" + uuid4().hex, gate="security"),
                client.post(
                    f"/api/v1/releases/{release['id']}/approve", headers=headers("approver")
                ),
            )
            assert gate.status_code == 200
            assert approved.status_code in (200, 409)
            if approved.status_code == 409:
                approved = await client.post(
                    f"/api/v1/releases/{release['id']}/approve", headers=headers("approver")
                )
            assert approved.status_code == 200 and approved.json()["status"] == "approved"
            async with session_factory() as session:
                results = (
                    await session.execute(
                        text("SELECT name,status FROM gate_results WHERE release_id=:id"),
                        {"id": UUID(release["id"])},
                    )
                ).all()
            assert set(results) == {("tests", "passed"), ("security", "passed")}
            audit = (
                await client.get(
                    f"/api/v1/releases/{release['id']}/events", headers=headers("viewer")
                )
            ).json()
            approvals = [
                item
                for item in audit
                if item["event_type"] == "release.status_changed"
                and item["payload"]["to"] == "approved"
            ]
            assert len(approvals) == 1 and approvals[0]["actor"] == "local-approver"
            deployed = await client.post(
                f"/api/v1/releases/{release['id']}/deploy",
                headers=headers("admin"),
                json={"canary_percent": 10},
            )
            assert deployed.status_code == 200 and deployed.json()["status"] == "canary"


async def test_policy_engine_still_approves_after_all_gates_without_manual_approval(client):
    async with client:
        environment_id, release, _ = await make_release(client, gates=["tests", "security"])
        async with session_factory.begin() as session:
            environment = await session.get(Environment, UUID(environment_id))
            environment.requires_approval = False
        premature = await client.post(
            f"/api/v1/releases/{release['id']}/approve", headers=headers("approver")
        )
        assert premature.status_code == 409
        partial = await send_gate(client, release["id"], "event-" + uuid4().hex)
        assert partial.status_code == 200 and partial.json()["status"] == "evaluating"
        completed = await send_gate(client, release["id"], "event-" + uuid4().hex, gate="security")
        assert completed.status_code == 200 and completed.json()["status"] == "approved"
        assert completed.json()["approved_by"] is None
        deployed = await client.post(
            f"/api/v1/releases/{release['id']}/deploy",
            headers=headers("admin"),
            json={"canary_percent": 10},
        )
        assert deployed.status_code == 200 and deployed.json()["status"] == "canary"


@pytest.mark.parametrize("gate_status", [None, "passed", "failed"])
async def test_deploy_rechecks_gates_for_previously_approved_release(client, gate_status):
    async with client:
        environment_id, release, _ = await make_release(client, gates=["tests", "security"])
        if gate_status is not None:
            await send_gate(client, release["id"], "event-" + uuid4().hex, gate_status)
        # Старый обход мог оставить approved без успешных проверок до обновления сервиса.
        async with session_factory.begin() as session:
            await session.execute(
                text("UPDATE releases SET status='approved' WHERE id=:id"),
                {"id": UUID(release["id"])},
            )
            environment = await session.get(Environment, UUID(environment_id))
            environment.active_release_id = UUID(release["id"])
        deployed = await client.post(
            f"/api/v1/releases/{release['id']}/deploy",
            headers=headers("admin"),
            json={"canary_percent": 10},
        )
        assert deployed.status_code == 409
        current = await client.get(f"/api/v1/releases/{release['id']}", headers=headers("viewer"))
        assert current.json()["status"] == "approved"
        assert current.json()["traffic_percent"] == 0


async def advance_before_cancel(client, release_id, desired):
    if desired in {"awaiting_approval", "approved"}:
        response = await send_gate(client, release_id, "event-" + uuid4().hex)
        assert response.status_code == 200
    if desired == "approved":
        response = await client.post(
            f"/api/v1/releases/{release_id}/approve", headers=headers("approver")
        )
        assert response.status_code == 200


@pytest.mark.parametrize("initial", ["evaluating", "awaiting_approval", "approved"])
async def test_cancel_releases_only_own_environment_with_audited_reason(client, initial):
    async with client:
        environment_id, release, _ = await make_release(client)
        await advance_before_cancel(client, release["id"], initial)
        response = await client.post(
            f"/api/v1/releases/{release['id']}/cancel",
            headers=headers("admin"),
            json={"reason": "  Релиз отложен владельцем  ", "actor": "подставной-клиент"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"
        assert response.json()["state_reason"] == "Релиз отложен владельцем"
        assert response.json()["traffic_percent"] == 0
        async with session_factory() as session:
            environment = await session.get(Environment, UUID(environment_id))
            assert environment.active_release_id is None
            assert environment.current_release_id is None
        events = (
            await client.get(f"/api/v1/releases/{release['id']}/events", headers=headers("viewer"))
        ).json()
        cancelled = [e for e in events if e["payload"].get("to") == "cancelled"]
        assert len(cancelled) == 1 and cancelled[0]["actor"] == "local-admin"
        assert cancelled[0]["payload"] == {
            "from": initial,
            "to": "cancelled",
            "reason": "Релиз отложен владельцем",
        }
        _, next_release, _ = await make_release(client, environment_id)
        repeated = await client.post(
            f"/api/v1/releases/{release['id']}/cancel",
            headers=headers("admin"),
            json={"reason": "Повторный запрос"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["state_reason"] == "Релиз отложен владельцем"
        async with session_factory() as session:
            environment = await session.get(Environment, UUID(environment_id))
            assert environment.active_release_id == UUID(next_release["id"])
        for operation, body, role in [
            ("approve", {}, "approver"),
            ("deploy", {"canary_percent": 10}, "admin"),
        ]:
            assert (
                await client.post(
                    f"/api/v1/releases/{release['id']}/{operation}",
                    headers=headers(role),
                    json=body,
                )
            ).status_code == 409
        assert (await send_gate(client, release["id"], "late-" + uuid4().hex)).status_code == 409
        events = (
            await client.get(f"/api/v1/releases/{release['id']}/events", headers=headers("viewer"))
        ).json()
        assert sum(e["payload"].get("to") == "cancelled" for e in events) == 1


@pytest.mark.parametrize("role", ["viewer", "approver", "observer"])
async def test_only_admin_can_cancel(client, role):
    async with client:
        _, release, _ = await make_release(client)
        assert (
            await client.post(
                f"/api/v1/releases/{release['id']}/cancel",
                headers=headers(role),
                json={"reason": "Не запускать"},
            )
        ).status_code == 403


@pytest.mark.parametrize(
    "reason", [None, "", "   ", "x" * 2001], ids=["missing", "empty", "spaces", "too_long"]
)
async def test_cancel_requires_meaningful_bounded_reason(client, reason):
    async with client:
        _, release, _ = await make_release(client)
        assert (
            await client.post(
                f"/api/v1/releases/{release['id']}/cancel",
                headers=headers("admin"),
                json={} if reason is None else {"reason": reason},
            )
        ).status_code == 422


async def test_cancel_cannot_change_current_release_after_deploy(client):
    async with client:
        environment_id, release, _ = await make_release(client)
        await advance_to_canary(client, release["id"])
        assert (
            await client.post(
                f"/api/v1/releases/{release['id']}/cancel",
                headers=headers("admin"),
                json={"reason": "Уже выполняется"},
            )
        ).status_code == 409
        observed = await client.post(
            f"/api/v1/releases/{release['id']}/observations",
            headers=headers("observer"),
            json={"request_count": 10, "error_rate": 0, "p95_ms": 50},
        )
        assert observed.json()["status"] == "succeeded"
        assert (
            await client.post(
                f"/api/v1/releases/{release['id']}/cancel",
                headers=headers("admin"),
                json={"reason": "Слишком поздно"},
            )
        ).status_code == 409
        async with session_factory() as session:
            environment = await session.get(Environment, UUID(environment_id))
            assert environment.current_release_id == UUID(release["id"])
            assert environment.active_release_id is None


async def test_cancel_preserves_previous_successful_release(client):
    async with client:
        environment_id, current, _ = await make_release(client)
        await advance_to_canary(client, current["id"])
        completed = await client.post(
            f"/api/v1/releases/{current['id']}/observations",
            headers=headers("observer"),
            json={"request_count": 10, "error_rate": 0, "p95_ms": 50},
        )
        assert completed.json()["status"] == "succeeded"
        _, next_release, _ = await make_release(client, environment_id)
        cancelled = await client.post(
            f"/api/v1/releases/{next_release['id']}/cancel",
            headers=headers("admin"),
            json={"reason": "Сохраняем текущую версию"},
        )
        assert cancelled.status_code == 200
        async with session_factory() as session:
            environment = await session.get(Environment, UUID(environment_id))
            assert environment.current_release_id == UUID(current["id"])
            assert environment.active_release_id is None
            old = await session.get(Release, UUID(current["id"]))
            assert old.status.value == "succeeded"


@pytest.mark.parametrize("operation", ["approve", "deploy", "webhook"])
async def test_cancellation_race_preserves_release_and_environment(client, operation):
    async with client:
        environment_id, release, _ = await make_release(client)
        initial = "approved" if operation == "deploy" else "awaiting_approval"
        if operation != "webhook":
            await advance_before_cancel(client, release["id"], initial)
        cancel = client.post(
            f"/api/v1/releases/{release['id']}/cancel",
            headers=headers("admin"),
            json={"reason": "Отмена в гонке"},
        )
        if operation == "webhook":
            concurrent = send_gate(client, release["id"], "race-" + uuid4().hex)
        else:
            concurrent = client.post(
                f"/api/v1/releases/{release['id']}/{operation}",
                headers=headers("admin" if operation == "deploy" else "approver"),
                json={"canary_percent": 10} if operation == "deploy" else {},
            )
        cancelled, other = await asyncio.gather(cancel, concurrent)
        assert cancelled.status_code in {200, 409}
        assert other.status_code in {200, 409}
        state = (
            await client.get(f"/api/v1/releases/{release['id']}", headers=headers("viewer"))
        ).json()
        async with session_factory() as session:
            environment = await session.get(Environment, UUID(environment_id))
            if state["status"] == "cancelled":
                assert cancelled.status_code == 200
                assert environment.active_release_id is None
            else:
                assert operation == "deploy" and state["status"] == "canary"
                assert cancelled.status_code == 409 and other.status_code == 200
                assert environment.active_release_id == UUID(release["id"])
            assert environment.current_release_id is None


async def test_cancel_rolls_back_when_audit_cannot_be_saved(client, monkeypatch):
    from releaseguard import service

    async with client:
        environment_id, release, _ = await make_release(client)
        original = service.add_event

        def fail_cancel_audit(session, record, event_type, actor, payload=None):
            if payload and payload.get("to") == "cancelled":
                raise RuntimeError("Injected audit failure")
            return original(session, record, event_type, actor, payload)

        monkeypatch.setattr(service, "add_event", fail_cancel_audit)
        with pytest.raises(RuntimeError, match="audit failure"):
            await client.post(
                f"/api/v1/releases/{release['id']}/cancel",
                headers=headers("admin"),
                json={"reason": "Откатить при ошибке"},
            )
        async with session_factory() as session:
            current = await session.get(Release, UUID(release["id"]))
            environment = await session.get(Environment, UUID(environment_id))
            assert current.status.value == "evaluating"
            assert environment.active_release_id == UUID(release["id"])
