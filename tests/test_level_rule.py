##
# @file test_level_rule.py
# @brief The level identity, per game and per starting class.
#
# For each class: build the character the game creates at level 1 of its own existence
# — the class's base stats at its starting level — and assert it passes. Then move the
# level and assert it fires.
#
# HOW FAR THE LEVEL HAS TO MOVE IS NOT THE SAME IN EVERY GAME, and that is the finding
# this file exists to pin. Where K is a single value (DS3 89, ER 79, DS2 53) a level off
# by one is already impossible, so +-1 fires. Dark Souls has a genuine SET — Sorcerer 79,
# Knight and Thief 81, Warrior and four others 82, Wanderer and Pyromancer 83 — so a
# Warrior at level 5 sits exactly on the Knight constant and CANNOT be called a
# contradiction. The rule tests membership, so the test does too: the smallest step that
# leaves the whole set is what must fire.
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validators.data import game_data  # noqa: E402
from validators.rules.common import level_vs_stats  # noqa: E402

## @brief One game key per class table. Both DS1 releases and both DS2 releases share
#  a table, so one of each is enough.
GAMES = ("dsr", "ds3", "er")


class LevelIdentityPerClass(unittest.TestCase):
    def test_every_starting_class_is_consistent_with_its_own_level(self):
        for game in GAMES:
            gd = game_data(game)
            for name, row in gd["classes"].items():
                ch = {"klass": name, "level": row["level"], "stats": dict(row["stats"])}
                with self.subTest(game=game, klass=name):
                    self.assertEqual(level_vs_stats(ch, gd), [])

    def test_a_level_outside_the_games_constants_fires(self):
        for game in GAMES:
            gd = game_data(game)
            ks = set(gd["k_values"])
            for name, row in gd["classes"].items():
                total = sum(row["stats"].values())
                for delta in (-1, 1):
                    level = row["level"] + delta
                    if total - level in ks:
                        # A neighbouring class's constant. Legitimate by construction —
                        # this is the DS1 case, and the rule is right not to fire.
                        continue
                    ch = {"klass": name, "level": level, "stats": dict(row["stats"])}
                    with self.subTest(game=game, klass=name, delta=delta):
                        (f,) = level_vs_stats(ch, gd)
                        self.assertEqual(f.found, f"level {level}")

    def test_single_valued_games_fire_on_a_one_level_difference(self):
        # DS3, ER and DS2 all have exactly one constant, so this is the strong form of
        # the check and it must hold for every class in them.
        for game in ("ds3", "er"):
            gd = game_data(game)
            self.assertEqual(len(gd["k_values"]), 1, game)
            for name, row in gd["classes"].items():
                for delta in (-1, 1):
                    ch = {
                        "klass": name,
                        "level": row["level"] + delta,
                        "stats": dict(row["stats"]),
                    }
                    with self.subTest(game=game, klass=name, delta=delta):
                        self.assertEqual(len(level_vs_stats(ch, gd)), 1)

    def test_dark_souls_really_does_need_the_set(self):
        # The one game where +-1 is NOT enough: a Warrior (K 82) at level 5 lands on the
        # Knight/Thief constant. Documented here so a future "simplification" to a single
        # expected level has to delete a passing test to happen.
        gd = game_data("dsr")
        row = gd["classes"]["Warrior"]
        ch = {
            "klass": "Warrior",
            "level": row["level"] + 1,
            "stats": dict(row["stats"]),
        }
        self.assertEqual(level_vs_stats(ch, gd), [])
        self.assertEqual(sorted(gd["k_values"]), [79, 81, 82, 83])

    def test_ds2_runs_on_a_measured_constant_with_no_class_rows(self):
        gd = game_data("ds2sotfs")
        self.assertEqual(gd["k_values"], [53])
        self.assertEqual(gd["classes"], {})
        stats = {k: 6 for k in gd["stat_order"]}  # Deprived: nine sixes at SL 1
        self.assertEqual(level_vs_stats({"level": 1, "stats": stats}, gd), [])
        (f,) = level_vs_stats({"level": 2, "stats": stats}, gd)
        self.assertEqual(f.expected, "level 1 for a stat total of 54")

    def test_each_games_constants_predict_its_published_maximum_level(self):
        # The independent check on the tables: 99 in every stat minus the smallest
        # constant is the maximum level the game is known to allow. If a class row were
        # wrong, this number would not land on the published one.
        for game, want in (("dsr", 713), ("ds3", 802), ("er", 713), ("ds2sotfs", 838)):
            gd = game_data(game)
            top = gd["stat_cap"] * len(gd["stat_order"]) - min(gd["k_values"])
            with self.subTest(game=game):
                self.assertEqual(top, want)


if __name__ == "__main__":
    unittest.main()
