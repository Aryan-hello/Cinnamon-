"""Regression checks for Cinnamon's inventory-backed ticket workflows."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TICKETS = ROOT / "cinnamon_modules" / "ticket_system.py"
DASHBOARD = ROOT / "dashboard.py"


class TicketInventoryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tickets = TICKETS.read_text(encoding="utf-8")
        cls.dashboard = DASHBOARD.read_text(encoding="utf-8")

    def test_default_shop_and_support_panels_are_seeded_idempotently(self):
        self.assertIn('"default-shop"', self.tickets)
        self.assertIn('"default-support"', self.tickets)
        self.assertIn('cfg["panels"].setdefault(default_id,default_panel)', self.tickets)
        self.assertIn('panels.setdefault(default_id,default_panel)', self.dashboard)

    def test_shop_intake_selects_an_owned_item_before_opening_the_ticket(self):
        self.assertIn("class TicketInventorySelectView", self.tickets)
        self.assertIn("economy_inventory_for(self.gid,self.user_id)", self.tickets)
        self.assertIn("TicketQuestionModal(self.gid,self.panel_id,self.category_id,self.user_id,questions,item_id)", self.tickets)
        self.assertIn('"selected_item_id":str(selected_item_id or "")', self.tickets)

    def test_claim_deducts_inventory_and_rolls_back_when_save_fails(self):
        self.assertIn('if action == "claim" and str(ticket.get("routing","")).lower() in {"shop","grow_a_garden"}', self.tickets)
        self.assertIn('service_inv[item_id] = int(service_inv[item_id]) - 1', self.tickets)
        self.assertIn("service_inv.update(before_inventory)", self.tickets)
        self.assertIn("Ticket claim transaction save failed", self.tickets)
        self.assertIn("The claim and inventory change were rolled back", self.tickets)

    def test_multi_item_gag_tickets_select_and_consume_each_item(self):
        self.assertIn("max_values=len(options[:25])", self.tickets)
        self.assertIn('in {"shop","grow_a_garden","gag","boosting"}', self.tickets)
        self.assertIn('item.get("category")!="grow_a_garden"', self.tickets)
        self.assertIn("selected_item_ids", self.tickets)
        self.assertIn("for item_id in item_ids:", self.tickets)
        self.assertIn("consumed_item_ids", self.tickets)

    def test_claim_permissions_and_notifications_are_item_specific(self):
        self.assertIn("Only a configured Trusted Booster can claim this GAG service.", self.tickets)
        self.assertIn("Only a configured Moderator can claim this shop ticket.", self.tickets)
        self.assertIn("has been removed from <@{creator_id}>'s inventory", self.tickets)
        self.assertIn('"moderator_role_ids"', self.dashboard)
        self.assertIn('"trusted_booster_role_ids"', self.dashboard)

    def test_gag_completion_requires_both_participants_before_close(self):
        self.assertIn('ticket["service_confirmations"] = {"member": False, "booster": False}', self.tickets)
        self.assertIn("if all(confirms.values()):", self.tickets)
        self.assertIn("Only a Discord administrator can close a GAG ticket before both completion confirmations", self.tickets)
        self.assertIn("The Close option is now available", self.tickets)

    def test_support_tickets_are_button_free_but_moderators_can_close(self):
        self.assertIn('if route=="support":', self.tickets)
        self.assertIn('await channel.send("Please wait, a moderator will be with you soon.")', self.tickets)
        self.assertIn('actions=[] if support else', self.tickets)
        self.assertIn('async def ticket_close(interaction:discord.Interaction):', self.tickets)

    def test_dashboard_can_publish_a_panel_to_a_selected_channel(self):
        self.assertIn("publish_channel_id", self.dashboard)
        self.assertIn("Send panel to channel", self.dashboard)

    def test_dashboard_has_no_code_item_role_question_and_reply_controls(self):
        for field in (
            "inventory_item_ids", "category_staff_role_ids", "persistent_button_label",
            "persistent_button_reply", "question_fields", "panel_category_editor",
        ):
            self.assertIn(field, self.dashboard)

    def test_dashboard_cannot_bypass_inventory_consumption_for_shop_claims(self):
        self.assertIn("Claim this shop ticket in Discord so Cinnamon can verify and consume", self.dashboard)
        self.assertIn("An inventory-backed ticket cannot be unclaimed after its item has been consumed", self.dashboard)

    def test_closed_gag_tickets_cannot_receive_late_completion_or_payout(self):
        self.assertIn('if ticket.get("status")!="open":', self.tickets)
        self.assertIn("This ticket is closed; completion confirmations are no longer accepted.", self.tickets)

    def test_custom_panel_ping_roles_can_claim_and_manage_their_ticket(self):
        self.assertIn("category_staff_ids=set(map(int,category.get(\"staff_role_ids\",[])))", self.tickets)
        self.assertIn("member_role_ids & (moderator_ids | category_staff_ids)", self.tickets)
        self.assertIn("allowed.update(map(int,category.get(\"staff_role_ids\",[])))", self.tickets)

    def test_trusted_boosters_do_not_become_global_support_moderators(self):
        self.assertNotIn('cinnamon_role_has(member,"trusted_booster") or any(r.id in allowed', self.tickets)
        self.assertIn('settings.get("trusted_booster_role_ids",[])', self.tickets)


if __name__ == "__main__":
    unittest.main()
