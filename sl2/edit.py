"""Copy-only archive edits that validate the save before writing it."""

import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .bnd4 import checksum_ok, parse_bnd4
from .convert import DS2_STEAM_ID_LEN, DS2_STEAM_ID_OFF, STEAM_ID64_HIGH, steam_owner
from .detect import detect_game
from .ds2 import DS2_GAMES
from .er import (
    ER_MENU_DATA_OFF,
    ER_MENU_LEN_OFF,
    ER_PROFILE_STRIDE,
    ER_SLOT_COUNT,
    er_roster,
)
from .keys import DS2_KEY, DS2_VANILLA_KEY, DS3_KEY
from .reader import u32
from .sdt import SDT_MENU_ENTRY, SDT_SLOT_COUNT, SDT_STEAM_OFF, sdt_active_slots


## @brief Complete on-disk size of one ER character entry, including its MD5 prefix.
ER_SLOT_ENTRY_SIZE = 0x280010


## @brief Return a mutable, checksum-verified BND4 save and its identified game.
def _checked_save(data):
    entries = parse_bnd4(data)
    game = detect_game(data, entries)
    bad = [str(e.index) for e in entries if not checksum_ok(data, e)]
    if bad:
        raise ValueError("Refusing to edit a save with bad BND4 checksum(s): " + ", ".join(bad))
    ordered = sorted(entries, key=lambda e: e.offset)
    if any(a.offset + a.size > b.offset for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Refusing to edit a save with overlapping BND4 entries.")
    return bytearray(data), entries, game


## @brief Recalculate an entry's outer MD5 after its payload has changed.
def _seal(data, entry):
    start = entry.offset
    data[start : start + 16] = hashlib.md5(data[start + 16 : start + entry.size]).digest()


## @brief Encrypt a complete AES-CBC plaintext using the entry's unchanged IV.
def _encrypt(key, iv, plaintext):
    return Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor().update(plaintext)


## @brief Change the SteamID64 in a save format whose every required copy is known.
def set_steam_id(data, steam_id):
    """Return a verified edited copy; never changes @p data in place."""
    try:
        steam_id = int(str(steam_id), 10)
    except ValueError as exc:
        raise ValueError("SteamID64 must be a decimal integer.") from exc
    if not 0 < steam_id < 1 << 64 or steam_id >> 32 != STEAM_ID64_HIGH:
        raise ValueError("SteamID64 must be an individual Steam account ID.")

    out, entries, game = _checked_save(data)
    old = steam_owner(data, entries, game)
    if old is None:
        raise ValueError(f"{game} has no verified writable SteamID64 field.")
    packed = steam_id.to_bytes(8, "little")

    if game == "sdt":
        active = sdt_active_slots(data, entries, lambda b: b[16:])
        if active is None:
            raise ValueError("Sekiro's occupancy array is unreadable; refusing to guess slots.")
        menu = entries[SDT_MENU_ENTRY]
        out[menu.offset + 16 + 0x24 : menu.offset + 16 + 0x2C] = packed
        _seal(out, menu)
        for i in active:
            entry = entries[i]
            at = entry.offset + 16 + SDT_STEAM_OFF
            if int.from_bytes(data[at : at + 8], "little") != int(old[1]):
                raise ValueError(f"Sekiro slot {i + 1} does not match the menu SteamID64.")
            out[at : at + 8] = packed
            _seal(out, entry)
    elif game == "ds3":
        entry = entries[10]
        blob = data[entry.offset : entry.offset + entry.size]
        plain = bytearray(
            Cipher(algorithms.AES(DS3_KEY), modes.CBC(blob[16:32])).decryptor().update(blob[16:])
        )
        if len(plain) < 28 or u32(plain, 16) is None:
            raise ValueError("Dark Souls III menu block is not a complete AES payload.")
        plain[24:32] = packed
        out[entry.offset + 16 : entry.offset + entry.size] = _encrypt(DS3_KEY, blob[16:32], plain)
        _seal(out, entry)
    elif game in DS2_GAMES:
        entry = entries[0]
        blob = data[entry.offset : entry.offset + entry.size]
        key = DS2_KEY if game == "ds2sotfs" else DS2_VANILLA_KEY
        plain = bytearray(
            Cipher(algorithms.AES(key), modes.CBC(blob[16:32])).decryptor().update(blob[32:])
        )
        length = u32(plain, 0)
        if length is None or not 0 < length <= len(plain) - 4:
            raise ValueError("Dark Souls II header is not a complete AES payload.")
        at = 4 + DS2_STEAM_ID_OFF
        if at + DS2_STEAM_ID_LEN > 4 + length:
            raise ValueError("Dark Souls II SteamID64 field falls outside the header.")
        plain[at : at + DS2_STEAM_ID_LEN] = f"{steam_id:016x}".encode("ascii")
        out[entry.offset + 32 : entry.offset + entry.size] = _encrypt(key, blob[16:32], plain)
        _seal(out, entry)
    elif game == "er":
        raise ValueError(
            "Elden Ring repeats SteamID64 inside variable-length active slots; "
            "this editor will not change only the menu copy."
        )
    else:
        raise ValueError(f"SteamID64 editing is not supported for {game}.")

    _verify(out, game, steam_id=steam_id, active=active if game == "sdt" else None)
    return bytes(out)


## @brief Clear ER slots absent from the roster, or every slot not explicitly retained.
def trim_er_slots(data, keep_slots=None):
    """Return a verified archive copy with selected ER profiles and slots zeroed."""
    keep = None if keep_slots is None else set(keep_slots)
    if keep is not None and (
        not keep or any(not isinstance(i, int) or not 1 <= i <= ER_SLOT_COUNT for i in keep)
    ):
        raise ValueError("--trim-slots needs one or more slot numbers from 1 through 10.")
    out, entries, game = _checked_save(data)
    if game != "er" or len(entries) < ER_SLOT_COUNT + 1:
        raise ValueError("--trim-slots currently supports Elden Ring saves only.")
    if any(entries[i].size != ER_SLOT_ENTRY_SIZE for i in range(ER_SLOT_COUNT)):
        raise ValueError("Elden Ring slot entries do not have the verified fixed size.")

    menu = entries[10]
    menu_data = data[menu.offset : menu.offset + menu.size]
    length = u32(menu_data, ER_MENU_LEN_OFF)
    profile = ER_MENU_DATA_OFF + (length if length is not None else -1) + ER_SLOT_COUNT
    if length is None or profile + ER_SLOT_COUNT * ER_PROFILE_STRIDE > len(menu_data):
        raise ValueError("Elden Ring roster layout is incomplete; refusing to trim it.")
    roster = er_roster(menu_data)
    if len(roster) != ER_SLOT_COUNT:
        raise ValueError("Elden Ring roster is incomplete; refusing to trim it.")

    empty = {
        i
        for i in range(ER_SLOT_COUNT)
        if (keep is None and not roster[i][0]) or (keep is not None and i + 1 not in keep)
    }

    changed_menu = False
    for i in empty:
        entry = entries[i]
        out[entry.offset + 16 : entry.offset + entry.size] = b"\0" * (entry.size - 16)
        _seal(out, entry)
        out[menu.offset + profile - ER_SLOT_COUNT + i] = 0
        start = menu.offset + profile + i * ER_PROFILE_STRIDE
        out[start : start + ER_PROFILE_STRIDE] = b"\0" * ER_PROFILE_STRIDE
        changed_menu = True
    if changed_menu:
        _seal(out, menu)
    _verify(out, game, empty_slots=empty)
    return bytes(out)


## @brief Canonicalise inactive slots without changing any listed character.
def trim_inactive_slots(data):
    """Return a verified copy with inactive Sekiro or ER slots cleared."""
    out, entries, game = _checked_save(data)
    if game == "er":
        return trim_er_slots(data)
    if game == "sdt":
        active = sdt_active_slots(data, entries, lambda b: b[16:])
        if active is None:
            raise ValueError("Sekiro's occupancy array is unreadable; refusing to guess slots.")
        for i in set(range(SDT_SLOT_COUNT)) - active:
            entry = entries[i]
            out[entry.offset + 16 : entry.offset + entry.size] = b"\0" * (entry.size - 16)
            _seal(out, entry)
    else:
        raise ValueError("--trim-inactive supports Sekiro and Elden Ring only.")
    _verify(out, game)
    return bytes(out)


## @brief Check the edited archive's MD5 wrappers and operation-specific invariants.
def _verify(data, game, steam_id=None, active=None, empty_slots=None):
    entries = parse_bnd4(data)
    if detect_game(data, entries) != game or not all(checksum_ok(data, e) for e in entries):
        raise ValueError("Edited save failed its BND4 integrity check.")
    if steam_id is not None:
        owner = steam_owner(data, entries, game)
        if owner is None or int(owner[1]) != steam_id:
            raise ValueError("Edited save did not retain the requested SteamID64.")
        if active is not None:
            for i in active:
                e = entries[i]
                at = e.offset + 16 + SDT_STEAM_OFF
                if int.from_bytes(data[at : at + 8], "little") != steam_id:
                    raise ValueError(f"Edited Sekiro slot {i + 1} has a mismatched SteamID64.")
    if empty_slots is not None:
        menu = entries[10]
        roster = er_roster(data[menu.offset : menu.offset + menu.size])
        for i in empty_slots:
            if i >= len(roster) or roster[i][0]:
                raise ValueError(f"Edited Elden Ring slot {i + 1} is still active.")
            e = entries[i]
            if any(data[e.offset + 16 : e.offset + e.size]):
                raise ValueError(f"Edited Elden Ring slot {i + 1} still has payload data.")
