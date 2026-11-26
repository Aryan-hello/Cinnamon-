"""Regression tests for Mythical pet passives and fishing treasure chests."""
import ast
import asyncio
import copy
import random
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PETS = ROOT / "cinnamon_modules" / "collectible_pets_crime.py"
FISHING = ROOT / "cinnamon_modules" / "cinnamon_adventure_fishing.py"
ADVANCED = ROOT / "cinnamon_modules" / "advanced_economy.py"


def extract(path, names, assignments, namespace):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in assignments
            for target in node.targets
        ):
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class FixedRandom:
    def __init__(self, number=0):
        self.number = number

    def random(self):
        return self.number

    def choices(self, values, weights=None, k=1):
        return [values[0] for _ in range(k)]

    def randint(self, low, high):
        return low


class MythicalPetTests(unittest.TestCase):
    def test_mythical_pets_are_in_normal_discovery_catalog(self):
        tree = ast.parse(PETS.read_text(encoding="utf-8"))
        catalog = next(node.value for node in tree.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "_COLLECTIBLE_PET_CATALOG"
                               for t in node.targets))
        entries = {
            next(v.value for k, v in zip(item.keys, item.values)
                 if isinstance(k, ast.Constant) and k.value == "species"):
            next(v.value for k, v in zip(item.keys, item.values)
                 if isinstance(k, ast.Constant) and k.value == "ability")
            for item in catalog.elts
        }
        expected = {
            "Griffin": "mission_master",
            "Kitsune": "double_illusion",
            "Kraken": "treasure_hunter",
            "Golem": "unbreakable_core",
            "Starling": "cosmic_jackpot",
            "Owl": "night_watch",
        }
        for species, ability in expected.items():
            self.assertEqual(entries.get(species), ability)

    def test_kitsune_golem_and_starling_have_live_integrations(self):
        advanced = ADVANCED.read_text(encoding="utf-8")
        pets = PETS.read_text(encoding="utf-8")
        self.assertIn('"double_illusion"', advanced)
        self.assertIn("Kitsune's Double Illusion", advanced)
        self.assertIn('"unbreakable_core"', advanced)
        self.assertIn("Golem's Unbreakable Core", advanced)
        self.assertIn('"cosmic_jackpot"', pets)
        self.assertIn("return amount * 2", pets)


class FishingTreasureTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self, save=True, rng=None, pet=None):
        player = {
            "treasure_chests": {"common": 1},
            "bait": {"normal": 10},
            "fish": {},
            "seen": [],
        }
        balances = {(1, 7): 50}

        async def persist():
            return save

        namespace = {
            "asyncio": asyncio,
            "_wlf_copy": copy,
            "_wlf_random": rng or FixedRandom(),
            "_WLF_TREASURE_CHEST_TIERS": {
                "common": {"label": "Common", "emoji": "🟫", "weight": 72,
                           "catnip": (100, 250), "bait": "normal"},
                "rare": {"label": "Rare", "emoji": "🟦", "weight": 20,
                         "catnip": (250, 600), "bait": "glow"},
                "epic": {"label": "Epic", "emoji": "🟪", "weight": 7,
                         "catnip": (600, 1200), "bait": "tide"},
                "legendary": {"label": "Legendary", "emoji": "🟨", "weight": 1,
                              "catnip": (1200, 2500), "bait": "moon"},
            },
            "_WLF_TREASURE_COLLECTIBLES": {
                "common": "Old Coin", "rare": "Pearl Fragment",
                "epic": "Ancient Scale", "legendary": "Abyssal Pearl",
            },
            "_WLF_BAIT": [
                {"id": "normal", "name": "Normal Bait"},
                {"id": "glow", "name": "Glowworm Bait"},
                {"id": "tide", "name": "Tide Pearl Bait"},
                {"id": "moon", "name": "Moonblossom Bait"},
            ],
            "_CINNAMON_SHOP_LOCKS": {},
            "_wlf_player": lambda gid, uid: player,
            "_collectible_pet_ability": lambda gid, uid: pet or {},
            "economy_balances": balances,
            "economy_balance": lambda gid, uid: balances.get((int(gid), int(uid)), 0),
            "bd_save_data": persist,
        }
        extract(FISHING, {"_wlf_roll_treasure_chest", "_wlf_open_treasure_chests"},
                set(), namespace)
        return namespace, player, balances

    async def test_kraken_increases_chest_discovery_chance(self):
        ns, player, _ = self.runtime(
            rng=FixedRandom(0.05),
            pet={"ability": "treasure_hunter", "value": 0.05},
        )
        tier = ns["_wlf_roll_treasure_chest"](1, 7)
        self.assertEqual(tier, "common")
        self.assertEqual(player["treasure_chests"]["common"], 2)

    async def test_base_fishing_can_find_chest(self):
        ns, player, _ = self.runtime(rng=FixedRandom(0))
        tier = ns["_wlf_roll_treasure_chest"](1, 7)
        self.assertEqual(tier, "common")
        self.assertEqual(player["treasure_chests"]["common"], 2)

    async def test_chest_opening_grants_reward_and_consumes_chest(self):
        ns, player, balances = self.runtime()
        ok, message, rewards = await ns["_wlf_open_treasure_chests"](1, 7, "common", 1)
        self.assertTrue(ok)
        self.assertEqual(player["treasure_chests"], {})
        self.assertEqual(balances[(1, 7)], 150)
        self.assertEqual(rewards, ["🌿 +100 Catnip"])

    async def test_failed_save_restores_chest_and_wallet(self):
        ns, player, balances = self.runtime(save=False)
        ok, _, rewards = await ns["_wlf_open_treasure_chests"](1, 7, "common", 1)
        self.assertFalse(ok)
        self.assertEqual(rewards, [])
        self.assertEqual(player["treasure_chests"], {"common": 1})
        self.assertEqual(balances[(1, 7)], 50)

    def test_both_fishing_modes_roll_for_chests_and_commands_exist(self):
        adventure = FISHING.read_text(encoding="utf-8")
        timed = (ROOT / "cinnamon_modules" / "cinnamon_fishing_game.py").read_text(encoding="utf-8")
        self.assertIn("_wlf_roll_treasure_chest(self.guild_id, self.owner_id)", adventure)
        self.assertIn("chest_fn(self.gid, self.uid)", timed)
        self.assertIn("_wlf_roll_treasure_chest", timed)
        self.assertIn('name="chests"', adventure)
        self.assertIn('name="open-chest"', adventure)


if __name__ == "__main__":
    unittest.main()
