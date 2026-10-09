"""Операторские сценарии через HTTP: состояние допуска, без управления ingress."""

import json
import time
import urllib.error
from uuid import uuid4

from scripts.smoke import request, signed_gate


def run() -> dict[str, object]:
    app = request(
        "POST",
        "/api/v1/applications",
        {
            "name": "Operator proof",
            "slug": "operator-" + uuid4().hex,
            "required_gates": ["tests", "security"],
        },
    )
    env = request(
        "POST",
        f"/api/v1/applications/{app['id']}/environments",
        {"name": "operator", "min_requests": 10, "max_error_rate": 0.01, "max_p95_ms": 200},
    )
    scenarios = {}

    def create():
        return request(
            "POST",
            f"/api/v1/environments/{env['id']}/releases",
            {
                "version": uuid4().hex,
                "artifact_digest": "sha256:" + "a" * 64,
                "idempotency_key": uuid4().hex,
            },
        )

    def gate(rid, name, status="passed"):
        return signed_gate(
            {"event_id": uuid4().hex, "release_id": rid, "gate": name, "status": status}
        )

    def events(rid):
        return request("GET", f"/api/v1/releases/{rid}/events")

    def canary():
        r = create()
        rid = r["id"]
        gate(rid, "tests")
        gate(rid, "security")
        request("POST", f"/api/v1/releases/{rid}/approve", role="approver")
        request("POST", f"/api/v1/releases/{rid}/deploy", {"canary_percent": 10})
        return rid

    rid = create()["id"]
    missing = gate(rid, "tests")
    assert (
        missing["status"] == "evaluating"
        and missing["state_reason"] == "Ожидаются проверки CI: security"
    )
    gate(rid, "security")
    request("POST", f"/api/v1/releases/{rid}/approve", role="approver")
    request("POST", f"/api/v1/releases/{rid}/deploy", {"canary_percent": 10})
    waiting = request(
        "POST",
        f"/api/v1/releases/{rid}/observations",
        {"request_count": 3, "error_rate": 0, "p95_ms": 100},
        role="observer",
    )
    assert (
        waiting["status"] == "canary"
        and waiting["state_reason"] == "Недостаточно запросов: 3 из 10"
    )
    promoted = request(
        "POST",
        f"/api/v1/releases/{rid}/observations",
        {"request_count": 10, "error_rate": 0.01, "p95_ms": 200},
        role="observer",
    )
    assert promoted["status"] == "succeeded" and promoted["traffic_percent"] == 100
    rolled = request("POST", f"/api/v1/releases/{rid}/rollback")
    assert rolled["status"] == "rolled_back" and rolled["state_reason"] == "Ручной откат"
    scenarios["insufficient_then_promote_and_manual_rollback"] = {
        "release": rolled,
        "events": events(rid),
    }

    rid = create()["id"]
    blocked = gate(rid, "security", "failed")
    assert (
        blocked["status"] == "blocked"
        and blocked["state_reason"] == "Провалены проверки CI: security"
    )
    journal = events(rid)
    try:
        gate(rid, "tests")
    except urllib.error.HTTPError as exc:
        assert exc.code == 409
    else:
        raise AssertionError("Blocked release accepted late gate")
    assert events(rid) == journal
    scenarios["failed_gate_terminal"] = {"release": blocked, "events": journal}

    rid = create()["id"]
    cancelled = request(
        "POST", f"/api/v1/releases/{rid}/cancel", {"reason": "Оператор отложил релиз"}
    )
    journal = events(rid)
    repeat = request("POST", f"/api/v1/releases/{rid}/cancel", {"reason": "Повтор запроса"})
    assert cancelled == repeat and events(rid) == journal
    scenarios["cancel_before_canary"] = {"release": cancelled, "events": journal}

    rid = canary()
    bad = request(
        "POST",
        f"/api/v1/releases/{rid}/observations",
        {"request_count": 3, "error_rate": 0.02, "p95_ms": 201},
        role="observer",
    )
    assert (
        bad["status"] == "rolled_back"
        and bad["state_reason"] == "Превышены канареечные пороги: error_rate, p95_ms"
    )
    scenarios["bad_metrics_even_with_small_sample"] = {"release": bad, "events": events(rid)}

    rid = canary()
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        timed = request("GET", f"/api/v1/releases/{rid}")
        if timed["status"] == "rolled_back":
            break
        time.sleep(0.2)
    else:
        raise TimeoutError("Reconciler did not finish the canary; configure a short proof timeout")
    assert timed["state_reason"] == "Истекло время ожидания канареечных метрик"
    journal = events(rid)
    assert any(e["event_type"] == "canary.timeout" for e in journal)
    scenarios["missing_metrics_timeout"] = {"release": timed, "events": journal}
    return {
        "scenarios": scenarios,
        "scope": (
            "HTTP API + persisted journal + reconciler; "
            "traffic_percent is modeled state, no ingress traffic was switched"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
