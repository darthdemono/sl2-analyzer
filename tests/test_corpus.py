##
# @file test_corpus.py
# @brief The acceptance criterion: no legitimate save may produce an `impossible` or an
#        `inconsistent` finding.
#
# Every `.sl2` this machine holds — 264 files: 89 Dark Souls III characters, 75 Dark
# Souls II, 91 Sekiro, 182 Elden Ring, three Dark Souls — is parsed and validated. One
# hit means the RULE is wrong, not the save. Nothing here is a fixture that can be
# adjusted to make a rule pass.
#
# The corpus is not in the repository (`test/` is git-ignored personal saves, the rest
# lives outside it), so this test SKIPS rather than fails where the files are absent.
# Run it with the folders present before shipping a rule; that is what it is for.
#
#   python3 -m unittest tests.test_corpus -v
#   SL2_CORPUS=/path/one:/path/two python3 -m unittest tests.test_corpus
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sl2_to_md as m  # noqa: E402
from validators import IMPOSSIBLE, INCONSISTENT, run_validation  # noqa: E402

## @brief Where the corpus lives on this machine. Override with SL2_CORPUS (os.pathsep
#  separated) to point the same test at another collection.
DEFAULT_ROOTS = (
    "test",
    "/mnt/nobara-data/Backup/AppData/Roaming/DarkSoulsII",
    "/mnt/nobara-data/Backup/AppData/Roaming/DarkSoulsIII",
    "/mnt/nobara-data/Backup/AppData/Roaming/Sekiro",
)
HARD = (IMPOSSIBLE, INCONSISTENT)


def corpus_files():
    env = os.environ.get("SL2_CORPUS")
    roots = env.split(os.pathsep) if env else DEFAULT_ROOTS
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []
    for r in roots:
        root = r if os.path.isabs(r) else os.path.join(base, r)
        out += glob.glob(os.path.join(root, "**", "*.sl2"), recursive=True)
    return sorted(set(out))


class Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = corpus_files()
        if not cls.files:
            raise unittest.SkipTest("no corpus on this machine; set SL2_CORPUS")
        cls.base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_legitimate_save_is_called_impossible_or_inconsistent(self):
        offenders, characters = [], 0
        for path in self.files:
            with open(path, "rb") as f:
                save = m.parse_save(f.read(), self.base)
            for _, ch in save.characters:
                characters += 1
                for finding in run_validation(ch, save.game, self.base).findings:
                    if finding.tier in HARD:
                        offenders.append(
                            f"{os.path.basename(path)} [{finding.tier}] "
                            f"{finding.title}: expected {finding.expected}, "
                            f"found {finding.found}"
                        )
        self.assertEqual(offenders, [], f"{len(offenders)} of {characters} characters")

    def test_the_corpus_actually_exercises_the_rules(self):
        # A regression test that skipped every file would also pass, so this asserts
        # the run had material: characters with stats, in more than one game.
        games, with_stats = set(), 0
        for path in self.files:
            with open(path, "rb") as f:
                save = m.parse_save(f.read(), self.base)
            games.add(save.game)
            for _, ch in save.characters:
                if ch.get("stats") and ch.get("level") is not None:
                    with_stats += 1
        self.assertGreater(with_stats, 100)
        self.assertGreaterEqual(len(games), 3)


if __name__ == "__main__":
    unittest.main()
