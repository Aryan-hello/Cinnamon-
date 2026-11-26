import ast
import asyncio
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_transfer_helper(initial=None, save_result=True):
    source = (ROOT / "cinnamon_modules" / "economy.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "economy_transfer_catnip"
    )
    balances = dict(initial or {})

    async def save():
        return save_result

    namespace = {
        "asyncio": asyncio,
        "_CINNAMON_SHOP_LOCKS": {},
        "economy_balances": balances,
        "economy_balance": lambda guild_id, user_id: balances.get(
            (int(guild_id), int(user_id)), 1000
        ),
        "bd_save_data": save,
    }
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "economy.py", "exec"), namespace)
    return namespace["economy_transfer_catnip"], balances


class EconomyTransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_transfers_cannot_spend_the_same_balance_twice(self):
        transfer, balances = load_transfer_helper({(1, 10): 1000})
        results = await asyncio.gather(
            transfer(1, 10, 20, 800),
            transfer(1, 10, 30, 800),
        )

        self.assertEqual(sum(1 for result in results if result[0]), 1)
        self.assertEqual(balances[(1, 10)], 200)
        self.assertEqual(balances.get((1, 20), 1000) + balances.get((1, 30), 1000), 2800)

    async def test_unconfirmed_save_rolls_back_both_wallets(self):
        transfer, balances = load_transfer_helper(
            {(1, 10): 1500, (1, 20): 2500}, save_result=False
        )

        result = await transfer(1, 10, 20, 700)

        self.assertFalse(result[0])
        self.assertEqual(result[3], "save_failed")
        self.assertEqual(balances, {(1, 10): 1500, (1, 20): 2500})

    async def test_failed_first_transfer_does_not_create_phantom_wallets(self):
        transfer, balances = load_transfer_helper(save_result=False)

        result = await transfer(1, 10, 20, 400)

        self.assertFalse(result[0])
        self.assertEqual(result[3], "save_failed")
        self.assertEqual(balances, {})


if __name__ == "__main__":
    unittest.main()
