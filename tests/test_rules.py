##
# @file test_rules.py
# @brief One test per rule, both directions, on hand-built character dicts.
#
# Hand-built rather than sampled from a save on purpose: a rule has to be exercised on
# the state it is looking for, and no legitimate save on this machine holds any of them.
# The corpus goes the other way — see test_corpus.py, which asserts that nothing fires
# on 264 real files.
#
#   python3 -m unittest discover -s tests
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validators import (  # noqa: E402
    IMPOSSIBLE,
    INCONSISTENT,
    file_rules,  # noqa: E402
    run_validation,
)
from validators.data import game_data  # noqa: E402
from validators.rules import common, ds2  # noqa: E402


## @brief A DS3 Knight exactly as the game creates one: SL 9, the class's own stats.
def ds3_knight(**over):
    gd = game_data("ds3")
    row = gd["classes"]["Knight"]
    ch = {
        "game": "ds3",
        "tier": "full",
        "name": "T",
        "level": row["level"],
        "stats": dict(row["stats"]),
        "souls": 0,
    }
    ch.update(over)
    return ch, gd


class LevelVsStats(unittest.TestCase):
    def test_a_legitimate_character_passes(self):
        ch, gd = ds3_knight()
        self.assertEqual(common.level_vs_stats(ch, gd), [])

    def test_level_edited_down_fires(self):
        ch, gd = ds3_knight(level=1)
        (f,) = common.level_vs_stats(ch, gd)
        self.assertEqual(f.tier, INCONSISTENT)
        self.assertIn("level 9", f.expected)
        self.assertEqual(f.found, "level 1")

    def test_stats_edited_up_without_level_fires(self):
        ch, gd = ds3_knight()
        ch["stats"]["Vigor"] = 99
        (f,) = common.level_vs_stats(ch, gd)
        self.assertEqual(f.tier, INCONSISTENT)

    def test_no_stats_is_not_a_finding(self):
        # Sekiro reaches here with an empty stat dict; "nothing to check" is None.
        self.assertIsNone(common.level_vs_stats({"stats": {}, "level": None}, None))


class StatBounds(unittest.TestCase):
    def test_above_cap_fires_once_per_stat(self):
        ch, gd = ds3_knight()
        ch["stats"]["Vigor"] = 255
        ch["stats"]["Luck"] = 100
        out = common.stat_above_cap(ch, gd)
        self.assertEqual([f.found for f in out], ["luck 100", "vigor 255"])
        self.assertTrue(all(f.tier == IMPOSSIBLE for f in out))

    def test_at_the_cap_is_legitimate(self):
        ch, gd = ds3_knight()
        ch["stats"] = {k: 99 for k in ch["stats"]}
        self.assertEqual(common.stat_above_cap(ch, gd), [])

    def test_below_the_class_base_fires(self):
        # DS1 is the case where the class is known, so the floor is that class's own
        # base rather than the minimum across all ten. A Warrior starts Vitality 11.
        gd = game_data("dsr")
        row = gd["classes"]["Warrior"]
        ch = {"klass": "Warrior", "level": row["level"], "stats": dict(row["stats"])}
        self.assertEqual(common.stat_below_floor(ch, gd), [])
        ch["stats"]["Vitality"] = 10
        (f,) = common.stat_below_floor(ch, gd)
        self.assertEqual(f.tier, IMPOSSIBLE)
        self.assertIn("11", f.expected)
        self.assertIn("Warrior", f.expected)
        self.assertTrue(f.note)

    def test_a_known_class_floor_is_tighter_than_the_shared_one(self):
        # Vitality 10 is under a Warrior's 11 but over Thief's 9, so it is a finding
        # only because the save says which class it is.
        gd = game_data("dsr")
        ch = {"klass": None, "level": 4, "stats": {"Vitality": 10}}
        self.assertEqual(common.stat_below_floor(ch, gd), [])

    def test_unknown_class_uses_the_lowest_start_across_classes(self):
        # Sorcerer's 7 is the lowest Vitality any DS3 class starts with, so 7 passes
        # where the class is unknown and 6 does not.
        ch, gd = ds3_knight(klass=None)
        ch["stats"]["Vitality"] = 7
        self.assertEqual(common.stat_below_floor(ch, gd), [])
        ch["stats"]["Vitality"] = 6
        self.assertEqual(len(common.stat_below_floor(ch, gd)), 1)

    def test_ds2_has_no_floor_to_check(self):
        gd = game_data("ds2sotfs")
        ch = {"stats": {"Vigor": 1}, "level": 1}
        self.assertIsNone(common.stat_below_floor(ch, gd))


class Currency(unittest.TestCase):
    def test_at_the_cap_passes_and_past_it_fires(self):
        ch, gd = ds3_knight(souls=999999999)
        self.assertEqual(common.souls_above_cap(ch, gd), [])
        ch["souls"] += 1
        (f,) = common.souls_above_cap(ch, gd)
        self.assertEqual(f.tier, IMPOSSIBLE)

    def test_ds2_souls_cannot_exceed_soul_memory(self):
        gd = game_data("ds2sotfs")
        self.assertEqual(
            ds2.souls_vs_soul_memory({"souls": 100, "soul_memory": 100}, gd), []
        )
        (f,) = ds2.souls_vs_soul_memory({"souls": 101, "soul_memory": 100}, gd)
        self.assertEqual(f.tier, INCONSISTENT)

    def test_no_soul_memory_is_not_a_finding(self):
        self.assertIsNone(
            ds2.souls_vs_soul_memory({"souls": 5, "soul_memory": 0}, None)
        )


class FileRules(unittest.TestCase):
    # The container rules take the reader in rather than importing it, so the tests do
    # too: a fake entry list and a fake checksum function is the whole fixture.
    class Entry:
        offset = 0
        size = 16

    def test_a_clean_container_reports_nothing(self):
        entries = [self.Entry(), self.Entry()]
        r = file_rules.run_file_validation("ds3", entries, b"", lambda d, e: True)
        self.assertEqual(r.findings, [])
        self.assertEqual(r.rules_run, 1)

    def test_a_mismatched_entry_is_named(self):
        entries = [self.Entry(), self.Entry(), self.Entry()]
        r = file_rules.run_file_validation(
            "ds3", entries, b"", lambda d, e: e is not entries[1]
        )
        (f,) = r.findings
        self.assertEqual(f.tier, INCONSISTENT)
        self.assertIn("index 1", f.found)
        self.assertIn("proved nothing", f.note)

    def test_nightreign_is_excluded_and_says_why(self):
        r = file_rules.run_file_validation(
            "nr", [self.Entry()], b"", lambda d, e: False
        )
        self.assertEqual(r.findings, [])
        self.assertEqual(r.rules_run, 0)
        self.assertIn("IV in front", r.unimplemented[0])

    def test_no_entries_is_not_a_finding(self):
        r = file_rules.run_file_validation("ds3", [], b"", lambda d, e: False)
        self.assertEqual(r.findings, [])
        self.assertEqual(r.rules_run, 0)


class Reports(unittest.TestCase):
    def test_findings_are_ordered_worst_first(self):
        ch, _ = ds3_knight(level=1)
        ch["stats"]["Vigor"] = 255
        tiers = [f.tier for f in run_validation(ch, "ds3").findings]
        self.assertEqual(tiers, [IMPOSSIBLE, INCONSISTENT])

    def test_a_game_with_no_rules_says_so(self):
        r = run_validation({"name": "x"}, "nr")
        self.assertTrue(r.no_rules)
        self.assertEqual(r.rules_run, 0)
        self.assertTrue(r.unimplemented)

    def test_sekiro_runs_nothing_rather_than_clearing_the_save(self):
        r = run_validation({"stats": {}, "level": None}, "sdt")
        self.assertTrue(r.no_rules)
        self.assertEqual(r.findings, [])

    def test_every_game_key_has_a_module(self):
        from sl2_to_md import GAMES
        from validators.rules import MODULES

        self.assertEqual(set(GAMES), set(MODULES))


if __name__ == "__main__":
    unittest.main()
