##
# @file file_rules.py
# @brief The rules that are about the FILE rather than about a character.
#
# Separate entry point, because these do not fit the `(character, game_data)` shape: a
# checksum belongs to a BND4 entry and an account belongs to the container. The sl2
# package is not imported here — the caller passes the reader in — so the dependency
# still points one way and `validators` stays importable on its own.
from .models import INCONSISTENT, Finding, Report

## @brief Games whose entries carry a plain @c MD5(rest) wrapper the caller can check.
#  Measured across the whole local corpus: every entry of every DS1, DS2, DS3, Sekiro
#  and Elden Ring save verifies. NIGHTREIGN IS DELIBERATELY ABSENT — its entries are
#  AES with the IV at offset 0, so the MD5 only appears after decryption and all 14
#  entries "fail" a plain check. Reporting that would be reporting this pass's own
#  ignorance as a finding about the save.
CHECKSUM_GAMES = frozenset(
    {"ptde", "dsr", "ds2vanilla", "ds2sotfs", "ds3", "er", "sdt"}
)

## @brief What no file-level rule covers yet, and why. The account one is not laziness:
#  the reader exposes the account the CONTAINER records, not a per-slot copy, so there
#  is nothing to compare slot against slot without teaching this pass new offsets — and
#  a validation pass inventing offsets is exactly how it would start lying.
FILE_UNIMPLEMENTED = [
    "slots spliced from different accounts (the reader exposes one file-level Steam "
    "account, not a per-slot one, so there is nothing to compare between slots)",
]


##
# @brief Every BND4 entry whose stored MD5 disagrees with its own bytes.
# @details A game always writes a correct checksum, so a wrong one did not come out of
# one. It is a WEAK check in the direction that matters, though, and the note says so:
# every save editor worth the name fixes the checksum, so this catches a hex-editor
# poke and nothing else. A file that passes has proved nothing.
# @param entries      BND4 entries. @param data The full file bytes.
# @param checksum_ok  The caller's @c checksum_ok(data, entry).
def bnd4_checksums(entries, data, checksum_ok):
    bad = [i for i, e in enumerate(entries) if not checksum_ok(data, e)]
    if not bad:
        return []
    where = ", ".join(str(i) for i in bad[:8]) + ("…" if len(bad) > 8 else "")
    return [
        Finding(
            "bnd4-checksum",
            INCONSISTENT,
            "Save entry checksum",
            f"MD5 matching its own bytes on all {len(entries)} entries",
            f"{len(bad)} entr{'y' if len(bad) == 1 else 'ies'} mismatched (index {where})",
            "Only crude edits are caught: a save editor rewrites the checksum, and a "
            "corrupt or truncated copy fails the same way an edit does. A file that "
            "passes this has proved nothing.",
        )
    ]


##
# @brief Run the file-level rules over one container.
# @param game        Game key. @param entries BND4 entries. @param data File bytes.
# @param checksum_ok The caller's checksum function, injected so this module imports
#                    nothing from the parser package.
# @return A @ref Report whose `game` is the file's.
def run_file_validation(game, entries, data, checksum_ok):
    if game not in CHECKSUM_GAMES or not entries:
        why = (
            "Nightreign entries are encrypted with the IV in front, so their MD5 "
            "only exists after decryption and cannot be checked here"
        )
        return Report(
            game,
            [],
            0,
            [why] + FILE_UNIMPLEMENTED
            if game == "nr"
            else ["no file-level rule for this game"] + FILE_UNIMPLEMENTED,
        )
    return Report(
        game, bnd4_checksums(entries, data, checksum_ok), 1, list(FILE_UNIMPLEMENTED)
    )
