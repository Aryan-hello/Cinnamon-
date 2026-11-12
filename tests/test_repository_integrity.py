"""Static safety checks for Cinnamon's shared-namespace module architecture.

These tests intentionally parse the real source with AST rather than import
main.py: importing main starts network services and loads Discord credentials.
"""
import ast
from collections import defaultdict
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "cinnamon_modules"


def runtime_modules():
    main_tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in main_tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_CINNAMON_MODULES"
                        for t in node.targets)):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("_CINNAMON_MODULES is missing from main.py")


def name_kw(node):
    for kw in node.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def attribute_path(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = attribute_path(node.value)
        return parent + "." + node.attr if parent else node.attr
    return ""


class RepositoryIntegrityTests(unittest.TestCase):
    def test_only_existing_active_modules_are_loaded(self):
        loaded = runtime_modules()
        self.assertEqual(len(loaded), len(set(loaded)), "Module loaded twice")
        for module in loaded:
            self.assertTrue((MODULE_DIR / module).is_file(), module)
        for active in ("cinnamon_adventure_art.py", "cinnamon_adventure_fishing.py", "cinnamon_adventure_story.py"):
            self.assertIn(active, loaded)
        self.assertLess(loaded.index("cinnamon_adventure_fishing.py"), loaded.index("cinnamon_adventure_story.py"))

    def test_obsolete_duplicate_games_removed(self):
        loaded = runtime_modules()
        for retired in ("wildlands.py", "fishing.py"):
            self.assertNotIn(retired, loaded)
            self.assertFalse((MODULE_DIR / retired).exists(),
                             "Legacy module should not remain alongside its replacement")

    def test_no_copying_global_commands_into_every_guild(self):
        text = (MODULE_DIR / "core_events.py").read_text(encoding="utf-8")
        self.assertNotIn("bot.tree.copy_global_to(", text,
                         "Duplicated guild/global registrations risk showing commands twice")
        self.assertIn("bot.tree.sync()", text)
        self.assertNotIn("bot.tree.clear_commands(guild=guild)", text)
        self.assertNotIn("bot.tree.sync(guild=guild)", text)

    def test_no_duplicate_loaded_slash_command_names(self):
        loaded = runtime_modules()
        roots = defaultdict(list)
        children = defaultdict(list)
        group_vars = {}
        trees = {}
        for file in loaded:
            tree = ast.parse((MODULE_DIR / file).read_text(encoding="utf-8"))
            trees[file] = tree
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    if attribute_path(node.value.func) == "app_commands.Group":
                        group = name_kw(node.value)
                        if group:
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    group_vars[target.id] = group

        for file, tree in trees.items():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        if not isinstance(decorator, ast.Call):
                            continue
                        fn = attribute_path(decorator.func)
                        name = name_kw(decorator) or node.name
                        if fn == "bot.tree.command":
                            roots[name].append((file, node.lineno))
                        elif fn.endswith(".command") and fn.split(".")[0] in group_vars:
                            group = group_vars[fn.split(".")[0]]
                            children[(group, name)].append((file, node.lineno))
                if isinstance(node, ast.Call) and attribute_path(node.func) == "app_commands.Command":
                    # The manual /help registration is the only expected bare
                    # command constructor passed into the command tree.
                    name = name_kw(node)
                    if name:
                        roots[name].append((file, node.lineno))
        for variable, group in group_vars.items():
            roots[group].append(("group:" + variable, 0))

        dup_roots = {name: refs for name, refs in roots.items() if len(refs) > 1}
        dup_children = {key: refs for key, refs in children.items() if len(refs) > 1}
        self.assertEqual(dup_roots, {}, f"Duplicate slash roots: {dup_roots}")
        self.assertEqual(dup_children, {}, f"Duplicate slash group commands: {dup_children}")
        self.assertIn("quest", roots)
        self.assertIn("quests", roots)
        self.assertNotIn("dailyquests", roots)
        self.assertNotIn("weeklyquests", roots)


    def test_setup_runs_recovery_and_setup_log_once(self):
        tree = ast.parse((MODULE_DIR / "server_setup.py").read_text(encoding="utf-8"))
        setup = next(node for node in tree.body
                     if isinstance(node, ast.AsyncFunctionDef) and node.name == "setup_cmd")
        recall_calls = [
            node for node in ast.walk(setup)
            if isinstance(node, ast.Call) and attribute_path(node.func) == "recall_guild_data"
        ]
        setup_logs = [
            node for node in ast.walk(setup)
            if isinstance(node, ast.Call) and attribute_path(node.func) == "send_log"
            and any(kw.arg == "title" and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "⚙️ Cinnamon setup applied"
                    for kw in node.keywords)
        ]
        self.assertEqual(len(recall_calls), 1, "/setup must run recovery exactly once")
        self.assertEqual(len(setup_logs), 1, "/setup must log completion exactly once")


    def test_recovery_scanner_initializes_seen_sets_and_result_fields(self):
        tree = ast.parse((MODULE_DIR / "server_setup.py").read_text(encoding="utf-8"))
        scanner = next(node for node in tree.body
                       if isinstance(node, ast.AsyncFunctionDef)
                       and node.name == "_scan_recovery_log_channels")
        assigned_names = {
            node.id for node in ast.walk(scanner)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
        loaded_seen_names = {
            node.id for node in ast.walk(scanner)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            and node.id.startswith("seen_")
        }
        self.assertEqual(loaded_seen_names - assigned_names, set(),
                         "Recovery scanner reads a seen_* variable before defining it")

        result_assignment = next(
            node for node in ast.walk(scanner)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "result"
                    for target in node.targets)
        )
        result_keys = {
            key.value for key in result_assignment.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        referenced_result_keys = {
            node.slice.value for node in ast.walk(scanner)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id == "result" and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        }
        self.assertLessEqual(referenced_result_keys, result_keys,
                             "Recovery scanner reads a result field it never initializes")


if __name__ == "__main__":
    unittest.main()
