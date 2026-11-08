"""Natural-language memory controls remain explicit, private and member-scoped."""
import ast
from pathlib import Path
import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]


def load_handler(namespace):
    path = ROOT / "cinnamon_modules" / "cinnamon_memory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body
                if isinstance(item, ast.AsyncFunctionDef)
                and item.name == "_cmem_maybe_handle")
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
         namespace)
    return namespace["_cmem_maybe_handle"]


class FakeAllowedMentions:
    @staticmethod
    def none():
        return None


class MemoryChatControlTests(unittest.IsolatedAsyncioTestCase):
    def make_message(self, *, guild=True):
        message = SimpleNamespace(
            guild=SimpleNamespace(id=10) if guild else None,
            author=SimpleNamespace(id=20),
            reply=AsyncMock(),
        )
        return message

    async def test_explicit_opt_out_clears_only_requesting_members_notes(self):
        set_enabled = AsyncMock(return_value=True)
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "_cmem_set_enabled": set_enabled,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message()
        handled = await handler(message, "Cinnamon, turn my memory off")
        self.assertTrue(handled)
        set_enabled.assert_awaited_once_with(10, 20, False)
        self.assertIn("cleared", message.reply.await_args.args[0].lower())

    async def test_failed_opt_out_does_not_claim_success(self):
        set_enabled = AsyncMock(return_value=False)
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "_cmem_set_enabled": set_enabled,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message()
        await handler(message, "forget everything about me")
        self.assertIn("storage didn't confirm",
                      message.reply.await_args.args[0].lower())

    async def test_explicit_opt_in_is_member_scoped(self):
        set_enabled = AsyncMock(return_value=True)
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "_cmem_set_enabled": set_enabled,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message()
        await handler(message, "turn my memory on")
        set_enabled.assert_awaited_once_with(10, 20, True)

    async def test_ambiguous_single_note_request_never_deletes_everything(self):
        set_enabled = AsyncMock()
        remove = AsyncMock()
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "_cmem_set_enabled": set_enabled,
            "_cmem_remove": remove,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message()
        handled = await handler(message, "forget my saved preference")
        self.assertTrue(handled)
        set_enabled.assert_not_awaited()
        remove.assert_not_awaited()
        self.assertIn("/cinnamon-memory view",
                      message.reply.await_args.args[0])

    async def test_clear_request_uses_member_scoped_removal(self):
        remove = AsyncMock(return_value=(True, "All your Cinnamon notes were cleared."))
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "_cmem_remove": remove,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message()
        handled = await handler(message, "clear my notes")
        self.assertTrue(handled)
        remove.assert_awaited_once_with(10, 20)

    async def test_edit_request_points_to_self_service_command(self):
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message()
        handled = await handler(message, "edit my preferences")
        self.assertTrue(handled)
        self.assertIn("/cinnamon-memory edit",
                      message.reply.await_args.args[0])

    async def test_view_request_points_to_private_command(self):
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message()
        handled = await handler(message, "show my notes")
        self.assertTrue(handled)
        self.assertIn("/cinnamon-memory view",
                      message.reply.await_args.args[0])

    async def test_direct_messages_do_not_enter_guild_memory_controls(self):
        set_enabled = AsyncMock()
        handler = load_handler({
            "_cmem_re": re,
            "_cmem_parse": lambda text: None,
            "_CMEM_ERROR": ValueError,
            "_cmem_set_enabled": set_enabled,
            "discord": SimpleNamespace(AllowedMentions=FakeAllowedMentions),
        })
        message = self.make_message(guild=False)
        self.assertFalse(await handler(message, "turn my memory off"))
        set_enabled.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
