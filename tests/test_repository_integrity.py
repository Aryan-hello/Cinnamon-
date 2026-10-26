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
        for active in ("wildlands_art.py", "wildlands_fishing.py", "wildlands_story.py"):
            self.assertIn(active, loaded)
        self.assertLess(loaded.index("wildlands_fishing.py"), loaded.index("wildlands_story.py"))

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
        self.assertIn("bot.tree.clear_commands(guild=guild)", text)
        self.assertIn("bot.tree.sync(guild=guild)", text)

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


if __name__ == "__main__":
    unittest.main()
