Elden Ring item names, keyed by the id AS THE SAVE STORES IT (hex, category nibble
included): weapons 0x0, armour 0x1, talismans 0x2, goods 0x4, Ashes of War 0x8.

THESE COME FROM THE GAME, NOT FROM A COMMUNITY LIST.  Regenerate with:

    python3 tools/gamefiles.py --ooz scratch/libooz.so unpack --game er \
        --game-root <install> --keys ArchiveKeys.cs --dict EldenRingDictionary.txt \
        --out <unpacked> --prefix /msg/
    python3 tools/gamefiles.py ernames --msg <unpacked>/msg/engus --db db_er --write

The source is engUS `item.msgbnd` plus both DLC layers -- WeaponName, ProtectorName,
AccessoryName, GoodsName and GemName -- merged in patch order, from Shadow of the
Erdtree v1.16.  A row the game lists but leaves nameless is dropped; a row the game
has no entry for keeps whatever the old table called it, which is what preserves the
`[NPC]`-prefixed weapons and the NPC flask variants.

That transcription was measurably wrong, which is why this is generated now.  Against
the game: 83 names differed outright and 35 more differed only in their diacritics,
ashes.json was the worst of it -- 239 rows carrying 120 distinct names, sixteen
separate ids all reading "Ash of War: Lion's Claw" and seven reading "Ash of War:",
a forward-fill over the 123 rows the game deliberately leaves blank.

Used by er_parse: the owned-item set is walked from the GaItem array and each id is
resolved here, scoped to the category its top nibble names.  A reinforced or affinity
weapon resolves through its affinity row and carries the `+N`.  Per-item quantities
are still not read, and the held inventory -- where talismans, spells and consumables
live -- is still not walked, so those two tables load and are rarely consulted.

Five ids are deliberately NOT reported: weapon 110000 (Unarmed) and armour
10000/10100/10200/10300 (bare Head/Body/Arms/Legs).  They are what the game puts in an
empty equipment slot, so they say nothing about what a character owns.
