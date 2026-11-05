"""Run the real shared-runtime dispatch functions without credentials or services."""
import ast
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1]


def load_functions(names, namespace):
    from cinnamon_modules.brain_intent import plan_intent
    namespace.setdefault('plan_intent', plan_intent)
    tree = ast.parse((ROOT / 'cinnamon_modules/core_events.py').read_text())
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            body.append(node)
    exec(compile(ast.Module(body=body, type_ignores=[]), 'core_events.py', 'exec'), namespace)
    return namespace


class AssistanceDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_is_handled_without_an_action(self):
        help_handler = AsyncMock(return_value=True)
        action_handler = AsyncMock()
        ns = load_functions({'_cinnamon_try_assistance'}, {
            '_ch_maybe_handle': help_handler, '_ca_maybe_handle': action_handler,
        })
        message = SimpleNamespace(guild=object())
        self.assertTrue(await ns['_cinnamon_try_assistance'](message, 'how do I fish?'))
        help_handler.assert_awaited_once_with(message, 'how do I fish?')
        action_handler.assert_not_awaited()

    async def test_private_data_questions_redirect_before_public_chat(self):
        private_handler = AsyncMock(return_value=True)
        help_handler = AsyncMock(return_value=False)
        ns = load_functions({'_cinnamon_try_assistance'}, {
            '_ch_maybe_handle': help_handler,
            '_ch_private_data_redirect': private_handler,
            '_ca_maybe_handle': AsyncMock(return_value=False),
        })
        message = SimpleNamespace(guild=object())
        self.assertTrue(await ns['_cinnamon_try_assistance'](
            message, 'How much Catnip do I have?'
        ))
        private_handler.assert_awaited_once_with(message, 'How much Catnip do I have?')
        help_handler.assert_not_awaited()

    async def test_actions_keep_the_original_discord_message(self):
        handler = AsyncMock(return_value=True)
        ns = load_functions({'_cinnamon_try_assistance'}, {
            '_ch_maybe_handle': AsyncMock(return_value=False), '_ca_maybe_handle': handler,
        })
        message = SimpleNamespace(guild=object(), author=object(), id=123)
        self.assertTrue(await ns['_cinnamon_try_assistance'](message, 'add 20000 Catnip to @member'))
        handler.assert_awaited_once_with(message, 'add 20000 Catnip to @member')

    async def test_direct_messages_never_reach_guild_actions(self):
        handler = AsyncMock()
        ns = load_functions({'_cinnamon_try_assistance'}, {
            '_ch_maybe_handle': AsyncMock(return_value=False), '_ca_maybe_handle': handler,
        })
        self.assertFalse(await ns['_cinnamon_try_assistance'](SimpleNamespace(guild=None), 'hello'))
        handler.assert_not_awaited()

    async def test_prefix_ask_uses_the_same_assistance_path(self):
        assistance = AsyncMock(return_value=True)
        ctx = SimpleNamespace(channel=SimpleNamespace(id=4), guild=SimpleNamespace(id=3), message=object())
        ns = load_functions({'prefix_ask'}, {'disabled_channels': defaultdict(set),
                                           '_cinnamon_try_assistance': assistance})
        await ns['prefix_ask'](ctx, prompt='what does /recall do?')
        assistance.assert_awaited_once_with(ctx.message, 'what does /recall do?')

    async def test_disabled_prefix_channel_stays_silent(self):
        assistance = AsyncMock()
        ctx = SimpleNamespace(channel=SimpleNamespace(id=4), guild=SimpleNamespace(id=3))
        ns = load_functions({'prefix_ask'}, {'disabled_channels': {3: {4}},
                                           '_cinnamon_try_assistance': assistance})
        await ns['prefix_ask'](ctx, prompt='help')
        assistance.assert_not_awaited()

    async def test_invited_help_bypasses_grumpy_mood_and_pranks(self):
        user = SimpleNamespace(id=99)
        author = SimpleNamespace(id=11, bot=False, display_name='Member')
        message = SimpleNamespace(author=author, content='<@99> how do I fish?',
                                  guild=SimpleNamespace(id=3), channel=SimpleNamespace(id=4),
                                  mentions=[user], mention_everyone=False, reference=None)
        assistance = AsyncMock(return_value=True)
        prank, mood, model = AsyncMock(), AsyncMock(), Mock()
        memory = defaultdict(lambda: deque(maxlen=10))
        ns = load_functions({'on_message'}, {
            'discord': SimpleNamespace(Message=object),
            'bot': SimpleNamespace(user=user, get_context=AsyncMock(return_value=SimpleNamespace(valid=False))),
            'afk_users': {}, 'run_automod': AsyncMock(return_value=False),
            'award_xp': AsyncMock(), 'channel_memories': memory,
            'disabled_channels': defaultdict(set), 'category_log_channels': {},
            '_cb_observe': Mock(), 'ai_channels': {}, '_cp_direct_name': lambda text: False,
            'time': SimpleNamespace(monotonic=lambda: 100),
            '_cinnamon_try_assistance': assistance, '_ca_maybe_prank': prank,
            '_cm_ping': mood, 'ask_gemini': model,
        })
        await ns['on_message'](message)
        assistance.assert_awaited_once_with(message, 'how do I fish?')
        prank.assert_not_awaited()
        mood.assert_not_awaited()
        model.assert_not_called()

    async def test_disabled_channel_does_not_enter_conversation_memory(self):
        user = SimpleNamespace(id=99)
        message = SimpleNamespace(author=SimpleNamespace(id=11, bot=False, display_name='Member'),
                                  content='private conversation', guild=SimpleNamespace(id=3),
                                  channel=SimpleNamespace(id=4), mentions=[])
        memory = defaultdict(lambda: deque(maxlen=10))
        ns = load_functions({'on_message'}, {
            'discord': SimpleNamespace(Message=object),
            'bot': SimpleNamespace(user=user, get_context=AsyncMock(return_value=SimpleNamespace(valid=False))),
            'afk_users': {}, 'run_automod': AsyncMock(return_value=False),
            'award_xp': AsyncMock(), 'channel_memories': memory, 'disabled_channels': {3: {4}},
        })
        await ns['on_message'](message)
        self.assertEqual(dict(memory), {})


if __name__ == '__main__':
    unittest.main()
