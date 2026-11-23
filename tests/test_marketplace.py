"""Regression checks for marketplace, trades and auction escrow."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cinnamon_modules" / "economy_marketplace.py"
MAIN = ROOT / "main.py"


class MarketplaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MODULE.read_text(encoding="utf-8")
        cls.main = MAIN.read_text(encoding="utf-8")

    def test_marketplace_trade_and_auction_groups_are_registered(self):
        for name in ('name="market"', 'name="trade"', 'name="auction"'):
            self.assertIn(name, self.source)
        self.assertIn("bot.tree.add_command(market_group)", self.source)
        self.assertIn("bot.tree.add_command(trade_group)", self.source)
        self.assertIn("bot.tree.add_command(auction_group)", self.source)

    def test_marketplace_escrows_items_and_rolls_back_failed_writes(self):
        self.assertIn('"status": "active"', self.source)
        self.assertIn("inv[item_id] = owned - quantity", self.source)
        self.assertIn("The listing couldn't be saved. Your item was returned.", self.source)
        self.assertIn("record[\"status\"] = \"sold\"", self.source)
        self.assertIn("_market_persist_or_rollback", self.source)

    def test_trade_offer_escrows_and_transfers_both_sides(self):
        self.assertIn('"status": "pending"', self.source)
        self.assertIn("expires_at", self.source)
        self.assertIn("trade_accept", self.source)
        self.assertIn("trade_decline", self.source)
        self.assertIn("trade_cancel", self.source)
        self.assertIn("economy_balances[(gid, recipient_id)]", self.source)

    def test_auction_bids_are_reserved_and_expiry_is_settled(self):
        self.assertIn("_auction_expiry_loop", self.source)
        self.assertIn("economy_balances[(gid, bidder_id)] = balance - amount", self.source)
        self.assertIn("_auction_finalize_locked", self.source)
        self.assertIn("highest_bidder_id", self.source)

    def test_collection_and_wishlist_use_existing_inventory(self):
        self.assertIn('name="collection"', self.source)
        self.assertIn('name="wishlist"', self.source)
        self.assertIn("economy_inventory_for", self.source)
        self.assertIn("bd_save_data()", self.source)

    def test_module_is_loaded_without_adventure_dependencies(self):
        self.assertIn('"economy_marketplace.py"', self.main)
        self.assertNotIn("wildlands_", self.source)


if __name__ == "__main__":
    unittest.main()
