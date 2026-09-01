from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid

BASE_URL = "http://localhost:8091"
SECRET = "change-me-in-production"


def request(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())


def signed_gate(payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        BASE_URL + "/api/v1/webhooks/ci",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-ReleaseGuard-Signature": f"sha256={signature}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    application = request(
        "POST",
        "/api/v1/applications",
        {
            "name": "Checkout API",
            "slug": f"checkout-{suffix}",
            "required_gates": ["tests", "security", "signature"],
        },
    )
    environment = request(
        "POST",
        f"/api/v1/applications/{application['id']}/environments",
        {
            "name": "production",
            "requires_approval": True,
            "min_requests": 100,
            "max_error_rate": 0.02,
            "max_p95_ms": 800,
        },
    )
    release = request(
        "POST",
        f"/api/v1/environments/{environment['id']}/releases",
        {
            "version": "2026.09.1",
            "artifact_digest": "sha256:" + "a" * 64,
            "idempotency_key": f"deploy-{suffix}",
        },
    )
    for gate in ("tests", "security", "signature"):
        release = signed_gate(
            {
                "event_id": f"evt-{gate}-{suffix}",
                "release_id": release["id"],
                "gate": gate,
                "status": "passed",
                "details": {"pipeline": "smoke"},
            }
        )
    assert release["status"] == "awaiting_approval", release
    release = request(
        "POST", f"/api/v1/releases/{release['id']}/approve", {"actor": "oncall@example.com"}
    )
    release = request(
        "POST",
        f"/api/v1/releases/{release['id']}/deploy",
        {"actor": "deploy-bot", "canary_percent": 10},
    )
    assert release["status"] == "canary", release
    release = request(
        "POST",
        f"/api/v1/releases/{release['id']}/observations",
        {"request_count": 500, "error_rate": 0.002, "p95_ms": 240},
    )
    assert release["status"] == "succeeded", release
    events = request("GET", f"/api/v1/releases/{release['id']}/events")
    assert len(events) >= 8, events

    failing_release = request(
        "POST",
        f"/api/v1/environments/{environment['id']}/releases",
        {
            "version": "2026.09.2",
            "artifact_digest": "sha256:" + "b" * 64,
            "idempotency_key": f"deploy-failing-{suffix}",
        },
    )
    for gate in ("tests", "security", "signature"):
        failing_release = signed_gate(
            {
                "event_id": f"evt-failing-{gate}-{suffix}",
                "release_id": failing_release["id"],
                "gate": gate,
                "status": "passed",
                "details": {"pipeline": "smoke"},
            }
        )
    failing_release = request(
        "POST",
        f"/api/v1/releases/{failing_release['id']}/approve",
        {"actor": "oncall@example.com"},
    )
    failing_release = request(
        "POST",
        f"/api/v1/releases/{failing_release['id']}/deploy",
        {"actor": "deploy-bot", "canary_percent": 10},
    )
    failing_release = request(
        "POST",
        f"/api/v1/releases/{failing_release['id']}/observations",
        {"request_count": 500, "error_rate": 0.12, "p95_ms": 240},
    )
    assert failing_release["status"] == "rolled_back", failing_release
    assert failing_release["previous_release_id"] == release["id"], failing_release
    print(
        json.dumps(
            {
                "status": "ok",
                "promoted_release_id": release["id"],
                "rolled_back_release_id": failing_release["id"],
                "events": len(events),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(exc.read().decode())
        raise
