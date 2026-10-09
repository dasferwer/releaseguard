import pytest

from releaseguard.domain import GateStatus, canary_reason, gate_reason


def test_gate_reason_names_missing_and_failed_checks():
    assert (
        gate_reason(["tests", "security"], {"tests": GateStatus.passed}, requires_approval=True)
        == "Ожидаются проверки CI: security"
    )
    assert (
        gate_reason(["tests", "security"], {"tests": GateStatus.failed}, requires_approval=True)
        == "Провалены проверки CI: tests"
    )
    assert (
        gate_reason(["tests"], {"tests": GateStatus.passed}, requires_approval=True)
        == "Проверки CI пройдены; ожидается ручное согласование"
    )
    assert (
        gate_reason(["tests"], {"tests": GateStatus.passed}, requires_approval=False)
        == "Проверки CI пройдены; ручное согласование не требуется"
    )


@pytest.mark.parametrize(
    "count,errors,p95,reason",
    [
        (3, 0.0, 100, "Недостаточно запросов: 3 из 10"),
        (10, 0.01, 200, "Достаточно запросов; канареечные пороги соблюдены"),
        (3, 0.02, 201, "Превышены канареечные пороги: error_rate, p95_ms"),
    ],
)
def test_canary_reason_distinguishes_sample_size_and_thresholds(count, errors, p95, reason):
    assert (
        canary_reason(
            request_count=count,
            error_rate=errors,
            p95_ms=p95,
            min_requests=10,
            max_error_rate=0.01,
            max_p95_ms=200,
        )
        == reason
    )
