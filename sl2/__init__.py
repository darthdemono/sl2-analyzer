"""Read a FromSoftware `.sl2` save and report what is in it.

The package is layered, and the layers only point one way:

    reader / keys                    bounds-checked reads, the AES keys
    bnd4 / crypto / detect           the container, per-game decryption, which game
    itemdb / progress / roster       item tables, the shared progress floor, names
    ds1 / ds2 / ds3 / er             one module per game family
    totals                           the "of N" denominators (needs every game)
    render / jsonout                 the two writers
    convert                          the driver: parse_save, then either writer
    cli                              argument parsing and main()

`parse_save` does all the reading and `render_markdown` / `build_json` do all the
writing, so the two output formats cannot drift apart — they are the same data.

Everything below is imported for its side effect of being re-exported: the CLI, the
parity harnesses and the scratch tools all reach in through this one name.
"""

from .convert import (
    GAMES,
    REPO_URL,
    SaveData,
    convert,
    parse_save,
    render_markdown,
    footer_for,
    disclaimer_for,
    save_format_version,
    er_game_patch,
)
from .jsonout import SCHEMA_URL, SCHEMA_VERSION, build_json, parse_meta
from .render import md_for_character
from .bnd4 import parse_bnd4, checksum_ok, Bnd4Entry
from .detect import detect_game
from .reader import read_uint, u8, u16, u32, u64, read_utf16, is_valid_name

__all__ = [
    "GAMES",
    "REPO_URL",
    "SaveData",
    "convert",
    "parse_save",
    "render_markdown",
    "footer_for",
    "disclaimer_for",
    "save_format_version",
    "er_game_patch",
    "SCHEMA_URL",
    "SCHEMA_VERSION",
    "build_json",
    "parse_meta",
    "md_for_character",
    "parse_bnd4",
    "checksum_ok",
    "Bnd4Entry",
    "detect_game",
    "read_uint",
    "u8",
    "u16",
    "u32",
    "u64",
    "read_utf16",
    "is_valid_name",
]
