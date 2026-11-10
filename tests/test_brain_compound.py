from cinnamon_modules.brain_compound import parse_compound_request
from cinnamon_modules.brain_actions import ActionValidationError


A = "<@123456789012345>"
B = "<@223456789012345>"
C = "<@323456789012345>"


def test_add_to_two_members_and_timeout_is_expanded():
    plan = parse_compound_request(f"add 2k catnip to {A} and {B} and mute {C} for 10 minutes")
    assert len(plan.actions) == 3
    assert [x.action for x in plan.actions] == [
        "economy.add_catnip", "economy.add_catnip", "moderation.timeout"
    ]
    assert [x.target_user_id for x in plan.actions] == [123456789012345, 223456789012345, 323456789012345]
    assert plan.actions[0].amount == plan.actions[1].amount == 2000
    assert plan.actions[2].seconds == 600


def test_k_and_m_amounts_and_duration_units():
    plan = parse_compound_request(f"add 1.5k catnip to {A} and mute {B} for 2h")
    assert plan.actions[0].amount == 1500
    assert plan.actions[1].seconds == 7200


def test_single_action_is_left_to_existing_parser():
    assert parse_compound_request(f"add 100 catnip to {A}") is None


def test_unsupported_clause_fails_closed():
    try:
        parse_compound_request(f"add 100 catnip to {A} and ban {B}")
    except ActionValidationError as exc:
        assert "couldn't safely parse" in str(exc)
    else:
        raise AssertionError("unsupported compound must fail closed")


def test_rejects_duplicate_targets_and_too_many_expanded_actions():
    try:
        parse_compound_request(f"add 100 catnip to {A} and {A} and mute {B} for 1m")
    except ActionValidationError:
        pass
    else:
        raise AssertionError("duplicate targets should be rejected")
