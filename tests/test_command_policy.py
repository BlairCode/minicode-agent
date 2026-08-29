import pytest

from minicode_agent.safety import CommandPolicy, RiskLevel


def test_safe_test_command_is_allowed() -> None:
    decision = CommandPolicy("ask").evaluate("python -m pytest -q")
    assert decision.risk is RiskLevel.SAFE
    assert decision.allowed
    assert not decision.approval_required


def test_javascript_test_command_is_safe() -> None:
    decision = CommandPolicy("ask").evaluate("npm test")
    assert decision.risk is RiskLevel.SAFE
    assert decision.allowed


def test_dependency_install_requires_approval() -> None:
    decision = CommandPolicy("ask").evaluate("python -m pip install requests")
    assert decision.risk is RiskLevel.MEDIUM
    assert decision.approval_required


@pytest.mark.parametrize(
    "command",
    ["git reset --hard HEAD", "git clean -fd", "rm -rf build"],
)
def test_destructive_command_is_high_risk(command: str) -> None:
    decision = CommandPolicy("full").evaluate(command)
    assert decision.risk is RiskLevel.HIGH
    assert decision.approval_required


def test_shell_composition_is_blocked() -> None:
    decision = CommandPolicy("full").evaluate("pytest | tee result.txt")
    assert decision.risk is RiskLevel.BLOCKED
    assert not decision.allowed


def test_network_command_respects_network_setting() -> None:
    assert CommandPolicy("full", network_access=False).evaluate("curl https://example.com").risk is RiskLevel.BLOCKED
    assert CommandPolicy("full", network_access=True).evaluate("curl https://example.com").risk is RiskLevel.MEDIUM
