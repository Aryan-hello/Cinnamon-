import unittest
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
        self.assertIsNone(_ccr_command("how much Catnip do I have"))

if __name__ == "__main__":
    unittest.main()
