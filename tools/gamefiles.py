#!/usr/bin/env python3
"""
gamefiles.py — read a FromSoftware install directly: archives, maps, event scripts.

WHAT THIS IS FOR
    Every id table in `db_*/` was transcribed from a community source. That was the only
    option while the games' own files were sealed, and it costs accuracy: a randomizer's
    enemy list can be missing five entries and mislabel fourteen more, and nothing in a
    save can tell you so. This reads the installed game instead — the same four steps a
    modding tool takes, in one place, with no Windows dependency:

        unpack   open the `.bhd`/`.bdt` archives and extract files by path
        msb      read a map layout: every enemy placement, its entity id and model
        emevd    read the event scripts: instruction by instruction, arguments unpacked
        roster   the payoff — check db_sdt/minibosses.json against the scripts themselves

    It is a READER. It never writes into a game folder, never patches an executable, and
    the one subcommand that can write a `db_*` table only does so when asked (`--write`).

WHY ONE FILE
    These began as four throwaway scripts, and four scripts is how the BHD5 reader gets
    copied three times and then fixed once. The formats are shared — a `.msb` and an
    `.emevd` both come out of a `.bhd`, and both are DCX-wrapped — so the code is too.

WHAT COMES FROM WHERE — none of the layouts here are invented
  * Archive container, DCX, MSB and EMEVD layouts: `JKAnderson/SoulsFormats`
    (`Formats/BHD5.cs`, `Formats/DCX.cs`, `Formats/MSB/MSBS/*`, `Formats/EMEVD/*`).
  * The RSA step: `Nordgaren/UXM-Selective-Unpack` `CryptographyUtility.DecryptRsa` —
    raw RSA, no padding, 256-byte blocks in and 255-byte blocks out, left-zero-padded.
  * The filename hash: `SFUtil.FromPathHash` — lowercase, backslashes to slashes, a
    leading slash, then `h = h * 37 + c` over a uint32.
  * Instruction names and argument types: `AinTunez/DarkScript3`'s
    `sekiro-common.emedf.json`. Only the handful of instructions this file names are
    hardcoded (@ref LAYOUTS), so no EMEDF file is needed at run time.
  * Keys and name dictionaries: UXM's `ArchiveKeys.cs` and `res/<game>Dictionary.txt`.
    NEITHER IS VENDORED HERE — pass them in. Dark Souls II needs neither: it ships its
    own `*KeyCode.pem` beside each archive.
  * BND4 and FMG parsing is imported from `gen_sdt_from_regulation.py` rather than
    written twice.

THE TWO TRAPS, BOTH FOUND THE HARD WAY
  * **FromSoft's Oodle streams decode ONE 256 KiB CHUNK AT A TIME, each against its own
    window.** Hand a Kraken decoder the whole stream and chunk 1 comes out perfect and
    chunk 2 fails — in `powzix/ooz` and in the unrelated Rust `oozextract` alike. See
    @ref ooz_decompress_chunked.
  * **A boss/miniboss handler is usually PARAMETERISED.** Its own instruction args are
    zeroes; the real values arrive through `2000[6] Initialize Common Event`. Scan only
    the inline calls and Sekiro reports one miniboss instead of thirty-seven.

ELDEN RING: WHAT IS WIRED AND WHAT IS NOT
    Target is **Shadow of the Erdtree Deluxe, v1.16.1**. No install on this machine yet, so
    everything ER here is written from UXM's key list and SoulsFormats' `Game.EldenRing` and
    is **UNTESTED** — treat the first run as a measurement, not a formality.

      * `unpack --game er` — ready. Archives `Data0..Data3` + `DLC`; keys `EldenRingKeys`;
        dictionary `EldenRingDictionary.txt` (9 MB, so expect the index step to be slower
        than Sekiro's).
      * **Two ER-only differences are already handled, and both fail SILENTLY if missed.**
        The filename hash widened to **uint64 with multiplier 0x85** (@ref HASH_PRIME), and
        the archive entry keeps DS3's 40-byte stride while laying its fields out differently
        — 64-bit hash, then two 32-bit sizes (@ref parse_bhd5). Either one wrong produces an
        archive that simply contains nothing you asked for.
      * `DCX/ZSTD` is handled as well as `KRAK`, because ER's later patches use it.
      * `regulation.bin` is loose at the install root and is ER-encrypted; nothing here
        decrypts it, and nothing needs to — `db_er/`'s names come from Paramdex.
      * **`msb` will NOT read ER maps.** ER is `MSBE`, whose part struct differs from
        Sekiro's `MSBS`; the reader asserts rather than guesses (@ref read_msb).
      * **`roster` is Sekiro-specific and stays that way.** The instruction ids in
        @ref LAYOUTS are Sekiro's. ER's own convention is already known from the flag
        research — defeat flag == entity id for 156 of 176 bosses — so the ER equivalent is
        an ER EMEDF plus its `Handle Boss Defeat` id, not new machinery.
      * `emevd` may work as-is: ER is expected to be the same version `0xCD` container as
        Sekiro. If the header check rejects it, the flags it prints are the thing to look at
        first — do not widen the check without knowing which permutation it is.

    The real ER blocker is elsewhere and this tool does not touch it: the SAVE-side flag
    region is still unsolved, so ER ids remain unreadable however many of them get extracted.

THE OODLE DEPENDENCY
    Sekiro and later compress with Oodle Kraken, which has no pure-Python decoder. Build
    `powzix/ooz` as a shared object once:

        git clone --depth 1 https://github.com/powzix/ooz && cd ooz
        head -4286 kraken.cpp > kraken_lib.cpp
        printf '\\nextern "C" int ooz_decompress(const byte *s, size_t sl, byte *d, size_t dl)'\\
               '{ return Kraken_Decompress(s, sl, d, dl); }\\n' >> kraken_lib.cpp
        # plus a compat/ shim supplying tchar.h, intrin.h and Windows.h on Linux
        g++ -O2 -DNDEBUG -fPIC -shared -Icompat kraken_lib.cpp bitknit.cpp lzna.cpp \\
            -o libooz.so

    Point `--ooz` (or `$SL2_OOZ_LIB`) at the result. Games that use Deflate — Dark Souls
    II, Dark Souls III, Dark Souls Remastered — need none of this.

USAGE
    python3 tools/gamefiles.py unpack --game sekiro --game-root ~/Games/Sekiro \\
        --keys ArchiveKeys.cs --dict SekiroDictionary.txt --out ~/Games/Sekiro-unpacked \\
        --prefix /event/ --prefix /param/ --prefix /msg/engus/ --prefix /map/mapstudio/
    python3 tools/gamefiles.py msb    <unpacked>/map/mapstudio --entity 1120450
    python3 tools/gamefiles.py emevd  <unpacked>/event --instr 2003:87
    python3 tools/gamefiles.py roster <unpacked>/event --msg <unpacked>/msg/engus \\
        [--maps <unpacked>/map/mapstudio] [--paramdex <Paramdex>] [--write db_sdt/minibosses.json]

EXIT CODES
    0 ok · 2 bad input/paths · 3 parse failure
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_sdt_from_regulation as fs  # noqa: E402  (BND4 + FMG readers, written once)

BASE = Path(__file__).resolve().parent.parent

# ==========================================================================
# Archives
# ==========================================================================

##
# @brief Per-game archive layout: which pairs exist, whose keys open them, which BHD5 shape.
# @details `keys` names the dictionary inside UXM's `ArchiveKeys.cs`, or None for a game that
# ships its own key file — DS2 puts `GameDataKeyCode.pem` next to `GameDataEbl.bhd`, so
# nothing external is needed there. `bhd5` picks the entry stride. Sekiro having no `Data0`
# is a fact about Sekiro, not a gap in this table.
GAMES = {
    "sekiro": {"archives": ["Data1", "Data2", "Data3", "Data4", "Data5"],
               "keys": "SekiroKeys", "bhd5": "ds3", "dict": "SekiroDictionary.txt"},
    "ds3": {"archives": ["Data0", "Data1", "Data2", "Data3", "Data4", "Data5",
                         "DLC1", "DLC2"],
            "keys": "DarkSouls3Keys", "bhd5": "ds3", "dict": "DarkSouls3Dictionary.txt"},
    "ds2": {"archives": ["GameDataEbl", "LqChrEbl", "HqChrEbl", "LqMapEbl", "HqMapEbl",
                         "LqObjEbl", "HqObjEbl", "LqPartsEbl", "HqPartsEbl"],
            "keys": None, "bhd5": "ds2", "dict": "ScholarDictionary.txt"},
    # Elden Ring, including Shadow of the Erdtree: `DLC.bhd/.bdt` is the DLC pair and UXM
    # publishes its key alongside the four base ones. `sd/` (sound) is deliberately absent —
    # nothing here wants it and no key for it is published. UNTESTED: written from UXM's
    # key list and SoulsFormats' `Game.EldenRing`, with no install on this machine yet.
    "er": {"archives": ["Data0", "Data1", "Data2", "Data3", "DLC"],
           "keys": "EldenRingKeys", "bhd5": "er", "dict": "EldenRingDictionary.txt"},
}

##
# @brief The filename hash, per era. Same rolling shape, different width and multiplier.
# @details Through Sekiro it is `SFUtil.FromPathHash`: uint32, multiplier 37. **Elden Ring
# widened it to uint64 with multiplier 0x85 (133)** — UXM's `ArchiveDictionary.ComputeHash`
# switches on `game >= EldenRing`. Using the old one against an ER archive finds nothing at
# all, which reads as a bad dictionary rather than as a wrong hash.
HASH_PRIME = {"ds2": (37, 32), "ds3": (37, 32), "er": (0x85, 64)}
## @brief AES block size, and so the granularity an encrypted range can be decrypted at.
AES_BLOCK = 16

KEY_HELP = """the RSA keys and the name dictionary are not vendored. Fetch them:

  curl -sSLO https://raw.githubusercontent.com/Nordgaren/UXM-Selective-Unpack/master/UXM/ArchiveKeys.cs
  curl -sSLO https://raw.githubusercontent.com/Nordgaren/UXM-Selective-Unpack/master/UXM/res/SekiroDictionary.txt

Dark Souls II needs only the dictionary: its keys ship in the install as *KeyCode.pem.
"""


##
# @brief One game's public keys out of UXM's `ArchiveKeys.cs`.
# @details A C# source file rather than anything structured, so this is a text scrape: the
# named dictionary, then each `["DataN"] = @"...PEM..."` inside it. Scoping to one
# dictionary body matters — the same file carries DS3's, Sekiro's, Elden Ring's and AC6's,
# and the wrong game's key fails as plausible garbage rather than as an error.
#
# No completeness check on purpose: UXM publishes no key for DS3's `Data0` because that
# header is not encrypted, so an archive missing here is a fact, not a failure.
# @param path `ArchiveKeys.cs`. @param dict_name e.g. `SekiroKeys`.
# @return @c {archive name: PEM text}.
def load_keys(path: Path, dict_name: str) -> dict[str, str]:
    src = Path(path).read_text(encoding="utf-8-sig")
    body = re.search(
        dict_name + r"\s*=\s*new\s+Dictionary<string,\s*string>\s*\{(.*?)\n\s*\};", src, re.S)
    if not body:
        sys.exit(f"no {dict_name} dictionary in {path}")
    return dict(re.findall(r'\["([A-Za-z0-9_]+)"\]\s*=\s*@"(.*?)"', body.group(1), re.S))


##
# @brief Decrypt a `.bhd` with a PKCS#1 public key.
# @details Raw RSA, deliberately: UXM runs BouncyCastle's `RsaEngine` with no padding
# scheme, so every 256-byte ciphertext block becomes a 255-byte plaintext block — the
# engine's own input and output block sizes for a 2048-bit modulus. The left-zero pad is
# not cosmetic: a block whose plaintext happens to start with a zero byte would otherwise
# shift the whole rest of the header.
def rsa_decrypt(data: bytes, pem: str) -> bytes:
    from cryptography.hazmat.primitives import serialization

    pub = serialization.load_pem_public_key(pem.encode())
    n, e = pub.public_numbers().n, pub.public_numbers().e
    in_size = (n.bit_length() + 7) // 8
    out_size = (n.bit_length() - 1) // 8
    out = bytearray()
    for i in range(0, len(data), in_size):
        block = data[i:i + in_size]
        if len(block) < in_size:
            break
        out += pow(int.from_bytes(block, "big"), e, n).to_bytes(out_size, "big")
    return bytes(out)


## @brief A little-endian struct reader that exits rather than reading past its buffer.
class Reader:
    def __init__(self, buf: bytes, pos: int = 0):
        self.buf, self.pos = buf, pos

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            sys.exit(f"header truncated at 0x{self.pos:X} (+{n})")
        v = self.buf[self.pos:self.pos + n]
        self.pos += n
        return v

    def u8(self) -> int:
        return self.take(1)[0]

    def i32(self) -> int:
        return int.from_bytes(self.take(4), "little", signed=True)

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def i64(self) -> int:
        return int.from_bytes(self.take(8), "little", signed=True)

    def ascii(self, n: int) -> str:
        return self.take(n).decode("ascii", "replace")

    def expect(self, want: str) -> None:
        got = self.ascii(len(want))
        if got != want:
            sys.exit(f"expected {want!r} at 0x{self.pos - len(want):X}, got {got!r}")


##
# @brief Parse a decrypted BHD5 header into @c {file name hash: entry}.
# @details `Game.DarkSouls3` shape is a 32-bit name hash, a padded size, a 64-bit offset,
# the SHA and AES side-table offsets, then the unpadded size. **DS2 stops before that last
# field**, so its entries are 32 bytes and not 40 — read a DS2 header on the DS3 stride and
# it does not error, it walks off by eight bytes per entry and reports an empty archive,
# which is exactly what a wrong key looks like.
def parse_bhd5(buf: bytes, variant: str = "ds3") -> dict[int, dict]:
    r = Reader(buf)
    r.expect("BHD5")
    if r.u8() == 0:
        sys.exit("big-endian BHD5; the PC games' are little-endian")
    r.u8()                                   # Unk05, "crypto allowed?" per SoulsFormats
    r.u8(), r.u8()
    if r.i32() != 1:
        sys.exit("BHD5 version word is not 1")
    r.i32()                                  # file size, unused: the buffer is the size
    bucket_count, buckets_offset = r.i32(), r.i32()
    r.ascii(r.i32())                         # salt; only the SHA side-table needs it

    # Three entry shapes, all 32 or 40 bytes, and the difference is not cosmetic:
    #   ds2  hash(u32) padded(i32) offset(i64) sha(i64) aes(i64)                     = 32
    #   ds3  the same, then unpadded(i64)                                            = 40
    #   er   hash(U64) padded(i32) UNPADDED(i32) offset(i64) sha(i64) aes(i64)       = 40
    # Elden Ring widened the hash to 64 bits and shrank both sizes to 32, so it is the same
    # length as DS3's and lays out differently — read one as the other and every offset is
    # garbage while nothing errors.
    stride = 32 if variant == "ds2" else 40
    out: dict[int, dict] = {}
    for b in range(bucket_count):
        r.pos = buckets_offset + b * 8
        count, offset = r.i32(), r.i32()
        for i in range(count):
            e = Reader(buf, offset + i * stride)
            if variant == "er":
                entry = {"hash": int.from_bytes(e.take(8), "little"),
                         "padded": e.i32(), "unpadded": e.i32(), "offset": e.i64()}
            else:
                entry = {"hash": e.u32(), "padded": e.i32(), "offset": e.i64()}
            e.i64()                          # SHA side table, not verified here
            aes_off = e.i64()
            if variant == "ds3":
                entry["unpadded"] = e.i64()
            entry.setdefault("unpadded", 0)
            entry["aes"] = read_aes_key(buf, aes_off) if aes_off else None
            out[entry["hash"]] = entry
    return out


##
# @brief The per-file AES key and the ranges it covers, or None where there is none.
# @details Most entries carry no key at all, and the ones that do encrypt only slices — so
# the ranges have to be honoured rather than decrypting the whole file. A `-1..-1` range is
# the unused-slot marker SoulsFormats filters out.
def read_aes_key(buf: bytes, off: int) -> dict:
    r = Reader(buf, off)
    key = r.take(AES_BLOCK)
    ranges = []
    for _ in range(r.i32()):
        start, end = r.i64(), r.i64()
        if start != -1 and end != -1 and start != end:
            ranges.append((start, end))
    return {"key": bytes(key), "ranges": ranges}


##
# @brief `SFUtil.FromPathHash`: the only way to find a file whose name was thrown away.
# @details The archives store no names. Knowing the path is enough — but only exactly: case
# and the leading slash both feed the hash, so `/Event/x`, `/event/x` and `event/x` are
# three different numbers and two of them are in no archive.
def path_hash(path: str, variant: str = "ds3") -> int:
    s = path.lower().replace("\\", "/")
    if not s.startswith("/"):
        s = "/" + s
    prime, width = HASH_PRIME[variant]
    mask = (1 << width) - 1
    h = 0
    for c in s:
        h = (h * prime + ord(c)) & mask
    return h


##
# @brief Read one entry out of a `.bdt`, decrypting the ranges its header marks.
# @details The read is padded-size, and the entry's own unpadded size is only trusted when
# POSITIVE: Sekiro writes 0 there on every entry checked, so honouring it blindly truncates
# every file to nothing. The real length comes from the DCX header, which is verified
# anyway. Ranges are clamped to whole AES blocks for the same reason the read is padded.
def read_entry(bdt, entry: dict) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    bdt.seek(entry["offset"])
    data = bytearray(bdt.read(entry["padded"]))
    aes = entry["aes"]
    if aes:
        cipher = Cipher(algorithms.AES(aes["key"]), modes.ECB())
        for start, end in aes["ranges"]:
            end = min(end, len(data))
            span = (end - start) // AES_BLOCK * AES_BLOCK
            if span <= 0:
                continue
            dec = cipher.decryptor()
            data[start:start + span] = dec.update(bytes(data[start:start + span])) \
                + dec.finalize()
    if 0 < entry["unpadded"] < len(data):
        del data[entry["unpadded"]:]
    return bytes(data)


# ==========================================================================
# DCX, and Oodle
# ==========================================================================

## @brief Oodle's block length. Every chunk past the first starts a fresh match window.
OODLE_BLOCK = 0x40000
##
# @brief Slack on the Kraken output buffer.
# @details ooz's decoder writes in quantums and can overshoot the exact declared size while
# finishing the last one. Sizing to the declared length alone corrupts the heap.
OOZ_SLACK = 0x10000
_OOZ = None


## @brief Where to find the Kraken decoder. See the module docstring for the build recipe.
def ooz_paths(explicit: str | None) -> list[Path]:
    out = [Path(explicit)] if explicit else []
    if os.environ.get("SL2_OOZ_LIB"):
        out.append(Path(os.environ["SL2_OOZ_LIB"]))
    return out + [BASE / "scratch" / "libooz.so", BASE / "libooz.so", Path("libooz.so")]


## @brief Load `libooz.so` once, from the first candidate path that exists.
def ooz_load(explicit: str | None = None):
    global _OOZ
    if _OOZ is None:
        for cand in ooz_paths(explicit):
            if cand.is_file():
                _OOZ = ctypes.CDLL(str(cand))
                _OOZ.ooz_decompress.restype = ctypes.c_int
                _OOZ.ooz_decompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                                ctypes.c_char_p, ctypes.c_size_t]
                break
        else:
            sys.exit("no libooz.so found — build it (see this file's docstring) and pass "
                     "--ooz, or set SL2_OOZ_LIB")
    return _OOZ


def ooz_decompress(src: bytes, dst_len: int) -> bytes:
    lib = ooz_load()
    dst = ctypes.create_string_buffer(dst_len + OOZ_SLACK)
    n = lib.ooz_decompress(src, len(src), dst, dst_len)
    if n < 0:
        sys.exit("ooz_decompress failed")
    return dst.raw[:n]


##
# @brief Kraken decode a stream FROM's way: one 256 KiB chunk at a time.
# @details THE SINGLE MOST EXPENSIVE THING IN THIS FILE TO LEARN. Handing the whole stream
# to a Kraken decoder decodes chunk 1 and then fails on chunk 2, in `powzix/ooz` AND in the
# unrelated Rust `oozextract` — two independent implementations, the same failure, which is
# what ruled out the decoders; `libooz` decoding ooz's own 21-chunk `xml.kraken` vector
# cleanly ruled out the build. The difference is the WINDOW: FromSoft compresses each chunk
# against its own base, and a whole-stream decode hands chunk 2 the buffer's start instead.
# Decode chunk by chunk and every file decodes.
#
# The framing has to be walked to do that, since a chunk's compressed size is only in its
# own header: two bytes of block header (magic nibble `0xC`, then decoder type and a
# checksum flag), a three-byte quantum header holding `size - 1` in its low 18 bits, then
# three more bytes of checksum if the flag is set. An `uncompressed` block carries raw bytes
# instead, and a zero compressed size is a memset/whole-match chunk with no payload at all.
def ooz_decompress_chunked(src: bytes, dst_len: int) -> bytes:
    out, pos = bytearray(), 0
    while len(out) < dst_len:
        want = min(OODLE_BLOCK, dst_len - len(out))
        if pos + 2 > len(src):
            sys.exit(f"KRAK stream ended early at chunk offset {pos}")
        b0, b1 = src[pos], src[pos + 1]
        if b0 & 0x0F != 0x0C:
            sys.exit(f"not an Oodle block header at {pos}: 0x{b0:02X}")
        frame = 2
        if b0 & 0x40:                                    # uncompressed block
            frame += want
        else:
            v = int.from_bytes(src[pos + 2:pos + 5], "big")
            frame += 3 + (3 if b1 & 0x80 else 0)
            size = v & 0x3FFFF
            frame += 0 if size == 0x3FFFF else size + 1
        out += ooz_decompress(src[pos:pos + frame], want)
        pos += frame
    if pos != len(src):
        sys.exit(f"KRAK stream has {len(src) - pos} trailing byte(s)")
    return bytes(out)


##
# @brief Undo a `DCX\0` wrapper, KRAK or DFLT. Returns the input unchanged if it is not one.
# @details The header is BIG-endian inside a format whose every other number is little,
# which is the one thing here that produces nonsense rather than an error. The declared
# uncompressed size is checked against what came out, so a wrong decoder fails loudly
# instead of writing a plausible short file.
def dcx_decompress(data: bytes) -> bytes:
    if data[:4] != b"DCX\0":
        return data
    fmt = data[0x28:0x2C]
    uncompressed = int.from_bytes(data[0x1C:0x20], "big")
    compressed = int.from_bytes(data[0x20:0x24], "big")
    # DCA\0 then its own length: the payload starts after that, and the length is read
    # rather than assumed because the DCX permutations differ in header size.
    dca = data.index(b"DCA\0")
    body = data[dca + int.from_bytes(data[dca + 4:dca + 8], "big"):][:compressed]
    if fmt == b"KRAK":
        out = ooz_decompress_chunked(body, uncompressed)
    elif fmt == b"DFLT":
        out = zlib.decompress(body)
    elif fmt == b"ZSTD":
        # Elden Ring's later patches use Zstandard for some files, so it is handled here
        # rather than discovered at the worst moment. Plain frame, no chunking: this one is
        # nothing like KRAK.
        try:
            import zstandard
        except ImportError:
            sys.exit("this file is DCX/ZSTD — pip install zstandard")
        out = zstandard.ZstdDecompressor().decompress(body, max_output_size=uncompressed)
    else:
        sys.exit(f"unsupported DCX compression {fmt!r}")
    if len(out) != uncompressed:
        sys.exit(f"DCX size mismatch: {len(out)} out, {uncompressed} declared")
    return out


# ==========================================================================
# MSB — map layouts
# ==========================================================================

## @brief Section names, from `MSBS.cs`. Only the two a placement needs are named.
MODEL_SECTION, PARTS_SECTION = "MODEL_PARAM_ST", "PARTS_PARAM_ST"

##
# @brief Part type ids from `PartsParam.PartType`.
# @details Both enemy types matter: `DummyEnemy` placements are cutscene or unused copies
# and they still carry entity ids, so filtering on "has an id" does not separate them.
PART_ENEMY, PART_DUMMY_ENEMY = 2, 10
PART_NAMES = {0: "MapPiece", 1: "Object", 2: "Enemy", 4: "Player", 5: "Collision",
              9: "DummyObject", 10: "DummyEnemy", 11: "ConnectCollision"}

## @brief Offsets inside a Part's base struct, and inside an enemy's type data.
P_NAME_OFF, P_TYPE, P_MODEL_INDEX = 0x00, 0x08, 0x10
P_ENTITY_DATA_OFF, P_TYPE_DATA_OFF = 0x60, 0x68
E_THINK_PARAM, E_NPC_PARAM, E_CHARA_INIT = 0x08, 0x0C, 0x18
E_EVENT_FLAG, E_EVENT_FLAG_STATE = 0x40, 0x44


def _i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _i64(b: bytes, o: int) -> int:
    return struct.unpack_from("<q", b, o)[0]


## @brief A NUL-terminated UTF-16LE string at @p off.
def _utf16(b: bytes, off: int) -> str:
    end = off
    while end + 1 < len(b) and b[end:end + 2] != b"\0\0":
        end += 2
    return b[off:end].decode("utf-16-le", "replace")


##
# @brief Every section of an MSB as @c {name: [entry offsets]}.
# @details Walks the chain by each section's own `nextParamOffset`, which is what makes this
# robust: the section ORDER is a fact about the game version, the chain is a fact about the
# file.
def msb_sections(buf: bytes) -> dict[str, list[int]]:
    if buf[:4] != b"MSB ":
        sys.exit("not an MSB")
    out, pos = {}, 0x10
    while pos:
        count = _i32(buf, pos + 4)
        name_off = _i64(buf, pos + 8)
        entries = [_i64(buf, pos + 16 + i * 8) for i in range(count - 1)]
        nxt = _i64(buf, pos + 16 + (count - 1) * 8)
        out[_utf16(buf, name_off)] = entries
        pos = nxt
    return out


##
# @brief Byte offset of one section's header, for reading its version word.
# @details Walks the same chain `msb_sections` does. Kept separate rather than folded into
# that function's return shape, because every other caller wants the entry list and nothing
# else, and the version is only consulted to refuse a layout this reader does not know.
def msb_section_pos(buf: bytes, name: str) -> int:
    pos = 0x10
    while pos:
        count = _i32(buf, pos + 4)
        if _utf16(buf, _i64(buf, pos + 8)) == name:
            return pos
        pos = _i64(buf, pos + 16 + (count - 1) * 8)
    sys.exit(f"no {name} section")


## @brief Model names in index order, so a part's `ModelIndex` resolves to `c1470_0000`.
def msb_models(buf: bytes, offsets: list[int]) -> list[str]:
    return [_utf16(buf, off + _i64(buf, off + P_NAME_OFF)) for off in offsets]


##
# @brief Every part in one MSB as a dict, enemies carrying their param joins.
# @details The entity id is read for every part type, because objects carry them too. The
# NPC and think ids exist only on the enemy types and are None elsewhere, rather than a
# misread of some other struct's bytes.
def msb_parts(buf: bytes, offsets: list[int], models: list[str]) -> list[dict]:
    out = []
    for off in offsets:
        kind = _u32(buf, off + P_TYPE)
        mi = _i32(buf, off + P_MODEL_INDEX)
        row = {
            "name": _utf16(buf, off + _i64(buf, off + P_NAME_OFF)),
            "type": kind, "type_name": PART_NAMES.get(kind, str(kind)),
            "model": models[mi] if 0 <= mi < len(models) else None,
            "entity_id": _i32(buf, off + _i64(buf, off + P_ENTITY_DATA_OFF)),
            "npc_param": None, "think_param": None, "chara_init": None,
            "event_flag": None, "event_flag_state": None,
        }
        if kind in (PART_ENEMY, PART_DUMMY_ENEMY):
            t = off + _i64(buf, off + P_TYPE_DATA_OFF)
            row.update(npc_param=_i32(buf, t + E_NPC_PARAM),
                       think_param=_i32(buf, t + E_THINK_PARAM),
                       chara_init=_i32(buf, t + E_CHARA_INIT),
                       event_flag=_i32(buf, t + E_EVENT_FLAG),
                       event_flag_state=_i32(buf, t + E_EVENT_FLAG_STATE))
        out.append(row)
    return out


##
# @brief Parse one `.msb` into @c (map name, [part rows]). SEKIRO's `MSBS` layout only.
# @details Elden Ring's `MSBE` shares the section names and the chain, and its Part base
# struct is NOT the same — extra offsets before the type data. So an ER map would walk this
# reader without erroring and report entity ids read out of the wrong words. The version
# word is what separates them, and it is asserted rather than assumed: a file this reader
# does not know is refused, because a wrong entity id here becomes a wrong flag downstream.
def read_msb(path: Path) -> tuple[str, list[dict]] | None:
    buf = Path(path).read_bytes()
    sec = msb_sections(buf)
    for want in (MODEL_SECTION, PARTS_SECTION):
        if want not in sec:
            sys.exit(f"{path}: no {want} (sections: {', '.join(sec)})")
    # The section's own version word, not the file header — the header is identical across
    # MSBS and MSBE. Sekiro's real maps read 0x23 and its tiny `m89` test map reads 0x21;
    # Elden Ring's is higher, and this reader refuses it rather than reporting entity ids
    # taken from the wrong words.
    parts_version = _i32(buf, msb_section_pos(buf, PARTS_SECTION))
    if parts_version not in MSBS_PARTS_VERSIONS:
        return None
    return (Path(path).name.replace(".msb", ""),
            msb_parts(buf, sec[PARTS_SECTION], msb_models(buf, sec[MODEL_SECTION])))


## @brief `PARTS_PARAM_ST` versions this reader's part struct is known to match (Sekiro).
MSBS_PARTS_VERSIONS = {0x21, 0x23}


## @brief Every `.msb` under a directory, parsed, in map order; unknown layouts skipped.
def read_msbs(root: str) -> list[tuple[str, list[dict]]]:
    p = Path(root)
    paths = [p] if p.is_file() else sorted(p.glob("*.msb"))
    out = []
    for f in paths:
        got = read_msb(f)
        if got is None:
            print(f"  ! {f.name}: not a Sekiro MSBS part layout (Elden Ring's MSBE is not "
                  f"implemented), skipped", file=sys.stderr)
            continue
        out.append(got)
    return out


##
# @brief The map file an entity id belongs to, by the same decomposition the flags use.
# @details A Sekiro entity id is `AAB nnnn` — area, sub-area, placement — so `1120450` is
# `m11_02`. That identical decomposition is the whole reason a defeat flag and an entity id
# can be the same number.
def entity_map(eid: int) -> str:
    return f"m{eid // 100000 % 100:02d}_{eid // 10000 % 10:02d}"


# ==========================================================================
# EMEVD — event scripts
# ==========================================================================

## @brief The instructions that define a roster, and what each contributes.
MINIBOSS_BAR, MINIBOSS_DEFEAT = (2003, 87), (2003, 15)
BOSS_BAR, BOSS_DEFEAT, BOSS_BANNER = (2003, 11), (2003, 12), (2003, 74)
AWARD_ITEM_LOT = (2003, 4)
## @brief `Initialize Common Event` — how a parameterised handler gets its real arguments.
INIT_COMMON_EVENT = (2000, 6)

## @brief EMEDF numeric type code -> (struct format, size).
ARG_TYPES = {0: ("B", 1), 1: ("H", 2), 2: ("I", 4), 3: ("b", 1), 4: ("h", 2),
             5: ("i", 4), 6: ("f", 4)}

## @brief Argument layouts for the instructions this file reads, from the EMEDF.
LAYOUTS = {
    MINIBOSS_BAR: [3, 5, 4, 5],     # enabled, entity, slot, name id
    BOSS_BAR: [3, 5, 4, 5],
    MINIBOSS_DEFEAT: [5],           # entity
    BOSS_DEFEAT: [5],
    BOSS_BANNER: [5, 0],            # entity, banner type
    AWARD_ITEM_LOT: [5],            # item lot id
}

##
# @brief The Dark Souls III `common_func` templates that flag a one-time enemy death.
# @details Each takes a death flag and an entity id (some take more). Reading these out of
# an install is how `db_ds3/enemies.json` was confirmed: 125 of the 130 flags they carry
# land on a byte and bit that table already has, and none contradict it.
DS3_DEATH_TEMPLATES = (20005340, 20005341, 20005342, 20000343, 20005416, 20005061, 20005760)


##
# @brief Unpack one instruction's argument blob against a type list.
# @details Each field is aligned to `min(its size, 4)` before it is read — FromSoft's own
# packing, and the thing that silently shifts every later argument if you skip it. A blob
# shorter than the layout demands returns None rather than a wrong number.
def unpack_args(data: bytes, types: list[int]) -> list | None:
    out, pos = [], 0
    for t in types:
        fmt, size = ARG_TYPES[t]
        pos += (-pos) % min(size, 4)
        if pos + size > len(data):
            return None
        out.append(struct.unpack_from("<" + fmt, data, pos)[0])
        pos += size
    return out


##
# @brief `Initialize Common Event`'s variadic arguments: the event id, then its parameters.
# @details The EMEDF entry is `[Event ID, Parameters]` with `Parameters` repeating, so the
# blob is a plain run of u32 with no alignment to honour.
def common_init_args(data: bytes) -> list[int] | None:
    if len(data) < 4 or len(data) % 4:
        return None
    return list(struct.unpack_from(f"<{len(data) // 4}I", data, 0))


##
# @brief Every instruction in one `.emevd` as @c (event id, bank, instruction id, argdata),
#        or None if the file is not the DS3/Sekiro shape.
# @details Sekiro sets `unk07` and DS3 does not; both are version `0xCD` with the same
# tables, so both are read. An older permutation is SKIPPED rather than guessed at — DS3
# ships eight stray `m20_*`/`m21_00`/`m29_*` scripts in the Bloodborne shape (version
# `0xCC`, no unicode flag) whose varint width differs, and parsing those on this layout
# would invent events.
def read_emevd(path: Path) -> list[tuple[int, int, int, bytes]] | None:
    buf = Path(path).read_bytes()
    if buf[:4] != b"EVD\0":
        sys.exit(f"{path}: not an EMEVD")
    if buf[4] != 0 or buf[5] != 0xFF or buf[6] != 1 or buf[7] not in (0, 0xFF) \
            or _i32(buf, 8) != 0xCD:
        return None

    v = [_i64(buf, 0x10 + i * 8) for i in range(16)]
    event_count, events_off, instrs_off, args_off = v[0], v[1], v[3], v[13]

    out = []
    for e in range(event_count):
        base = events_off + e * 48
        eid, n, ioff = _i64(buf, base), _i64(buf, base + 8), _i64(buf, base + 16)
        for i in range(n):
            ib = instrs_off + ioff + i * 32
            alen, aoff = _i64(buf, ib + 8), _i64(buf, ib + 16)
            data = buf[args_off + aoff:args_off + aoff + alen] if alen > 0 else b""
            out.append((eid, _i32(buf, ib), _i32(buf, ib + 4), data))
    return out


## @brief Every `.emevd` under a directory, as @c {map name: [instructions]}.
def read_emevds(root: str) -> dict[str, list]:
    p = Path(root)
    paths = [p] if p.is_file() else sorted(p.glob("*.emevd"))
    out = {}
    for f in paths:
        got = read_emevd(f)
        if got is None:
            print(f"  ! {f.name}: not a DS3/Sekiro EMEVD, skipped", file=sys.stderr)
            continue
        out[f.name.replace(".emevd", "")] = got
    return out


##
# @brief Every boss/miniboss call in the scripts, as @c (map, event, kind, entity, name id).
# @details TWO MECHANISMS, and missing the second is why a first pass finds ONE miniboss in
# the whole of Sekiro. Bosses are handled inline, so their entity id is a literal in the
# instruction. Minibosses go through a single PARAMETERISED event in `common_func` whose own
# copy of `Display Miniboss Health Bar` has zeroes where the entity and name belong; the
# real values arrive per placement through `Initialize Common Event`.
#
# The handler set is DISCOVERED, not hardcoded — any common event carrying one of the five
# instructions counts — so a patch adding a second handler cannot silently halve the roster.
# In Sekiro 1.06 there is exactly one, `20005330`, called 41 times with
# `(entity, name id, 0, kind)`.
def roster_calls(scripts: dict[str, list]) -> list[tuple]:
    kinds = {MINIBOSS_BAR, BOSS_BAR, MINIBOSS_DEFEAT, BOSS_DEFEAT, BOSS_BANNER}
    handlers = {eid: (b, i) for name, instrs in scripts.items() if name.startswith("common")
                for eid, b, i, _d in instrs if (b, i) in kinds}

    out = []
    for mapname, instrs in scripts.items():
        for eid, b, i, data in instrs:
            key = (b, i)
            if key in kinds:
                vals = unpack_args(data, LAYOUTS[key])
                if not vals:
                    continue
                if key in (MINIBOSS_BAR, BOSS_BAR):
                    out.append((mapname, eid, key, vals[1], vals[3]))
                else:
                    out.append((mapname, eid, key, vals[0], None))
            elif key == INIT_COMMON_EVENT:
                vals = common_init_args(data)
                if not vals or vals[0] not in handlers:
                    continue
                out.append((mapname, vals[0], handlers[vals[0]],
                            vals[1] if len(vals) > 1 else 0,
                            vals[2] if len(vals) > 2 else None))
    return out


##
# @brief The boss/miniboss roster keyed by entity id.
# @details An entity can be named by its health bar in one event and defeated in another, so
# the two halves meet on the entity. `miniboss` and `boss` are not exclusive by construction
# — a placement called by both is reported as such rather than silently filed under one.
def build_roster(scripts: dict[str, list]) -> dict[int, dict]:
    roster: dict[int, dict] = {}
    for mapname, eid, key, entity, name_id in roster_calls(scripts):
        if entity <= 0:
            continue
        row = roster.setdefault(entity, {"entity": entity, "maps": set(), "name_ids": set(),
                                         "miniboss": False, "boss": False, "events": set()})
        row["maps"].add(mapname)
        row["events"].add(eid)
        if key in (MINIBOSS_BAR, MINIBOSS_DEFEAT):
            row["miniboss"] = True
        else:
            row["boss"] = True
        if name_id and name_id > 0:
            row["name_ids"].add(name_id)
    return roster


##
# @brief Every death flag the DS3 one-time-enemy templates are initialised with.
# @details The first template argument is the flag; the rest are entity ids and extras that
# differ per template. Returns @c {flag: (map, template)}.
def ds3_death_flags(scripts: dict[str, list]) -> dict[int, tuple[str, int]]:
    out = {}
    for mapname, instrs in scripts.items():
        for _eid, b, i, data in instrs:
            if (b, i) != INIT_COMMON_EVENT:
                continue
            vals = common_init_args(data)
            if vals and len(vals) > 1 and vals[0] in DS3_DEATH_TEMPLATES:
                out.setdefault(vals[1], (mapname, vals[0]))
    return out


# ==========================================================================
# Names
# ==========================================================================

##
# @brief Every FMG table in the English message binders, keyed by table name.
# @details Which table holds an NPC name is not assumed: every table is loaded and the
# caller picks by coverage of the ids it is resolving. Same probe-then-report discipline the
# param extractor uses. An unpacked tree has no `.dcx` suffix; a raw one does; both work.
def load_fmg_tables(msg_dir: str) -> dict[str, dict[int, str]]:
    tables: dict[str, dict[int, str]] = {}
    for stem in ("menu.msgbnd", "item.msgbnd"):
        for cand in (stem, stem + ".dcx"):
            path = Path(msg_dir) / cand
            if not path.is_file():
                continue
            for bf in fs.read_bnd4(path.read_bytes()):
                key = Path(bf.name.replace("\\", "/")).name.rsplit(".", 1)[0]
                try:
                    tables[key] = fs.read_fmg(bf.data)
                except Exception as exc:                          # noqa: BLE001
                    print(f"  ! {cand}:{key} unreadable ({exc})", file=sys.stderr)
            break
    return tables


## @brief The FMG table covering the most of @p ids, and how many it covered.
def pick_table(tables: dict[str, dict[int, str]], ids: set[int]) -> tuple[str, int]:
    best, hits = "", -1
    for name, tbl in tables.items():
        n = sum(1 for i in ids if tbl.get(i))
        if n > hits:
            best, hits = name, n
    return best, hits


## @brief Paramdex's `NpcParam` annotations as @c {row id: english text}.
def npc_dev_names(paramdex: str) -> dict[int, str]:
    path = Path(paramdex) / "SDT" / "Names" / "NpcParam.txt"
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+)\s+(.*)$", line.strip())
        if m:
            out[int(m.group(1))] = m.group(2).split(" -- ")[0].strip()
    return out


##
# @brief The travel-menu area a Sekiro entity id belongs to, for the shipped table's keys.
# @details `db_sdt/minibosses.json` is keyed by the game's TRAVEL AREAS and the maps are the
# game's FILES — two different partitions, the same split the idol table lives with. This
# mapping is the one the shipped table already uses, so a regenerated table keeps its shape;
# the two Ashina Castle map files both fall under one menu area, and `m11_02` is the
# Reservoir, which the menu files under its own name.
SDT_AREA_BY_MAP = {
    "m10_00": "Hirata Estate", "m11_00": "Ashina Outskirts", "m11_01": "Ashina Castle",
    "m11_02": "Ashina Reservoir", "m13_00": "Abandoned Dungeon",
    "m15_00": "Ashina Depths", "m17_00": "Sunken Valley",
    "m20_00": "Senpou Temple, Mt. Kongo", "m25_00": "Fountainhead Palace",
}

##
# @brief The order areas are printed in: the game's own travel-menu order.
# @details `db_sdt/idols.json` uses exactly this sequence, so the two Sekiro progress
# sections read in the same order, and a regenerated table does not reshuffle the output.
# Sorting by map id instead would put Hirata before the Outskirts, which is neither the
# menu's order nor the order the player sees them in. The Reservoir has no key of its own
# in `idols.json` — its idol is filed under Ashina Castle — but it does have minibosses,
# so it is inserted where the menu puts it rather than appended.
SDT_AREA_ORDER = ["Ashina Outskirts", "Hirata Estate", "Ashina Castle", "Ashina Reservoir",
                  "Abandoned Dungeon", "Senpou Temple, Mt. Kongo", "Sunken Valley",
                  "Ashina Depths", "Fountainhead Palace"]

##
# @brief Indent for a generated `db_*` table. ONE space, matching every other table there.
# @details `.prettierignore` excludes `db_*/` on purpose — these are data, not code — so
# nothing reformats them afterwards and the house style has to be produced here. Writing
# prettier's two-space default instead reflows the whole file and buries the real diff.
DB_INDENT = 1


# ==========================================================================
# Subcommands
# ==========================================================================

## @brief Which dictionary paths to extract, from the prefixes and exact paths given.
def wanted(dict_path: str, prefixes: list[str], paths: list[str]) -> list[str]:
    names = [ln.strip() for ln in Path(dict_path).read_text(encoding="utf-8-sig").splitlines()
             if ln.strip()]
    if not prefixes and not paths:
        return names
    keep = [n for n in names if any(n.startswith(p) for p in prefixes)]
    known = set(keep)
    return keep + [p for p in paths if p not in known]


def cmd_unpack(args) -> int:
    spec = GAMES[args.game]
    if not Path(args.dict).is_file() or (
            spec["keys"] and not (args.keys and Path(args.keys).is_file())):
        print(KEY_HELP, file=sys.stderr)
        return 2
    keys = load_keys(args.keys, spec["keys"]) if spec["keys"] else {}

    # One index over every archive, so a lookup does not care which one a file landed in —
    # the split is a packaging detail, not a namespace. A missing archive is skipped, not
    # fatal: one install's DLC layout should not stop the run.
    index: dict[int, tuple[Path, dict]] = {}
    for name in spec["archives"]:
        bhd, bdt = Path(args.game_root) / f"{name}.bhd", Path(args.game_root) / f"{name}.bdt"
        if not bhd.is_file() or not bdt.is_file():
            print(f"{name}: absent, skipped")
            continue
        raw = bhd.read_bytes()
        # NOT EVERY HEADER IS ENCRYPTED — DS3's `Data0` is a plain BHD5, which is why UXM
        # publishes no key for it — so the magic decides and a key is only demanded when the
        # bytes are not already a header.
        if raw[:4] == b"BHD5":
            header = raw
        else:
            pem = keys.get(name)
            if pem is None:
                own = Path(args.game_root) / f"{name.replace('Ebl', '')}KeyCode.pem"
                if own.is_file():
                    pem = own.read_text(encoding="utf-8")
            if pem is None:
                # DS3's `Data0` is encrypted some other way again and nobody publishes a key
                # for it. It holds `regulation.bin`, which Paramdex covers anyway.
                print(f"{name}: encrypted with no published key, skipped")
                continue
            header = rsa_decrypt(raw, pem)
        entries = parse_bhd5(header, spec["bhd5"])
        print(f"{name}: {len(entries)} entries")
        for h, e in entries.items():
            index.setdefault(h, (bdt, e))

    todo = wanted(args.dict, args.prefix, args.path)
    print(f"{len(todo)} path(s) requested, {len(index)} entries indexed")

    open_bdt: dict[Path, object] = {}
    done, missing, failed = 0, [], []
    for path in todo:
        hit = index.get(path_hash(path, spec["bhd5"]))
        if hit is None:
            missing.append(path)
            continue
        bdt_path, entry = hit
        if bdt_path not in open_bdt:
            open_bdt[bdt_path] = open(bdt_path, "rb")
        data = read_entry(open_bdt[bdt_path], entry)
        rel = path.lstrip("/")
        if not args.keep_dcx:
            # A file this decoder cannot open is REPORTED AND SKIPPED, not fatal: a few
            # `drawparam/*.gparam.dcx` use Oodle decoder type 2 (LZNIB), which `ooz` does
            # not implement, and aborting over a lighting table would take the params and
            # the event scripts down with it.
            try:
                data = dcx_decompress(data)
            except SystemExit as why:
                failed.append(f"{path} ({why})")
                continue
            if rel.endswith(".dcx"):
                rel = rel[:-4]
        dest = Path(args.out) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        done += 1
    for f in open_bdt.values():
        f.close()

    print(f"wrote {done} file(s) to {args.out}")
    for f in failed:
        print(f"  ! could not decompress {f}")
    if missing:
        print(f"{len(missing)} dictionary path(s) in no archive (normal — the dictionary "
              f"covers every patch): {', '.join(missing[:5])}"
              + (" ..." if len(missing) > 5 else ""))
    return 0


def cmd_msb(args) -> int:
    maps = read_msbs(args.root)
    for name, rows in maps:
        enemies = [r for r in rows if r["type"] in (PART_ENEMY, PART_DUMMY_ENEMY)]
        ided = [r for r in enemies if r["entity_id"]]
        print(f"{name}: {len(rows)} parts, {len(enemies)} enemies, "
              f"{len(ided)} with an entity id")

    if args.entity:
        want = set(args.entity)
        for name, rows in maps:
            for r in rows:
                if r["entity_id"] in want:
                    print(f"\n{name}  entity {r['entity_id']}")
                    for k, v in r.items():
                        if v is not None:
                            print(f"    {k}: {v}")

    if args.enemies:
        for name, rows in maps:
            for r in rows:
                if r["type"] in (PART_ENEMY, PART_DUMMY_ENEMY) and r["entity_id"]:
                    print(f"{name}\t{r['entity_id']}\t{r['model']}\t{r['npc_param']}"
                          f"\t{r['type_name']}\t{r['name']}")
    return 0


def cmd_emevd(args) -> int:
    scripts = read_emevds(args.root)
    print(f"{len(scripts)} script(s), {sum(len(v) for v in scripts.values())} instructions")

    for spec in args.instr:
        bank, iid = (int(x) for x in spec.split(":"))
        types = LAYOUTS.get((bank, iid))
        print(f"\n=== {bank}[{iid}] ===")
        for name, instrs in scripts.items():
            for eid, b, i, data in instrs:
                if (b, i) == (bank, iid):
                    vals = unpack_args(data, types) if types else data.hex(" ")
                    print(f"  {name}  event {eid}  {vals}")

    if args.ds3_deaths:
        flags = ds3_death_flags(scripts)
        print(f"\n=== DS3 one-time-enemy death flags: {len(flags)} ===")
        for fid, (mapname, template) in sorted(flags.items()):
            print(f"  {fid}  {mapname}  template {template}")
    return 0


##
# @brief Print the roster, compare it with the shipped table, optionally rewrite it.
# @details The comparison is the point. It reports three kinds of disagreement separately,
# because they need different judgements: an id the scripts do not call a miniboss (a row
# that should go), a miniboss the table lacks (a row that should arrive), and a row whose id
# is right but whose name is a model family rather than a character.
def cmd_roster(args) -> int:
    scripts = read_emevds(args.root)
    print(f"{len(scripts)} script(s), {sum(len(v) for v in scripts.values())} instructions")
    roster = build_roster(scripts)

    name_ids = {n for r in roster.values() for n in r["name_ids"] if n > 0}
    names: dict[int, str] = {}
    if args.msg:
        tables = load_fmg_tables(args.msg)
        table, hits = pick_table(tables, name_ids)
        print(f"name table: {table} ({hits} of {len(name_ids)} name ids resolved, "
              f"{len(tables)} tables probed)")
        names = tables.get(table, {})

    placed = {}
    if args.maps:
        for mapname, rows in read_msbs(args.maps):
            for r in rows:
                if r["type"] in (PART_ENEMY, PART_DUMMY_ENEMY) and r["entity_id"]:
                    placed[r["entity_id"]] = dict(r, map=mapname)
    dev = npc_dev_names(args.paramdex) if args.paramdex else {}

    mini = sorted(e for e, r in roster.items() if r["miniboss"] and not r["boss"])
    boss = sorted(e for e, r in roster.items() if r["boss"] and not r["miniboss"])
    both = sorted(e for e, r in roster.items() if r["boss"] and r["miniboss"])
    print(f"\n{len(mini)} miniboss entities, {len(boss)} boss entities, "
          f"{len(both)} called by both")

    def printed_name(e: int) -> str:
        got = sorted({names.get(n, f"name#{n}") for n in roster[e]["name_ids"] if n > 0})
        return ", ".join(got) or "(no health bar)"

    for label, ids in (("MINIBOSSES", mini), ("BOSSES", boss), ("BOTH", both)):
        if not ids:
            continue
        print(f"\n=== {label} ===")
        for e in ids:
            extra = ""
            if e in placed:
                extra = f"  {placed[e]['model']}"
                if placed[e]["npc_param"] in dev:
                    extra += f"  [{dev[placed[e]['npc_param']]}]"
            print(f"  {e}  {printed_name(e):38} {'/'.join(sorted(roster[e]['maps']))}{extra}")

    shipped_path = BASE / "db_sdt" / "minibosses.json"
    if shipped_path.is_file():
        shipped_raw = json.loads(shipped_path.read_text(encoding="utf-8"))
        shipped = {eid: n for rows in shipped_raw.values() for eid, n in rows}
        measured = set(mini) | set(both)
        print(f"\n=== db_sdt/minibosses.json: {len(shipped)} rows vs {len(measured)} "
              f"measured ===")
        for eid in sorted(set(shipped) - measured):
            why = ""
            if eid in placed:
                why = f" — {placed[eid]['model']}"
                if placed[eid]["npc_param"] in dev:
                    why += f", {dev[placed[eid]['npc_param']]}"
            print(f"  NOT A MINIBOSS  {eid}  shipped as '{shipped[eid]}'{why}")
        for eid in sorted(measured - set(shipped)):
            print(f"  MISSING         {eid}  {printed_name(eid)}")
        for eid in sorted(measured & set(shipped)):
            got = printed_name(eid)
            if got and shipped[eid] not in got:
                print(f"  RENAMED         {eid}  '{shipped[eid]}' -> '{got}'")

    if args.write:
        rows: dict[str, list] = {}
        for e in sorted(set(mini) | set(both)):
            area = SDT_AREA_BY_MAP.get(entity_map(e), entity_map(e))
            rows.setdefault(area, []).append([e, printed_name(e)])
        # Travel-menu order, then anything this table has never seen, so a new area shows up
        # at the end rather than silently sorting itself into the middle.
        out = {a: rows[a] for a in SDT_AREA_ORDER if a in rows}
        out.update({a: r for a, r in rows.items() if a not in out})
        Path(args.write).write_text(
            json.dumps(out, indent=DB_INDENT, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nwrote {args.write}: {sum(len(v) for v in out.values())} rows in "
              f"{len(out)} areas")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {str(e): {"entity": e, "maps": sorted(r["maps"]), "miniboss": r["miniboss"],
                      "boss": r["boss"], "name_ids": sorted(r["name_ids"]),
                      "names": sorted({names[n] for n in r["name_ids"] if n in names}),
                      "events": sorted(r["events"])}
             for e, r in sorted(roster.items())}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"wrote {args.json} ({len(roster)} entities)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ooz", help="path to libooz.so (Oodle Kraken; see the docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("unpack", help="extract files from a game's .bhd/.bdt archives")
    u.add_argument("--game", default="sekiro", choices=sorted(GAMES))
    u.add_argument("--game-root", required=True)
    u.add_argument("--keys", help="UXM's ArchiveKeys.cs; DS2 ships its own keys")
    u.add_argument("--dict", required=True, help="UXM's <game>Dictionary.txt")
    u.add_argument("--out", required=True)
    u.add_argument("--prefix", action="append", default=[],
                   help="extract every dictionary path starting with this; repeatable")
    u.add_argument("--path", action="append", default=[],
                   help="extract one exact path; repeatable")
    u.add_argument("--keep-dcx", action="store_true",
                   help="write the .dcx as stored instead of decompressing it")
    u.set_defaults(func=cmd_unpack)

    m = sub.add_parser("msb", help="read map layouts: enemy placements and entity ids")
    m.add_argument("root", help="mapstudio directory, or one .msb")
    m.add_argument("--entity", type=int, action="append", default=[],
                   help="print the placement carrying this entity id; repeatable")
    m.add_argument("--enemies", action="store_true", help="list every enemy placement")
    m.set_defaults(func=cmd_msb)

    e = sub.add_parser("emevd", help="read event scripts (DS3 and Sekiro)")
    e.add_argument("root", help="event directory, or one .emevd")
    e.add_argument("--instr", action="append", default=[], metavar="BANK:ID",
                   help="dump every call of this instruction; repeatable")
    e.add_argument("--ds3-deaths", action="store_true",
                   help="list the death flags the DS3 one-time-enemy templates carry")
    e.set_defaults(func=cmd_emevd)

    r = sub.add_parser("roster", help="Sekiro's boss/miniboss roster, from the scripts")
    r.add_argument("root", help="event directory")
    r.add_argument("--msg", help="msg/engus directory, to resolve the printed names")
    r.add_argument("--maps", help="mapstudio directory, to add each entity's model")
    r.add_argument("--paramdex", help="Paramdex checkout, for NpcParam dev names")
    r.add_argument("--json", help="write the full roster here")
    r.add_argument("--write", help="regenerate a minibosses.json at this path")
    r.set_defaults(func=cmd_roster)

    args = ap.parse_args()
    if args.ooz:
        ooz_load(args.ooz)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
