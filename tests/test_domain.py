import pytest

from releaseguard.domain import (
    CanaryDecision,
    GateStatus,
    ReleaseStatus,
    evaluate_canary,
    evaluate_gates,
    require_transition,
)


def test_gate_policy_waits_for_all_required_results() -> None:
    result = evaluate_gates(
        ["tests", "security"], {"tests": GateStatus.passed}, requires_approval=False
    )

    assert result == ReleaseStatus.evaluating


def test_gate_policy_blocks_on_any_failure() -> None:
    result = evaluate_gates(
        ["tests", "security"],
        {"tests": GateStatus.passed, "security": GateStatus.failed},
        requires_approval=False,
    )

    assert result == ReleaseStatus.blocked


def test_gate_policy_can_require_human_approval() -> None:
    result = evaluate_gates(["tests"], {"tests": GateStatus.passed}, requires_approval=True)

    assert result == ReleaseStatus.awaiting_approval


@pytest.mark.parametrize(
    ("requests", "error_rate", "p95_ms", "expected"),
    [
        (10, 0.001, 200, CanaryDecision.continue_observing),
        (500, 0.001, 200, CanaryDecision.promote),
        (500, 0.1, 200, CanaryDecision.rollback),
        (500, 0.001, 2_000, CanaryDecision.rollback),
    ],
)
def test_canary_policy(
    requests: int, error_rate: float, p95_ms: int, expected: CanaryDecision
) -> None:
    assert (
        evaluate_canary(
            request_count=requests,
            error_rate=error_rate,
            p95_ms=p95_ms,
            min_requests=100,
            max_error_rate=0.02,
            max_p95_ms=800,
        )
        == expected
    )


def test_state_machine_rejects_skipping_canary() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        require_transition(ReleaseStatus.approved, ReleaseStatus.succeeded)
