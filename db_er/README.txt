items.json maps Elden Ring item id -> name (5443 entries, from "ITEM IDS Elden Ring.txt").

Used by er_parse: the owned-item set is walked from the GaItem array and each id is
resolved here (direct hit, then the id masked to its low 28 bits). Names are
best-effort: reinforced/affinity weapons and some ids resolve approximately, so a
few entries can carry the wrong name. Per-item quantities are not read.

The list is not grouped by item category, and the id ranges do not separate cleanly
(armor, goods, and weapons overlap in id-space), so the owned items are printed as a
single list rather than split into weapon/armour/talisman/goods categories.
