"""Static integration guards for Cinnamon's community tools module."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cinnamon_modules" / "community_tools.py"
MAIN = ROOT / "main.py"


def test_community_tools_module_is_valid_python():
    ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def test_community_tools_are_loaded_after_shared_storage_and_ticket_foundation():
    source = MAIN.read_text(encoding="utf-8")
    assert '"ticket_system.py"' in source
    assert '"community_tools.py"' in source
    assert source.index('"ticket_system.py"') < source.index('"community_tools.py"')


def test_community_commands_are_registered_once_and_named():
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
    assert {"suggest", "suggestion-settings", "starboard-settings"} <= set(names)
    assert len(names) == len(set(names))


def test_community_state_is_namespaced_and_does_not_touch_adventure_save_keys():
    source = MODULE.read_text(encoding="utf-8")
    assert '"cinnamon_community_tools_v1"' in source
    assert "wildlands_" not in source
    assert "bd_save_data()" in source
