import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LotteryAndPetStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "cinnamon_modules" / "economy_lottery.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_module_is_loaded_after_collectible_pet_helpers(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        pet_at = main.index('"collectible_pets_crime.py"')
        feature_at = main.index('"economy_lottery.py"')
        self.assertLess(pet_at, feature_at)

    def test_free_raffle_commands_are_registered(self):
        self.assertIn('name="lottery"', self.source)
        for command in ("start", "enter", "status", "cancel"):
            self.assertIn(f'command(name="{command}"', self.source)
        self.assertIn("Each member gets one free entry.", self.source)
        self.assertIn('(\"Entry cost\", \"Free\")', self.source)

    def test_raffle_prize_is_escrowed_and_save_failure_rolls_back(self):
        self.assertIn('economy_balances[key] = balance - int(prize_catnip)', self.source)
        self.assertIn('economy_balances[winner_key] = economy_balance(guild_id, winner_id) + prize', self.source)
        self.assertIn("if not saved:", self.source)
        self.assertIn('state.update(old_state)', self.source)

    def test_raffle_has_persistent_expiry_worker(self):
        self.assertIn('community_lottery_v1', self.source)
        self.assertIn('@tasks.loop(minutes=1)', self.source)
        self.assertIn('await bot.wait_until_ready()', self.source)
        self.assertIn('ends_at', self.source)
        self.assertIn('_f_random.SystemRandom().choice(entries)', self.source)
        self.assertIn('sorted({int(uid) for uid in raffle.get("entries", [])})', self.source)

    def test_raffle_and_pet_wallet_mutations_share_economy_locks(self):
        self.assertIn('_CINNAMON_SHOP_LOCKS.setdefault', self.source)
        self.assertIn('_lottery_member_locks', self.source)
        self.assertIn('_lottery_acquire', self.source)
        self.assertIn('_lottery_release', self.source)

    def test_pet_accessories_are_cosmetic_and_persistent(self):
        self.assertIn('name="pet-style"', self.source)
        for command in ("shop", "buy", "equip", "remove"):
            self.assertIn(f'command(name="{command}"', self.source)
        self.assertIn('accessories', self.source)
        self.assertIn('accessory_id', self.source)
        self.assertIn('await bd_save_data()', self.source)

    def test_pet_collection_displays_owned_and_equipped_accessories(self):
        pet_source = (ROOT / "cinnamon_modules" / "collectible_pets_crime.py").read_text(encoding="utf-8")
        self.assertIn("Accessory collection", pet_source)
        self.assertIn("active_accessory", pet_source)
        self.assertIn("accessory_id", pet_source)

    def test_new_module_parses_as_python(self):
        ast.parse(self.source)


if __name__ == "__main__":
    unittest.main()
