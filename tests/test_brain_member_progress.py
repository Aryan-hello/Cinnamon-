"""Read-only level progress helper tests."""
import unittest

from cinnamon_modules.brain_member_v2 import level_progress


def level_for_xp(xp):
    return min(5, xp // 100)


def threshold(level):
    return level * 100


class LevelProgressTests(unittest.TestCase):
    def test_start_and_mid_level(self):
        self.assertEqual(
            level_progress(150, level_from_xp=level_for_xp,
                           total_xp_for_level=threshold, max_level=5),
            {"level": 1, "total_xp": 150, "xp_into_level": 50,
             "xp_for_level": 100, "xp_remaining": 50, "max_level": False},
        )

    def test_exact_boundary_and_max_level(self):
        boundary = level_progress(200, level_from_xp=level_for_xp,
                                  total_xp_for_level=threshold, max_level=5)
        self.assertEqual(boundary["level"], 2)
        self.assertEqual(boundary["xp_into_level"], 0)
        maximum = level_progress(900, level_from_xp=level_for_xp,
                                 total_xp_for_level=threshold, max_level=5)
        self.assertTrue(maximum["max_level"])
        self.assertEqual(maximum["xp_remaining"], 0)

    def test_invalid_xp_and_thresholds(self):
        for xp in (-1, True, 2.5):
            with self.subTest(xp=xp), self.assertRaises(ValueError):
                level_progress(xp, level_from_xp=level_for_xp,
                               total_xp_for_level=threshold, max_level=5)


if __name__ == "__main__":
    unittest.main()
