"""Regression tests for collectible pets, cartoon capers, and giveaway publishing."""
import ast
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "cinnamon_modules"


def load_functions(path, names, assignments=(), extra=None):
    tree = ast.parse((MODULES / path).read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name in targets for name in assignments):
                nodes.append(node)
    namespace = extra if extra is not None else {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), namespace)
    return namespace


async def async_noop(*args, **kwargs):
    return None


class CollectiblePetPersistenceTests(unittest.TestCase):
    def make_namespace(self, saved):
        return {
            "advanced_features_data": {
                "collectible_pets_v1": {
                    "10": {
                        "20": {
                            "pets": [{"id": "pet-1", "species": "Tabby Cat", "emoji": "🐈", "rarity": "Common", "xp": 5, "level": 1}],
                            "active_id": "pet-1",
                        }
                    }
                }
            },
            "_cp_copy": copy,
            "_cp_random": SimpleNamespace(random=lambda: 1.0, choices=lambda values, **kwargs: [values[0]], randint=lambda a, b: 123),
            "_cp_time": SimpleNamespace(time=lambda: 1000),
            "bd_save_data": saved,
            "economy_log": async_noop,
        }

    def pet_functions(self, namespace):
        return load_functions(
            "collectible_pets_crime.py",
            {"_collectible_pet_user", "_collectible_pet_active", "_collectible_pet_level", "collectible_pet_work_drop"},
            {"_COLLECTIBLE_PETS_KEY", "_COLLECTIBLE_PET_CATALOG"},
            namespace,
        )

    def test_active_pet_xp_rolls_back_when_snapshot_save_fails(self):
        async def failed_save():
            return False
        ns = self.make_namespace(failed_save)
        before = copy.deepcopy(ns["advanced_features_data"])
        functions = self.pet_functions(ns)
        result = asyncio.run(functions["collectible_pet_work_drop"](10, SimpleNamespace(id=20)))
        self.assertIsNone(result)
        self.assertEqual(ns["advanced_features_data"], before)

    def test_new_discovery_is_not_kept_when_snapshot_save_fails(self):
        async def failed_save():
            return False
        ns = self.make_namespace(failed_save)
        ns["advanced_features_data"] = {}
        ns["_cp_random"] = SimpleNamespace(random=lambda: 0.0, choices=lambda values, **kwargs: [values[0]], randint=lambda a, b: 123)
        result = asyncio.run(self.pet_functions(ns)["collectible_pet_work_drop"](10, SimpleNamespace(id=20)))
        self.assertIsNone(result)
        self.assertEqual(ns["advanced_features_data"], {})

    def test_active_pet_xp_is_saved_on_success(self):
        async def successful_save():
            return True
        ns = self.make_namespace(successful_save)
        self.pet_functions(ns)
        asyncio.run(self.pet_functions(ns)["collectible_pet_work_drop"](10, SimpleNamespace(id=20)))
        pet = ns["advanced_features_data"]["collectible_pets_v1"]["10"]["20"]["pets"][0]
        self.assertEqual(pet["xp"], 15)


class CrimePersistenceTests(unittest.TestCase):
    def test_failed_save_restores_catnip_and_removes_new_cooldown(self):
        async def failed_save():
            return False
        replies = []
        class Context:
            guild = SimpleNamespace(id=10)
            author = SimpleNamespace(id=20)
            async def reply(self, *args, **kwargs):
                replies.append((args, kwargs))
        ns = {
            "_cp_random": SimpleNamespace(choice=lambda values: values[0], random=lambda: 0.0, randint=lambda a, b: 100),
            "_cp_time": SimpleNamespace(time=lambda: 5000),
            "_collectible_pet_perks": lambda guild_id, user_id: {"luck": 0.0, "fine_guard": 0.0, "reward": 0.0, "pet": None},
            "economy_cooldown_remaining": lambda *args: 0,
            "economy_balances": {(10, 20): 500},
            "economy_cooldowns": {},
            "economy_balance": lambda guild_id, user_id: ns["economy_balances"].get((guild_id, user_id), 0),
            "bd_save_data": failed_save,
            "discord": SimpleNamespace(AllowedMentions=SimpleNamespace(none=lambda: None)),
        }
        functions = load_functions("collectible_pets_crime.py", {"prefix_crime"}, extra=ns)
        asyncio.run(functions["prefix_crime"](Context()))
        self.assertEqual(ns["economy_balances"][(10, 20)], 500)
        self.assertNotIn((10, 20, "crime"), ns["economy_cooldowns"])
        self.assertTrue(replies)
        self.assertIn("couldn't save", replies[0][0][0].lower())


class GiveawayPermissionTests(unittest.TestCase):
    def test_publish_rechecks_current_permission(self):
        replies = []
        async def deny(*args, **kwargs):
            replies.append((args, kwargs))
        async def should_not_publish(*args, **kwargs):
            raise AssertionError("A revoked user must not publish")
        ns = {"_giveaway_role_gate": lambda interaction: False, "cinnamon_send": deny, "_create_giveaway": should_not_publish}
        functions = load_functions("giveaway_wizard.py", {"_gw_publish"}, extra=ns)
        asyncio.run(functions["_gw_publish"](SimpleNamespace(), SimpleNamespace(draft={})))
        self.assertTrue(replies)
        self.assertIn("no longer have permission", replies[0][0][1].lower())
        self.assertTrue(replies[0][1]["ephemeral"])


class SlashWorkWiringTests(unittest.TestCase):
    def test_slash_work_uses_the_collectible_pet_progression_hook(self):
        source = (MODULES / "economy.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "economy_work_cmd")
        handler_source = ast.get_source_segment(source, handler)
        self.assertIn("collectible_pet_work_drop", handler_source)
        self.assertIn("New discovery", handler_source)


if __name__ == "__main__":
    unittest.main()
