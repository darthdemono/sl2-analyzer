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
| [FrankvdStam/SoulSplitter](https://github.com/FrankvdStam/SoulSplitter) | DS3 bonfire, boss and item-pickup event-flag ID lists, used as a reference to compute save offsets. Cross-checked 60/60 against the TGA Cheat Engine table. Also the Sekiro boss and Sculptor's Idol flag IDs in `db_sdt/`, and the decompiled `GetEventFlag` that shows Sekiro's bit arithmetic is DS3's. |
| [thefifthmatt/SoulsRandomizers](https://github.com/thefifthmatt/SoulsRandomizers) | DS3 item-lot annotations — the location text for each world pickup, and the lot IDs that join to the pickup event flags. Used as reference data; no code from it is here. |

### MIT

| Project | What was used |
|---|---|
| [alfizari/Dark-Souls-3-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-3-Save-Editor-PS4-PC) | DS3 stat offsets, play time, and the event-flag region block walk. This is the one place an *algorithm* was ported rather than a constant read off — and it is MIT, which imposes nothing incompatible. |
| [alfizari/Dark-Souls-2-Save-Editor-PS4-PC](https://github.com/alfizari/Dark-Souls-2-Save-Editor-PS4-PC) | DS2 offsets and item tables. |
| [tarvitz/dsfp](https://github.com/tarvitz/dsfp) | The PtDE load-screen roster record and the deaths struct. |
| [uberhalit/SimpleSekiroSavegameHelper](https://github.com/uberhalit/simplesekirosavegamehelper) | The Sekiro container layout: slot count, slot and settings block lengths, checksum positions, the settings-block field offsets, and the minimum file length. It credits "klm123" for some of those offsets. |

### Apache-2.0

| Project | What was used |
|---|---|
| [alfizari/Dark-Souls-Remastered-Save-Editor](https://github.com/alfizari/Dark-Souls-Remastered-Save-Editor) | DSR and DS1 offsets, the gender byte, and item tables. |
| [alfizari/Sekiro-Save-Editor](https://github.com/alfizari/Sekiro-Save-Editor) | Sekiro slot field offsets, the GaItem and item-list region offsets and record shapes, the item type nibbles, and English item names. **Its licence is ambiguous** — the repository carries Apache-2.0 while its README claims MIT — so it is listed under the more restrictive of the two rather than the more convenient one. Nothing here depends on which it is: what was taken is byte offsets and record sizes, which are measurements of a file format FromSoftware defined, and no code from it is reproduced. |

### WTFPL

| Project | What was used |
|---|---|
| [Bergbok/Elden-Ring-Saves](https://github.com/Bergbok/Elden-Ring-Saves) | Elden Ring **test input**, not code and not data that ships: 17 saves of ten built characters each, every one documented with its own in-game Status screenshot. Those screenshots are the ground truth the ER stat reader is verified against, and the breadth of the set is what exposed the stat block's alignment. Nothing from it is redistributed here — the saves live in the git-ignored `test/`. |

### MIT (tooling, not vendored)

| Project | What was used |
|---|---|
| [Nordgaren/UXM-Selective-Unpack](https://github.com/Nordgaren/UXM-Selective-Unpack) | `ArchiveKeys.cs` (the published RSA keys that open Elden Ring's `.bhd` headers) and `res/EldenRingDictionary.txt` (the archive path list). **Neither is vendored here** — `tools/gamefiles.py` takes both as arguments, and they were fetched at the point of use. What came out of them is Elden Ring's own English item names, which is what `db_er/`'s tables are now generated from rather than transcribed. The RSA step itself is `CryptographyUtility.DecryptRsa`, credited above. |

### No licence stated

These publish no licence, which means no permission is granted for their *code*. Only
factual information was taken from them, and none of their source is reproduced here.

| Source | What was used |
|---|---|
| [ClayAmore/ER-Save-Lib](https://github.com/ClayAmore/ER-Save-Lib) and [ER-Save-Editor](https://github.com/ClayAmore/ER-Save-Editor) | Elden Ring save structure: the GaItem array, the profile table, the "File version" word, and the in-save regulation block that carries the game patch. |
| [Paramdex](https://github.com/soulsmods/Paramdex) and the soulsmodding wiki | DS1 item IDs, bonfire IDs, and the event-flag addressing formula. It used to back `db_er/`'s item names too; those are now read from Elden Ring's own `msg/engus` FMGs instead, and the rows the game has no entry for are all that is left of the transcription. Also the complete Sekiro ID sets for `EquipParamWeapon`, `EquipParamProtector` and `EquipParamGoods`, and the machine-translated development names for the IDs with no English name — those are kept in their own `_devnames` files precisely because they are uncertain. |
| The Save Wizard Sekiro code sheet, via alfizari's credits | Independent confirmation of the Sekiro slot stat offsets, and the play-time field: its "Playtime 999:59:59" entry writes `0x36EE7F` = 3,599,999 = 999×3600 + 59×60 + 59, which is what identifies the field as a `uint32` of seconds. |
| [The-Grand-Archives/Dark-Souls-III-CT-TGA](https://github.com/The-Grand-Archives/Dark-Souls-III-CT-TGA) | DS3 and ER Cheat Engine tables, used for their ID→name dropdowns and the flag group base table. |
| [Sibert-Aerts/sibert-aerts.github.io](https://github.com/Sibert-Aerts/sibert-aerts.github.io) — the [FromSoft Image Macro Creator](https://rezuaq.be/new-area/image-creator/) | Which typeface each game sets its overlays in (Adobe Garamond Pro for Dark Souls 1-3 and Sekiro's Latin text, Agmena Pro for Elden Ring, Pinnacle JY / ITC Galliard for Demon's Souls), and the measured RGB of the on-screen text itself — BONFIRE LIT, LOST GRACE DISCOVERED, YOU DIED, SCULPTOR'S IDOL FOUND and the rest — which is where this page's per-game palettes come from. Also its vertical-stretch and zoom-blur values, which the titles here imitate. Colour measurements and font attributions, not code. |
| The Jappi88 DS2 save editor; the SOTFS Hex Code Compendium; the SOTFS and ER Cheat Engine tables | DS2 world-block offsets; DS2 and ER item name lists. |
| [fextralife](https://darksouls2.wiki.fextralife.com/) and the Dark Souls wikidot | Derived-stat formulas, bonfire-to-area mappings, boss route ordering. (The web app used to hot-link DS2 item thumbnails from fextralife's CDN; that was removed along with `db_ds2/images.json`, so the page now makes no cross-origin request at all — see the fonts below, which are self-hosted for the same reason.) |

## Game content

Item, boss, bonfire, area and covenant names are FromSoftware's. They appear here as
lookup tables so that a save file can be read at all, which is interoperability, not
republication of the games. This project ships no game assets, no executable code from
any game, and nothing that helps you obtain one. It reads a file you already own and
it never writes to it.

## Vendored code

**Mermaid** (`vendor/mermaid.min.js`) — MIT, © 2014–2024 Knut Sveidqvist.
<https://github.com/mermaid-js/mermaid>. Vendored rather than loaded from a CDN so
the page stays self-contained, works offline, and makes no cross-origin request. It
renders the flowcharts in the combined view; the Markdown export carries the same
charts as plain ```mermaid blocks, which need no library at all.

**doxygen-awesome-css** v2.4.2 (`vendor/doxygen-awesome/`) — MIT, © 2021–2023 jothepro.
<https://github.com/jothepro/doxygen-awesome-css>. The theme for the generated API
documentation at `/documentation/`, vendored for the same reason as Mermaid: the docs
build is then reproducible and needs no network. Four of its optional JavaScript
extensions ship with it (dark-mode toggle, fragment copy button, paragraph links,
interactive table of contents), loaded by `doc-theme/header.html`. Its own licence text
sits beside the files in `vendor/doxygen-awesome/LICENSE`.

## Fonts

**This repo ships no font files.** The whole page is set in
`adobe-garamond-pro, Georgia, serif`. Adobe Garamond Pro is the face FromSoftware
actually uses for the Dark Souls games and for Sekiro's Latin text, and it is not
redistributable, so it is first in the stack and resolves only for a reader who already
has it installed or who adds an Adobe Fonts kit to the page. Everybody else gets
Georgia, which every machine already ships and which is the nearest system serif to it.
Nothing is downloaded either way, and the page still makes no cross-origin request.

Which game uses which face is the FromSoft Image Macro Creator's work, credited in the
table above: Adobe Garamond Pro for Dark Souls 1-3 and Sekiro's Latin, Agmena Pro for
Elden Ring, Pinnacle JY or ITC Galliard for Demon's Souls, Reimin Y10 for Bloodborne,
and 白舟極太楷書 for Sekiro's decorative Japanese. The same source is where every accent
colour on this page was measured.

`graphics/noise.svg` is the page grain: one patch of `feTurbulence`, drained of colour,
laid over each panel. The technique is the one the macro creator uses on its own boxes.
The file is written for this project.
