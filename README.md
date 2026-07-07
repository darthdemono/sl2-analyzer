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

| Game | Save file | Tier | What you get |
|---|---|---|---|
| Dark Souls II: SOTFS | `DS2SOFS0000.sl2` | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls Remastered | `DRAKS0005.sl2` | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls: Prepare to Die Edition | `DRAKS0005.sl2` | **inventory** | full inventory + progress + name (stats not calibrated) |
| Dark Souls II: vanilla | `DARKSII0000.sl2` | **blocked** | needs its AES key, which isn't public — see below |
| Dark Souls III | `DS30000.sl2` | **roster** | character names from the header |
| Elden Ring | `ER0000.sl2` | **roster*** | detected, but its offsets shifted across patches |

The script picks the game itself from the bytes — you never tell it which one.

\* On the Elden Ring save tested here, the public roster offsets did not line up
with the game version, so it honestly prints "detected but not readable in this
build" rather than fabricate names. Same for DS3 if a save's table doesn't match.

## Why some games are held back

- **Vanilla DS2** is encrypted with a key that is not published in any tool I
  could find. Everything else about it works — detection, structure, offsets —
  but without the key the slots can't be decrypted. Re-save in SOTFS, or drop the
  key in, and it reads fully.
- **PtDE** stats sit at byte distances this build hasn't calibrated (they differ
  from the Remaster), so stats and level are omitted. The inventory, boss souls,
  and key items come from a game-independent anchor and are printed in full.
- **DS3 / Elden Ring** stat and inventory blocks moved across patches, and their
  item-name tables live on Nexus behind a login I can't script. The character
  roster is read from the save's load-screen table when it lines up.

Give me the missing pieces (see *Lifting a game to full*) and any of these moves up.

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

Past the envelope the games diverge: DS2 keeps stats at fixed offsets; DSR and
PtDE move the character block, so stats are read relative to a fixed "magic" byte
pattern that always sits next to it; DS3 and ER change layout between patches.
That is the whole reason for the tier system.

---

## How it works, step by step

1. **Read and validate.** The `.sl2` is loaded and the BND4 table is checked —
   bad magic, silly entry counts, or entries pointing outside the file are
   rejected before any offset is trusted.
2. **Detect the game** from the header signature and entry count, with two
   content tie-breaks: SOTFS vs vanilla DS2 (which key decrypts cleanly) and DS3
   vs ER (entry size).
3. **Load the item database** for that game's family from the right `db_*` folder.
4. **Decrypt each entry** with the correct key and layout, or strip the header for
   the unencrypted games.
5. **Find the characters.** Empty slots decode to garbage, so a slot only counts
   if its name — or, for the anchor games, its whole stat block — reads as sane.
6. **Parse** name, class, level, attributes, souls, HP, and NG cycle, then walk
   the inventory and sort every item into its category by id.
7. **Infer progress** from boss souls and key items still held.
8. **Write the Markdown** with a header note stating exactly what is read and what
   is inferred.

Every integer read goes through a bounds-checked helper that returns "unknown"
rather than reading past the end of a buffer — a missing field can travel through
the whole pipeline, but a wrong or out-of-range one cannot.

---

## The honest limitations

**Progress is inferred, not read.** Which bosses you beat is worked out from the
boss souls still in your pack. That is accurate, but it only sees souls you have
not spent. Spend a boss soul and this can no longer tell the boss is dead — that
fact lives in the event-flag blob, and those flag IDs are not publicly mapped. So
the boss list is a floor, not a ceiling. Same for key items and locations.

**DSR / PtDE omit upgraded gear from the named list.** Dark Souls 1 bakes the
reinforcement level into the item id, so a `+5` weapon has a different id from its
base and does not match the name table. Those items are counted and reported as
omitted rather than guessed at.

---

## How to run it

You need Python 3 and one library.

```bash
pip install -r requirements.txt
```

Then point it at a save. It figures out the game on its own:

```bash
python3 sl2_to_md.py "/path/to/DS2SOFS0000.sl2" -o ds2sotfs_playthrough.md
python3 sl2_to_md.py "/path/to/DRAKS0005.sl2"    -o dsr_playthrough.md
```

`-o` is the output path; the folder is created if it doesn't exist. On Linux the
saves usually sit under the Proton prefix
(`~/.local/share/Steam/steamapps/compatdata/<appid>/pfx/...`).

To convert a whole folder of saves at once, loop over them:

```bash
for f in test/*.sl2; do
  python3 sl2_to_md.py "$f" -o "test/output/$(basename "${f%.*}")_playthrough.md"
done
```

---

## Lifting a game to full

The tier a game sits at is only limited by two things — offsets and item tables —
and both are just files.

- **Item-name tables** go in the game's `db_*` folder as JSON mapping
  `"Item Name": "<id>"`. DS2 ids are little-endian hex; DS1 ids are decimal. Drop
  DS3 tables in `db_ds3/` and Elden Ring tables in `db_er/`.
- **The vanilla DS2 key** or **recalibrated DS3/ER/PtDE offsets** go into the
  matching constants at the top of `sl2_to_md.py`.

Give me the tables (or the key) and the roster/inventory code already in place
does the rest.

---

## Layout

```
sl2_to_md.py      the converter (Doxygen-commented, bounds-checked throughout)
db_ds1/*.json     Dark Souls 1 item tables (shared by DSR and PtDE)
db_ds2/*.json     Dark Souls 2 item tables (shared by vanilla and SOTFS)
db_ds3/           Dark Souls 3 item tables (empty — drop yours in)
db_er/            Elden Ring item tables (empty — drop yours in)
test/             sample saves, one per game
test/output/      generated Markdown, one per save
requirements.txt  the one dependency
README.md         this file
```

---

## Credits

I did not reverse-engineer these formats from scratch, and I am not going to
pretend I did.

- DS2 offsets and item tables: [alfizari/Dark-Souls-2-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-2-Save-Editor-PS4-PC).
- DSR / DS3 / ER decryption, keys, and header layout: [jtesta/souls_givifier](https://github.com/jtesta/souls_givifier).
- DSR / DS1 offsets and item tables: [alfizari/Dark-Souls-Remastered-Save-Editor](https://github.com/alfizari/Dark-Souls-Remastered-Save-Editor).
- DS2 key: the DS2 profile in [mi5hmash/SL2Bonfire](https://github.com/mi5hmash/SL2Bonfire).

The `.sl2`-to-Markdown idea, the game auto-detection, the tier system, the
progress inference, and this tool are mine.
