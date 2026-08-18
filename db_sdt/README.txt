Sekiro tables.  Item names are keyed by param id per type; flag tables are keyed by
their own event-flag id.

THESE COME FROM THE GAME, NOT FROM PARAMDEX.  Sekiro's shipped English names are in
the game's own msg/engus FMGs and are not in Paramdex at all -- Paramdex SDT carries
machine-translated development rows ("Molotov cocktail -- 火炎瓶").  So
`tools/gen_from_paramdex.py` deliberately does not touch this directory.  Do not add
it there: two generators writing one table from two sources is how the two disagree.

  armors.json  goods.json  prosthetics.json   names, from a local install:
      python3 tools/gen_sdt_from_regulation.py --game-root <install> \
          --paramdex <Paramdex> --out db_sdt --report db_sdt/_extract_report.md

  minibosses.json                             the boss/miniboss roster, read out of
      the event scripts themselves:
      python3 tools/gamefiles.py roster <unpacked>/event --msg <unpacked>/msg/engus \
          --maps <unpacked>/map/mapstudio --write db_sdt/minibosses.json

That roster is why the rule above is worth keeping.  Regenerating it from the scripts
returned 37 rows where the community list carried 33: all five Headless were missing,
fourteen more were named after their model family rather than the enemy, and one entry
was not a miniboss at all.

  *_devnames.json                             machine-translated development names,
      for ids with no shipped English name.  Kept in their own files precisely because
      they are uncertain, and never merged into the tables above.

  boss_flags.json  item_flags.json  idols.json   event-flag ids.  Sekiro's flag
      arithmetic is Dark Souls III's; sub-5000 local ids are permanent, >= 5000 are
      temporary and an idol rest wipes them.

House style is one-space indent.  `db_*/` is prettier-ignored on purpose -- these are
data, not code -- so the generators produce that style directly and nothing reformats
them afterwards.  Hand-editing a generated table is how a regeneration silently reverts
your fix; fix the generator, or fix the game-file reader it draws on.
