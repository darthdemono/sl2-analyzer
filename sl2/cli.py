"""Command line: argument parsing, save auto-detection, and main().
"""
import argparse
import glob
import json
import os
import sys
from .convert import parse_save, render_markdown
from .jsonout import build_json, parse_meta


## @brief Folders a Souls save can live in, per OS. Each game keeps its `.sl2` in
#  a game-named subfolder, hence the trailing `*/`. Steam/Proton, Heroic, Lutris,
#  and plain Wine all mirror the Windows `%APPDATA%` tree inside a prefix, so the
#  tail of every glob is the same `.../AppData/Roaming/<game>/*.sl2`.
def _save_globs():
    globs = ["*.sl2", os.path.join("*", "*.sl2")]      # cwd and one level down
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA")
    if appdata:                                        # native Windows
        globs.append(os.path.join(appdata, "*", "*.sl2"))
    roaming = "drive_c/users/steamuser/AppData/Roaming/*/*.sl2"
    user_roaming = "drive_c/users/*/AppData/Roaming/*/*.sl2"
    # Steam through Proton.
    for steam in (".local/share/Steam", ".steam/steam", ".steam/root"):
        globs.append(os.path.join(home, steam, "steamapps/compatdata/*/pfx", roaming))
    # Heroic (Epic / GOG) Wine prefixes.
    for heroic in ("Games/Heroic/Prefixes/default/*/pfx",
                   ".config/heroic/prefixes/default/*/pfx", "Games/Heroic/*/pfx"):
        globs.append(os.path.join(home, heroic, roaming))
    # Lutris and a plain ~/.wine prefix (user-named, not always "steamuser").
    globs.append(os.path.join(home, ".local/share/lutris/*/pfx", user_roaming))
    globs.append(os.path.join(home, ".wine", user_roaming))
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
        sys.exit("No .sl2 found in the current folder or the usual save locations. "
                 "Pass the path explicitly: sl2_to_md.py <save.sl2>")
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
                    "(DS PtDE/Remastered, DS2 vanilla/SOTFS, DS3, Elden Ring)",
        epilog="Metadata example: --meta source=Steam --meta os='Nobara 43' "
               "--meta launcher=Heroic --meta proton='GE-Proton 9-20' "
               "--meta dlc='Ashes of Ariandel' --meta dlc='The Ringed City'. "
               "A key repeated becomes a list. Any key is accepted.")
    ap.add_argument("sl2", nargs="?",
                    help="path to the .sl2 save (auto-detected if omitted)")
    ap.add_argument("-o", "--out", default="playthrough.md",
                    help="output path; a .json extension selects JSON")
    ap.add_argument("--format", choices=("auto", "md", "json"), default="auto",
                    help="output format (default: from the -o extension)")
    ap.add_argument("--meta", action="append", metavar="KEY=VALUE",
                    help="record how the game was run: store, version, DLC, OS, "
                         "launcher, Proton build, anything. Repeatable; a repeated "
                         "key becomes a list. None of it is read from the save.")
    ap.add_argument("--meta-json", metavar="PATH",
                    help="JSON object of the same metadata, merged underneath --meta")
    ap.add_argument("--indent", type=int, default=2,
                    help="JSON indent; 0 for one dense line (default: 2)")
    args = ap.parse_args()

    sl2 = args.sl2 or auto_find_save()
    if not os.path.isfile(sl2):
        sys.exit(f"No such file: {sl2}")
    with open(sl2, "rb") as f:
        data = f.read()

    try:
        meta = parse_meta(args.meta, args.meta_json)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))

    fmt = args.format
    if fmt == "auto":
        fmt = "json" if args.out.lower().endswith(".json") else "md"

    # The db_* folders sit beside the package, not inside it.
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    name = os.path.basename(sl2)
    save = parse_save(data, base_dir)
    if fmt == "json":
        text = json.dumps(build_json(save, name, meta), ensure_ascii=False,
                          indent=args.indent or None)
        text += "\n"
    else:
        text = render_markdown(save, name, meta)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote {args.out}")
