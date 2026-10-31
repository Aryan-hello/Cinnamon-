"""Behavior checks for administrator-only Brain controls, without Flask/Discord login."""
import ast
import asyncio
import datetime
import html
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def runtime(*names, **values):
    tree = ast.parse((ROOT / 'dashboard.py').read_text(encoding='utf-8'))
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    ns = {'asyncio': asyncio, 'dt': datetime, **values}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'dashboard.py', 'exec'), ns)
    return ns


class AccessDenied(Exception):
    def __init__(self, code):
        self.code = code


def abort(code):
    raise AccessDenied(code)


class AdminOnlyDashboardTests(unittest.TestCase):
    def setUp(self):
        self.fetches = []
        self.role_admin = True
        self.guild = SimpleNamespace(id=100, owner_id=900)
        # A cached administrator is intentionally never authoritative.
        self.guild.get_member = lambda uid: SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=True, manage_guild=True))

        async def fetch_member(uid):
            self.fetches.append(('member', uid))
            return SimpleNamespace(roles=[SimpleNamespace(id=100), SimpleNamespace(id=200)])

        async def fetch_roles():
            self.fetches.append(('roles', None))
            return [SimpleNamespace(id=100, permissions=SimpleNamespace(administrator=False)),
                    SimpleNamespace(id=200, permissions=SimpleNamespace(administrator=self.role_admin))]

        self.guild.fetch_member = fetch_member
        self.guild.fetch_roles = fetch_roles
        self.bot = SimpleNamespace(get_guild=lambda gid: self.guild if gid == 100 else None,
                                   guilds=[self.guild])
        self.tokens = {'session': {'user': {'id': '700'}}}
        self.ns = runtime('_dashboard_is_admin', '_get_access', '_dashboard_context',
                          _bot=self.bot, _tokens=self.tokens, abort=abort,
                          _run_bot=asyncio.run, session={'dash_sid': 'session'})

    def access(self, permissions=8, owner=False):
        return self.ns['_get_access']('session', [{'id': '100', 'permissions': str(permissions),
                                                  'owner': owner}], '100')

    def test_manage_server_alone_is_denied_before_live_check(self):
        with self.assertRaises(AccessDenied) as exc:
            self.access(permissions=32)
        self.assertEqual(exc.exception.code, 403)
        self.assertEqual(self.fetches, [])

    def test_admin_requires_current_member_and_role_permissions(self):
        self.assertIs(self.access()[0], self.guild)
        self.assertEqual(self.fetches, [('member', 700), ('roles', None)])
        self.role_admin = False
        with self.assertRaises(AccessDenied) as exc:
            self.access()
        self.assertEqual(exc.exception.code, 403)

    def test_owner_has_access_without_role_lookup(self):
        self.tokens['session']['user']['id'] = '900'
        self.assertIs(self.access(permissions=0, owner=True)[0], self.guild)
        self.assertEqual(self.fetches, [])

    def test_unavailable_live_lookup_fails_closed(self):
        async def fetch_member(uid):
            raise RuntimeError('Discord unavailable')
        self.guild.fetch_member = fetch_member
        with self.assertRaises(AccessDenied):
            self.access()

    def test_server_selector_filters_manage_server_only(self):
        self.bot.guilds.append(SimpleNamespace(id=300))
        self.ns['_discord_get'] = lambda *args: [
            {'id': '100', 'permissions': '8'}, {'id': '300', 'permissions': '32'}]
        _, _, eligible = self.ns['_dashboard_context']()
        self.assertEqual([g['id'] for g in eligible], ['100'])


class BrainControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = runtime('_apply_brain_settings')
        self.stored = []
        self.success = True

        async def save():
            self.stored.append(1)
            return self.success

        self.state = {'advanced_features_data': {}, 'bd_save_data': save}

    async def test_success_saves_both_guild_scoped_controls(self):
        await self.ns['_apply_brain_settings'](
            self.state, 100, independence_enabled=False, chat_actions_enabled=True)
        advanced = self.state['advanced_features_data']
        self.assertFalse(advanced['cinnamon_brain_v1']['100']['independence_enabled'])
        self.assertTrue(advanced['cinnamon_actions_v2']['100']['enabled'])
        self.assertNotIn('200', advanced['cinnamon_actions_v2'])
        self.assertEqual(len(self.stored), 1)

    async def test_failed_save_keeps_off_switch_off_and_undoes_enable(self):
        self.success = False
        with self.assertRaisesRegex(ValueError, 'could not be verified'):
            await self.ns['_apply_brain_settings'](
                self.state, 100, independence_enabled=False, chat_actions_enabled=True)
        advanced = self.state['advanced_features_data']
        self.assertFalse(advanced['cinnamon_brain_v1']['100']['independence_enabled'])
        self.assertFalse(advanced['cinnamon_actions_v2']['100']['enabled'])

    async def test_cancelled_save_undoes_enable(self):
        async def save():
            raise asyncio.CancelledError()
        self.state['bd_save_data'] = save
        self.state['advanced_features_data']['cinnamon_brain_v1'] = {
            '100': {'independence_enabled': False}}
        with self.assertRaises(asyncio.CancelledError):
            await self.ns['_apply_brain_settings'](
                self.state, 100, independence_enabled=True, chat_actions_enabled=True)
        advanced = self.state['advanced_features_data']
        self.assertFalse(advanced['cinnamon_brain_v1']['100']['independence_enabled'])
        self.assertFalse(advanced['cinnamon_actions_v2']['100']['enabled'])

    async def test_failed_older_enable_cannot_reverse_a_new_pause(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def save():
            started.set()
            await release.wait()
            return False

        self.state['bd_save_data'] = save
        pending = asyncio.create_task(self.ns['_apply_brain_settings'](
            self.state, 100, independence_enabled=True, chat_actions_enabled=True))
        await started.wait()
        advanced = self.state['advanced_features_data']
        advanced['cinnamon_brain_v1']['100']['independence_enabled'] = False
        advanced['cinnamon_actions_v2']['100']['enabled'] = False
        release.set()
        with self.assertRaisesRegex(ValueError, 'could not be verified'):
            await pending
        self.assertFalse(advanced['cinnamon_brain_v1']['100']['independence_enabled'])
        self.assertFalse(advanced['cinnamon_actions_v2']['100']['enabled'])

    async def test_save_wrapper_reports_failure(self):
        ns = runtime('_save', _state=lambda: self.state, _run_bot=lambda coro: asyncio.run(coro))
        self.success = False
        # _save is called on a Flask thread, outside an existing event loop.
        with self.assertRaisesRegex(ValueError, 'could not be verified'):
            await asyncio.to_thread(ns['_save'])


class BrainPresentationTests(unittest.TestCase):
    def test_boundaries_and_storage_status_are_visible_without_private_values(self):
        ns = runtime('_mind', _esc=lambda value: html.escape(str(value), quote=True),
                     _channel_select=lambda *args, **kwargs: '<select></select>',
                     _form=lambda gid, action, content, button: '<form data-action="' + action + '">' + content + '</form>')
        guild = SimpleNamespace(id=100, get_channel=lambda cid: None, get_member=lambda uid: None)
        state = {
            'cinnamon_social': {'100': {'last_brain_reason': 'not_enough_recent_conversation'}},
            'cinnamon_brain': {'100': {'independence_enabled': False}},
            'cinnamon_trusted_actions': {'100': {'enabled': True}},
            'brain_storage': {'ready': True, 'durable': True, 'status': 'ready',
                              'private_token': 'do-not-display'},
        }
        output = ns['_mind'](guild, state)
        self.assertIn("name='independence_enabled'", output)
        self.assertIn("name='chat_actions_enabled' checked", output)
        self.assertIn('Next activity check', output)
        self.assertIn('Requires recent engagement', output)
        self.assertIn('not enough recent conversation', output)
        self.assertIn('Storage: Ready', output)
        self.assertNotIn('One game every', output)
        self.assertNotIn('Next surprise game', output)
        self.assertNotIn('do-not-display', output)


if __name__ == '__main__':
    unittest.main()
