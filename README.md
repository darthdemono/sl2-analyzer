# SL2-TO-MD

This turns a FromSoftware save file into a Markdown file. That is the whole job.

You point it at your `.sl2`, it reads the save, and it writes one `.md` file that
describes your playthrough: who your characters are, their level, class, and
stats, their souls, their whole inventory with real item names, which key items
they hold, and which bosses they have beaten. An LLM cannot read a `.sl2` — it is
an encrypted binary blob. But it reads Markdown fine, so you dump the save into
Markdown and paste that in as context. Now the model knows where you actually are
in the game instead of guessing.

It reads the save and nothing else. It never writes to it. Point it at your live
save if you want — the worst thing that can happen is a bad Markdown file.

## Supported games and how far each goes

Not every Souls save is mapped to the same depth in public tooling, so each game
is handled at the highest tier it can be trusted at. **A tier is a promise:
everything printed at any tier is read from the save, never guessed.** If a number
can't be trusted, it is left out, because a wrong stat is worse than a missing one.

| Game | Save file | Status | Tier | What you get |
|---|---|:---:|---|---|
| Dark Souls: Prepare to Die Edition | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls Remastered | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls II: SOTFS | `DS2SOFS0000.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls II (vanilla) | `DARKSII0000.sl2` | No | — | unsupported — AES key not public (re-save in SOTFS) |
| Dark Souls III | `DS30000.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Elden Ring | `ER0000.sl2` | Yes | **full\*** | identity, attributes, runes, remembrances, owned items (\*item list partial) |

Five of the six FromSoftware `.sl2` variants are fully supported; only vanilla
Dark Souls II is out. The script picks the game itself from the bytes — you never
tell it which one.

Vanilla Dark Souls II (`DARKSII0000.sl2`) is **not supported**: it is encrypted
with a key that is not published anywhere I could find. The tool detects it and
says so instead of pretending. Re-save it in Scholar of the First Sin.

\* Elden Ring is partial: owned items are read from the GaItem array (armour,
talismans, goods, base weapons resolve; reinforced/affinity weapons carry the
upgrade in their id and are skipped). Per-item quantities and stats are not read —
ER's detailed inventory and stat blocks shift between patches. Name, level, and
what is listed are real.

---

## What a `.sl2` actually is

A `.sl2` is a `BND4` archive. Inside it are a handful of entries, and each entry
is wrapped as `[16B MD5 checksum][16B IV][payload]`. Most games encrypt the
payload with AES-128-CBC; the keys are not secrets — FromSoftware ships them
inside the games, so decryption is just reading a documented format.

- **DS2 key:** `599F9B699640A55236EE2D70835EC744`
- **DSR key:** `0123456789ABCDEFFEDCBA9876543210`
- **DS3 key:** `FD464D695E69A39A10E319A7ACE8B7FA`
- **PtDE and Elden Ring:** payload is not encrypted at all.

Past the envelope the games diverge, and that is the whole reason for tiers:

- **DS2** keeps stats and inventory at fixed offsets — read straight off.
- **DSR / PtDE** move the character block, so stats are read relative to an anchor
  that always sits next to it — DSR keys on a fixed "magic" byte pattern, PtDE on
  the character name (the two games share the identical stat layout). Inventory is
  found by a second, game-independent anchor.
- **DS3** keeps stats behind patch-dependent offsets, so the stat block is *located
  by content*: the only nine attributes whose sum minus 89 equals the stored soul
  level (DS3's own level formula). Its item ids are full 32-bit and sparse, so the
  inventory is found by *scanning* the slot for known ids. Names come from the
  load-screen table.
- **Elden Ring** locates its stat block by content too, but the block's offset
  *varies from character to character*, so the search keys on the eight attributes
  whose sum minus 79 equals the in-slot level (ER's own rune-level formula). The
  owned-item set is walked from the GaItem array at the slot start; name and level
  also come from the header's profile table. The item list stays partial (no
  quantities, reinforced weapons miss the base-id table).

---

## How it works, step by step

1. **Read and validate.** The `.sl2` is loaded and the BND4 table is checked —
   bad magic, silly entry counts, or entries pointing outside the file are
   rejected before any offset is trusted.
2. **Detect the game** from the header signature and entry count, with two
   content tie-breaks: SOTFS DS2 (which key decrypts cleanly) and DS3 vs ER
   (entry size).
3. **Load the item database** for that game from the right `db_*` folder.
4. **Decrypt each entry** with the correct key and layout, or strip the header for
   the unencrypted games.
5. **Find the characters.** Empty slots decode to garbage, so a slot only counts
   if its name, stat block, or item list reads as real.
6. **Parse** whatever the tier allows — identity, stats, souls, and the inventory
   sorted into categories by id.
7. **Infer progress** from boss souls / remembrances and key items still held.
8. **Write the Markdown** with a header note stating what is read and what is
   inferred.

Every integer read goes through a bounds-checked helper that returns "unknown"
rather than reading past the end of a buffer. A missing field can travel through
the whole pipeline; a wrong or out-of-range one cannot.

---

## The honest limitations

**Progress is inferred, not read.** Which bosses you beat is worked out from the
boss souls (or, in Elden Ring, remembrances) still in your pack. That is accurate,
but it only sees what you have not spent. Consume a boss soul and this can no
longer tell the boss is dead — that fact lives in the event-flag blob, and those
flag IDs are not publicly mapped. So the boss list is a floor, not a ceiling.

**Upgraded gear is omitted from the named list.** Dark Souls 1 and 3 bake the
reinforcement level into the item id, so a upgraded weapon has a different id from
its base and does not match the name table. Those items are counted (DS1/DS3) or
skipped (ER) rather than guessed at.

---

## How to run it

You need Python 3 and one library.

```bash
pip install -r requirements.txt
```

Then point it at a save. It figures out the game on its own:

```bash
python3 sl2_to_md.py "/path/to/DS2SOFS0000.sl2" -o playthrough.md
```

`-o` is the output path; the folder is created if it doesn't exist. On Linux the
saves usually sit under the Proton prefix
(`~/.local/share/Steam/steamapps/compatdata/<appid>/pfx/...`).

To convert a folder of saves at once, loop over them:

```bash
for f in *.sl2; do
  python3 sl2_to_md.py "$f" -o "output/$(basename "${f%.*}").md"
done
```

---

## Layout

```
sl2_to_md.py      the converter (Doxygen-commented, bounds-checked throughout)
db_ds1/*.json     Dark Souls 1 item tables (shared by DSR and PtDE)
db_ds2/*.json     Dark Souls 2 item tables
db_ds3/*.json     Dark Souls 3 item tables (id-scan)
db_er/*.json      Elden Ring item table (GaItem walk)
requirements.txt  the one dependency
README.md         this file
```

---

## Adding item tables

Every tier is limited only by offsets and item tables, and both are just files.

- **DS2** tables: JSON of `{"Item Name": "<little-endian-hex-id>"}`, by category.
- **DS1 / DS3 / ER** tables: JSON of `{"Item Name": <decimal-id>}`.

Drop a game's tables into its `db_*` folder and the existing code resolves the
names. Every supported game's stat offsets are calibrated; the remaining gap is
Elden Ring's *item list* (no quantities, and reinforced/affinity weapons miss the
base-id table).

---

## Credits

I did not reverse-engineer these formats from scratch, and I am not going to
pretend I did.

- DS2 offsets and item tables: [alfizari/Dark-Souls-2-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-2-Save-Editor-PS4-PC).
- DSR / DS3 / ER keys, decryption, and header layout: [jtesta/souls_givifier](https://github.com/jtesta/souls_givifier).
- DSR / DS1 offsets and item tables: [alfizari/Dark-Souls-Remastered-Save-Editor](https://github.com/alfizari/Dark-Souls-Remastered-Save-Editor).
- Elden Ring save structure (GaItem array, profile table): [ClayAmore/ER-Save-Editor](https://github.com/ClayAmore/ER-Save-Editor).
- DS2 key: the DS2 profile in [mi5hmash/SL2Bonfire](https://github.com/mi5hmash/SL2Bonfire).

The `.sl2`-to-Markdown idea, the game auto-detection, the tier system, the
id-scan and GaItem-walk inventory readers, and the progress inference are mine.
