"""Dependency-free consistency checks; live discord.py/Render needs staging tests."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import time
import unittest

BASE=Path(__file__).resolve().parents[1]
STORY=BASE/'cinnamon_modules'/'cinnamon_adventure_story.py'
FISHING=BASE/'cinnamon_modules'/'cinnamon_adventure_fishing.py'
MAIN=BASE/'main.py'


def namespace_with_functions(path,names,namespace):
    root=ast.parse(path.read_text())
    body=[n for n in root.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)
    return namespace


class StoryTests(unittest.TestCase):
    def test_all_scenes_have_three_choices_and_solvable_puzzles(self):
        root=ast.parse(STORY.read_text())
        scenes=next(n.value for n in root.body if isinstance(n,ast.Assign) and
                    any(isinstance(t,ast.Name) and t.id=='_WLS_SCENES' for t in n.targets))
        self.assertGreaterEqual(len(scenes.elts),25)
        for entry in scenes.elts:
            opts=entry.args[4]
            self.assertEqual(len(opts.elts),3)
            self.assertTrue(any(isinstance(o.elts[-1],ast.Constant) and o.elts[-1].value for o in opts.elts))
        assert '100_000' in STORY.read_text()

    def test_module_order_and_no_old_story_loaded(self):
        main=MAIN.read_text()
        self.assertLess(main.index('"cinnamon_adventure_fishing.py"'),main.index('"cinnamon_adventure_story.py"'))
        self.assertNotIn('    "wildlands.py",',main)
        self.assertIn('    "school_incident.py",',main)

    def test_merchant_window_and_finder_commission(self):
        state={}
        balances={(1,10):10_000,(1,20):10_000,(1,30):1000}
        w={'ends_at':time.time()+3600, 'finder_id':30,'channel_id':123}
        now=time.time()
        def server(g):return {'merchant_windows':{'bait':w}}
        def player(g,u):return {'bait':{'normal':10},'rods':['twig'],'rod':'twig'}
        logs=[]
        async def save():logs.append('saved')
        async def log(*a,**kw):logs.append('logged')
        ns=dict(_WLF_PURCHASE_LOCKS={},asyncio=asyncio,economy_balances=balances,
                _wlf_player=player,_wlf_server=server,_WLF_SHOP_NAMES={'bait':'fishing-bait-merchant'},
                _wlf_time=time,bd_save_data=save,economy_log=log,
                economy_balance=lambda g,u:balances[(g,u)],
                _wlf_story_complete=lambda g,u,kind=None:False,
                _wlf_channel=lambda guild,kind:SimpleNamespace(id=123),
                _cm_price=lambda g,u,item,price: price,  # Normal mood preserves historical purchase totals.
                _cp_react=lambda *a,**kw: save(),  # Side-effect stub; does not affect commission.
                log=SimpleNamespace(exception=lambda *a:None))
        namespace_with_functions(FISHING,[' _wlf_active'.strip(),'_wlf_window','_wlf_merchant_open','_wlf_purchase'],ns)
        item={'id':'glow','price':35,'name':'Glowworm Bait'}
        def inter(u,channel):return SimpleNamespace(guild=SimpleNamespace(id=1),user=SimpleNamespace(id=u),channel_id=channel,channel=SimpleNamespace(id=channel))
        async def run():
            msg=await ns['_wlf_purchase'](inter(10,123),'bait',item,10)
            self.assertIn('35',msg)
            self.assertEqual(balances[(1,30)],1035)  # 10% of 350
            await ns['_wlf_purchase'](inter(30,123),'bait',item,10)
            self.assertEqual(balances[(1,30)],1035-350)  # no self commission
            await ns['_wlf_purchase'](inter(20,456),'bait',item,10)
            self.assertEqual(balances[(1,30)],1035-350)  # elsewhere = no commission
            w['ends_at']=time.time()-5
            self.assertFalse(ns['_wlf_merchant_open'](1,'bait',20))
        asyncio.run(run())

    def test_fish_and_story_preserve_existing_data_keys(self):
        text=FISHING.read_text()
        self.assertIn("'wildlands_fishing_v1'",text)
        self.assertIn("'wildlands_story_v2'",text)
        self.assertIn('merchant_windows',text)
        self.assertIn('closed_notice',text)
        self.assertIn('story for permanent',text)


if __name__=='__main__':unittest.main()