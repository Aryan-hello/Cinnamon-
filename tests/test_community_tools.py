"""Static integration guards for Cinnamon community features."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cinnamon_modules" / "community_tools.py"
MAIN = ROOT / "main.py"


class CommunityToolsTests(unittest.TestCase):
    def test_module_is_valid_python(self):
        ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))

    def test_module_is_loaded_after_ticket_foundation(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn('"ticket_system.py"', source)
        self.assertIn('"community_tools.py"', source)
        self.assertLess(source.index('"ticket_system.py"'), source.index('"community_tools.py"'))

    def test_commands_are_registered_once(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if (isinstance(func, ast.Attribute) and func.attr == "command"
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "tree"):
                    for keyword in decorator.keywords:
                        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                            names.append(keyword.value.value)
        self.assertTrue({"suggest", "suggestion-settings", "starboard-settings"} <= set(names))
        self.assertEqual(len(names), len(set(names)))

    def test_state_is_namespaced_and_persistent_without_adventure_keys(self):
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn('"cinnamon_community_tools_v1"', source)
        self.assertNotIn("wildlands_", source)
        self.assertIn("bd_save_data()", source)


if __name__ == "__main__":
    unittest.main()
