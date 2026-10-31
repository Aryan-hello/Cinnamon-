import pytest

from cinnamon_modules.brain_activation import (
    is_directly_addressed,
    strip_bot_addressing,
)


@pytest.mark.parametrize("content", [
    "Cinnamon, what's my balance?",
    "hey cinnamon!!",
    "cInNaMoN can you help",
    "please Cinnamon tell me",
])
def test_name_addressing_is_case_insensitive_and_punctuation_tolerant(content):
    assert is_directly_addressed(content, bot_user_id=123)


@pytest.mark.parametrize("content", [
    "cinnamonroll is delicious",
    "I saw cinnamon in the shop",
    "the wordcinnamon",
    "cinnamon2",
])
def test_name_requires_a_standalone_token(content):
    assert not is_directly_addressed(content, bot_user_id=123)


@pytest.mark.parametrize("content", ["<@123> hi", "<@!123> what's up"])
def test_direct_bot_mention_activates(content):
    assert is_directly_addressed(content, bot_user_id=123)


def test_other_user_mention_does_not_activate():
    assert not is_directly_addressed("<@456> help", bot_user_id=123)


def test_reply_to_bot_activates_without_name_or_mention():
    assert is_directly_addressed("what about this?", bot_user_id=123, reply_author_id=123)


def test_reply_to_other_member_does_not_activate():
    assert not is_directly_addressed("what about this?", bot_user_id=123, reply_author_id=456)


@pytest.mark.parametrize("content", [
    "> Cinnamon tell me my balance",
    "```\nCinnamon help\n```",
    "`Cinnamon`",
    "> <@123> hello",
])
def test_quoted_or_code_content_does_not_activate(content):
    assert not is_directly_addressed(content, bot_user_id=123)


def test_real_address_after_quoted_text_activates():
    assert is_directly_addressed("> someone said hi\nCinnamon, help me", bot_user_id=123)


def test_strip_name_and_bot_mention_from_request():
    assert strip_bot_addressing("Hey Cinnamon, what's my balance?", bot_user_id=123) == "what's my balance?"


def test_strip_bot_mention_forms():
    assert strip_bot_addressing("<@!123> balance pls", bot_user_id=123) == "balance pls"
