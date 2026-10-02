import pytest
from pydantic import ValidationError

from redbench.scenario import AgentScenario, AttackerGoal, Email, EnvironmentSpec, Injection, make_canary

GOAL = AttackerGoal(kind="canary_exfil")


def test_canary_is_deterministic_per_seed():
    assert make_canary(1) == make_canary(1)
    assert make_canary(1) != make_canary(2)
    assert make_canary(1).startswith("CANARY-")


def test_materialize_plants_canary_and_inserts_payload_at_marker():
    scenario = AgentScenario(
        environment=EnvironmentSpec(
            files={"a.txt": "secret={canary}"},
            web={"https://site.example.invalid/": "before {injection} after"},
        ),
        injection=Injection(location="web", key="https://site.example.invalid/", payload="PLACEHOLDER_PAYLOAD"),
        attacker_goal=GOAL,
    )
    env = scenario.materialize("CANARY-X")
    assert env.files["a.txt"] == "secret=CANARY-X"
    assert env.web["https://site.example.invalid/"] == "before PLACEHOLDER_PAYLOAD after"


def test_materialize_appends_without_marker_and_targets_email():
    scenario = AgentScenario(
        environment=EnvironmentSpec(inbox=[Email(id="m1", sender="s", subject="t", body="hello")]),
        injection=Injection(location="email", key="m1", payload="PLACEHOLDER_PAYLOAD"),
        attacker_goal=GOAL,
    )
    assert scenario.materialize("C").inbox[0].body == "hello\n\nPLACEHOLDER_PAYLOAD"


def test_unused_marker_removed_for_benign_control():
    scenario = AgentScenario(environment=EnvironmentSpec(files={"a.txt": "x{injection}y"}), attacker_goal=GOAL)
    assert scenario.materialize("C").files["a.txt"] == "xy"


def test_injection_target_must_exist():
    with pytest.raises(ValidationError, match="not in the environment"):
        AgentScenario(injection=Injection(location="file", key="missing.txt", payload="p"), attacker_goal=GOAL)


@pytest.mark.parametrize(
    "goal",
    [
        {"kind": "tool_call"},
        {"kind": "canary_exfil", "tool": "send_email"},
    ],
)
def test_attacker_goal_validation(goal):
    with pytest.raises(ValidationError):
        AttackerGoal(**goal)


def test_duplicate_email_ids_rejected():
    email = Email(id="m1", sender="s", subject="t", body="b")
    with pytest.raises(ValidationError, match="unique"):
        EnvironmentSpec(inbox=[email, email])
