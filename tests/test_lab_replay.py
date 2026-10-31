import pytest

from payops.lab.replay import replay_trace

SUCCESS = ["submit", "publish", "deliver", "commit", "ack"]
RECOVERY = [
    "submit",
    "publish",
    "deliver",
    "crash",
    "expire_lease",
    "publish",
    "deliver",
    "commit",
    "ack",
]
STALE = RECOVERY[:7] + ["late_response", "commit", "ack"]


@pytest.mark.parametrize(
    "actions",
    [
        SUCCESS,
        RECOVERY,
        STALE,
        [
            "submit",
            "publish",
            "deliver",
            "lose_response",
            "commit",
            "ack",
            "publish",
            "deliver",
            "commit",
            "ack",
        ],
    ],
)
def test_correct_implementation_preserves_invariants(actions):
    result = replay_trace(actions)
    assert result["violations"] == []
    assert result["state"]["payment"]["status"] == "succeeded"
    assert result["state"]["provider_effects"] == 1


@pytest.mark.parametrize(
    ("mutation", "actions", "invariant"),
    [
        ("omit_outbox", ["submit"], "durable_intent"),
        ("ack_before_commit", ["submit", "publish", "deliver"], "commit_before_ack"),
        ("unstable_provider_key", RECOVERY, "single_provider_effect"),
        ("accept_stale_result", STALE, "stale_result_fenced"),
    ],
)
def test_faulty_adapters_are_detected_by_observed_evidence(mutation, actions, invariant):
    result = replay_trace(actions, mutation)
    assert invariant in [v["invariant"] for v in result["violations"]]
    assert result["steps"][-1]["state"] == result["state"]
    assert replay_trace(actions)["violations"] == []


def test_each_replay_is_isolated_and_does_not_patch_application_functions():
    first = replay_trace(RECOVERY, "unstable_provider_key")
    second = replay_trace(RECOVERY)
    assert first["state"]["provider_effects"] == 2
    assert second["state"]["provider_effects"] == 1
    assert second["violations"] == []


@pytest.mark.parametrize(
    ("actions", "mutation"),
    [
        (["shell"], "baseline"),
        (SUCCESS, "typo"),
        (["observe"] * 33, "baseline"),
    ],
)
def test_replay_rejects_invalid_contract(actions, mutation):
    with pytest.raises(ValueError):
        replay_trace(actions, mutation)


def test_empty_or_inapplicable_actions_are_explained_without_inventing_failures():
    result = replay_trace(["commit", "expire_lease", "late_response"])
    assert result["violations"] == []
    assert all(not step["applied"] for step in result["steps"])
    assert result["state"]["payment"] is None
