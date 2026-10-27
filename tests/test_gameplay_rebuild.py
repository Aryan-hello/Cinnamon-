"""Offline behavior tests for meaningful Wildlands choices, fishing, and feeds."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "cinnamon_modules"


def pick(path, definitions, assignments=(), extra=None):
    tree = ast.parse((MODULES / path).read_text(encoding="utf-8"))
    nodes = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in definitions:
            nodes.append(item)
        if isinstance(item, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id in assignments for t in item.targets):
                nodes.append(item)
    ns = extra if extra is not None else {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), ns)
    return ns


class ChoiceBehavior(unittest.TestCase):
    def game(self):
        return pick('wildlands_story.py',
                    {'_wls_scene', '_wls_apply_choice', '_wls_echo'},
                    {'_WLS_SCENES', '_WLS_BRANCHES', '_WLS_ENTRY', '_WLS_NEXT', '_WLS_EFFECTS'})

    def test_fifty_percent_is_two_scenes_and_changes_the_ending(self):
        ns = self.game()
        choose = ns['_wls_apply_choice']
        rec = {'index': 0, 'branch': None, 'clues': [], 'history': [],
               'flags': {}, 'relationship': {}, 'treasure_deal': 'none'}
        self.assertTrue(choose(rec, 0, 2))
        self.assertEqual(rec['index'], 1)
        self.assertEqual(rec['branch'], 'half_talk')
        self.assertTrue(choose(rec, 1, 0, rec['branch']))
        self.assertEqual(rec['branch'], 'half_contract')
        self.assertEqual(rec['treasure_deal'], 'half')
        self.assertTrue(choose(rec, 1, 1, rec['branch']))
        self.assertIsNone(rec['branch'])
        self.assertIn('business partner', ns['_wls_echo'](rec, 1).lower())
        self.assertIn('half a chew toy', ns['_wls_echo'](rec, 25).lower())
        self.assertGreater(len(rec['history']), 2)

    def test_paths_rejoin_and_remember_relationships(self):
        ns = self.game()
        for option, route in enumerate(('employment', 'contract_review', 'half_talk')):
            rec = {'index': 0, 'branch': None}
            ns['_wls_apply_choice'](rec, 0, option)
            self.assertEqual(rec['branch'], route)
            seen = set()
            while rec['branch']:
                self.assertNotIn(rec['branch'], seen, 'a narrative detour must not loop forever')
                seen.add(rec['branch'])
                ns['_wls_apply_choice'](rec, rec['index'], 0, rec['branch'])
            self.assertEqual(rec['index'], 1)
        rec = {'index': 18, 'branch': None}
        ns['_wls_apply_choice'](rec, 18, 0)
        ns['_wls_apply_choice'](rec, 19, 2, rec['branch'])
        self.assertGreaterEqual(rec['relationship']['beans_friendship'], 2)
        self.assertIn('Beans', ns['_wls_echo'](rec, 19))

    def test_wrong_puzzle_does_not_grant_flag(self):
        ns = self.game()
        rec = {'index': 8, 'branch': None}
        self.assertFalse(ns['_wls_apply_choice'](rec, 8, 1))
        self.assertEqual(rec['index'], 8)
        self.assertNotIn('history', rec)


class FishingBehavior(unittest.TestCase):
    def test_skill_turns_are_not_cosmetic(self):
        ns = pick('wildlands_fishing_game.py', {'_fg_move'})
        step = ns['_fg_move']
        self.assertLess(step(48, 0, 0, 'give')[0], step(48, 0, 0, 'reel')[0])
        self.assertGreater(step(48, 0, 1, 'reel')[1], step(48, 0, 1, 'give')[1])
        self.assertGreater(step(48, 0, 2, 'steady')[1], step(48, 0, 2, 'reel')[1])

    def test_discord_state_machine_and_module_order(self):
        text = (MODULES / 'wildlands_fishing_game.py').read_text()
        self.assertIn('_wlf_random.randint(10, 20)', text)
        self.assertIn("state['phase'] = self.phase = 'bite'", text)
        self.assertIn("state['phase'] = self.phase = 'fight'", text)
        self.assertIn("p['bait'][self.bait] -= 1", text)
        self.assertIn("@_wlf_group.command(name='cast'", text)
        main = (ROOT / 'main.py').read_text()
        self.assertLess(main.index('"wildlands_fishing.py"'), main.index('"wildlands_fishing_game.py"'))
        self.assertLess(main.index('"wildlands_fishing_game.py"'), main.index('"wildlands_story.py"'))


class FeedingBehavior(unittest.TestCase):
    def test_seven_successful_feeds_trigger_exactly_one_naughty_event(self):
        tick = [10000.0]
        async def save(): pass
        naughty = []
        async def set_naughty(guild, member): naughty.append(tick[0])
        async def log(*args): pass
        fake_time = SimpleNamespace(time=lambda: tick[0])
        ns = {'advanced_features_data': {}, 'time': fake_time,
              '_CM_FOOD_WINDOW': 600, '_CM_ACTION_COOLDOWN': 90,
              '_cm_set_naughty': set_naughty, 'bd_save_data': save,
              '_cp_log': log, '_cp_good_event': log,
              '_cm_naughty': lambda *a: False}
        pick('cinnamon_moods.py',
             {'_cm_root', '_cm_state', '_cm_member', '_cm_tier', '_cm_adjust', '_cm_action'},
             extra=ns)
        guild = SimpleNamespace(id=123)
        member = SimpleNamespace(id=456)
        async def run():
            results = []
            for n in range(7):
                results.append(await ns['_cm_action'](guild, member, 'feed'))
                tick[0] += 45  # Faster than the old shared 90-second cooldown.
            self.assertEqual(len(naughty), 1)
            self.assertEqual(ns['_cm_member'](123, 456)['food_count'], 7)
            self.assertIn('7/5', results[-1])
            self.assertEqual(ns['_cm_tier'](123), 'grumpy')
            tick[0] += 601
            result = await ns['_cm_action'](guild, member, 'feed', 5)
            self.assertIn('THAT IS', result)
            self.assertEqual(len(naughty), 2)
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
