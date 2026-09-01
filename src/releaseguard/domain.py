from enum import StrEnum


class ReleaseStatus(StrEnum):
    evaluating = "evaluating"
    blocked = "blocked"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    canary = "canary"
    succeeded = "succeeded"
    rolled_back = "rolled_back"


class GateStatus(StrEnum):
    passed = "passed"
    failed = "failed"


class CanaryDecision(StrEnum):
    continue_observing = "continue"
    promote = "promote"
    rollback = "rollback"


def evaluate_gates(
    required_gates: list[str], results: dict[str, GateStatus], *, requires_approval: bool
) -> ReleaseStatus:
    relevant = [results[name] for name in required_gates if name in results]
    if GateStatus.failed in relevant:
        return ReleaseStatus.blocked
    if not required_gates or len(relevant) == len(required_gates):
        return ReleaseStatus.awaiting_approval if requires_approval else ReleaseStatus.approved
    return ReleaseStatus.evaluating


def evaluate_canary(
    *,
    request_count: int,
    error_rate: float,
    p95_ms: int,
    min_requests: int,
    max_error_rate: float,
    max_p95_ms: int,
) -> CanaryDecision:
    if error_rate > max_error_rate or p95_ms > max_p95_ms:
        return CanaryDecision.rollback
    if request_count >= min_requests:
        return CanaryDecision.promote
    return CanaryDecision.continue_observing


def require_transition(current: ReleaseStatus, target: ReleaseStatus) -> None:
    allowed = {
        ReleaseStatus.evaluating: {
            ReleaseStatus.blocked,
            ReleaseStatus.awaiting_approval,
            ReleaseStatus.approved,
        },
        ReleaseStatus.awaiting_approval: {ReleaseStatus.approved, ReleaseStatus.blocked},
        ReleaseStatus.approved: {ReleaseStatus.canary},
        ReleaseStatus.canary: {ReleaseStatus.succeeded, ReleaseStatus.rolled_back},
        ReleaseStatus.succeeded: {ReleaseStatus.rolled_back},
    }
    if target not in allowed.get(current, set()):
        raise ValueError(f"transition {current.value} -> {target.value} is not allowed")
