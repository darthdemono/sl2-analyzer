# sl2-analyzer

This reads a FromSoftware `.sl2` save and tells you what is in it. That is the whole job.

There are two ways to use it, and they run the exact same reading logic:

- **A web page.** Drop a `.sl2` onto [the site](https://darthdemono.github.io/sl2-analyzer/) and it lays the playthrough out as cards, stat bars, a build radar, and progress lists. It parses the file in your browser. Nothing uploads, nothing hits a server, and the save never leaves your machine.
- **A Python CLI.** Point `sl2_to_md.py` at a save and it writes one Markdown file describing the run. That is the format an LLM can actually read. A `.sl2` is an encrypted binary blob; paste it into a chat and you get nothing. Paste the Markdown and the model knows where you are in the run instead of guessing at it.

Both read the save and never write to it. Point either one at your live save if you like. The worst case is a bad output file, not a bricked character.

The code lives at **https://github.com/darthdemono/sl2-analyzer**. Every Markdown file it writes carries the repo link and a one-line note on how that game was read, so a summary you pasted somewhere months ago still points back at the tool that made it.

## Supported games, and how far each one goes

Not every Souls save is mapped to the same depth in public tooling, so each game is handled at the highest tier it can be *trusted* at. A tier is a promise: everything printed at any tier is read from the save, never guessed. If a number cannot be trusted, it is left out. A wrong stat is worse than a missing one, and that rule decides every judgement call in the code.

| Game | Save file | Supported | Tier | What you get |
|---|---|:---:|---|---|
| Dark Souls: Prepare to Die Edition | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls Remastered | `DRAKS0005.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Dark Souls II: SOTFS | `DS2SOFS0000.sl2` | Yes | **full** | identity, stats, souls, full inventory, deep progress |
| Dark Souls II (vanilla) | `DARKSII0000.sl2` | No | — | unsupported: AES key not public (re-save in SOTFS) |
| Dark Souls III | `DS30000.sl2` | Yes | **full** | identity, stats, souls, full inventory, progress |
| Elden Ring | `ER0000.sl2` | Yes | **full\*** | identity, attributes, runes, remembrances, owned items (\*item list partial) |

Five of the six FromSoftware `.sl2` variants are fully supported. Only vanilla Dark Souls II is out, and you never tell the tool which game it is: it works that out from the bytes itself.

Vanilla Dark Souls II is the one wall I could not get past. Its payload is encrypted with an AES key that has never been published anywhere I could find, and the Scholar of the First Sin key does not decrypt it. So the tool detects it, says so plainly, and stops, instead of printing garbage. Re-save the file in Scholar of the First Sin and it becomes a `DS2SOFS0000.sl2` that works.

The asterisk on Elden Ring is honest too. Identity, every attribute, runes held, and remembrances are read straight from the save. The item *list* is partial: owned items come from the GaItem array, so armour, talismans, goods, and base weapons resolve, but a reinforced or affinity weapon bakes the upgrade into its id and misses the base-id table. Per-item quantities are not read either. What is listed is really owned. It is just not the complete stash.

---

## What a `.sl2` actually is

A `.sl2` is a `BND4` archive. Inside it sit a handful of entries, one per character slot plus a header slot and a few world slots, and each entry is wrapped as `[16B MD5 checksum][16B IV][payload]`. Most of the games encrypt that payload with AES-128-CBC. The keys are not secrets. FromSoftware ships them inside the games, so "decryption" here is just reading a documented format with a key everyone already has.

- **DS2 key:** `599F9B699640A55236EE2D70835EC744`
- **DSR key:** `0123456789ABCDEFFEDCBA9876543210`
- **DS3 key:** `FD464D695E69A39A10E319A7ACE8B7FA`
- **PtDE and Elden Ring:** the payload is not encrypted at all. You strip the 16-byte checksum wrapper and read the plaintext.

One catch worth knowing if you build on this: the cipher is raw AES-CBC with no padding. The browser's own `WebCrypto` cannot do that — its AES-CBC forces PKCS#7 and throws on Souls ciphertext — so the web app ships a small AES-128 implementation instead of using the platform one.

Past that envelope the games stop agreeing with each other, and that disagreement is the entire reason tiers exist. Here is where each one keeps its data:

- **DS2** keeps stats and inventory at fixed offsets. You read them straight off. Item counts hide in the low two bytes of a four-byte field, because special items like the Estus Flask pack their charge state into the high two. So counts are read as a `uint16`, and the Estus keeps its charges to itself.
- **DSR and PtDE** move the character block around, so a fixed offset is useless. Stats are read relative to an anchor that always sits next to the block. DSR keys on a fixed "magic" byte pattern. PtDE has no such pattern, so it anchors on the character name instead. The two games share the identical stat layout, which is why the same distances work once you find the anchor. Inventory is found by a second, game-independent anchor.
- **DS3** hides its stats behind offsets that shift between patches, so guessing an offset is a losing game. Instead the stat block is *found by content*: it is the only run of nine attributes whose sum minus 89 equals the stored soul level. That is DS3's own levelling formula, so a false match is not credible. Item ids are full 32-bit and sparse, so the inventory is found by scanning the slot for known ids. Names come from the load-screen roster.
- **Elden Ring** locates its stat block by content too, but with a twist: the block's offset varies from one character to the next, because variable-length data sits in front of it. So the search keys on the eight attributes whose sum minus 79 equals the in-slot level, which is ER's rune-level formula (a Wretch is all-tens at level one). Owned items are walked from the GaItem array at the slot start. Name and level come from the header's profile table.

Notice the pattern. Where an offset is stable, read it. Where it moves, find the block by a fact only the real block satisfies. The level formulas do that work: they are cheap to check and almost impossible to hit by accident.

---

## The progress it can work out

Bosses and areas are not printed from a "bosses beaten" counter, because no such honest counter is readable. They are *inferred*, and inference here follows one rule: the progress shown is a floor, not a ceiling. Everything on the list is real. There may be more you have already cashed in that the save can no longer prove.

Every game gets the baseline: **boss souls and remembrances still held.** You cannot own a boss's soul without killing it, so a held soul is a certain kill. The web app and the Markdown both name the boss, not just the soul item. Spend the soul and the kill goes invisible, which is exactly why this is a floor.

**Dark Souls II goes much further,** because more of it is mapped:

- **Bonfires discovered.** DS2 keeps rest-point progress in a separate world block, not the character block. The tool reads it and lists every bonfire you have lit. Areas reached is itself a floor on how far you got. A fresh mule shows one bonfire; a thirty-hour save showed forty-nine across the whole game.
- **Bosses defeated, from three independent signals**, each certain when it fires, merged per boss so overlap reads as corroboration. A **flag** is a mapped defeat event in the world block. A **soul** is the boss soul still in your pack. A **gate** is progression: a bonfire or item you could not have reached without the kill, plus the mandatory predecessors that chain implies. The gate logic is deliberately endgame-only. DS2's mid-game is four parallel, largely skippable paths, so a mid-game gate would risk claiming a kill you never made, and a false kill breaks the whole rule.
- **Class, covenant, and hollowing level**, read from the character block by offsets pinned with differential saves, not guessed. An unknown covenant id is dropped rather than shown wrong.

**Dark Souls III, Elden Ring, and Dark Souls 1** get the soul floor plus the same endgame-gate idea. Hold Dark Souls III's Soul of Cinder and all four Lords of Cinder are proven dead, because Cinder sits behind every throne. Hold Elden Ring's Remembrance of Hoarah Loux and Maliketh, the Fire Giant, and Morgott fall with it, because that chain is forced. Only strictly-linear, cannot-skip endgame chains qualify, for the same reason DS2's gates are endgame-only.

What it does **not** do is read boss-defeat event flags for DS3 and Elden Ring. Those games store flags in a runtime "virtual memory" structure that tools read out of the live game's process, not the save file, and nobody has published how that block is serialised into the `.sl2`. So a consumed soul with no gate stays off the list. Honest floor, not a guess.

---

## The web app

The page is one static bundle. There is no backend, no upload, no analytics call. You drop a file, JavaScript reads it in the tab, and that is the end of it. Host it on any static host — it is built to run straight off GitHub Pages — or open it from a local server.

On top of the plain data it shows a few things Markdown cannot:

- **Stat tiles** for the headline numbers: soul memory, souls or runes held, max HP, bosses defeated, bonfires lit.
- **Attribute bars**, each read on the real 0–99 scale, so the shape of the build is obvious at a glance.
- **A build radar**, scaled to the character's own highest stat so the shape fills the wheel. A strength build spikes hard toward STR; a quality build sits even. The bars carry the absolute numbers; the radar carries the shape.
- **Copy Markdown.** One button dumps the exact same Markdown the Python CLI writes, ready to paste into a model.

That last point is not a coincidence. The web app is a faithful port of the Python reader, and both are held to it: the JavaScript parser is checked byte-for-byte against the Python tool's output for every test save, and the browser's Markdown is checked byte-for-byte against the CLI's Markdown. If they ever drift, the check fails. Two front ends, one source of truth.

---

## How to run it

**The web app.** Open the hosted page, or serve the folder yourself. It uses ES modules and `fetch`, so it needs a real server, not a `file://` open:

```bash
python3 -m http.server 8000
# then open http://localhost:8000/
```

To put it online, push the repo and turn on GitHub Pages from the `main` branch, root folder. The `.nojekyll` file is already there so Pages serves the `app/` and `db_*` folders as-is.

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

One `.md` per save. Header, then one section per character. Roughly this:

```markdown
# Dark Souls II: Scholar of the First Sin — Playthrough Save Summary

- **Game:** Dark Souls II: Scholar of the First Sin
- **Support tier:** full
- **Characters found:** 1

## Slot 2: Joy

- **Soul Level:** 88
- **Class:** Knight
- **Covenant:** Way of Blue
- **Souls held:** 0
- **Hollowing:** 2
- **Build:** strength-focused melee

### Attributes

| VGR | END | VIT | ATN | STR | DEX | ADP | INT | FTH |
|----|----|----|----|----|----|----|----|----|
|  22 |  16 |  15 |   4 |  45 |  15 |  15 |   3 |   6 |

### Bonfires Discovered (33)  _(areas reached — a floor on progress)_
- Majula
- Things Betwixt

### Bosses Defeated (12)  _(a floor — from defeat flags, held boss souls, and progression)_
- The Last Giant  _(confirmed)_
- The Pursuer  _(soul held)_

### Inventory

#### Weapons
- Fire Longsword +6
```

The inventory mirrors the in-game item menu: one heading per category, boss souls split into the four "Old" great souls and the ordinary ones, and special items carrying their state, so the Estus Flask shows its charge count. Paste the whole file into a model and ask it to plan your next steps, tune your build, or tell you what you missed. It has the facts now.

---

## The honest limitations

Said out loud rather than papered over:

- **Progress is a floor, not a ceiling.** Covered above. A spent soul with no flag and no gate is a kill the save can no longer prove, so it is not listed.
- **Boss-defeat flags for DS3 and Elden Ring are not read.** They live in a runtime structure, not the save file, and the save serialisation is not public. DS2's flags are readable and are used.
- **Upgraded gear in DS1 and DS3 is not named.** Those games bake the reinforcement level into the item id, so a +5 weapon has a different id from its base and misses the name table. Such items are counted so you know they exist, not guessed at. DS2 does not have this problem: its tables are built from the full SOTFS id list, so reinforced and infused variants all resolve by name. Elden Ring is the reverse, where the reinforced-weapon ids are skipped rather than counted.
- **Vanilla Dark Souls II is unsupported.** No public key.

---

## Layout

```
sl2_to_md.py      the CLI converter (Doxygen-commented, bounds-checked throughout)
index.html        the web app: markup and styling
.nojekyll         tells GitHub Pages to serve the folders as-is
app/
  aes.js          AES-128-CBC decrypt, no padding (WebCrypto cannot do this)
  reader.js       bounds-checked buffer reads, the JS mirror of the Python helpers
  parser.js       the reader ported to the browser, all five games
  db.js           loads the item / progress databases
  tables.js       shared lookup tables and formatters
  render.js       the DOM cards, stat tiles, bars, and build radar
  markdown.js     the browser's Copy-Markdown output
  main.js         file-drop wiring
db_ds1/*.json     Dark Souls 1 item tables (shared by DSR and PtDE)
db_ds2/*.json     Dark Souls 2 tables, bonfires, boss flags, boss souls
db_ds3/*.json     Dark Souls 3 item tables (id-scan) and boss souls
db_er/*.json      Elden Ring item tables (GaItem walk) and remembrance map
requirements.txt  the one Python dependency
```

The Python tool and the JavaScript port keep the same offsets and constants. Change one and you change the other, and the parity checks catch it if you forget.

---

## Adding or extending item tables

Every tier is limited by two things only: offsets and item tables. Both are just files, so both are yours to extend.

- **DS2** tables are id-keyed: `{"<little-endian-hex-id>": "Item Name"}`, one file per category. Id-keyed on purpose, not by accident. DS2 gives one item name several ids (a base form plus its reinforced and infused variants, and sometimes duplicate entries besides), and a name-keyed file would keep one id per name and silently drop the variant your save actually holds. So the id is the key, and every variant gets its own line.
- **DS1, DS3, and ER** tables are name-keyed: `{"Item Name": <decimal-id>}` (ER uses hex ids), kept per category because the raw numbers repeat across categories.

Drop a game's tables into its `db_*` folder and both front ends resolve the names on the next run. Every supported game's stat offsets are already calibrated. The one remaining item gap is Elden Ring's list: no quantities, and reinforced or affinity weapons still miss the base-id table.

---

## Credits

I did not reverse-engineer these formats from scratch, and I am not going to pretend I did. The keys, offsets, and structures come from people who mapped them first:

- DS2 offsets and item tables: [alfizari/Dark-Souls-2-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-2-Save-Editor-PS4-PC).
- DSR, DS3, and ER keys, decryption, and header layout: [jtesta/souls_givifier](https://github.com/jtesta/souls_givifier).
- DSR and DS1 offsets and item tables: [alfizari/Dark-Souls-Remastered-Save-Editor](https://github.com/alfizari/Dark-Souls-Remastered-Save-Editor).
- Elden Ring save structure (GaItem array, profile table): [ClayAmore/ER-Save-Editor](https://github.com/ClayAmore/ER-Save-Editor).
- DS2 key: the DS2 profile in [mi5hmash/SL2Bonfire](https://github.com/mi5hmash/SL2Bonfire).
- DS2 bonfire, class, covenant, and world-block offsets: the Jappi88 DS2 save editor and the SOTFS Cheat Engine tables.

What is mine: the `.sl2`-to-Markdown idea, the browser front end and its charts, the game auto-detection, the tier system and the rule behind it, the content-scan stat finders and the level-formula checks that make them safe, the id-scan and GaItem-walk inventory readers, the DS2 bonfire and multi-source boss inference, the cross-game endgame gates, and the byte-for-byte parity between the two front ends.
