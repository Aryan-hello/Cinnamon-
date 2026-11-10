"""Regression tests for expanded, safe feature explanations."""
import unittest
from types import SimpleNamespace
from cinnamon_modules.brain_help import answer_help, build_command_catalog, feature_knowledge

def cmd(name, parent=None, description="Live command description"):
    return SimpleNamespace(name=name, parent=parent, description=description, parameters=(), callback=lambda: None)

class ExpandedFeatureHelpTests(unittest.TestCase):
    def setUp(self):
        economy=SimpleNamespace(name="economy", parent=None, commands=[])
        self.catalog=build_command_catalog([cmd("balance",economy), cmd("daily",economy), cmd("work",economy), cmd("shop",economy), cmd("mute"), cmd("unmute"), cmd("role"), cmd("reactionrole"), cmd("profile"), cmd("rank"), cmd("leaderboard"), cmd("dashboard"), cmd("giveaway"), cmd("hangry"), cmd("cinnamon-mind"), cmd("wildlands")])

    def test_feature_overview_is_live_registry_backed(self):
        answer=answer_help("what features can you do?",self.catalog)
        self.assertIn("feature atlas",answer)
        self.assertIn("/economy balance",answer)
        self.assertIn("registered right now",answer)

    def test_moderation_explains_permissions_without_action(self):
        answer=answer_help("how does moderation work?",self.catalog)
        self.assertIn("Discord permissions",answer)
        self.assertIn("/mute",answer)
        self.assertNotIn("punished",answer)

    def test_roles_and_leveling_have_guidance(self):
        self.assertIn("role hierarchy",answer_help("explain reaction roles",self.catalog))
        self.assertIn("data-driven",answer_help("how does leveling work?",self.catalog))

    def test_dashboard_and_giveaways(self):
        self.assertIn("Administrators",answer_help("what is the dashboard?",self.catalog))
        self.assertIn("staff-controlled",answer_help("how do giveaways work?",self.catalog))

    def test_feature_knowledge_includes_slash_and_prefix_registry(self):
        reference=feature_knowledge(self.catalog, [SimpleNamespace(path='?quest daily'), SimpleNamespace(path='?automod spam')])
        self.assertIn('/economy balance',reference)
        self.assertIn('?quest daily',reference)
        self.assertIn('?automod spam',reference)
        self.assertIn('never reveal another member',reference)
        self.assertIn('AI never punishes',reference)

    def test_games_and_wildlands_do_not_claim_unreleased_content(self):
        self.assertIn("optional",answer_help("how do games work?",self.catalog))
        self.assertIn("not necessarily live",answer_help("explain Wildlands",self.catalog))

if __name__ == "__main__": unittest.main()
