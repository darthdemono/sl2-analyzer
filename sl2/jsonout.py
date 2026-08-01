"""JSON output: the same parsed save the Markdown writer gets, as a machine-readable
document against a published schema.

The Markdown is written for a person (or an LLM) to read; this is written for a
program. Both start from `parse_save`, so a field can never say one thing in one
format and something else in the other.

Two rules shape the document. Nothing is invented to fill a hole — a field the save
does not carry is simply absent, exactly as in the Markdown, so a consumer can tell
"not in this game" from "zero". And nothing about the machine that produced it is
guessed: the environment block holds only what the caller passed on the command line.
"""
import json
import os
from collections import OrderedDict
from datetime import datetime, timezone

from .convert import REPO_URL

## @brief Where the schema is published. Static file at the site root, so a consumer
#  can resolve it without cloning anything.
SCHEMA_URL = "https://darthdemono.github.io/sl2-analyzer/schema.json"

## @brief Schema version, semver. MINOR for a new optional field, MAJOR for anything
#  that would break a reader which trusted the previous shape.
SCHEMA_VERSION = "1.0.0"

## @brief Environment keys the schema names explicitly. Any other key is still
#  accepted and written through — this list is what gets documented and type-checked,
#  not a whitelist. The point of the block is that a save alone cannot tell you which
#  store sold the game, which patch it ran, or what it ran under.
KNOWN_META = ("source", "version", "dlc", "os", "launcher", "proton", "gamemode",
              "mangohud", "notes")


##
# @brief Normalise a CLI metadata key: lowercase, spaces and dashes to underscores.
# @details "Proton version" and "proton-version" are the same key. The value is left
#  exactly as typed — only the key is canonicalised, because the key is what a
#  consumer looks up.
# @param key Raw key as typed. @return The canonical form.
def meta_key(key):
    return key.strip().lower().replace(" ", "_").replace("-", "_")


##
# @brief Build the environment block from repeated `--meta key=value` arguments and
#        an optional JSON file.
# @details A key given more than once becomes a LIST, in the order given — that is how
#  `--meta dlc=X --meta dlc=Y` says two DLCs, with no comma-splitting guesswork (item
#  and boss names are full of commas, so splitting on one would be a bug waiting).
#  The JSON file is merged first so an explicit `--meta` on the command line wins.
# @param pairs List of "key=value" strings, or None.
# @param path  Path to a JSON object to merge underneath, or None.
# @return An OrderedDict, empty when nothing was passed.
# @throws ValueError on an argument with no "=", or a JSON file that is not an object.
def parse_meta(pairs, path=None):
    meta = OrderedDict()
    if path:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: expected a JSON object at the top level")
        for k, v in loaded.items():
            meta[meta_key(k)] = v
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--meta expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        key, value = meta_key(key), value.strip()
        if key in meta:
            # Repeat means "and also", so the first repeat turns the value into a list.
            meta[key] = (meta[key] if isinstance(meta[key], list) else [meta[key]]) + [value]
        else:
            meta[key] = value
    return meta


##
# @brief Make a parsed value safe for json.dump, without changing what it says.
# @details The parser uses sets for boss evidence and tuples for fixed-shape rows;
#  both become lists, and a set is sorted so two runs of the same save produce the
#  same bytes. Everything else passes through untouched.
def jsonable(value):
    if isinstance(value, dict):
        return OrderedDict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


##
# @brief One character as a JSON object: its slot number, then every field the parse
#        actually set.
# @details Absent stays absent. The keys are the parser's own, which is deliberate —
#  the Markdown, the web app and this document all name a field the same thing.
# @param slot_no 1-based slot number. @param ch The character dict.
def character_json(slot_no, ch):
    out = OrderedDict([("slot", slot_no)])
    for key, value in ch.items():
        if value is None or value == [] or value == {}:
            continue
        out[key] = jsonable(value)
    return out


##
# @brief Build the whole JSON document for a parsed save.
# @param save     A @ref sl2.convert.SaveData.
# @param filename The source filename, recorded so an export can be traced back.
# @param meta     The environment block from @ref parse_meta, or None.
# @return A dict ready for json.dump.
def build_json(save, filename, meta=None):
    cfg = save.cfg
    source = OrderedDict([
        ("filename", os.path.basename(filename)),
        ("game", save.game),
        ("game_title", cfg["title"]),
        ("support_tier", cfg["tier"]),
    ])
    # Both are properties of the FILE, not of any character, and both are frequently
    # absent — DS2 has no version word, and only ER carries a regulation version.
    if save.version is not None:
        source["save_format_version"] = save.version
    if save.patch is not None:
        source["game_patch"] = save.patch

    doc = OrderedDict([
        ("$schema", SCHEMA_URL),
        ("schema_version", SCHEMA_VERSION),
        ("generated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("tool", OrderedDict([("name", "sl2-analyzer"), ("url", REPO_URL)])),
        ("source", source),
    ])
    if meta:
        doc["environment"] = OrderedDict(meta)
    doc["characters"] = [character_json(i - cfg["slots"].start + 1, ch)
                         for i, ch in save.characters]
    return doc
