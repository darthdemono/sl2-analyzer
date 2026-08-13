"""Command line: argument parsing, save auto-detection, and main()."""

import argparse
import glob
import json
import os
import sys

from .combine import build_combined, find_saves
from .convert import parse_save, render_markdown
from .jsonout import build_json, parse_meta


## @brief Folders a Souls save can live in, per OS. Each game keeps its `.sl2` in
#  a game-named subfolder, hence the trailing `*/`. Steam/Proton, Heroic, Lutris,
#  and plain Wine all mirror the Windows `%APPDATA%` tree inside a prefix, so the
#  tail of every glob is the same `.../AppData/Roaming/<game>/*.sl2`.
def _save_globs():
    globs = ["*.sl2", os.path.join("*", "*.sl2")]  # cwd and one level down
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA")
    if appdata:  # native Windows
        globs.append(os.path.join(appdata, "*", "*.sl2"))
        globs.append(os.path.join(appdata, "*", "*", "*.sl2"))
    # Most games write %APPDATA%/<game>/<file>.sl2; Sekiro puts a Steam-id folder in
    # between, so every prefix is searched at both depths.
    roaming = [
        "drive_c/users/steamuser/AppData/Roaming/*/*.sl2",
        "drive_c/users/steamuser/AppData/Roaming/*/*/*.sl2",
    ]
    user_roaming = [
        "drive_c/users/*/AppData/Roaming/*/*.sl2",
        "drive_c/users/*/AppData/Roaming/*/*/*.sl2",
    ]
    # Steam through Proton.
    for steam in (".local/share/Steam", ".steam/steam", ".steam/root"):
        for tail in roaming:
            globs.append(os.path.join(home, steam, "steamapps/compatdata/*/pfx", tail))
    # Heroic (Epic / GOG) Wine prefixes. Heroic names a prefix after the game, so the
    # per-game folder is a wildcard too.
    for heroic in (
        "Games/Heroic/Prefixes/default/*/pfx",
        "Games/Heroic/Prefixes/*/pfx",
        ".config/heroic/prefixes/default/*/pfx",
        "Games/Heroic/*/pfx",
    ):
        for tail in roaming:
            globs.append(os.path.join(home, heroic, tail))
    # Lutris and a plain ~/.wine prefix (user-named, not always "steamuser").
    for tail in user_roaming:
        globs.append(os.path.join(home, ".local/share/lutris/*/pfx", tail))
        globs.append(os.path.join(home, ".wine", tail))
    return globs


##
# @brief Find a `.sl2` when none was given on the command line.
# @details Globs the current folder and the usual Steam/Proton and Windows save
# locations, and returns the most recently modified match — the live character is
# almost always the newest file. Exits with a clear message if nothing is found.
# @return The path to the chosen save.
def auto_find_save():
    found = []
    for pat in _save_globs():
        found += glob.glob(pat)
    found = sorted(set(found), key=lambda p: os.path.getmtime(p), reverse=True)
    if not found:
        sys.exit(
            "No .sl2 found in the current folder or the usual save locations. "
            "Pass the path explicitly: sl2_to_md.py <save.sl2>"
        )
    if len(found) > 1:
        print(f"Auto-detected {len(found)} saves; using the newest: {found[0]}")
        print("  (pass a path to pick another)")
    else:
        print(f"Auto-detected save: {found[0]}")
    return found[0]


##
# @brief Program entry point.
# @details Output format follows the -o extension (.json → JSON, anything else →
#  Markdown) unless --format says otherwise, so the common case is one flag, not two.
# @return None. Writes the chosen file and prints where it went.
def main():
    ap = argparse.ArgumentParser(
        description="FromSoftware .sl2 save -> Markdown or JSON playthrough summary "
        "(DS PtDE/Remastered, DS2 vanilla/SOTFS, DS3, Sekiro, Elden Ring)",
        epilog="Metadata example: --meta source=Steam --meta os='Nobara 43' "
        "--meta launcher=Heroic --meta proton='GE-Proton 9-20' "
        "--meta dlc='Ashes of Ariandel' --meta dlc='The Ringed City'. "
        "A key repeated becomes a list. Any key is accepted.",
    )
    ap.add_argument(
        "sl2",
        nargs="*",
        help="path to a .sl2 save, or a FOLDER of them (auto-detected if "
        "omitted). Several paths, or one folder, produce a combined "
        "playthrough document covering every character found.",
    )
    ap.add_argument(
        "-o",
        "--out",
        default="playthrough.md",
        help="output path; a .json extension selects JSON",
    )
    ap.add_argument(
        "--format",
        choices=("auto", "md", "json"),
        default="auto",
        help="output format (default: from the -o extension)",
    )
    ap.add_argument(
        "--meta",
        action="append",
        metavar="KEY=VALUE",
        help="record how the game was run: store, version, DLC, OS, "
        "launcher, Proton build, anything. Repeatable; a repeated "
        "key becomes a list. None of it is read from the save.",
    )
    ap.add_argument(
        "--meta-json",
        metavar="PATH",
        help="JSON object of the same metadata, merged underneath --meta",
    )
    ap.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent; 0 for one dense line (default: 2)",
    )
    ap.add_argument(
        "--combined",
        action="store_true",
        help="force the combined document even for a single save",
    )
    args = ap.parse_args()

    try:
        meta = parse_meta(args.meta, args.meta_json)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))

    # The db_* folders sit beside the package, not inside it.
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # A folder, or more than one path, can only mean the combined document — there is
    # no single save to summarise. One file still takes the single-save path unless
    # --combined asks otherwise.
    paths = list(args.sl2)
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += find_saves(p)
        elif os.path.isfile(p):
            files.append(os.path.abspath(p))
        else:
            sys.exit(f"No such file or folder: {p}")
    if paths and not files:
        sys.exit("No .sl2 files found in: " + ", ".join(paths))

    if args.combined or len(files) > 1 or any(os.path.isdir(p) for p in paths):
        text = build_combined(files, base_dir, meta)
        if text is None:
            sys.exit("None of those files could be read as a supported save.")
        write_out(args.out, text)
        return

    sl2 = files[0] if files else auto_find_save()
    if not os.path.isfile(sl2):
        sys.exit(f"No such file: {sl2}")
    with open(sl2, "rb") as f:
        data = f.read()

    fmt = args.format
    if fmt == "auto":
        fmt = "json" if args.out.lower().endswith(".json") else "md"

    name = os.path.basename(sl2)
    save = parse_save(data, base_dir)
    warn_foreign_folder(sl2, save)
    if fmt == "json":
        text = json.dumps(
            build_json(save, name, meta), ensure_ascii=False, indent=args.indent or None
        )
        text += "\n"
    else:
        text = render_markdown(save, name, meta)

    write_out(args.out, text)


##
# @brief Warn when a save is sitting in a folder belonging to a different account.
# @details DS3, Sekiro and Elden Ring write the owning account into the save, and the
# game only reads a save back from the folder named for that account — so a save whose
# account id changed underneath it (a Steam emulator reconfigured, a different profile)
# will not load, and the game says nothing useful about why. Comparing the two is free
# once both are known.
# @note Deliberately printed to STDERR and never into the document: the browser cannot
# see a dropped file's folder, and the two front ends have to stay byte-identical.
# @param path The save file's path. @param save The parsed @ref sl2.convert.SaveData.
def warn_foreign_folder(path, save):
    if save.folder is None:
        return
    here = os.path.basename(os.path.dirname(os.path.abspath(path)))
    # Only complain when the folder is clearly one of the game's own account folders:
    # same width as the real thing and made of the right digits. A save copied into a
    # working directory is not a mismatch, it is just somewhere else — and the width
    # test is what stops an ordinary folder that happens to spell hex ("beef", "decade")
    # from being read as somebody's account.
    if not here or here.lower() == save.folder.lower() or len(here) != len(save.folder):
        return
    if not all(c in "0123456789abcdefABCDEF" for c in here):
        return
    print(
        f"Warning: this save was written by Steam account {save.owner[0]} and the "
        f"game will only load it from a folder named '{save.folder}', but it is in "
        f"'{here}'. Under the account that owns '{here}' the game will not see it.",
        file=sys.stderr,
    )


## @brief Write the document, making the output folder if it does not exist yet.
def write_out(path, text):
    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote {path}")
