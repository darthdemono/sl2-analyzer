# sl2-analyzer

This reads a FromSoftware `.sl2` save and tells you what is in it. That is the whole job.

There are two ways to use it, and they run the exact same reading logic:

- **A web page.** Drop a `.sl2` onto [the site](https://darthdemono.github.io/sl2-analyzer/) and it lays each character out as a replica of that game's own in-game **Level-Up screen** — a framed stat panel skinned to the game, with progress lists and (for DS2) item thumbnails below. It parses the file in your browser. Nothing uploads, nothing hits a server, and the save never leaves your machine.
- **A Python CLI.** Point `sl2_to_md.py` at a save and it writes one Markdown file describing the run (or JSON, against a [published schema](schema.json), if a program is reading it). That is the format an LLM can actually read. A `.sl2` is an encrypted binary blob; paste it into a chat and you get nothing. Paste the Markdown and the model knows where you are in the run instead of guessing at it.

Both read the save and never write to it. Point either one at your live save if you like. The worst case is a bad output file, not a bricked character.

There is a third way to use this repo, and it has nothing to do with saves at all. **The `db_*/` folders are a curated Souls data set** — item ID tables for four games, bonfire tables, boss-defeat flag tables, NPC questline flags, covenant flags, boss-soul-to-boss maps. They are plain JSON with no dependency on the parser. If you are building a randomizer, a wiki scraper, a speedrun tool, a mod, or a Cheat Engine table and you just need "ID 7010900 is a Deep Battle Axe," take the folder and ignore everything else. See **[The data](#the-data-a-curated-souls-json-set)**.

The code lives at **https://github.com/darthdemono/sl2-analyzer**. Every Markdown file it writes carries the repo link and a one-line note on how that game was read, so a summary you pasted somewhere months ago still points back at the tool that made it.

---

## Supported games, and how far each one goes

Not every Souls save is mapped to the same depth in public tooling, so each game is handled at the highest tier it can be *trusted* at. A tier is a promise: everything printed at any tier is read from the save, never guessed. If a number cannot be trusted, it is left out. A wrong stat is worse than a missing one, and that rule decides every judgement call in the code.

| Game | Save file | Supported | Tier | What you get |
|---|---|:---:|---|---|
| Dark Souls: Prepare to Die Edition | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, deep progress |
| Dark Souls Remastered | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, deep progress |
| Dark Souls II: SOTFS | `DS2SOFS0000.sl2` | Yes | **full** | identity, stats, souls, full inventory, deep progress |
| Dark Souls II (vanilla) | `DARKSII0000.sl2` | Yes | **full** | identity, stats, souls, full inventory, deep progress |
| Dark Souls III | `DS30000.sl2` | Yes | **full** | identity, stats, souls, full inventory, deepest progress |
| Elden Ring | `ER0000.sl2` | Yes | **full\*** | identity, attributes, runes, remembrances, owned items (\*item list partial) |

All six FromSoftware `.sl2` variants are supported, and you never tell the tool which game it is: it works that out from the bytes itself.

Vanilla Dark Souls II used to be the one wall, because the Scholar key does not decrypt it and I could not find its own key anywhere. The key turned out to be published after all, in TKGP's SoulsFormats (`SFUtil.GetDS2SaveKey`). Everything else about the two releases is identical — same BND4 layout, same field offsets, same item ids — so once the right key goes in, vanilla reads exactly as deep as Scholar does. Both are told apart automatically by which key decrypts the block.

The asterisk on Elden Ring is honest too. Identity, every attribute, runes held, and remembrances are read straight from the save. The item *list* is partial: owned items come from the GaItem array, so armour, talismans, goods, and base weapons resolve, but a reinforced or affinity weapon bakes the upgrade into its id and misses the base-id table. Per-item quantities are not read either. What is listed is really owned. It is just not the complete stash.

### Field by field

What each game actually surfaces. A blank cell means the field is not readable from that game's save with anything published today, so it is omitted rather than faked.

| | DS1 (PtDE / DSR) | DS2 (both releases) | DS3 | Elden Ring |
|---|:---:|:---:|:---:|:---:|
| Name, level, attributes | yes | yes | yes | yes |
| Souls / runes held | yes | yes | yes | yes |
| Soul Memory | — | yes | — | — |
| Max HP | yes | yes | yes | yes |
| Max FP | — | — | yes | — |
| Stamina | yes | derived | yes | — |
| Derived stats | equip load, attunement slots | full panel, verified byte-exact | slots, equip load, item discovery | — |
| Starting class | yes | yes | — | — |
| Gender | yes | yes | — | — |
| Covenant worn | — | yes | yes | — |
| Covenants found + rank | — | yes (rank 0–3) | yes (join + rank rewards) | — |
| Play time | yes | yes | yes | — |
| Deaths | yes | yes | — | — |
| Hollowing | humanity | yes | embered flag | — |
| Playthrough (NG+) | DSR only | yes | yes | — |
| Inventory, named | yes | yes, with `+N` and infusion | yes | partial |
| Equipped gear | — | — | weapons, armour, rings, ammo | — |
| Bonfires | 43, named, with kindle level | 77, named, by area | 77, named, by area | — |
| Boss defeats by flag | 12 | 6 | 25 | — |
| Boss defeats by held soul | yes | yes | yes | yes |
| Boss defeats by gate / NG+ | yes | yes | yes | gate only |
| NPC questline rewards | — | — | 58 NPCs, 101 rewards | — |

---

## The data: a curated Souls JSON set

This started as tables the parser needed. It ended up being the part of the repo most likely to be useful to somebody who never touches a `.sl2`. So it is documented properly here, as a data set in its own right.

Everything below is plain UTF-8 JSON, no schema files, no build step, no dependency on the Python or the JavaScript. Clone the repo, take the folder you want, delete the rest.

### Item name tables

Four games, three ID schemes, because the games do not agree with each other.

| Folder | Files | IDs | Key scheme |
|---|---|---:|---|
| `db_ds1/` | `MeleeWeapons`, `Armor`, `Rings`, `Consumables` | 862 | **name-keyed**, decimal ID as a string: `{"Dagger": "100000"}` |
| `db_ds2/` | `weapons`, `armors`, `rings`, `spells`, `bolts`, `upgrade`, `consumables`, `online`, `emotes`, `key`, `bosssouls` | 1,336 | **id-keyed**, little-endian hex with spaces: `{"40 42 0F 00": "Dagger"}` |
| `db_ds3/` | `weapons`, `armors`, `rings`, `spells`, `goods`, `bolts` | 3,288 | **name-keyed**, decimal integer: `{"Torch": 90000}` |
| `db_er/` | `weapons`, `armors`, `talismans`, `goods`, `ashes` | 2,668 | **id-keyed**, 8-digit hex: `{"000F4240": "Dagger"}` |

Three details that will bite you if you assume they work like each other:

**DS2 is id-keyed on purpose.** One DS2 item name owns several IDs — a base form plus its reinforced, infused, and variant forms. There are four separate "Prisoner's Hood" IDs. A name-keyed file collapses those to one and silently drops whichever variant the save actually holds, so the key is the ID and every variant gets its own line. The hex keys carry spaces because they were transcribed that way from the SOTFS compendium; strip whitespace before decoding (Python's `bytes.fromhex` already ignores it, JavaScript does not).

**DS1 and DS3 numbers repeat across categories,** which is why the tables are kept per category instead of merged into one flat map. Category scoping is what stops an armour ID resolving to a weapon.

**Elden Ring encodes the type in the ID itself.** The top nibble is the item type: `0x0` weapons, `0x1` armour, `0x2` talismans, `0x4` goods, `0x8` Ashes of War. The key keeps that nibble, so a lookup is scoped by construction and cross-type collisions cannot happen. If you only want the master list, concatenating the five files is safe.

Upgrade arithmetic, where the games bake it into the ID rather than storing it separately:

- **DS1 and DS3:** `id = base + infusion*100 + level`, base ends in `000`. A Deep Battle Axe +1 in DS3 is `7010000 + 900 + 1 = 7010901`. DS1 rings are stored at 1/1000 of their real ID, so they resolve through `id // 1000`.
- **DS2:** the ID does *not* move. A +10 weapon keeps its base ID; reinforcement is the low byte of the uint32 at record `+12` and infusion is the byte at `+13` (`1` Fire, `2` Magic, `3` Lightning, `4` Dark, `5` Poison, `6` Bleed, `7` Raw, `8` Enchanted, `9` Mundane).
- **Elden Ring:** reinforced and affinity IDs step by `ER_WEAPON_BASE_STEP`, and the base is recovered with `id - id % step`. The exact upgrade level is not read.

### Progress tables

These are the interesting ones, and they took a lot more work than the item lists.

| File | Shape | Count | What it is |
|---|---|---:|---|
| `db_ds1/bonfires.json` | `{netbonfiredb_id: [name, area]}` | 43 | Every DS1 bonfire, with the area it belongs to |
| `db_ds1/boss_flags.json` | `{boss: [region_offset, uint32_mask]}` | 12 | Boss-defeat event flags, offsets relative to the DS1 flag region |
| `db_ds1/boss_souls.json` | `{soul_item: boss}` | 16 | Boss soul → the boss that drops it |
| `db_ds2/bonfires.json` | `{id_hex: name}` | 77 | Every DS2 bonfire, keyed by the low 16 bits of its world-block ID |
| `db_ds2/bonfire_areas.json` | `{id_hex: area}` | 77 | The same IDs mapped to their area |
| `db_ds2/boss_flags.json` | `{world_offset_hex: boss}` | 6 | The six DS2 boss-defeat flags that could be isolated |
| `db_ds2/boss_souls.json` | `{soul_item: boss}` | 43 | Every main-game and DLC boss soul |
| `db_ds2/images.json` | `{item_name: filename}` | 600 | Verified fextralife image filenames, for a UI |
| `db_ds3/bonfires.json` | `{area: [[dist, bit, name]]}` | 77 in 14 areas | Every DS3 and DLC bonfire, as a save byte-offset and bit |
| `db_ds3/boss_flags.json` | `{boss: [dist, bit]}` | 25 | Boss-defeat flags, same addressing |
| `db_ds3/boss_victory.json` | `{boss: [dist, bit]}` | 26 | The `63xx` boss-victory flags — a second kill signal that, unlike the per-map flags, survives an NG+ reset |
| `db_ds3/lord_cinders.json` | `{lord: [dist, bit]}` | 1 | The flag set when a Lord's Cinders go on the Firelink throne. Only Abyss Watchers is pinned; the other three need their own differentials |
| `db_ds3/boss_souls.json` | `{soul_item: boss}` | 22 | Boss soul → boss |
| `db_ds3/covenants.json` | `{covenant: [[dist, bit, what it proves]]}` | 8 / 20 flags | Join and rank-reward flags per covenant |
| `db_ds3/questlines.json` | `{npc: [[dist, bit, reward]]}` | 58 / 101 flags | NPC quest reward flags |
| `db_er/boss_souls.json` | `{remembrance: boss}` | 14 | Remembrance → the boss that drops it |

The DS3 tables store `[dist, bit]` rather than a flag ID, because the ID-to-byte conversion is not obvious and doing it once at generation time means a consumer does not need the formula. `dist` is a byte offset from the start of that slot's event-flag region and `bit` is the bit index within the byte, MSB-first. The formula that produced them is documented below, so you can regenerate the tables for any other flag you care about.

DS1's boss flags use a `uint32` mask instead of a bit index, because DS1's own published addressing is word-oriented. Same idea, different unit.

**A note on what these tables mean.** A boss-defeat flag being set is proof the boss is dead. A flag *not* being set is not proof it is alive — it may just be unmapped. Every table here is a floor. Build on that assumption and you will not print something false.

### Reading a table without the tool

```python
import json
weapons = json.load(open("db_ds3/weapons.json"))     # {"Torch": 90000, ...}
by_id  = {v: k for k, v in weapons.items()}
print(by_id[7010000])                                 # Battle Axe

er = json.load(open("db_er/weapons.json"))            # {"000F4240": "Dagger", ...}
print(er["%08X" % 0x000F4240])                        # Dagger
```

```javascript
const ds2 = await (await fetch("db_ds2/weapons.json")).json();
// keys are spaced little-endian hex; normalise before comparing
const norm = h => h.replace(/\s+/g, "").toUpperCase();
const table = Object.fromEntries(Object.entries(ds2).map(([k, v]) => [norm(k), v]));
console.log(table["40420F00"]);                       // Dagger
```

### Extending the tables

Every tier the tool reaches is limited by two things only: offsets and item tables. Both are just files, so both are yours to extend. Drop a game's tables into its `db_*` folder and both front ends resolve the names on the next run — there is no registry to update and no code to touch, as long as you keep the folder's key scheme.

The one remaining item gap is Elden Ring's list: no quantities, and reinforced or affinity weapons still miss the base-ID table.

### Provenance and licensing

I did not extract any of these from the games myself. They are transcribed, reconciled, and cross-checked from community sources, and where two sources disagreed I say which one won and why in `CLAUDE.md`'s change log. The originals:

- **DS1 items** — Paramdex (`ds1_item_ids.csv`), reconciled against the older alfizari tables. Where both carry an ID, the alfizari name wins, because it disambiguates duplicates that Paramdex leaves ambiguous (seven identical "Fire Keeper Soul" rows, two "Traveling Gloves").
- **DS1 bonfires and flags** — Paramdex + DSR-Gadget, cross-checked against a real all-bonfires save.
- **DS2 items** — the SOTFS Hex Code Compendium, sectioned into categories. That source covers every ID a DS2 save can hold, which is why DS2 reports zero unknown items on real saves.
- **DS2 bonfires, class, covenant** — the Jappi88 DS2 save editor and the SOTFS Cheat Engine tables, then pinned against differential saves.
- **DS2 bonfire areas** — the fextralife Bonfires page, cross-checked against the ID clusters (each ID's high byte groups by map file, and every cluster resolved to exactly one map's worth of areas).
- **DS3 flags** — FrankvdStam/SoulSplitter's flag lists, cross-checked against The-Grand-Archives Cheat Engine table. 60 of 60 bonfire names agree between the two.
- **Elden Ring items** — the ER TGA Cheat Engine table's master list, split by type nibble.

Two of these carry licence weight worth knowing about. SoulSplitter is **GPLv3**; the flag *lists* were used as a reference to compute offsets, and what ships here is derived data, but if you are redistributing verbatim tables in a closed product, go read their licence first. The Cheat Engine tables and the compendium have no stated licence at all, which is the usual state of affairs in this scene. I am not going to pretend that is settled.

---

## The reference: what took the longest to find

The tables above are the output. This section is the input — the keys, formulas, and offsets that make a `.sl2` readable at all. Most of it is scattered across half a dozen repos, a wiki, and some Cheat Engine tables. Collecting it in one place is half the value of this repo.

### Keys

The keys are not secrets. FromSoftware ships them inside the games, so "decryption" here is reading a documented format with a key everyone already has.

| Game | Key |
|---|---|
| Dark Souls II (SOTFS) | `599F9B699640A55236EE2D70835EC744` |
| Dark Souls II (vanilla) | `B7FD463E4A9C1102DF1739E5F3B2A50F` |
| Dark Souls Remastered | `0123456789ABCDEFFEDCBA9876543210` |
| Dark Souls III | `FD464D695E69A39A10E319A7ACE8B7FA` |
| PtDE, Elden Ring | not encrypted |

The vanilla DS2 key is the one that is hard to find; it lives in TKGP's SoulsFormats as `SFUtil.GetDS2SaveKey`, distinct from `GetScholarSaveKey`. The source that supplied it also warns that vanilla and Scholar slot sizes and internal offsets differ. That is **false** for the save file. I checked rather than believed it: identical BND4 entry count and sizes except one non-character block, name at the same offset, and DS2's own level identity holding on both. There is exactly one DS2 offset map.

### The container

A `.sl2` is a `BND4` archive. Inside sit a handful of entries — one per character slot, plus a header slot and some world slots — each wrapped as `[16B MD5 checksum][16B IV][payload]`.

One catch worth knowing if you build on this: the cipher is raw **AES-128-CBC with no padding**. The browser's own `WebCrypto` cannot do that; its AES-CBC forces PKCS#7 and throws on Souls ciphertext. That is why the web app ships its own small AES-128 implementation instead of using the platform one.

DS2 wraps its plaintext once more, with a `uint32` length prefix at `+0` and data at `+4`. Requiring `0 < length <= len(plaintext) - 4` is what lets you tell the two DS2 releases apart: try both keys, and the one that produces a sane length prefix is the right one. Skip that check and a wrong key hands you noise, which world-block readers will happily interpret as set event flags. That bug produced six bogus "confirmed" boss kills before it was caught.

### Locating a stat block that moves

Where an offset is stable, read it. Where it moves, find the block by a fact only the real block satisfies. The level formulas do that work — cheap to check, almost impossible to hit by accident:

| Game | Identity |
|---|---|
| DS2 | `sum(9 attributes) - level == 53` |
| DS3 | `sum(9 attributes) - 89 == soul level` |
| Elden Ring | `sum(8 attributes) - 79 == in-slot level` |

DSR anchors on a fixed magic byte pattern instead. PtDE has no such pattern, so it anchors on the character name and reuses DSR's distances — the two releases share an identical stat layout.

**The trap this cannot catch:** the identity is order-independent, so a permuted label mapping passes it silently. DS3 shipped with a wrong storage order that the sum check happily accepted, and it was only caught against a real lopsided build. Memory order is not screen order. In DS3, Vitality is stored **last, alone, at +40**, after the other eight. In DS2, Intelligence is `+44`, Faith `+46`, and Adaptability `+48` — not contiguous, and not in display order. Verify against a character with visibly uneven stats, never a maxed or fresh one.

### DS3 event flags: ID to save byte

This is the single most reusable thing in the repo. For flag `f`:

```
group        = f // 1000
n            = f % 1000
word         = n >> 5
byte_in_group = word * 4 + (3 - ((n & 31) >> 3))     # MSB-first WITHIN each uint32
bit_in_byte   = 7 - (n & 7)
```

The byte reverses within each group of four. That is the off-by-a-nibble trap, and it is confirmed against the decompiled `get_event_flag_pointer`.

For **map groups** (`13xxx`–`15xxx`), the Cheat Engine base is `k * 0x500`, and the save offset is one constant delta away:

```
save_distance = ce_byte_addr + 111
```

Verified across all sixteen map groups. Read it at `ds3_event_flag_base(slot) + save_distance`, where the region base is found by walking the variable-length blocks in front of it: GaItem array → inventory / storage / gesture blocks → NG+ header, then `new_game_plus + 0xBCC`, base at `-0x12`.

**Common groups** are not in any base table and each one has to be derived. The method: take a differential that flips one known common flag, find the **persistent** 0→1 bit (0→1 across the pair *and* still set in a much later save — the persistence filter kills map-flag movement noise), then `base = flip_offset - byte_in_group(flag)`. Two are pinned so far:

| Group | Base | Anchor |
|---|---:|---|
| `50006` (NPC rewards) | 86639 | Hawkwood's Heavy Gem, flag `50006070` |
| `6` (covenants) | 879 | Rosaria's Fingers emblem, flag `6760` |

The bulk world-pickup groups (`530xx`–`555xx`) are **not** derivable this way without their own anchor, and three separate scoring methods failed on them. Never ship a base picked by score — a wrong one invents item pickups out of nothing.

### DS1 event flags

DS1's addressing is public; where the region sits in the *save* is not.

```
offset = group_base + area*0x500 + section*128 + ((number - number % 32) / 8)
mask   = 0x80000000 >> (number % 32)
```

Group bases: `0 → 0`, `1 → 0x500`, `5 → 0x5F00`, `6 → 0xB900`, `7 → 0x11300`. Identical between PtDE and DSR.

The region's own position in the slot had to be searched for: **PtDE `127273`, DSR `127721`**. Found by taking an NG+2 all-bonfires save, where every boss must be dead, and looking for the one offset where all twelve boss flags and both Bells of Awakening read set. Guarded by a bit-density check — the true base measures 0.0068 set bits against ~0.32 for ordinary save data, which is what rules out the degenerate "solid `0xFF` matches everything" false positive.

DS1 bonfires are **not** flags. They are a `NetBonfireDb` record list, 20 bytes per record, `[marker 11][id][state][flags][0]`, with state `0/10/20/30/40` = discovered / lit / kindled +1 / +2 / +3. That is why DS1 is the only game here that can tell you a bonfire is discovered but never lit.

### Assorted offsets worth writing down

**DS1** — gender at `magic-237` (`1` = Male, note this is the **opposite polarity to DS2**); deaths at slot-absolute `0x1F118` (PtDE) / `0x1F2D8` (DSR), guarded on a `0xFFFFFFFF` sentinel at `+4`; play time in the load-screen roster, BND4 entry 10, record stride `0x170`, name at `+0`, level at `+36`, play time as a `uint32` of **seconds** at `+40`, block starting at `0x28` (PtDE) / `0xC0` (DSR).

**DS2** — the Jappi88 editor's `SaveBlocks[0]` position 0 equals our slot flat `+32`, which translates every offset that editor publishes. Class `+1024`, covenant `+189`, gender `+378` (`1` = Female), hollowing `+379`, deaths `+104` (mirrored at `+184` and `+7272`). Play time is *not* in the character block — it is in the header title record at `+66`, name at `+0`, level at `+74`, records at `1286 + 496*(entry-1)`. World state for status entry `i` lives in entry `i + 10`. Item records are 16 bytes; the count is the **low uint16** of the field at `+8`, because special items pack state into the high two bytes (the Estus Flask keeps its charge pair there).

**DS3** — everything equipment-related sits at a fixed distance from the Vigor anchor even though the anchor itself moves. EquipGameData at `vigor + 664`; from that base, armour at `+0x20/+0x24/+0x28/+0x2C`, rings at `+0x34/+0x38/+0x3C/+0x40`, ammo at `+0x08/+0x0C/+0x10/+0x14`, and the six weapon slots *interleaved and starting before it*: `LH1 -0x10, RH1 -0x0C, LH2 -0x08, RH2 -0x04, LH3 +0x00, RH3 +0x04`. Armour, ammo and weapons hold GaItem **handles** that resolve through the GaItem array; rings do not appear in that array at all, and instead a ring's handle encodes its ID directly — `id = (handle & 0x0FFFFFFF) | 0x20000000`. Covenant is a worn accessory, so it is a `uint32` handle at `vigor + 3944` whose low 28 bits are the covenant item ID. Embered is a lone boolean at `vigor + 188`. Max HP at `vigor - 40`, max FP at `vigor - 28` (each stores a current/max pair; those are the max copies). Play time is in the roster descriptor at `+38`, a `uint32` of seconds.

### The method behind all of it

Two techniques account for nearly every offset here, and neither is guesswork.

**Read somebody else's source first.** The vanilla DS2 key, DS1 gender, DS1 deaths, and DS1 play time were all sitting in public repositories the entire time they were listed as blockers. Before booking an experiment, go read the editors. And when a field exists in only one foreign source, **validate that source's frame before trusting the field** — dsfp's deaths offset was only trusted after its frame was shown to reproduce this parser's name, level, and gender on a real save. That check costs one script and catches a wrong frame immediately.

**Otherwise, take a differential.** One save before, one save after, exactly one thing changed. That is how DS2's class, covenant, gender, play time, and deaths were pinned, and how DS3's covenant, embered flag, weapon slots, and reinforcement scheme were pinned. A single labelled save cannot isolate a byte; a pair with one variable can. Two independent sources agreeing can substitute for a differential, and that is exactly what made DS1's gender polarity shippable when one editor alone would have left it unverified.

---

## The progress it can work out

Bosses and areas are not printed from a "bosses beaten" counter, because no such honest counter is readable. They are *inferred*, and inference here follows one rule: the progress shown is a floor, not a ceiling. Everything on the list is real. There may be more you have already cashed in that the save can no longer prove.

Every game gets the baseline: **boss souls and remembrances still held.** You cannot own a boss's soul without killing it, so a held soul is a certain kill. The web app and the Markdown both name the boss, not just the soul item. Spend the soul and the kill goes invisible, which is exactly why this is a floor.

**Dark Souls III goes deepest,** because its event flags turned out to be in the save after all:

- **Bonfires, all 77 named.** Not counted, named. Every base-game and DLC bonfire resolves to its own name, grouped by area. A real early save reads Cleansing Chapel, Deacons of the Deep and Cathedral of the Deep under Cathedral, Firelink Shrine, Cemetery of Ash and Iudex Gundyr under Cemetery, and so on.
- **Bosses defeated, from 25 defeat flags,** computed from the authoritative flag list rather than hand-checked. Every computed offset independently reproduced the older hand-verified table, which is mutual confirmation, and the rebuild added Ancient Wyvern, which the old one missed. This is what catches bosses that drop no soul, like Iudex Gundyr, which the soul floor could never see.
- **Bosses defeated again, from a second and independent set of 26 victory flags.** The per-map defeat flags reset when you start NG+; these do not, which is why a finished character reads a full roster where the map flags read nothing. They also cover Stray Demon, which the map table has no entry for. Every one of them was checked against a 36-save ladder and first appears in exactly the snapshot the boss died in.
- **Cinders of a Lord placed on the throne.** One lord so far — Abyss Watchers — pinned by a 46-second save pair either side of the offering. The other three are not guessed at; each needs its own pair.
- **NPC questlines.** 58 NPCs, 101 reward flags — what Hawkwood, Greirat, Siegward, Leonhard, Yuria and the rest have actually handed over. On a real early save this reads eleven coherent NPCs and zero late-game or DLC false positives.
- **Covenants found**, with join and rank-reward flags, alongside the covenant currently worn.
- **Equipped gear** — both hands' weapons with their reinforcement level, all four armour slots, all four rings, and ammo. Every slot is gated on the resolved ID landing in the right category, so a stray handle drops out instead of printing a weapon in a helmet slot.
- **Embered, play time, max FP, NG+.** Reaching NG+ proves every unskippable boss on the road to Soul of Cinder dead, even ones whose souls were long since spent.

**Dark Souls II is nearly as deep,** and its progression inference is the most elaborate of the lot:

- **Bonfires, all 77 named and grouped by area**, read out of a separate world block rather than the character block.
- **Bosses defeated, from three independent signals**, each certain when it fires, merged per boss so overlap reads as corroboration. A **flag** is a mapped defeat event in the world block. A **soul** is the boss soul still in your pack. A **gate** is progression — a bonfire or item you could not have reached without the kill, plus the mandatory predecessors that chain implies. The gate logic is deliberately endgame-only. DS2's mid-game is four parallel, largely skippable paths, so a mid-game gate would risk claiming a kill you never made, and a false kill breaks the whole rule.
- **Class, covenant with rank, gender, hollowing, deaths, play time**, all pinned with differential saves rather than guessed. An unknown covenant ID is dropped rather than shown wrong.
- **A full derived-stats panel** — stamina, equip load, agility with its roll i-frames, poise, attack ratings, elemental defences — every one verified byte-exact against a real in-game screen.

Only 6 of DS2's ~41 boss flags are mapped, and that is not for lack of trying. The community's 41-boss save set is one mule teleported to each arena with that boss resurrected, so only the six it actually resurrects produce a differential; the rest are dead in every folder. Several scanners were written to attack this from other angles and all of them came back negative. It needs a playthrough that kills one boss per save, and nothing else will do.

**Dark Souls 1 (both releases) reads far more than the soul floor.** Bonfires are not flags there — the game keeps a record list carrying each one's state — so DS1 is the only game that can tell you a bonfire is *discovered but never lit*, and how far each one is kindled. Twelve bosses have usable defeat flags. Alongside those: play time and soul level from the load-screen roster, total deaths, gender, and the derived values that are pure attribute functions. The other fifteen bosses stay on the soul and NG+ floor, because their rows in the published flag list are enum indices, not event flags.

**Elden Ring** gets the soul floor plus the endgame-gate idea. Hold the Remembrance of Hoarah Loux and Maliketh, the Fire Giant, and Morgott fall with it, because that chain is forced. Only strictly-linear, cannot-skip endgame chains qualify, for the same reason DS2's gates are endgame-only.

What it still does **not** do is read boss-defeat event flags for **Elden Ring**. ER keeps its flags in a runtime structure that tools read out of the live game's process, and no published editor maps how that block lands in the `.sl2` — the DS3 breakthrough was a save editor that did exactly that, and no equivalent for ER has surfaced. So on ER a consumed soul with no gate stays off the list. Honest floor, not a guess.

---

## The web app

The page is one static bundle. There is no backend, no upload, no analytics call. You drop a file, JavaScript reads it in the tab, and that is the end of it. Host it on any static host — it is built to run straight off GitHub Pages — or open it from a local server.

Instead of generic charts, each character is drawn as a replica of that game's own **Level-Up screen** — the screen you already know from playing it:

- **A framed stat panel, skinned per game.** DS1 and Elden Ring get the gold menu; DS2 the cold steel-blue; DS3 the ashen grey. A metallic title bar carries the name, slot, and support tier; the left column lists level, souls or runes, max HP and FP, then the attributes in the game's own on-screen order.
- **Derived stats where they exist** — the full verified panel for DS2, the three closed-form values for DS3, equip load and attunement slots for DS1. Fields the real screen shows but the save cannot prove (weapon AR, bonuses, resistances) are left off, not faked.
- **An Attribute Scaling reference**, folded away beside the sheet: what each attribute governs in that game and where it soft-caps, next to your own value. It is documented mechanics rather than anything read from the save, and it says so.
- **Bonfire completion as a fraction.** "22 of 77", with a bar. The denominator is real because the bonfire tables are complete for every game that has one. Bosses deliberately get no such fraction — those tables are a mapped subset, so a percentage would imply a roster the data cannot back.
- **A tab per character** when a save holds more than one, so a ten-slot mule is readable instead of ten stacked sheets. Arrow keys move between them.
- **Item thumbnails for DS2**, pulled from the wiki so the inventory reads like the in-game menu. This is the one thing that leaves your browser: the save is still never uploaded, but each thumbnail request tells the wiki's image host which item it was for. The privacy note on the page says so.
- **Copy Markdown, or download it.** Either button emits the exact same Markdown the Python CLI writes, for every character in the file — not just the tab you are looking at.

Three things make it quick. Parsing runs in a **Web Worker**, so a big save never freezes the tab. The game is detected from the archive header *before* any table is fetched, so dropping a DS3 save loads eleven files instead of all forty. And a **service worker** caches the page, its code and the tables you have used, so after the first visit it works with no connection at all — which suits a tool that already does all its work locally. The thumbnails are excluded from that cache on purpose: they are the one request that leaves the browser, and storing them would outlive the tab.

That last point is not a coincidence. The web app is a faithful port of the Python reader, and both are held to it: the JavaScript parser is checked byte-for-byte against the Python tool's output for every test save, and the browser's Markdown is checked byte-for-byte against the CLI's Markdown. If they ever drift, the check fails. Two front ends, one source of truth.

---

## How to run it

**The web app.** Open the hosted page, or serve the folder yourself. It uses ES modules and `fetch`, so it needs a real server, not a `file://` open:

```bash
python3 -m http.server 8000
# then open http://localhost:8000/
```

To put it online, push the repo and turn on GitHub Pages. There is a workflow at `.github/workflows/pages.yml` that packages the repo root on every push to `main`, so the one manual step is Settings → Pages → Source = **GitHub Actions**. Until that is switched, every run fails at the deploy step. The `.nojekyll` file is already there so Pages serves the `app/` and `db_*` folders as-is.

**The CLI.** You need Python 3 and one library, `cryptography`:

```bash
git clone https://github.com/darthdemono/sl2-analyzer
cd sl2-analyzer
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

### JSON, if something other than a person is reading it

Give `-o` a `.json` extension and you get the same data as a machine-readable document instead of Markdown. `--format json` forces it if your output path does not end in `.json`.

```bash
python3 sl2_to_md.py "/path/to/DS30000.sl2" -o run.json
```

The document is described by [`schema.json`](schema.json), published at <https://darthdemono.github.io/sl2-analyzer/schema.json> and referenced from every export's `$schema` key, so a validator picks it up with no configuration. Both formats come out of the same read, so they cannot disagree.

The one rule worth knowing before you consume it: **absence is meaningful.** A field appears only when it was actually read from the save. Dark Souls III stores no death counter, so a DS3 character has no `deaths` key at all — not `0`, and not `null`. That way you can always tell "this game does not record it" from "it really is zero". The same goes for progress: every section is a floor, reporting what the save proves rather than what it rules out.

### Recording how the game was run

A save knows your character. It does not know which store sold you the game, which patch it ran, or whether it was Proton or Windows — and none of that can be inferred from the bytes. So you can attach it yourself with `--meta key=value`, repeated as often as you like:

```bash
python3 sl2_to_md.py DS30000.sl2 -o run.json \
  --meta source=Steam --meta version=1.15.2 \
  --meta os="Nobara 43" --meta launcher=Heroic \
  --meta proton="GE-Proton9-20" --meta gamemode=yes --meta mangohud=no \
  --meta dlc="Ashes of Ariandel" --meta dlc="The Ringed City"
```

Any key is accepted — the schema names the common ones (`source`, `version`, `dlc`, `os`, `launcher`, `proton`, `gamemode`, `mangohud`, `notes`) but does not restrict you to them. Keys are lowercased with spaces and dashes folded to underscores, so `--meta "Proton version=..."` and `--meta proton_version=...` are the same key. **Repeat a key and it becomes a list** — that is how the two DLCs above end up as an array, with no comma-splitting to get wrong (Souls item names are full of commas). `--meta-json path.json` merges an object from a file underneath anything you pass on the command line.

In JSON this lands under `environment`. In Markdown it becomes a **Setup** block inside the closing details, labelled as supplied rather than read — because it is the one part of the output that did not come out of the save.

To convert a whole folder of saves in one go, loop over them:

```bash
for f in *.sl2; do
  python3 sl2_to_md.py "$f" -o "output/$(basename "${f%.*}").md"
done
```

Where do the saves live? On Windows they are under `%APPDATA%` (`C:\Users\<you>\AppData\Roaming\<game>`). On Linux the game runs inside a Wine/Proton prefix, and every launcher mirrors that same `AppData\Roaming\<game>` tree inside its prefix. So you are always looking for the same tail, `.../pfx/drive_c/users/<user>/AppData/Roaming/<game>/*.sl2`, under whichever launcher put it there:

- **Steam (Proton):** `~/.local/share/Steam/steamapps/compatdata/<appid>/pfx/drive_c/users/steamuser/AppData/Roaming/<game>`
- **Heroic (Epic / GOG):** `~/Games/Heroic/Prefixes/default/<Game>/pfx/drive_c/users/steamuser/AppData/Roaming/<game>` (older installs use `~/.config/heroic/prefixes/...`)
- **Lutris / plain Wine:** `~/.local/share/lutris/<game>/pfx/...` or `~/.wine/drive_c/users/<you>/AppData/Roaming/<game>`

The no-argument auto-detect already searches all of these, so on most setups you can just run it with no path. Copy the `.sl2` out first if you would rather not touch the live folder, though you do not have to: the tool only ever reads.

---

## What the Markdown looks like

One `.md` per save. A short header naming the source, one section per character, and a closing block that says what the tool is and how far to trust it — the boilerplate sits at the end, out of the way of the save's own numbers. Below is a real file, cut only where the inventory ran long. The `>` note in the closing block is what makes an old summary self-documenting: it names the repo and states, in plain English, how that specific game was read. It is one long line in the real output; it is wrapped here so it fits on the page.

````markdown
# Dark Souls III — Playthrough Save Summary

_Source: `JoyDS3.sl2` · generated 2026-07-31 04:21 · sl2_to_md_

---

## Slot 1: Joy

- **Soul Level:** 38
- **Covenant:** Rosaria's Fingers
- **Playthrough:** New Game
- **Play Time:** 12:32:11
- **Souls held:** 2,773
- **Max HP:** 900
- **Embered:** No  _(hollow — Max HP above is the base value)_
- **Max FP:** 72
- **Stamina:** 108
- **Build:** strength-focused melee

### Attributes

| VGR | ATN | END | VIT | STR | DEX | INT | FTH | LCK |
|----|----|----|----|----|----|----|----|----|
| 22 | 6 | 18 | 18 | 26 | 9 | 8 | 9 | 11 |

<details>
<summary><b>Attribute Scaling</b> — what each stat scales and its soft caps (game-mechanics reference, not read from this save)</summary>

- **Vigor** (22) — Max HP. Soft caps ~27 & 50; ~1,300 HP at 50, only ~100 more to 99.
- **Endurance** (18) — Stamina. Stamina soft cap 40.
- **Strength** (26) — Physical attack, strength-weapon scaling. Scaling soft caps 40 & 60.
- **Luck** (11) — Item discovery, bleed/poison buildup, hollow-weapon scaling. +1 item discovery/pt (base 100); bleed/poison speed soft cap 50.

</details>

### Derived Stats  _(computed from attributes — base values before rings, covenant & equipment)_

- **Attunement Slots:** 0
- **Equip Load (max capacity):** 58.0
- **Item Discovery:** 111

### Key Items  _(progress / areas & shortcuts unlocked)_

- Cell Key
- Small Lothric Banner
- Grave Key
- Tower Key
- Deep Braille Divine Tome

### Bonfires Discovered (22 of 77, in 6 of 14 areas)  _(bonfires lit, inferred from each area's flag bits — a floor)_

- High Wall of Lothric: 3/5 — Vordt of the Boreal Valley, Tower on the Wall, High Wall of Lothric  _(missing: Oceiros, the Consumed King · Dancer of the Boreal Valley)_
- Lothric Castle: 0/5
- Undead Settlement: 3/5 — Undead Settlement, Dilapidated Bridge, Foot of the High Wall  _(missing: Pit of Hollows · Cliff Underside)_
- Cathedral of the Deep: 4/4 — Cleansing Chapel, Deacons of the Deep, Rosaria's Bed Chamber, Cathedral of the Deep
- Catacombs of Carthus: 0/6
- Cemetery of Ash: 3/5 — Firelink Shrine, Cemetery of Ash, Iudex Gundyr  _(missing: Untended Graves · Champion Gundyr)_

### Covenants Found (4 of 9)  _(discovered — a floor; the one currently worn is the Covenant field above)_

- **Warrior of Sunlight:** joined (emblem found)
- **Blue Sentinels:** joined (emblem found)
- **Rosaria's Fingers:** joined (emblem found)
- **Way of Blue:** joined (emblem found)

_Not found yet: Aldrich Faithful · Blade of the Darkmoon · Mound-makers · Spears of the Church · Watchdogs of Farron._

### Rewards Obtained  _(one-off rewards from NPCs, invaders and landmark pickups — a progress floor)_

- **Yuria of Londor:** Londor Braille Divine Tome
- **Hawkwood the Deserter:** Heavy Gem
- **Ringfinger Leonhard:** Cracked Red Eye Orb
- **Greirat of the Undead Settlement:** Blue Tearstone Ring
- **Siegward of Catarina:** Siegbräu
- **High Priestess Emma:** Small Lothric Banner
- **Sword Master:** Uchigatana

### Bosses Defeated (5 of 26 tracked)  _(a floor — from defeat flags, held boss souls, progression, and NG+ clears; a boss whose soul was consumed and isn't gated may still be missing)_

- Vordt of the Boreal Valley  _(confirmed, soul held)_
- Stray Demon  _(confirmed, soul held)_
- Crystal Sage  _(confirmed, soul held)_
- Deacons of the Deep  _(confirmed, soul held)_
- Iudex Gundyr  _(confirmed, progression)_

_No evidence yet: Abyss Watchers · Aldrich, Devourer of Gods · Ancient Wyvern · Champion Gundyr · Curse-Rotted Greatwood · Dancer of the Boreal Valley · High Lord Wolnir · Lothric, Younger Prince · Nameless King · Old Demon King · Pontiff Sulyvahn · Soul of Cinder · Yhorm the Giant._

### Equipped  _(worn gear read from the equip slots)_

- **Right Hand:** Greataxe +1
- **Head:** Northern Helm
- **Chest:** Sellsword Armor
- **Hands:** Northern Gloves
- **Legs:** Cleric Trousers
- **Rings:** Life Ring, Covetous Silver Serpent Ring, Estus Ring, Lloyd's Sword Ring
- **Ammo:** Standard Arrow, Exploding Bolt, Heavy Bolt

### Inventory

#### Weapons

- Round Shield
- Battle Axe
- Lucerne
- Astora Straight Sword
- Uchigatana

#### Boss Souls

- Soul of Boreal Valley Vordt
- Soul of a Stray Demon
- Soul of a Crystal Sage
- Soul of the Deacons of the Deep

---

<details>
<summary>About this file — how it was produced, and how far to trust it</summary>

- **Game:** Dark Souls III
- **Support tier:** full
- **Character slots read:** 1

> Automated dump of the save. Code Repo: https://github.com/darthdemono/sl2-analyzer .
> How it works for Dark Souls III: the save is locked with AES-128 encryption, key
> shipped in the game, so the tool unlocks it first. The stats do not sit at a fixed
> position, and that position moves between game patches, so instead of trusting a
> location the tool searches for the stat block by its content: it looks for the run of
> nine numbers that, added together, equal the character's stored level — a rule the
> game itself follows, which makes a wrong match almost impossible. Items are found by
> scanning the slot for known IDs and matched to names.

</details>
````

Every progress section carries its denominator and the names still missing — that negative space is half the report. An area sitting at `0/6`, and the two bonfires you walked past in one at `3/5`, are the things a list of what you *found* can never tell you.

The other games slot their own fields into the same shape. DS2 adds Class, Gender, Soul Memory, Hollowing, Deaths, and a full derived-stats panel, and its inventory carries reinforcement and infusion in the name:

```markdown
- **Soul Level:** 88
- **Class:** Knight
- **Covenant:** Way of Blue
- **Gender:** Female
- **Soul Memory:** 675,393  _(total souls earned — main progress metric)_
- **Deaths:** 122

### Bonfires Discovered (33 of 77, in 17 of 34 areas)  _(each bonfire the save records as discovered, by area — a floor)_

- Things Betwixt: 1/1 — Fire Keepers' Dwelling
- Majula: 1/1 — The Far Fire
- Forest of Fallen Giants: 3/4 — Cardinal Tower, Soldiers' Rest, The Crestfallen's Retreat  _(missing: The Place Unbeknownst)_

### Covenants Found (1 of 9)  _(discovered — a floor; the one currently worn is the Covenant field above)_

- **Way of Blue:** rank 3 of 3

#### Weapons

- Fire Longsword +6
```

DS1 is the only one that reports how far each bonfire is kindled, because it is the only one that stores it:

```markdown
### Bonfires Discovered (38 of 43, in 22 of 24 areas)  _(each bonfire's own record, with how far it is kindled — a floor)_

- Firelink Altar: 1/1 — Firelink Altar - Lordvessel (kindled +3)
- Firelink Shrine: 1/1 — Firelink Shrine (kindled +1)
- The Abyss: 1/1 — The Abyss (discovered)
- Catacombs: 2/2 — Catacombs 2 (illusory wall) (lit), Catacombs 1 (necromancer) (lit)
```

Where a field cannot be trusted, the file says so instead of dropping it silently. An Elden Ring slot whose stat block fails the level identity prints this and carries on with what it *can* read:

```markdown
## Slot 1: Hee Yai

- **Level:** 5

_Attributes are not printed for this slot: its stat block did not validate (an
unrecognised patch or an edited save), and a wrong number is worse than none. Inventory
and progress below are read directly._
```

The inventory mirrors the in-game item menu: one heading per category, boss souls split into the four "Old" great souls and the ordinary ones, and special items carrying their state, so the Estus Flask shows its charge count. Paste the whole file into a model and ask it to plan your next steps, tune your build, or tell you what you missed. It has the facts now.

---

## The honest limitations

Said out loud rather than papered over:

- **Progress is a floor, not a ceiling.** Covered above. A spent soul with no flag and no gate is a kill the save can no longer prove, so it is not listed.
- **Boss-defeat flags for Elden Ring are not read.** ER keeps them in a runtime structure and no public editor maps them into the save. DS1's, DS2's and DS3's flags *are* read, so only ER falls back to the soul-and-gate floor for kills.
- **DS2 has only 6 of ~41 boss flags mapped.** Not for lack of effort — the available save set produces no differential for the other thirty-five, and three separate scanning approaches came back empty. Soul and gate inference covers most real cases; a mid-game boss whose soul you consumed can still be missing.
- **Upgraded gear in DS1's scanned inventory is not named with its level.** DS1 bakes the reinforcement into the item ID and its scan-based inventory carries base IDs. **DS3 no longer has this problem in either place** — the held inventory turned out to store the exact `base + infusion*100 + level` ID, same as the equip slots, so a held `Greataxe +6` reads as such rather than dropping out. DS2 never had it: its tables are built from the full SOTFS ID list, so reinforced and infused variants all resolve by name. Elden Ring is the reverse, where reinforced-weapon IDs fall back to the base name.
- **DS3 has no starting class, gender, or Dark Sigil level,** and no published editor reads them either, so there is nothing to port. Each needs its own differential save.
- **Scholar-only content is absent from a vanilla DS2 save,** which is the game's doing, not the tool's. The two releases share one ID table, so a vanilla save simply never carries the items and bonfires Scholar added.

---

## Layout

```
sl2_to_md.py      the entry point; re-exports the package so `import sl2_to_md` still works
schema.json       JSON Schema for the --json export, published at the site root
sl2/              the Python package, one module per layer and one per game
  reader.py       bounds-checked buffer reads; nothing else touches a raw offset
  keys.py         the five AES keys (all of them ship inside the games)
  bnd4.py         the BND4 archive every .sl2 is
  crypto.py       per-game decryption
  detect.py       which game a file is, from its signature and entry count
  itemdb.py       the three item-id schemes
  progress.py     the shared progress floor: boss souls, key items, NG+ clears
  roster.py       the header roster: names, and DS3 play time
  ds1.py ds2.py ds3.py er.py   one module per game family
  totals.py       the "of N" denominators (needs every game's tables, hence its own file)
  render.py       Markdown rendering
  jsonout.py      JSON rendering and the --meta environment block
  convert.py      the driver: parse_save, then either writer
  cli.py          argument parsing and main()
index.html        the web app: markup and styling
sw.js             service worker: caches the app + used tables so it runs offline
manifest.webmanifest / icon.svg   installable-app metadata
.nojekyll         tells GitHub Pages to serve the folders as-is
.github/workflows/pages.yml   deploys the repo root to Pages on push to main
app/
  aes.js          AES-128-CBC decrypt, no padding (WebCrypto refuses raw CBC)
  reader.js       bounds-checked buffer reads, the JS mirror of the Python helpers
  parser.js       the reader ported to the browser, all six save variants
  db.js           loads the item / progress databases, per game and in parallel
  tables.js       shared lookup tables, formatters, per-game attribute order and theme
  render.js       the per-game Level-Up screen replicas (framed panels, DS2 derived stats + thumbnails)
  markdown.js     the browser's Copy-Markdown output
  worker.js       runs detect + load + parse off the main thread
  main.js         file-drop wiring and the inline fallback
db_ds1/*.json     DS1 items (shared by DSR and PtDE), bonfires, boss flags, boss souls
db_ds2/*.json     DS2 items, bonfires + areas, boss flags, boss souls, wiki image map
db_ds3/*.json     DS3 items, bonfires, boss flags, boss souls, covenants, questlines
db_er/*.json      Elden Ring items by type nibble, remembrance map
requirements.txt  the one Python dependency
```

The Python tool and the JavaScript port keep the same offsets and constants. Change one and you change the other, and the parity checks catch it if you forget.

---

## Credits

I did not reverse-engineer these formats from scratch, and I am not going to pretend I did. The keys, offsets, and structures come from people who mapped them first:

- Vanilla DS2 key: [TKGP/SoulsFormats](https://github.com/JKAnderson/SoulsFormats) (`SFUtil.GetDS2SaveKey`).
- DS2 offsets and item tables: [alfizari/Dark-Souls-2-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-2-Save-Editor-PS4-PC).
- DSR, DS3, and ER keys, decryption, and header layout: [jtesta/souls_givifier](https://github.com/jtesta/souls_givifier).
- DS3 stat offsets, play time, and the event-flag region: [alfizari/Dark-Souls-3-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-3-Save-Editor-PS4-PC).
- DS3 bonfire, boss, and item-pickup flag lists: [FrankvdStam/SoulSplitter](https://github.com/FrankvdStam/SoulSplitter) (GPLv3) and [The-Grand-Archives/Dark-Souls-III-CT-TGA](https://github.com/The-Grand-Archives/Dark-Souls-III-CT-TGA).
- DSR and DS1 offsets and item tables: [alfizari/Dark-Souls-Remastered-Save-Editor](https://github.com/alfizari/Dark-Souls-Remastered-Save-Editor), plus [tarvitz/dsfp](https://github.com/tarvitz/dsfp) for the PtDE roster and deaths struct.
- DS1 item IDs, bonfire IDs, and flag addressing: Paramdex and the soulsmodding wiki.
- Elden Ring save structure (GaItem array, profile table): [ClayAmore/ER-Save-Editor](https://github.com/ClayAmore/ER-Save-Editor); the save-slot "File version" word and the in-save regulation block that carries the game patch: [ClayAmore/ER-Save-Lib](https://github.com/ClayAmore/ER-Save-Lib).
- DS2 bonfire, class, covenant, and world-block offsets: the Jappi88 DS2 save editor and the SOTFS Cheat Engine tables.
- Item name lists: the SOTFS Hex Code Compendium (DS2) and the ER TGA Cheat Engine table's master list.
- Derived-stat formulas and bonfire-to-area mappings: fextralife and the Dark Souls wikidot scaling tables.

What is mine: the `.sl2`-to-Markdown idea, the browser front end and its per-game Level-Up screens, the game auto-detection, the tier system and the rule behind it, the content-scan stat finders and the level-formula checks that make them safe, the ID-scan and GaItem-walk inventory readers, the DS1/DS2/DS3 bonfire and multi-source boss inference, the DS3 common-flag base derivations and the questline and covenant tables built on them, the cross-game endgame gates and NG+ clear floors, the differential work that pinned every field no editor publishes, and the byte-for-byte parity between the two front ends.
