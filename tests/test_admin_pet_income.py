"""Regression tests for Cinnamon's admin-only hourly Catnip pets."""
import ast
import asyncio
import random
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PET_FILE = ROOT / "cinnamon_modules" / "collectible_pets_crime.py"


def pet_runtime(save_result=True, random_stub=None):
    source = PET_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted_functions = {
        "_collectible_pet_active",
        "_collectible_pet_user",
        "_collectible_admin_pet_hourly_reward",
        "_collectible_admin_pet_claim",
    }
    wanted_assignments = {"_COLLECTIBLE_PETS_KEY", "_COLLECTIBLE_ADMIN_PETS"}
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted_functions:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in wanted_assignments
            for target in node.targets
        ):
            nodes.append(node)

    balances = {(1, 7): 250}
    state = {
        "pets": [{
            "id": "admin-puffy", "species": "Puffy", "admin_pet_key": "puffy",
            "granted_at": 1000, "income_last_claim": 1000,
        }],
        "active_id": "admin-puffy",
    }
    advanced = {"collectible_pets_v1": {"1": {"7": state}}}

    async def save():
        return save_result

    rng = random_stub or random
    namespace = {
        "asyncio": asyncio,
        "_cp_random": rng,
        "_cp_time": time,
        "_CINNAMON_SHOP_LOCKS": {},
        "advanced_features_data": advanced,
        "economy_balances": balances,
        "economy_balance": lambda gid, uid: balances.get((int(gid), int(uid)), 0),
        "bd_save_data": save,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(PET_FILE), "exec"), namespace)
    return namespace, balances, state


class AdminPetIncomeTests(unittest.IsolatedAsyncioTestCase):
    def test_each_admin_pet_has_one_hourly_reward_method_within_range(self):
        class RecordingRandom:
            def __init__(self):
                self.calls = []

            def randint(self, low, high):
                self.calls.append(("randint", low, high))
                return low

            def choice(self, values):
                self.calls.append(("choice", tuple(values)))
                return values[0]

        rng = RecordingRandom()
        ns, _, _ = pet_runtime(random_stub=rng)
        reward = ns["_collectible_admin_pet_hourly_reward"]
        keys = ("puffy", "shadow_bunny", "chicken_jockey", "monkey", "little_star")
        for key in keys:
            amount = reward(key)
            self.assertGreaterEqual(amount, 1000)
            self.assertLessEqual(amount, 5000)
        self.assertEqual([call[0] for call in rng.calls], [
            "randint", "choice", "choice", "randint", "randint"
        ])

    async def test_claim_pays_only_full_hours_and_preserves_partial_time(self):
        class FixedRandom:
            @staticmethod
            def randint(low, high):
                return 2000

            @staticmethod
            def choice(values):
                return 2000

        ns, balances, state = pet_runtime(random_stub=FixedRandom())
        status, result = await ns["_collectible_admin_pet_claim"](1, 7, now=8200)
        self.assertEqual(status, "paid")
        self.assertEqual(result["hours"], 2)
        self.assertEqual(result["amount"], 4000)
        self.assertEqual(balances[(1, 7)], 4250)
        self.assertEqual(state["pets"][0]["income_last_claim"], 8200)

    async def test_claim_is_not_available_before_one_full_hour(self):
        ns, balances, state = pet_runtime()
        status, result = await ns["_collectible_admin_pet_claim"](1, 7, now=4599)
        self.assertEqual(status, "not_ready")
        self.assertEqual(result["seconds"], 1)
        self.assertEqual(balances[(1, 7)], 250)
        self.assertEqual(state["pets"][0]["income_last_claim"], 1000)

    async def test_failed_save_rolls_back_catnip_and_claim_timestamp(self):
        ns, balances, state = pet_runtime(save_result=False)
        status, _ = await ns["_collectible_admin_pet_claim"](1, 7, now=4600)
        self.assertEqual(status, "save_failed")
        self.assertEqual(balances[(1, 7)], 250)
        self.assertEqual(state["pets"][0]["income_last_claim"], 1000)

    async def test_only_equipped_admin_pet_can_generate_income(self):
        ns, balances, state = pet_runtime()
        state["pets"].append({
            "id": "ordinary-cat", "species": "Tabby Cat", "level": 1,
        })
        state["active_id"] = "ordinary-cat"
        status, _ = await ns["_collectible_admin_pet_claim"](1, 7, now=9000)
        self.assertEqual(status, "no_admin_pet")
        self.assertEqual(balances[(1, 7)], 250)

    def test_admin_pets_are_granted_by_admin_command_not_random_work_drops(self):
        source = PET_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        catalog = next(
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_COLLECTIBLE_PET_CATALOG" for t in node.targets)
        )
        normal_species = {entry.value for entry in catalog.elts
                          if isinstance(entry, ast.Dict)
                          for key, entry_value in zip(entry.keys, entry.values)
                          if isinstance(key, ast.Constant) and key.value == "species"
                          and isinstance(entry_value, ast.Constant)}
        for name in ("Puffy", "Shadow Bunny", "Chicken Jockey", "Monkey", "Little Star"):
            self.assertNotIn(name, normal_species)
        self.assertIn('@prefix_pets.command(name="grant"', source)
        self.assertIn('@commands.has_permissions(administrator=True)', source)
        self.assertIn('@prefix_pets.command(name="claim"', source)
        self.assertIn('"admin_hourly_income"', source)


if __name__ == "__main__":
    unittest.main()
