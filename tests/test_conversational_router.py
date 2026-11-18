import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from cinnamon_modules.conversational_router import _ccr_command

class ConversationalRouterTests(unittest.TestCase):
    def test_directed_balance_and_work(self):
        self.assertEqual(_ccr_command("Cinnamon, how much Catnip do I have?"), "balance")
        self.assertEqual(_ccr_command("Cinnamon work please"), "work")
        self.assertEqual(_ccr_command("Cinnamon, can I work?"), "work")

    def test_daily_shop_inventory(self):
        self.assertEqual(_ccr_command("Cinnamon claim my daily"), "daily")
        self.assertEqual(_ccr_command("Cinnamon show me the shop"), "shop")
        self.assertEqual(_ccr_command("Cinnamon show my inventory"), "inventory")

    def test_buy_known_item_only(self):
        self.assertEqual(_ccr_command("Cinnamon buy me tuna"), "buy tuna 1")
        self.assertEqual(_ccr_command("Cinnamon buy 3 tuna"), "buy tuna 3")
        self.assertIsNone(_ccr_command("Cinnamon buy me a dragon"))
        self.assertIsNone(_ccr_command("Cinnamon buy 99 tuna"))

    def test_ambiguous_chat_does_not_route(self):
        self.assertIsNone(_ccr_command("Cinnamon, I had a long day"))
        self.assertIsNone(_ccr_command("I had a long day and spent some coins"))

def load_router(bot):
    path = Path(__file__).resolve().parents[1] / "cinnamon_modules" / "conversational_router.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_ccr_clean", "_ccr_command", "_ccr_invoke", "_ccr_maybe_route"}
    body = [node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names]
    namespace = {"_ccr_re": re, "bot": bot}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class ConversationalRouterRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_shortcut_uses_current_prefix_and_restores_message(self):
        seen = []
        context = SimpleNamespace(valid=True)

        async def get_context(message):
            seen.append(message.content)
            return context

        bot = SimpleNamespace(get_context=get_context, invoke=AsyncMock())
        namespace = load_router(bot)
        original = "Cinnamon, work please"
        message = SimpleNamespace(
            content=original, guild=SimpleNamespace(id=1),
            author=SimpleNamespace(bot=False),
        )
        handled = await namespace["_ccr_maybe_route"](message, original)
        self.assertTrue(handled)
        self.assertEqual(seen, ["!work"])
        bot.invoke.assert_awaited_once_with(context)
        self.assertEqual(message.content, original)

    async def test_ambiguous_chat_never_invokes_a_command_or_ai_router(self):
        bot = SimpleNamespace(
            get_context=AsyncMock(),
            invoke=AsyncMock(),
        )
        namespace = load_router(bot)
        message = SimpleNamespace(
            content="Cinnamon, I had a long day",
            guild=SimpleNamespace(id=1),
            author=SimpleNamespace(bot=False),
        )
        handled = await namespace["_ccr_maybe_route"](message, message.content)
        self.assertFalse(handled)
        bot.get_context.assert_not_awaited()
        bot.invoke.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
