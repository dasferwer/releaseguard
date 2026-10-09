from enum import StrEnum


class ReleaseStatus(StrEnum):
    evaluating = "evaluating"
    blocked = "blocked"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    canary = "canary"
    succeeded = "succeeded"
    rolled_back = "rolled_back"
    cancelled = "cancelled"


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
            ReleaseStatus.cancelled,
        },
        ReleaseStatus.awaiting_approval: {
            ReleaseStatus.approved,
            ReleaseStatus.blocked,
            ReleaseStatus.cancelled,
        },
        ReleaseStatus.approved: {ReleaseStatus.canary, ReleaseStatus.cancelled},
        ReleaseStatus.canary: {ReleaseStatus.succeeded, ReleaseStatus.rolled_back},
        ReleaseStatus.succeeded: {ReleaseStatus.rolled_back},
    }
    if target not in allowed.get(current, set()):
        raise ValueError(f"Переход {current.value} → {target.value} запрещён")


def gate_reason(
    required_gates: list[str], results: dict[str, GateStatus], *, requires_approval: bool
) -> str:
    failed = [name for name in required_gates if results.get(name) == GateStatus.failed]
    missing = [name for name in required_gates if name not in results]
    if failed:
        return "Провалены проверки CI: " + ", ".join(failed)
    if missing:
        return "Ожидаются проверки CI: " + ", ".join(missing)
    return (
        "Проверки CI пройдены; ожидается ручное согласование"
        if requires_approval
        else "Проверки CI пройдены; ручное согласование не требуется"
    )


def canary_reason(
    *,
    request_count: int,
    error_rate: float,
    p95_ms: int,
    min_requests: int,
    max_error_rate: float,
    max_p95_ms: int,
) -> str:
    exceeded = []
    if error_rate > max_error_rate:
        exceeded.append("error_rate")
    if p95_ms > max_p95_ms:
        exceeded.append("p95_ms")
    if exceeded:
        return "Превышены канареечные пороги: " + ", ".join(exceeded)
    if request_count < min_requests:
        return f"Недостаточно запросов: {request_count} из {min_requests}"
    return "Достаточно запросов; канареечные пороги соблюдены"
