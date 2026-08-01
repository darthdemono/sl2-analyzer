# Third-party notices

This project is [MIT licensed](LICENSE). Nothing here is a fork of anything, and no
third-party source code is bundled or vendored. What this file records is where the
*facts* came from — the encryption keys, the field offsets, the flag IDs, the item
names — because that is the part somebody else worked out first, and they deserve the
credit whether or not a licence demands it.

Three of the projects below are GPL-3.0. That is worth addressing head-on rather than
hoping nobody checks.

## Why MIT is compatible with the GPL-3.0 sources

**No GPL-licensed code is in this repository.** Every line of the Python and the
JavaScript was written for this project. From the GPL-3.0 projects listed below, what
was taken is factual information about a file format that FromSoftware defined:

- **AES key bytes.** A key is a number. It is not authored, it is discovered, and it
  is the same number no matter who writes it down.
- **Field offsets and record layouts.** "The death counter is a uint32 at +104" is a
  fact about Dark Souls II, not a creative work belonging to whoever measured it.
- **Event flag IDs.** `13500001` means "Deacons of the Deep bonfire" because
  FromSoftware made it so. The names in those lists are the game's names.

Copyright protects expression, not facts or discoveries. In US law that is the
holding of *Feist v. Rural Telephone* — an exhaustive compilation of facts, with no
creative selection or arrangement, is not protectable, and "sweat of the brow" earns
no copyright however much of it went into the work. The flag lists used here are
exhaustive by nature (every bonfire, every boss), so there is no creative selection to
infringe, and what ships in `db_ds3/` is not those lists anyway: it is byte offsets
and bit positions computed from them through the addressing formula.

Two caveats stated plainly, because the point of this file is honesty rather than
reassurance. The EU's *sui generis* database right is a separate regime from copyright
and protects substantial investment in compiling a database, so a European reading of
the flag lists could differ from the American one. And none of this is legal advice —
it is the reasoning behind the choice, offered so you can check it rather than trust
it. If you are shipping this inside a commercial product and the question matters to
you, ask a lawyer, not a README.

**If you want to avoid the question entirely:** the DS3 flag-derived tables are
`db_ds3/bonfires.json`, `boss_flags.json`, `boss_victory.json`, `questlines.json`,
`covenants.json`, `lord_cinders.json` and `item_pickups.json`. Delete those seven
files and the tool degrades gracefully — every loader returns `{}` and the features
turn themselves off — leaving a parser with no relationship to any GPL project at all.

## Sources

### GPL-3.0

| Project | What was used |
|---|---|
| [jtesta/souls_givifier](https://github.com/jtesta/souls_givifier) | DSR, DS3 and Elden Ring AES keys; the IV-prefixed block layout; BND4 header structure. Facts only — the decryption here is ordinary `cryptography` library usage in Python and a from-scratch AES implementation in JavaScript (the S-boxes are generated from GF(2⁸), not transcribed). |
| [TKGP/SoulsFormats](https://github.com/JKAnderson/SoulsFormats) | The vanilla Dark Souls II save key from `SFUtil.GetDS2SaveKey` — a single 16-byte constant. |
| [FrankvdStam/SoulSplitter](https://github.com/FrankvdStam/SoulSplitter) | DS3 bonfire, boss and item-pickup event-flag ID lists, used as a reference to compute save offsets. Cross-checked 60/60 against the TGA Cheat Engine table. |

### MIT

| Project | What was used |
|---|---|
| [alfizari/Dark-Souls-3-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-3-Save-Editor-PS4-PC) | DS3 stat offsets, play time, and the event-flag region block walk. This is the one place an *algorithm* was ported rather than a constant read off — and it is MIT, which imposes nothing incompatible. |
| [alfizari/Dark-Souls-2-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-2-Save-Editor-PS4-PC) | DS2 offsets and item tables. |
| [tarvitz/dsfp](https://github.com/tarvitz/dsfp) | The PtDE load-screen roster record and the deaths struct. |

### Apache-2.0

| Project | What was used |
|---|---|
| [alfizari/Dark-Souls-Remastered-Save-Editor](https://github.com/alfizari/Dark-Souls-Remastered-Save-Editor) | DSR and DS1 offsets, the gender byte, and item tables. |

### No licence stated

These publish no licence, which means no permission is granted for their *code*. Only
factual information was taken from them, and none of their source is reproduced here.

| Source | What was used |
|---|---|
| [ClayAmore/ER-Save-Lib](https://github.com/ClayAmore/ER-Save-Lib) and [ER-Save-Editor](https://github.com/ClayAmore/ER-Save-Editor) | Elden Ring save structure: the GaItem array, the profile table, the "File version" word, and the in-save regulation block that carries the game patch. |
| [Paramdex](https://github.com/soulsmods/Paramdex) and the soulsmodding wiki | DS1 item IDs, bonfire IDs, and the event-flag addressing formula. |
| [The-Grand-Archives/Dark-Souls-III-CT-TGA](https://github.com/The-Grand-Archives/Dark-Souls-III-CT-TGA) | DS3 and ER Cheat Engine tables, used for their ID→name dropdowns and the flag group base table. |
| The Jappi88 DS2 save editor; the SOTFS Hex Code Compendium; the SOTFS and ER Cheat Engine tables | DS2 world-block offsets; DS2 and ER item name lists. |
| [fextralife](https://darksouls2.wiki.fextralife.com/) and the Dark Souls wikidot | Derived-stat formulas, bonfire-to-area mappings, boss route ordering. DS2 item thumbnails in the web app are hot-linked to fextralife's CDN, not redistributed — only the filenames are stored, in `db_ds2/images.json`. |

## Game content

Item, boss, bonfire, area and covenant names are FromSoftware's. They appear here as
lookup tables so that a save file can be read at all, which is interoperability, not
republication of the games. This project ships no game assets, no executable code from
any game, and nothing that helps you obtain one. It reads a file you already own and
it never writes to it.
