# Contributing

**The most useful thing you can send is a save file.** Not a patch, not a feature request
— a `.sl2`, and a note saying what the tool got wrong about it.

There is a reason for that. This project has no test suite. Every offset in it was found
one of two ways: read out of somebody's published editor, or measured off a pair of real
saves with exactly one thing changed between them. Both need saves. The seven games are
mapped to wildly different depths — Dark Souls III has an 81-save ladder behind it and
Prepare to Die Edition has two files — and the gaps are gaps in the save corpus, not gaps
in effort. A save from a game or a patch that is thin here is worth more than a week of
staring at hex.

---

## Reporting a wrong reading

Three things: the save, what the tool printed, and what it should have printed.

**Trim the Markdown to the part that is wrong.** A full report is several hundred lines
and the defect is usually one of them. Cut everything that is correct. Keep just enough
around it to say where it lives — the heading above it is normally enough.

A whole report pasted in full is harder to act on than a trimmed one, not easier.

### The format

````markdown
**Save:** `Joy_1-34-40_lv17_5bf_1b.sl2` (attached)
**Game:** Dark Souls III, v1.15, Steam

**Output:**

```markdown
## Slot 1: Joy
```

**Should be:**

```markdown
## Slot 1: JoyBoy
```

The character is named JoyBoy in game. The last three characters are missing.
````

That is the entire report, and it is enough. The name is short by three characters, the
save is attached, so the read can be reproduced and the fix checked against it.

If several things are wrong in the same file, list them as separate output/should-be
pairs rather than pasting two full documents and letting the reader diff them.

### What "should be" means

Whatever the **game itself** shows you. Open the character in the Status or Equipment
screen and read the value off it. A screenshot beats a typed value and is very welcome,
because it is the same ground truth used here.

If you are not sure what the right answer is, say so and report it anyway — "this looks
wrong and here is why" is still a useful bug. What is not useful is a corrected value
guessed from a wiki, because the wiki and the save can both be right about different
things (a wiki lists base HP; the save records HP with your talismans on).

### Real examples

These are all real defects that shipped and have since been fixed. Every one of them
reduces to a diff of one or two lines, which is the point — none needed the whole file:

- **A level read as `2` on a character the game puts at `125`.** The stat block was
  matched against a coincidental run of bytes megabytes past the real one. Five characters
  were affected and they all looked plausible on their own — it took someone comparing one
  printed number against the Status screen.
- **`Unarmed`, `Arms` and `Legs` listed as owned items** in Elden Ring. Those are what the
  game puts in an *empty* equipment slot, so a fully-armoured character read as carrying
  them. It survived a long time because it is not obviously wrong until you notice every
  character has them.
- **"1001 inventory items had IDs not in the name database"**, on a character that
  actually had 74. The item names were all correct; only the count was junk. A report
  quoting that one line was all it took.
- **Sixteen different Ashes of War all named `Ash of War: Lion's Claw`.** The name table
  had been transcribed from a list that forward-filled every blank row.

Notice what none of those needed: a diagnosis. "This number is wrong, here is the save"
is a complete contribution. Working out why is the easy half.

---

## Better than a bug report: a differential pair

**Two saves, one variable changed between them.** This is the technique that pinned nearly
every field no published editor knows about, and it is the one thing that cannot be worked
around by being clever.

The recipe:

1. Save the game. Copy the `.sl2` somewhere safe.
2. Change **exactly one thing**. Join a covenant. Light one bonfire. Level one stat. Die
   once. Hand one item to one NPC.
3. Do nothing else — do not pick anything up, do not kill anything, do not spend souls.
4. Save again. Copy that `.sl2` too.
5. Send both, and say in one sentence what changed.

A single labelled save cannot isolate a byte. A pair with one variable in it can, and
usually does in an afternoon. That is how Dark Souls II's starting class, covenant,
gender, play time and deaths were found, and how Dark Souls III's covenant, embered flag
and weapon slots were.

### What is blocked on one right now

These are open specifically because nobody here has the save. Each needs one pair:

| What | The pair that would unlock it |
|---|---|
| **Elden Ring progress of any kind** | Two saves either side of discovering **one Site of Grace**. This is the big one: no grace, no boss flag and no world pickup is read for Elden Ring at all, because the flag region is unmapped. |
| **Dark Souls III starting class, gender, Dark Sigil level** | Two characters differing only in class, and two differing only in gender. No published editor reads any of the three, so there is no offset to port. |
| **Dark Souls II boss flags** (6 of ~41 mapped) | Saves either side of **one fog gate**. The community mule set has every boss already dead, which is exactly the wrong shape — it has no before. |
| **Dark Souls II play time and deaths** | A pair separated by a known amount of time, or by one death and nothing else. |
| **Dark Souls II gender** | Any save whose character's gender you can state. The byte is read; the Male/Female values are not confirmed, so it is not printed. |
| **Dark Souls III shop and handover flags** (~250) | Two saves either side of handing **one item** to the Shrine Handmaid. |

A save that is just "a character further along than anything in the corpus" is welcome
too, especially for Prepare to Die Edition, Dark Souls Remastered and vanilla Dark Souls
II, which have two, four and one file behind them respectively.

---

## Sending saves

**Name the file so it sorts.** The convention used here packs the useful facts into the
name:

```
Joy_1-34-40_lv17_5bf_1b.sl2
│   │        │    │    └─ bosses defeated
│   │        │    └────── bonfires lit
│   │        └─────────── soul level
│   └──────────────────── play time, H-MM-SS
└──────────────────────── character
```

Copy a fresh backup out under a new name each time you save, and a folder of them sorts
into a playthrough in order. That matters more than it sounds: point the tool at the whole
folder and it reads the run as a history, and a flag can only be trusted once it can be
*dated* — clear in one snapshot, set in the next. An undated flag does not ship.

**Check what is in the file before you post it publicly.** Three of these games write your
Steam account ID into the save, and the tool prints it, deliberately — the game refuses to
load a save belonging to a different account, so it is the first thing to check when a
character "vanishes". It is in the `About this file` block at the bottom of every report,
as both the account ID and the SteamID64. If you would rather that did not go in a public
issue, say so and send the file privately, or trim that block out of the report you paste.

Nothing else in a save identifies you. There is no name, no address, no telemetry — it is
your character, your stats and your bag.

---

## Contributing code

### The one rule

**A wrong number is worse than a missing one.** Everything else here follows from it.

If a field cannot be verified, it does not get printed, and the file says it was left out.
Progress is reported as a floor and never a ceiling: "at least these bosses are dead", not
"these are the bosses you have killed". A slot whose stat block fails validation drops to
a shallower tier rather than printing a plausible guess.

This is not negotiable, and it is the reason to reject an otherwise good patch. An offset
that is probably right is not right.

### Before you ship an offset

- **Read the published editors first.** Several fields that sat on the blocked list for
  months were already in a public repository. Credits in the README lists the ones already
  drawn on. Go and look before booking an experiment.
- **Validate a foreign source's frame before trusting one field out of it.** If an editor
  gives you a deaths offset, check that the same frame reproduces the name, level and
  class this parser already reads on a real save. That check costs one script and catches
  a wrong frame immediately.
- **Otherwise measure it,** with the differential above.
- **Cite where it came from,** in the comment, next to the constant.

### Conventions

- **Every read goes through the bounds-checked helpers** — `read_uint`, `u8`/`u16`/`u32`/
  `u64`, `read_utf16`. They return `None` or `""` on an out-of-range access instead of
  raising or reading past the buffer. Do not index a buffer directly and do not call
  `struct.unpack_from` in parsing code. A short or malformed save must degrade to
  "unknown", never crash.
- **Name every constant,** and say in the comment *why* the offset or the guard is there.
  Comments are Doxygen (`##` blocks with `@brief`), and they explain reasoning rather than
  restating the code. A comment that says what the next line does is noise; one that says
  what breaks if you change it is the point.
- **The two front ends must stay byte-identical.** The Python CLI and the browser app are
  one reading engine written twice, and they are held to producing the same bytes for
  every save in the corpus, across all three output formats. Change `sl2/*.py` and you
  change `app/*.js` in the same commit, or the change is half done.

### Checks

CI runs these, so run them first:

```bash
python3 -m py_compile sl2_to_md.py sl2/*.py
ruff format --check .
ruff check .
npx prettier --check "**/*.{js,html,json,yml}"
```

Then do the thing that actually matters: **run the tool against a real save and read what
comes out.** The saves are the fixtures. If you touched parsing, say in the pull request
which saves you ran it against and what you compared the output to.

The parity harnesses that hold the two front ends together are not in the repo — they
reference save files that cannot be published. A pull request touching either parser will
be run against them here before it merges, which is another way of saying: keep the two
ports in step, because the diff will find it if you do not.

### What will not be merged

- An offset that has not been checked against a real save.
- A field printed on the strength of a wiki, a guess, or "the other editor does it".
- A parsing change to one front end and not the other.
- A new dependency. The CLI has exactly one, `cryptography`, and the web app has none —
  it is static files, and it parses in the browser so that nobody's save is ever uploaded
  anywhere.
- Anything that writes to a save file. This reads. It has never written and it is not
  going to; the worst thing it can do to you is produce a bad Markdown file.

---

## The data tables

`db_*/` is a curated Souls data set — item IDs for five game families, bonfire and grace
tables, boss and NPC flag tables — and it is usable on its own, with no dependency on the
parser. Corrections to it are welcome on the same terms as everything else: say where the
right answer came from.

Where a table can be generated from the installed game, it is, and that beats any
transcription. `db_er/`'s item names and `db_sdt/minibosses.json` are both read out of the
games' own files now, and both replaced community lists that turned out to be measurably
wrong — the Sekiro roster was short by four bosses, and the Elden Ring name list had 83
names wrong outright. If you are about to hand-edit one of those two, regenerate it
instead; each has its generator recorded beside it.
