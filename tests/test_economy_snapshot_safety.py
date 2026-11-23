"""Safety checks for the single Catnip wallet and economy snapshot recovery."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
ECONOMY = ROOT / "cinnamon_modules" / "economy.py"


class EconomySnapshotSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.economy = ECONOMY.read_text(encoding="utf-8")

    def test_runtime_has_one_authoritative_catnip_mapping(self):
        declarations = re.findall(r"^\s*economy_balances\s*=\s*\{\}", self.main, re.MULTILINE)
        self.assertEqual(len(declarations), 1)
        self.assertIn("def economy_balance(guild_id: int, user_id: int)", self.economy)
        self.assertIn("value = economy_balances.get(key)", self.economy)
        self.assertIn("economy_key(interaction.guild.id, target.id)", self.economy)

    def test_diagnosis_is_read_only_and_exposes_raw_loaded_wallet(self):
        self.assertIn('name="diagnose"', self.economy)
        self.assertIn("Read-only diagnostics", self.economy)
        self.assertIn("Raw loaded value", self.economy)
        self.assertIn("Balance map entry", self.economy)

    def test_economy_snapshots_include_catnip_and_inventory(self):
        start = self.economy.index("async def economy_snapshot_payload")
        end = self.economy.index('@economy_group.command(name="snapshot"', start)
        block = self.economy[start:end]
        self.assertIn('"balance": economy_balance', block)
        self.assertIn('"inventory": dict(economy_inventory_for', block)

    def test_recall_is_merge_only_by_default_and_can_select_a_log_channel(self):
        self.assertIn('name="recall"', self.economy)
        self.assertIn("source_channel: discord.TextChannel | None = None", self.economy)
        self.assertIn("merge_only: bool = True", self.economy)
        self.assertIn("merge_only=True, source_channel=channel", self.economy)
        self.assertIn("existing wallets and inventory are never replaced", self.economy)

    def test_failed_snapshot_save_rolls_back_every_economy_map(self):
        for key in ("economy_balances", "economy_inventory",
                    "economy_level_rewards_claimed", "economy_achievements",
                    "ECONOMY_ITEMS", "ECONOMY_QUESTS"):
            self.assertIn(key, self.economy)
        self.assertIn("All in-memory changes were rolled back", self.economy)


if __name__ == "__main__":
    unittest.main()
