# SL2-TO-MD

This turns a FromSoftware `.sl2` save into one Markdown file. That is the whole job.

You point it at a save, it reads the bytes, and it writes a `.md` that describes the playthrough: who each character is, their level and class and stats, their souls or runes, their full inventory with real item names, the key items they carry, and the bosses they have put down. Why bother? Because an LLM cannot read a `.sl2`. It is an encrypted binary blob, and pasting it into a chat gets you nothing. Markdown it reads fine. So you convert the save, paste the Markdown in as context, and now the model knows where you actually are in the run instead of guessing at it.

It reads the save and never writes to it. Point it at your live save if you like. The worst case is a bad Markdown file, not a bricked character.

The code lives at **https://github.com/darthdemono/SL2-TO-MD**, and every file it writes says so: the header of each generated `.md` carries the repo link and a one-line note on how that game was read, so a summary you pasted somewhere months ago can still point back at the tool that made it.

## Supported games, and how far each one goes

Not every Souls save is mapped to the same depth in public tooling, so each game is handled at the highest tier it can be *trusted* at. A tier is a promise: everything printed at any tier is read from the save, never guessed. If a number cannot be trusted, it is left out. A wrong stat is worse than a missing one, and that rule decides every judgement call in the code.

| Game | Save file | Supported | Tier | What you get |
|---|---|:---:|---|---|
| Dark Souls: Prepare to Die Edition | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls Remastered | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls II: SOTFS | `DS2SOFS0000.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls II (vanilla) | `DARKSII0000.sl2` | No | — | unsupported: AES key not public (re-save in SOTFS) |
| Dark Souls III | `DS30000.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Elden Ring | `ER0000.sl2` | Yes | **full\*** | identity, attributes, runes, remembrances, owned items (\*item list partial) |

Five of the six FromSoftware `.sl2` variants are fully supported. Only vanilla Dark Souls II is out, and you never tell the tool which game it is: it works that out from the bytes itself.

Vanilla Dark Souls II is the one wall I could not get past. Its payload is encrypted with an AES key that has never been published anywhere I could find, and the Scholar of the First Sin key does not decrypt it. So the tool detects it, says so plainly, and stops, instead of printing garbage. Re-save the file in Scholar of the First Sin and it becomes a `DS2SOFS0000.sl2` that works.

The asterisk on Elden Ring is honest too. Identity, every attribute, runes held, and remembrances are read straight from the save. The item *list* is partial: owned items come from the GaItem array, so armour, talismans, goods, and base weapons resolve, but a reinforced or affinity weapon bakes the upgrade into its id and misses the base-id table. Per-item quantities are not read either. What is listed is really owned. It is just not the complete stash.

---

## What a `.sl2` actually is

A `.sl2` is a `BND4` archive. Inside it sit a handful of entries, one per character slot plus a header slot, and each entry is wrapped as `[16B MD5 checksum][16B IV][payload]`. Most of the games encrypt that payload with AES-128-CBC. The keys are not secrets. FromSoftware ships them inside the games, so "decryption" here is just reading a documented format with a key everyone already has.

- **DS2 key:** `599F9B699640A55236EE2D70835EC744`
- **DSR key:** `0123456789ABCDEFFEDCBA9876543210`
- **DS3 key:** `FD464D695E69A39A10E319A7ACE8B7FA`
- **PtDE and Elden Ring:** the payload is not encrypted at all. You strip the 16-byte checksum wrapper and read the plaintext.

Past that envelope the games stop agreeing with each other, and that disagreement is the entire reason tiers exist. Here is where each one keeps its data:

- **DS2** keeps stats and inventory at fixed offsets. You read them straight off. Item counts hide in the low two bytes of a four-byte field, because special items like the Estus Flask pack their charge state into the high two. So counts are read as a `uint16`, and the Estus keeps its charges to itself.
- **DSR and PtDE** move the character block around, so a fixed offset is useless. Stats are read relative to an anchor that always sits next to the block. DSR keys on a fixed "magic" byte pattern. PtDE has no such pattern, so it anchors on the character name instead. The two games share the identical stat layout, which is why the same distances work once you find the anchor. Inventory is found by a second, game-independent anchor.
- **DS3** hides its stats behind offsets that shift between patches, so guessing an offset is a losing game. Instead the stat block is *found by content*: it is the only run of nine attributes whose sum minus 89 equals the stored soul level. That is DS3's own levelling formula, so a false match is not credible. Item ids are full 32-bit and sparse, so the inventory is found by scanning the slot for known ids. Names come from the load-screen roster.
- **Elden Ring** locates its stat block by content too, but with a twist: the block's offset varies from one character to the next, because variable-length data sits in front of it. So the search keys on the eight attributes whose sum minus 79 equals the in-slot level, which is ER's rune-level formula (a Wretch is all-tens at level one). Owned items are walked from the GaItem array at the slot start. Name and level come from the header's profile table.

Notice the pattern. Where an offset is stable, read it. Where it moves, find the block by a fact only the real block satisfies. The level formulas do that work: they are cheap to check and almost impossible to hit by accident.

---

## How it works, step by step

The whole program is one pass. It never loops back.

1. **Read and validate.** The `.sl2` is loaded and the BND4 table is checked first. Bad magic, a silly entry count, or an entry that points outside the file is rejected before a single offset downstream is trusted.
2. **Detect the game** from the header signature and entry count. Two cases need a content tie-break: Scholar of the First Sin is the DS2 variant whose key actually decrypts, and DS3 versus Elden Ring (both twelve entries) split by first-entry size, since ER's is far larger.
3. **Load the item database** for that game from its `db_*` folder. No database, no run: the tool would rather stop than print numeric ids at you.
4. **Decrypt each slot** with the right key and layout, or strip the checksum for the two unencrypted games.
5. **Find the real characters.** An empty slot decodes to garbage, so a slot only counts if its name, its stat block, or its item list reads as genuine. This is why an all-items save does not fool it into printing a fake character.
6. **Parse whatever the tier allows.** Identity, stats, souls or runes, and the inventory sorted into weapons, armour, rings, goods, and the rest by id.
7. **Infer progress** from the boss souls or remembrances and the key items still held. More on the word "infer" below.
8. **Write the Markdown**, with a header note that states plainly what was read and what was inferred.

Every integer read in that pipeline goes through a bounds-checked helper. Read past the end of a buffer and it returns "unknown" rather than crashing or reading junk. So a missing field can travel through the whole program and come out as a blank. A wrong or out-of-range one cannot. That is the rule the entire tool is built to keep.

The control table is a single dict called `GAMES`. Each entry names the game, its tier, its decryption function, its parser, its item-database config, and its slot range. Adding or changing a game is mostly editing that dict and its one parse function. The driver does not care which game it is looking at.

---

## What the output looks like

One `.md` per save. Header, then one section per character. Roughly this:

```markdown
# Dark Souls II: Scholar of the First Sin — Playthrough Save Summary

- **Game:** Dark Souls II: Scholar of the First Sin
- **Support tier:** full
- **Characters found:** 2

> Automated dump of the save. Code Repo: https://github.com/darthdemono/SL2-TO-MD . How it works for Dark Souls II: Scholar of the First Sin: the game locks its save with a key it ships inside itself, so the tool unlocks it and reads each character from known spots. Every item is matched to its real name, and the Estus Flask even shows how many charges it is holding.

## Slot 2: Joy

- **Soul Level:** 88
- **Souls held:** 0
- **Max HP:** ...

### Attributes

| VGR | END | VIT | ATN | STR | DEX | ADP | INT | FTH |
|----|----|----|----|----|----|----|----|----|
|  22 |  16 |  15 |   4 |  45 |  15 |  15 |   3 |   6 |

### Inventory

#### Weapons
- Broadsword
- Blue Wooden Shield

#### Consumables
- Estus Flask (7/7 charges)
- Lifegem ×25

#### Great Boss Souls
- Old Witch Soul

#### Boss Souls
- Soul of the Lost Sinner
```

The inventory mirrors the in-game item menu: one heading per category, and boss souls split into the four "Old" great souls and the ordinary ones, the way the game grades them. Special items carry their state, so the Estus Flask shows its charge count. Paste the whole file into a model and ask it to plan your next steps, tune your build, or tell you what you missed. It has the facts now.

---

## How to run it

Clone it, and you need Python 3 and one library, `cryptography`:

```bash
git clone https://github.com/darthdemono/SL2-TO-MD
cd SL2-TO-MD
pip install -r requirements.txt
```

Then point the tool at a save. It figures out the game on its own, so there is no game flag to set:

```bash
python3 sl2_to_md.py "/path/to/DS2SOFS0000.sl2" -o playthrough.md
```

You can also leave the path off entirely. With no file argument the tool looks in the current folder and the usual Steam/Proton and Windows save locations, and takes the most recently modified `.sl2` it finds, which is almost always your live character:

```bash
python3 sl2_to_md.py -o playthrough.md
```

`-o` is the output path, and its folder is created for you if it does not exist. If you leave `-o` off, it writes `playthrough.md` in the current directory. On an unsupported or malformed file the tool prints why and exits non-zero, so it drops cleanly into a script.

To convert a whole folder of saves in one go, loop over them:

```bash
for f in *.sl2; do
  python3 sl2_to_md.py "$f" -o "output/$(basename "${f%.*}").md"
done
```

Where do the saves live? On Windows they are under `%APPDATA%` (`C:\Users\<you>\AppData\Roaming\<game>`). On Linux through Proton they sit inside the Steam prefix, along the lines of `~/.local/share/Steam/steamapps/compatdata/<appid>/pfx/drive_c/users/steamuser/AppData/Roaming/<game>`. Copy the `.sl2` out first if you would rather not touch the live folder, though you do not have to: the tool only ever reads.

There is no test suite and no linter config. The one gate is a compile check:

```bash
python3 -m py_compile sl2_to_md.py
```

Beyond that, you verify a change by running it against a real save and reading the Markdown it produces. The saves are the fixtures.

---

## The honest limitations

Two things this tool cannot do, and it says so in the output rather than papering over them.

**Progress is inferred, not read.** Which bosses you beat is worked out from the boss souls, or in Elden Ring the remembrances, still sitting in your pack. That is accurate as far as it goes, but it only sees what you have not spent. Consume a boss soul and the tool can no longer tell that the boss is dead. That fact lives in the event-flag blob, and those flag ids are not publicly mapped. So the boss list is a floor, not a ceiling. Everything on it is real. There may simply be more you have already cashed in.

**Upgraded gear in DS1 and DS3 is not named.** Dark Souls 1 and 3 bake the reinforcement level into the item id, so a +5 weapon has a different id from its base and misses the name table. Those items are counted so you know they exist, not guessed at. Dark Souls 2 does not have this problem here: its tables are built from the full SOTFS id list, so reinforced and infused variants all resolve by name. Elden Ring is the reverse case, where the reinforced-weapon ids are skipped rather than counted.

---

## Layout

```
sl2_to_md.py      the converter (Doxygen-commented, bounds-checked throughout)
db_ds1/*.json     Dark Souls 1 item tables (shared by DSR and PtDE)
db_ds2/*.json     Dark Souls 2 item tables (id-keyed, full SOTFS coverage)
db_ds3/*.json     Dark Souls 3 item tables (id-scan)
db_er/*.json      Elden Ring item table (GaItem walk)
requirements.txt  the one dependency
README.md         this file
```

---

## Adding or extending item tables

Every tier is limited by two things only: offsets and item tables. Both are just files, so both are yours to extend.

- **DS2** tables are id-keyed: `{"<little-endian-hex-id>": "Item Name"}`, one file per category. Id-keyed on purpose, not by accident. DS2 gives one item name several ids (a base form plus its reinforced and infused variants, and sometimes duplicate entries besides), and a name-keyed file would keep one id per name and silently drop the variant your save actually holds. So the id is the key, and every variant gets its own line.
- **DS1, DS3, and ER** tables are name-keyed: `{"Item Name": <decimal-id>}`, kept per category because the raw numbers repeat across categories.

Drop a game's tables into its `db_*` folder and the existing code resolves the names on the next run. Every supported game's stat offsets are already calibrated. The one remaining gap is Elden Ring's item list: no quantities, and reinforced or affinity weapons still miss the base-id table.

---

## Credits

I did not reverse-engineer these formats from scratch, and I am not going to pretend I did. The keys, offsets, and structures come from people who mapped them first:

- DS2 offsets and item tables: [alfizari/Dark-Souls-2-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-2-Save-Editor-PS4-PC).
- DSR, DS3, and ER keys, decryption, and header layout: [jtesta/souls_givifier](https://github.com/jtesta/souls_givifier).
- DSR and DS1 offsets and item tables: [alfizari/Dark-Souls-Remastered-Save-Editor](https://github.com/alfizari/Dark-Souls-Remastered-Save-Editor).
- Elden Ring save structure (GaItem array, profile table): [ClayAmore/ER-Save-Editor](https://github.com/ClayAmore/ER-Save-Editor).
- DS2 key: the DS2 profile in [mi5hmash/SL2Bonfire](https://github.com/mi5hmash/SL2Bonfire).

What is mine: the `.sl2`-to-Markdown idea, the game auto-detection, the tier system and the rule behind it, the content-scan stat finders and the level-formula checks that make them safe, the id-scan and GaItem-walk inventory readers, and the progress inference.
