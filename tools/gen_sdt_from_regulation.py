#!/usr/bin/env python3
"""
gen_sdt_from_regulation.py — extract Sekiro (SDT) param values, event flag ids and
shipped English display names from a local Sekiro install into db_sdt/ tables.

NAME CORRECTION — READ FIRST
    This file is called gen_sdt_from_REGULATION, and Sekiro has no regulation.bin.
    Not loose and not inside the archives: that is a DS3/Elden Ring file. Sekiro's
    params are /param/gameparam/gameparam.parambnd.dcx. The name is kept only because
    renaming it would break the /sekiro-data command that calls it; read every mention
    of "regulation.bin" below as that path instead. See CLAUDE.md and the memory
    sekiro-regulation-unpack for the unpack route (UXM-Selective-Unpack has the Sekiro
    RSA keys; BinderTool ships DS3's and will NOT open these archives unmodified).

WHY THIS EXISTS
    Paramdex ships PARAMDEFs (field layouts) and Names (id -> annotation) but NOT
    param VALUES. Every event flag id the analyzer needs lives in the game's own
    param binder. Paramdex SDT/Names are also machine-translated Japanese dev
    strings ("Rough temple", "Protagonist_arm_prosthesis") — the shipped English
    names live in msg/engus/*.msgbnd.dcx as FMG entries. So: defs from Paramdex,
    values from the param binder, display names from FMG.

FORMAT NOTES (reconciled against JKAnderson/SoulsFormats)
    - Sekiro's regulation.bin is NOT encrypted. SoulsFormats has
      DecryptDS3Regulation / DecryptERRegulation / DecryptAC6Regulation and no
      Sekiro equivalent; SDT regulation is a plain DCX-wrapped BND4.
    - PARAM header: Format2D lives at 0x2C (legacy name, real offset 0x2C).
      LongDataOffset (0x04) -> 24-byte row entries; OffsetParamType (0x80) ->
      param type is a string at an offset rather than inline.
    - FMG: Sekiro uses the DarkSouls3 ("wide") variant — 64-bit string offsets.

USAGE
    python3 tools/gen_sdt_from_regulation.py \
        --game-root "/path/to/Sekiro" \
        --paramdex  "/path/to/Paramdex" \
        --out       "db_sdt" \
        --report    "db_sdt/_extract_report.md" \
        [--strict]

EXIT CODES
    0 ok · 2 bad input/paths · 3 parse failure · 4 acceptance gate failed (--strict)
"""

from __future__ import annotations

import argparse
import io
import os
import re
import struct
import sys
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dc_field
from pathlib import Path

# --------------------------------------------------------------------------
# What we actually want out of regulation.bin.
#
# Field names below are verbatim from Paramdex SDT/Defs (commit ff7245e) and were
# confirmed present. If a future Paramdex bump renames one, this table is the
# single place to fix it — the extractor asserts every field exists before use.
# --------------------------------------------------------------------------

TARGETS: dict[str, dict] = {
    # Sculptor's Idols. The bonfire analogue: discovery flags.
    # NOTE: 58 rows, but Sekiro ships ~38 reachable idols — several rows are
    # per-map-state duplicates of the same physical idol (Dilapidated Temple is
    # both 100 and 1100). Dedupe on bonfireEntityId, never on row id.
    "BonfireWarpParam": {
        "out": "idols.tsv",
        "fields": ["eventflagId", "bonfireEntityId", "grayoutEventflagId",
                   "msgId", "menuTextId"],
        "name_fmg": ("menuTextId", "menu"),
        "purpose": "Sculptor's Idol discovery flags",
    },
    # Reflection of Strength roster = the canonical boss + miniboss list, each
    # row carrying up to 10 gating flags (defeat flags, availability flags).
    # Paramdex has NO Names file for this param — row ids need hand-mapping.
    "RematchWarpParam": {
        "out": "bosses.tsv",
        # EventFlagManByte<i> carries the required state for EventFlagId<i>
        # (i.e. flag polarity). Without it a "defeated" flag and a "not yet
        # available" flag look identical.
        "fields": (["WarpPointId"]
                   + [f"EventFlagId{i}" for i in range(1, 11)]
                   + [f"EventFlagManByte{i}" for i in range(1, 11)]),
        "name_fmg": None,
        "purpose": "boss/miniboss roster + gating flags",
    },
    # Door / shortcut / lever activations — the Sekiro analogue of DS3 shortcut
    # flags, and the cheapest source of "has this area been opened up" evidence.
    "ObjActParam": {
        "out": "objact_flags.tsv",
        "fields": ["spQualifiedPassEventFlag"],
        "name_fmg": None,
        "purpose": "door / shortcut activation flags",
    },
    # Skill tree unlocks — one flag per node, 89 annotated rows.
    "SkillParam": {
        "out": "skills.tsv",
        "fields": ["unlockEventFlag", "virtualWeaponId", "acquireWeaponId"],
        "name_fmg": None,
        "purpose": "skill / combat-art unlock flags",
    },
    # Pickup flags. The DS3-analogue for item completion tracking.
    "ItemLotParam": {
        "out": "item_flags.tsv",
        "fields": [f"lotItemId{i:02d}" for i in range(1, 9)]
                  + [f"getItemFlagId{i:02d}" for i in range(1, 9)]
                  + ["getItemFlagId", "cumulateNumFlagId"],
        "name_fmg": None,
        "purpose": "item pickup flags",
    },
    # Merchant unlocks — proves NPC availability without touching NPC flags.
    "ShopLineupParam": {
        "out": "shop_flags.tsv",
        "fields": ["equipId", "mtrlId", "eventFlag", "flagId_forRelease"],
        "name_fmg": None,
        "purpose": "shop unlock / sold-out flags",
    },
    # 13 rows driving the completion percentage.
    # CAUTION: Paramdex SDT Names for this param are DS3 leftovers ("Abyss
    # Watchers", "Aldrich", "Twin Princes"). Treat the annotation as junk and
    # judge purely on the eventFlagId values read here.
    "GameProgressParam": {
        "out": "progress.tsv",
        "fields": ["eventFlagId", "progressValue"],
        "name_fmg": None,
        "purpose": "main-progression milestone flags (names untrusted)",
    },
    # Boss health-bar rows: 18 real entries, ids match MSB entity ids.
    "GameAreaParam": {
        "out": "boss_areas.tsv",
        "fields": [],
        "name_fmg": None,
        "purpose": "boss entity ids (join key for RematchWarpParam)",
    },
    # Item tables, for the name database rather than flags.
    "EquipParamGoods": {
        "out": "goods.tsv",
        "fields": ["goodsType", "goodsUseAnim", "maxNum"],
        "name_fmg": ("__row_id__", "item"),
        "purpose": "consumables / key items / materials",
    },
    "EquipParamWeapon": {
        "out": "weapons.tsv",
        "fields": [],
        "name_fmg": ("__row_id__", "item"),
        "purpose": "weapons + prosthetic tools",
    },
}

# FMG ids differ per game; these are probed rather than assumed. The extractor
# reads every FMG in the msgbnd and picks the one whose id coverage best matches
# the param it is naming, then records the winning id in the report so it can be
# pinned later.
FMG_BUNDLES = {
    "item": ["item.msgbnd.dcx", "item_dlc1.msgbnd.dcx", "item_dlc2.msgbnd.dcx"],
    "menu": ["menu.msgbnd.dcx", "menu_dlc1.msgbnd.dcx", "menu_dlc2.msgbnd.dcx"],
}

JUNK = re.compile(
    r"(^\s*$|^\[?(DUMMY|dummy|ダミー|test|テスト)|^%null%|"
    r"Protagonist[_ ]|主人公|Original Memory|不明|未使用|使用しない|"
    r"^\d+$|^-+$)",
    re.IGNORECASE,
)


# ==========================================================================
# DCX
# ==========================================================================

def dcx_decompress(data: bytes) -> bytes:
    """Unwrap a DCX container. Sekiro uses DFLT (raw zlib)."""
    if data[:4] != b"DCX\0":
        return data
    dca = data.find(b"DCA\0")
    if dca < 0:
        raise ValueError("DCX: no DCA block")
    (dca_size,) = struct.unpack_from(">i", data, dca + 4)
    payload = data[dca + dca_size:]
    try:
        return zlib.decompress(payload)
    except zlib.error:
        # Fallback: scan forward for a zlib header. Cheap insurance against a
        # DCA header size we mis-read rather than a genuinely different codec.
        for i in range(len(payload) - 2):
            if payload[i] == 0x78 and payload[i + 1] in (0x01, 0x9C, 0xDA, 0x5E):
                try:
                    return zlib.decompress(payload[i:])
                except zlib.error:
                    continue
        raise ValueError("DCX: could not inflate (Oodle/KRAK payload?)")


# ==========================================================================
# BND4
# ==========================================================================

@dataclass
class BinderFile:
    id: int
    name: str
    data: bytes


def read_bnd4(data: bytes) -> list[BinderFile]:
    """
    Minimal BND4 reader — enough for regulation.bin and *.msgbnd.dcx.

    If sl2_to_md.py already exposes a BND4 reader (the .sl2 saves are BND4),
    prefer importing it and delete this. Kept standalone so the tool can run
    before that refactor lands.
    """
    data = dcx_decompress(data)
    if data[:4] != b"BND4":
        raise ValueError(f"not a BND4 (magic {data[:4]!r})")

    big = data[0x09] != 0
    e = ">" if big else "<"
    (file_count,) = struct.unpack_from(e + "i", data, 0x0C)
    (header_size,) = struct.unpack_from(e + "q", data, 0x10)
    (file_header_size,) = struct.unpack_from(e + "q", data, 0x20)
    unicode_names = data[0x30] != 0
    fmt = data[0x31]
    extended = data[0x32]

    out: list[BinderFile] = []
    pos = header_size
    for _ in range(file_count):
        p = pos
        flags = data[p]
        (compressed_size,) = struct.unpack_from(e + "q", data, p + 0x08)
        (uncompressed_size,) = struct.unpack_from(e + "q", data, p + 0x10) \
            if (fmt & 0b0010_0000) else (compressed_size,)
        off_field = 0x18 if (fmt & 0b0010_0000) else 0x10
        (data_offset,) = struct.unpack_from(e + "I", data, p + off_field)
        (file_id,) = struct.unpack_from(e + "i", data, p + off_field + 4)
        (name_offset,) = struct.unpack_from(e + "i", data, p + off_field + 8)

        name = ""
        if name_offset:
            if unicode_names:
                end = data.find(b"\x00\x00", name_offset)
                while (end - name_offset) % 2:
                    end = data.find(b"\x00\x00", end + 1)
                name = data[name_offset:end].decode("utf-16-le", "replace")
            else:
                end = data.find(b"\x00", name_offset)
                name = data[name_offset:end].decode("shift_jis", "replace")

        blob = data[data_offset:data_offset + compressed_size]
        if blob[:4] == b"DCX\0":
            blob = dcx_decompress(blob)
        out.append(BinderFile(file_id, name, blob))
        pos += file_header_size

    if not out:
        raise ValueError("BND4 parsed but contained no files — layout mismatch")
    return out


# ==========================================================================
# PARAMDEF (Paramdex XML)
# ==========================================================================

_SIZES = {
    "s8": 1, "u8": 1, "s16": 2, "u16": 2, "s32": 4, "u32": 4,
    "b32": 4, "f32": 4, "angle32": 4, "f64": 8,
    "dummy8": 1, "fixstr": 1, "fixstrW": 2,
}
_STRUCT = {
    "s8": "b", "u8": "B", "s16": "h", "u16": "H", "s32": "i", "u32": "I",
    "b32": "i", "f32": "f", "angle32": "f", "f64": "d",
}
_DEF_RE = re.compile(
    r"^\s*(?P<type>\w+)\s+(?P<name>\w+)"
    # Brackets are usually an array length, but Paramdex also uses them for
    # value-range comments (e.g. "u8 GroundMaterialType [0,1,2,3]"). Anything
    # that isn't a bare integer is treated as a comment, not an array.
    r"(?:\s*\[\s*(?P<arr>[^\]]*?)\s*\])?"
    r"(?:\s*:\s*(?P<bits>\d+))?"
    r"(?:\s*=\s*(?P<default>.+))?\s*$"
)


@dataclass
class DefField:
    type: str
    name: str
    array: int = 1
    bits: int = -1
    offset: int = -1
    bit_offset: int = -1


@dataclass
class ParamDef:
    param_type: str
    row_size: int
    fields: list[DefField] = dc_field(default_factory=list)

    def by_name(self, n: str) -> DefField | None:
        for f in self.fields:
            if f.name == n:
                return f
        return None


def load_paramdef(path: Path) -> ParamDef:
    root = ET.parse(path).getroot()
    param_type = (root.findtext("ParamType") or "").strip()

    fields: list[DefField] = []
    for node in root.findall("./Fields/Field"):
        m = _DEF_RE.match(node.get("Def", ""))
        if not m:
            raise ValueError(f"{path.name}: unparsable Def {node.get('Def')!r}")
        fields.append(DefField(
            type=m.group("type"),
            name=m.group("name"),
            array=int(m.group("arr")) if (m.group("arr") or "").isdigit() else 1,
            bits=int(m.group("bits") or -1),
        ))

    # Offset pass, mirroring SoulsFormats' bit packing: consecutive bitfields
    # of the same DefType share one storage unit; anything else flushes it.
    off = 0
    bit_off = -1
    bit_type = None
    for f in fields:
        if f.type not in _SIZES:
            raise ValueError(f"{path.name}: unknown type {f.type!r}")
        size = _SIZES[f.type]
        if f.bits == -1:
            if bit_off != -1:
                off += _SIZES[bit_type]
                bit_off, bit_type = -1, None
            f.offset = off
            off += size * f.array
        else:
            limit = size * 8
            if bit_off == -1 or bit_type != f.type or bit_off + f.bits > limit:
                if bit_off != -1:
                    off += _SIZES[bit_type]
                bit_off, bit_type = 0, f.type
            f.offset, f.bit_offset = off, bit_off
            bit_off += f.bits
    if bit_off != -1:
        off += _SIZES[bit_type]

    return ParamDef(param_type=param_type, row_size=off, fields=fields)


# ==========================================================================
# PARAM
# ==========================================================================

FLAG_INT_DATA_OFFSET = 0b0000_0010
FLAG_LONG_DATA_OFFSET = 0b0000_0100
FLAG_OFFSET_PARAM_TYPE = 0b1000_0000
FLAG2_UNICODE_ROW_NAMES = 0b0000_0001


@dataclass
class ParamRow:
    id: int
    name: str
    data: bytes


@dataclass
class Param:
    param_type: str
    rows: list[ParamRow]
    detected_row_size: int


def read_param(blob: bytes) -> Param:
    big = blob[0x2C] == 0xFF
    e = ">" if big else "<"
    f2d, f2e = blob[0x2D], blob[0x2E]

    (strings_offset,) = struct.unpack_from(e + "I", blob, 0x00)
    (row_count,) = struct.unpack_from(e + "H", blob, 0x0A)

    if f2d & FLAG_OFFSET_PARAM_TYPE:
        (pt_off,) = struct.unpack_from(e + "q", blob, 0x10)
        end = blob.find(b"\x00", pt_off)
        param_type = blob[pt_off:end].decode("ascii", "replace")
        rows_at = 0x40
    else:
        param_type = blob[0x0C:0x2C].split(b"\x00")[0].decode("ascii", "replace")
        rows_at = 0x30
        if f2d & FLAG_LONG_DATA_OFFSET:
            rows_at = 0x40

    long_rows = bool(f2d & FLAG_LONG_DATA_OFFSET)
    stride = 24 if long_rows else 12
    unicode_names = bool(f2e & FLAG2_UNICODE_ROW_NAMES)

    entries = []
    p = rows_at
    for _ in range(row_count):
        if long_rows:
            (rid,) = struct.unpack_from(e + "i", blob, p)
            (data_off,) = struct.unpack_from(e + "q", blob, p + 8)
            (name_off,) = struct.unpack_from(e + "q", blob, p + 16)
        else:
            rid, data_off, name_off = struct.unpack_from(e + "iII", blob, p)
        entries.append((rid, data_off, name_off))
        p += stride

    # Row size is inferred from the gap between consecutive rows, exactly as
    # SoulsFormats does — never from the paramdef, so a def/regulation version
    # mismatch shows up as a mismatch instead of silently shifting every field.
    if len(entries) > 1:
        detected = entries[1][1] - entries[0][1]
    elif entries:
        detected = (strings_offset or len(blob)) - entries[0][1]
    else:
        detected = -1

    rows = []
    for rid, data_off, name_off in entries:
        name = ""
        if name_off:
            if unicode_names:
                end = blob.find(b"\x00\x00", name_off)
                while (end - name_off) % 2:
                    end = blob.find(b"\x00\x00", end + 1)
                name = blob[name_off:end].decode("utf-16-le", "replace")
            else:
                end = blob.find(b"\x00", name_off)
                name = blob[name_off:end].decode("shift_jis", "replace")
        rows.append(ParamRow(rid, name, blob[data_off:data_off + max(detected, 0)]))

    return Param(param_type, rows, detected)


def read_cell(row: ParamRow, f: DefField, big: bool = False):
    e = ">" if big else "<"
    if f.type in ("dummy8", "fixstr", "fixstrW"):
        return None
    fmt = _STRUCT[f.type]
    (raw,) = struct.unpack_from(e + fmt, row.data, f.offset)
    if f.bits != -1:
        return (raw >> f.bit_offset) & ((1 << f.bits) - 1)
    return raw


# ==========================================================================
# FMG
# ==========================================================================

def read_fmg(blob: bytes) -> dict[int, str]:
    big = blob[1] != 0
    e = ">" if big else "<"
    version = blob[2]
    wide = version == 2  # DarkSouls3 variant; Sekiro uses it

    (group_count,) = struct.unpack_from(e + "i", blob, 0x0C)
    if wide:
        (str_off_off,) = struct.unpack_from(e + "q", blob, 0x18)
        groups_at, group_stride = 0x28, 16
    else:
        (str_off_off,) = struct.unpack_from(e + "i", blob, 0x14)
        groups_at, group_stride = 0x1C, 12

    out: dict[int, str] = {}
    p = groups_at
    for _ in range(group_count):
        idx, first_id, last_id = struct.unpack_from(e + "iii", blob, p)
        p += group_stride
        for j in range(last_id - first_id + 1):
            o = str_off_off + (idx + j) * (8 if wide else 4)
            if wide:
                (so,) = struct.unpack_from(e + "q", blob, o)
            else:
                (so,) = struct.unpack_from(e + "i", blob, o)
            if so:
                end = blob.find(b"\x00\x00", so)
                while (end - so) % 2:
                    end = blob.find(b"\x00\x00", end + 1)
                out[first_id + j] = blob[so:end].decode("utf-16-le", "replace")
    return out


def load_fmg_bundle(msg_dir: Path, bundle: str) -> dict[str, dict[int, str]]:
    """Return {fmg_name: {id: text}} for every FMG in the named msgbnd set."""
    tables: dict[str, dict[int, str]] = {}
    for fn in FMG_BUNDLES[bundle]:
        p = msg_dir / fn
        if not p.exists():
            continue
        for bf in read_bnd4(p.read_bytes()):
            key = Path(bf.name.replace("\\", "/")).stem or f"fmg_{bf.id}"
            try:
                tables.setdefault(key, {}).update(read_fmg(bf.data))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {fn}:{key} unreadable ({exc})", file=sys.stderr)
    return tables


def pick_name_table(tables: dict[str, dict[int, str]], ids: set[int]) -> tuple[str, dict[int, str]]:
    """Pick the FMG whose ids best cover the param's row ids. Reported, not assumed."""
    best, best_hit = "", -1
    for name, tbl in tables.items():
        if "name" not in name.lower():
            continue
        hit = len(ids & tbl.keys())
        if hit > best_hit:
            best, best_hit = name, hit
    return best, tables.get(best, {})


# ==========================================================================
# Paramdex Names (for the acceptance gate)
# ==========================================================================

def load_paramdex_names(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2 or not parts[0].lstrip("-").isdigit():
            continue
        name = parts[1].split(" -- ")[0].strip()
        if JUNK.search(name):
            continue
        out[int(parts[0])] = name
    return out


# ==========================================================================
# Driver
# ==========================================================================

def find_regulation(game_root: Path) -> Path:
    for cand in ("regulation.bin", "Game/regulation.bin", "sekiro/regulation.bin"):
        p = game_root / cand
        if p.exists():
            return p
    hits = list(game_root.rglob("regulation.bin"))
    if not hits:
        raise FileNotFoundError(f"no regulation.bin under {game_root}")
    return hits[0]


def find_msg_dir(game_root: Path, lang: str) -> Path | None:
    for p in game_root.rglob(f"msg/{lang}"):
        if p.is_dir():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-root", required=True, type=Path)
    ap.add_argument("--paramdex", required=True, type=Path,
                    help="Paramdex checkout root (SDT/ must exist under it)")
    ap.add_argument("--out", default="db_sdt", type=Path)
    ap.add_argument("--report", default=None, type=Path)
    ap.add_argument("--lang", default="engus")
    ap.add_argument("--strict", action="store_true",
                    help="exit 4 if any acceptance gate fails")
    args = ap.parse_args()

    sdt = args.paramdex / "SDT"
    if not (sdt / "Defs").is_dir():
        print(f"error: {sdt}/Defs missing", file=sys.stderr)
        return 2

    reg_path = find_regulation(args.game_root)
    print(f"regulation: {reg_path}")

    try:
        binder = read_bnd4(reg_path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        print(f"error: regulation unreadable: {exc}", file=sys.stderr)
        print("  Sekiro's regulation.bin should be a plain DCX-wrapped BND4 — "
              "if this fails, check whether the repack shipped a modified file.",
              file=sys.stderr)
        return 3

    params: dict[str, bytes] = {}
    for bf in binder:
        stem = Path(bf.name.replace("\\", "/")).stem
        params[stem] = bf.data
    print(f"regulation contains {len(params)} params")

    args.out.mkdir(parents=True, exist_ok=True)
    report: list[str] = ["# SDT extraction report", ""]
    report.append(f"- regulation: `{reg_path}`")
    report.append(f"- params in regulation: {len(params)}")
    report.append("")

    msg_dir = find_msg_dir(args.game_root, args.lang)
    fmg_cache: dict[str, dict[str, dict[int, str]]] = {}
    if msg_dir:
        print(f"msg dir:    {msg_dir}")
        report.append(f"- msg dir: `{msg_dir}`")
    else:
        print(f"warning: no msg/{args.lang} found — falling back to Paramdex names",
              file=sys.stderr)
        report.append(f"- msg dir: **not found** (`msg/{args.lang}`)")
    report.append("")
    report.append("| param | rows | def size | detected size | named ids | resolved | gate |")
    report.append("|---|---|---|---|---|---|---|")

    failures = 0

    for pname, spec in TARGETS.items():
        if pname not in params:
            print(f"  ! {pname}: not present in regulation", file=sys.stderr)
            report.append(f"| {pname} | — | — | — | — | — | **MISSING** |")
            failures += 1
            continue

        def_path = sdt / "Defs" / f"{pname}.xml"
        if not def_path.exists():
            report.append(f"| {pname} | — | — | — | — | — | **NO DEF** |")
            failures += 1
            continue

        pdef = load_paramdef(def_path)
        param = read_param(params[pname])

        # Gate 1 — the paramdef must describe the same row size the regulation
        # actually uses. A mismatch means every field offset is wrong.
        size_ok = (param.detected_row_size == pdef.row_size) or param.detected_row_size < 0

        # Gate 2 — every id Paramdex annotates must exist in the regulation.
        names = load_paramdex_names(sdt / "Names" / f"{pname}.txt")
        ids = {r.id for r in param.rows}
        missing = set(names) - ids
        names_ok = not missing

        # Gate 3 — every field we intend to read must exist in the def.
        want = [f for f in spec["fields"] if f != "__row_id__"]
        absent = [f for f in want if pdef.by_name(f) is None]
        fields_ok = not absent
        if absent:
            print(f"  ! {pname}: def lacks {absent}", file=sys.stderr)

        gate = "ok" if (size_ok and names_ok and fields_ok) else "FAIL"
        if gate == "FAIL":
            failures += 1

        # Display names: shipped English first, Paramdex annotation as fallback.
        fmg_name, fmg_tbl, fmg_src = "", {}, "paramdex"
        if msg_dir and spec["name_fmg"]:
            key, bundle = spec["name_fmg"]
            if bundle not in fmg_cache:
                fmg_cache[bundle] = load_fmg_bundle(msg_dir, bundle)
            lookup_ids = ids if key == "__row_id__" else set()
            if key != "__row_id__":
                fd = pdef.by_name(key)
                if fd:
                    lookup_ids = {read_cell(r, fd) for r in param.rows}
                    lookup_ids.discard(None)
                    lookup_ids.discard(-1)
            fmg_name, fmg_tbl = pick_name_table(fmg_cache[bundle], lookup_ids)
            if fmg_tbl:
                fmg_src = f"fmg:{fmg_name}"

        cols = ["id", "name", "name_source"] + want
        lines = ["\t".join(cols)]
        resolved = 0
        for r in param.rows:
            disp, src = "", ""
            if spec["name_fmg"]:
                key, _ = spec["name_fmg"]
                if key == "__row_id__":
                    disp = fmg_tbl.get(r.id, "")
                else:
                    fd = pdef.by_name(key)
                    if fd:
                        disp = fmg_tbl.get(read_cell(r, fd), "")
                src = fmg_src if disp else ""
            if not disp:
                disp = names.get(r.id, "")
                src = "paramdex" if disp else "unnamed"
            if disp and not JUNK.search(disp):
                resolved += 1
            else:
                disp = disp or ""
            vals = []
            for fn in want:
                fd = pdef.by_name(fn)
                v = read_cell(r, fd) if fd else None
                vals.append("" if v is None else str(v))
            lines.append("\t".join([str(r.id), disp, src] + vals))

        (args.out / spec["out"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  {pname:22s} -> {spec['out']:16s} "
              f"{len(param.rows):5d} rows  {resolved:5d} named  [{gate}]")

        report.append(
            f"| {pname} | {len(param.rows)} | {pdef.row_size} | "
            f"{param.detected_row_size} | {len(names)} | {resolved} | {gate} |"
        )
        if missing:
            report.append(f"|  ↳ ids in Paramdex but not in regulation: "
                          f"{sorted(missing)[:12]}{'…' if len(missing) > 12 else ''} ||||||")

    report.append("")
    report.append(f"**{failures} gate failure(s).**")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report) + "\n", encoding="utf-8")
        print(f"report: {args.report}")

    if failures and args.strict:
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
