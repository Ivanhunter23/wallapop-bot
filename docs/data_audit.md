# Legacy data audit

Audit of the prototype's local data files, done in Phase 0 before any
import. The files stay uncommitted and are never modified.

- **Regenerate:** `make audit` (about one minute; the 640 MB backup
  dominates). It rewrites only the block between the `GENERATED` markers.
- **Every number below** is copied from that block, which is produced by
  `backend/src/wallabot/importers/legacy_audit.py`.
- **Noise disagreement** compares the stored `is_noise` flag with the
  current prototype rules (`wallabot.legacy.wallapop_watcher.is_noise`).

## What the files are

| Label | Path | What it is |
|---|---|---|
| `snapshot-0621` | `../wallabotdata/` | Older copy of the working folder: one JSONL row per item per scan, Wallapop only, plus state files |
| `full-backup-0627` | `data/backups/wallapop_data.jsonl.bak` | One row per item per scan, Wallapop only; taken just before the switch to write-on-change |
| `compaction-1..3` | `data/backups/wallapop_data.jsonl.bak-20260628-*` | Backups taken before each of three manual clean-ups on 28 June |
| `current` | `data/wallapop_data.jsonl` | The live file: one row when an item is new or its price changes; Vinted added on 9 July |

The files are consecutive segments, not copies: `snapshot-0621` ends at
2026-06-24T12:57:00, and `full-backup-0627` starts 58 seconds later.

## Findings

1. **No single file is complete.** The union of all files holds 19,959
   Wallapop items; `current` holds 14,692 of them. Phase 1 must import every
   file, deduplicated by item id, and not just `current`.
2. **The 28 June clean-ups deleted real listings.** Each one removed every
   row of a search term that had been dropped from `SEARCHES`: "nintendo ds"
   (1,609 items), "coleccion ds" (1,258) and "mario & luigi DS" (1,626).
   Under the current rules, 772, 703 and 445 of those items are not noise.
   The rows survive only in the backups. This is why the import treats
   every legacy file as read-only input.
3. **Per-scan history exists for 21–27 June (Wallapop only).**
   `snapshot-0621` and `full-backup-0627` hold a row per item per scan
   (median 133 and 97 rows per item). For that window, "last seen" can be
   reconstructed. From 24 June the live file writes only on change, so
   `last_seen_at` imported from it is a lower bound.
4. **Vinted data covers twelve minutes.** All 13,199 Vinted items were
   scanned on 2026-07-09 between 14:25:27 and 14:37:55, and the scraper has
   not run since then. Vinted contributes no price history yet.
5. **Prices change rarely.** Between 3.8% and 5.8% of items have at least
   one price change, depending on the file. Price-cut analysis (Q5) will
   have small groups.
6. **Stored `is_noise` flags are stale.** They disagree with the current
   rules on 18.1% of `current` rows and 19.9% of the `snapshot-0621` rows
   that have the flag. The rules changed after the rows were written, so
   Phase 1 recomputes the flag and keeps the stored one only as raw data.
7. **The legacy label trap is large.** `reviewed.json` has 15,333 ids, of
   which 14,690 were never excluded. Most come from the auto-initialisation
   on first use, so none of them count as human approvals; they are
   imported as `legacy_unknown`. The 741 exclusions are the only reliable
   human labels, and all of them are in some JSONL file.
8. **95 of 368 learned rules never fire in the watcher.** Every one differs
   from a current search term only by whitespace: the server strips the
   term when saving the rule, but two search terms end in a space
   ("pokemon negro ", "pokemon blanco "). Separately, 19 rules have a
   single distinct word, and 6 contain duplicated words.
9. **History before 21 June is gone.** 680 ids in the snapshot's
   `seen.json` appear in no JSONL file. They can seed the notification
   state, but they have no title or price.
10. **Data quality is otherwise clean.** No unparseable lines, no
    out-of-order timestamps, and no nulls in `item_id`, `title`, `price` or
    `scanned_at`. `source` is missing on older rows, but the `v:` id prefix
    settles which source they come from.

## Consequences for Phase 1

- Import all six JSONL files, in scan order, deduplicated by
  `(source, external_id)`, with `history_origin = 'legacy_jsonl'`.
- Snapshots: keep one snapshot per price or title change, not one per scan
  row. Take `first_seen_at` and `last_seen_at` from the full per-scan rows
  where they exist.
- Recompute `is_noise` with the rules at import time.
- Normalise search terms (`strip()`) when linking them, and record the
  whitespace issue in DECISIONS.md.

<!-- BEGIN GENERATED: make audit -->

## Generated tables

### JSONL files

| Dataset | Size | Lines | Unparseable | scanned_at range | Wallapop rows | Vinted rows | Wallapop items | Vinted items | Out-of-order lines |
|---|---|---|---|---|---|---|---|---|---|
| `snapshot-0621` | 162.1 MB | 514,693 | 0 | 2026-06-21T15:13:06 → 2026-06-24T12:57:00 | 514,693 | 0 | 3,225 | 0 | 0 |
| `full-backup-0627` | 639.7 MB | 1,982,876 | 0 | 2026-06-24T12:57:58 → 2026-06-27T16:57:33 | 1,982,876 | 0 | 16,318 | 0 | 0 |
| `compaction-1` | 5.6 MB | 17,486 | 0 | 2026-06-24T12:57:58 → 2026-06-28T00:04:49 | 17,486 | 0 | 16,529 | 0 | 0 |
| `compaction-2` | 5.1 MB | 15,742 | 0 | 2026-06-24T12:58:01 → 2026-06-28T00:04:49 | 15,742 | 0 | 14,920 | 0 | 0 |
| `compaction-3` | 4.7 MB | 14,424 | 0 | 2026-06-24T12:58:01 → 2026-06-28T00:04:49 | 14,424 | 0 | 13,662 | 0 | 0 |
| `current` | 10.1 MB | 29,747 | 0 | 2026-06-24T12:58:01 → 2026-07-09T14:37:55 | 16,545 | 13,202 | 14,692 | 13,199 | 0 |

Union of all audited JSONL files: 19,959 Wallapop items, 13,199 Vinted items.

### `snapshot-0621` — `wallapop_data.jsonl`

- `created_at` range: 2016-04-27T13:00:33 → 2026-06-24T12:45:29
- `scanned_at` range for wallapop: 2026-06-21T15:13:06 → 2026-06-24T12:57:00
- Row schemas: 288,592 rows with 8 keys (no `source`) (no `is_noise`), 226,101 rows with 9 keys (no `source`)
- Rows per item: median 133, max 2,030
- Items with at least one price change: 188 of 3,225 (5.8%); 230 price changes in total
- Items with at least one title change: 24 (0.7%)
- Rows with a non-numeric price: 0 (0.0%)
- Stored `is_noise` disagrees with the current rules on 44,931 of 226,101 rows (19.9%)

Missing or null rate per field:

| Field | Rows | Rate |
|---|---|---|
| `scanned_at` | 0 | 0.0% |
| `search_term` | 0 | 0.0% |
| `source` | 514,693 | 100.0% |
| `item_id` | 0 | 0.0% |
| `title` | 0 | 0.0% |
| `price` | 0 | 0.0% |
| `currency` | 0 | 0.0% |
| `created_at` | 0 | 0.0% |
| `url` | 0 | 0.0% |
| `is_noise` | 288,592 | 56.1% |

Per search term (terms shown in quotes to expose whitespace):

| Source | Term | Rows | Unique items | Distinct scanned_at values |
|---|---|---|---|---|
| wallapop | "ace attorney" | 12,339 | 61 | 318 |
| wallapop | "ace attorney DS" | 200 | 40 | 5 |
| wallapop | "aliens infestation" | 17,750 | 89 | 448 |
| wallapop | "aliens infestation DS" | 255 | 45 | 9 |
| wallapop | "blue dragon" | 12,640 | 75 | 316 |
| wallapop | "blue dragon DS" | 180 | 36 | 5 |
| wallapop | "castlevania : order of ecclesia" | 12,565 | 46 | 317 |
| wallapop | "castlevania DS" | 12,920 | 64 | 323 |
| wallapop | "castlevania order of ecclesia DS" | 200 | 40 | 5 |
| wallapop | "coleccion ds" | 12,672 | 78 | 325 |
| wallapop | "dragon ball origins 2" | 11,803 | 40 | 319 |
| wallapop | "dragon ball origins 2 DS" | 345 | 60 | 6 |
| wallapop | "dragon quest IX" | 12,441 | 42 | 319 |
| wallapop | "dragon quest IX DS" | 190 | 38 | 5 |
| wallapop | "dragon quest VI" | 12,662 | 51 | 320 |
| wallapop | "dragon quest VI DS" | 200 | 40 | 5 |
| wallapop | "dragon quest monsters" | 12,720 | 63 | 318 |
| wallapop | "dragon quest monsters DS" | 190 | 38 | 5 |
| wallapop | "ds" | 5,673 | 282 | 142 |
| wallapop | "ds lite" | 13,113 | 120 | 328 |
| wallapop | "dsi" | 13,040 | 99 | 326 |
| wallapop | "dslite" | 13,039 | 44 | 326 |
| wallapop | "final fantasy tactics A2" | 13,242 | 75 | 327 |
| wallapop | "final fantasy tactics A2 DS" | 395 | 71 | 7 |
| wallapop | "ghost trick" | 12,599 | 44 | 315 |
| wallapop | "ghost trick DS" | 375 | 67 | 6 |
| wallapop | "golden sun dark dawn" | 12,323 | 41 | 316 |
| wallapop | "golden sun dark dawn DS" | 195 | 39 | 5 |
| wallapop | "infinite space" | 20,011 | 105 | 453 |
| wallapop | "infinite space DS" | 220 | 43 | 8 |
| wallapop | "kirby super star ultra" | 17,640 | 102 | 457 |
| wallapop | "kirby super star ultra DS" | 280 | 49 | 8 |
| wallapop | "last window" | 12,046 | 42 | 317 |
| wallapop | "last window DS" | 190 | 38 | 5 |
| wallapop | "legend of zelda phantom hourglass" | 12,837 | 59 | 321 |
| wallapop | "legend of zelda phantom hourglass DS" | 200 | 40 | 5 |
| wallapop | "legend of zelda spirit tracks" | 12,163 | 46 | 313 |
| wallapop | "legend of zelda spirit tracks DS" | 195 | 39 | 5 |
| wallapop | "lote nintendo ds" | 12,920 | 114 | 323 |
| wallapop | "mario & luigi DS" | 13,039 | 241 | 326 |
| wallapop | "metal slug 7" | 12,674 | 51 | 317 |
| wallapop | "metal slug 7 DS" | 265 | 47 | 7 |
| wallapop | "nintendo ds" | 7,198 | 78 | 180 |
| wallapop | "nintendo dsi" | 12,878 | 94 | 322 |
| wallapop | "pokemon blanco" | 12,637 | 96 | 316 |
| wallapop | "pokemon blanco DS" | 200 | 40 | 5 |
| wallapop | "pokemon diamante" | 12,760 | 86 | 319 |
| wallapop | "pokemon diamante DS" | 200 | 40 | 5 |
| wallapop | "pokemon ds" | 13,035 | 173 | 326 |
| wallapop | "pokemon heartgold" | 12,878 | 64 | 322 |
| wallapop | "pokemon heartgold DS" | 195 | 39 | 5 |
| wallapop | "pokemon mundo misterioso exploradores del cielo DS" | 175 | 36 | 5 |
| wallapop | "pokemon mundo misterioso: exploradores del cielo" | 11,198 | 40 | 320 |
| wallapop | "pokemon negro" | 12,840 | 112 | 321 |
| wallapop | "pokemon negro DS" | 200 | 40 | 5 |
| wallapop | "pokemon perla" | 12,716 | 79 | 319 |
| wallapop | "pokemon perla DS" | 200 | 40 | 5 |
| wallapop | "pokemon platino" | 12,757 | 67 | 319 |
| wallapop | "pokemon platino DS" | 200 | 40 | 5 |
| wallapop | "pokemon soulsilver" | 12,678 | 64 | 317 |
| wallapop | "pokemon soulsilver DS" | 200 | 40 | 5 |
| wallapop | "shin chan contra los plastas" | 8,917 | 64 | 257 |
| wallapop | "shin chan contra los plastas DS" | 240 | 43 | 8 |
| wallapop | "shin chan contra los plastas ds" | 6,615 | 61 | 199 |
| wallapop | "solatorobo" | 19,505 | 99 | 460 |
| wallapop | "solatorobo DS" | 287 | 55 | 7 |
| wallapop | "the world ends with you" | 12,678 | 55 | 317 |
| wallapop | "the world ends with you DS" | 360 | 60 | 7 |

### `full-backup-0627` — `wallapop_data.jsonl.bak`

- `created_at` range: 2015-07-18T22:01:19 → 2026-06-27T16:49:36
- `scanned_at` range for wallapop: 2026-06-24T12:57:58 → 2026-06-27T16:57:33
- Row schemas: 1,982,876 rows with 9 keys (no `source`)
- Rows per item: median 97, max 1,102
- Items with at least one price change: 621 of 16,318 (3.8%); 712 price changes in total
- Items with at least one title change: 72 (0.4%)
- Rows with a non-numeric price: 0 (0.0%)
- Stored `is_noise` disagrees with the current rules on 94,284 of 1,982,876 rows (4.8%)

Missing or null rate per field:

| Field | Rows | Rate |
|---|---|---|
| `scanned_at` | 0 | 0.0% |
| `search_term` | 0 | 0.0% |
| `source` | 1,982,876 | 100.0% |
| `item_id` | 0 | 0.0% |
| `title` | 0 | 0.0% |
| `price` | 0 | 0.0% |
| `currency` | 0 | 0.0% |
| `created_at` | 0 | 0.0% |
| `url` | 0 | 0.0% |
| `is_noise` | 0 | 0.0% |

Per search term (terms shown in quotes to expose whitespace):

| Source | Term | Rows | Unique items | Distinct scanned_at values |
|---|---|---|---|---|
| wallapop | "ace attorney DS" | 18,315 | 178 | 136 |
| wallapop | "aliens infestation DS" | 3,169 | 55 | 159 |
| wallapop | "blue dragon DS" | 6,930 | 57 | 139 |
| wallapop | "castlevania DS" | 130,016 | 1,438 | 135 |
| wallapop | "castlevania order of ecclesia DS" | 7,480 | 61 | 141 |
| wallapop | "coleccion ds" | 138,312 | 1,472 | 142 |
| wallapop | "dragon ball origins 2 DS" | 5,768 | 68 | 156 |
| wallapop | "dragon quest IX DS" | 8,456 | 74 | 140 |
| wallapop | "dragon quest VI DS" | 6,538 | 50 | 142 |
| wallapop | "dragon quest monsters DS" | 12,207 | 114 | 138 |
| wallapop | "final fantasy tactics A2 DS" | 7,044 | 77 | 150 |
| wallapop | "ghost trick DS" | 6,602 | 73 | 157 |
| wallapop | "golden sun dark dawn DS" | 6,338 | 48 | 142 |
| wallapop | "infinite space DS" | 2,196 | 52 | 160 |
| wallapop | "kirby super star ultra DS" | 3,801 | 59 | 171 |
| wallapop | "last window DS" | 5,372 | 43 | 137 |
| wallapop | "legend of zelda phantom hourglass" | 21,415 | 217 | 124 |
| wallapop | "legend of zelda phantom hourglass DS" | 480 | 40 | 12 |
| wallapop | "legend of zelda spirit tracks" | 8,105 | 68 | 140 |
| wallapop | "lote nintendo ds" | 137,544 | 1,545 | 139 |
| wallapop | "mario & luigi DS" | 137,213 | 1,713 | 136 |
| wallapop | "metal slug 7 DS" | 3,458 | 58 | 161 |
| wallapop | "nintendo ds" | 138,015 | 1,676 | 139 |
| wallapop | "nintendo ds lite" | 137,756 | 1,531 | 141 |
| wallapop | "nintendo dsi" | 134,586 | 1,486 | 140 |
| wallapop | "pokemon blanco " | 141,147 | 1,504 | 140 |
| wallapop | "pokemon diamante DS" | 118,787 | 1,258 | 140 |
| wallapop | "pokemon heartgold" | 109,803 | 1,157 | 139 |
| wallapop | "pokemon mundo misterioso exploradores del cielo" | 5,987 | 51 | 146 |
| wallapop | "pokemon negro " | 140,073 | 1,552 | 138 |
| wallapop | "pokemon perla DS" | 121,104 | 1,299 | 139 |
| wallapop | "pokemon platino" | 129,919 | 1,374 | 140 |
| wallapop | "pokemon soulsilver" | 118,654 | 1,246 | 140 |
| wallapop | "solatorobo DS" | 4,156 | 63 | 167 |
| wallapop | "the world ends with you DS" | 6,130 | 66 | 158 |

### `current` — `wallapop_data.jsonl`

- `created_at` range: 2015-07-18T22:01:19 → 2026-07-09T14:35:20
- `scanned_at` range for vinted: 2026-07-09T14:25:27 → 2026-07-09T14:37:55
- `scanned_at` range for wallapop: 2026-06-24T12:58:01 → 2026-07-09T14:34:19
- Row schemas: 16,158 rows with 10 keys, 13,589 rows with 9 keys (no `source`)
- Rows per item: median 1, max 9
- Items with at least one price change: 1,362 of 27,891 (4.9%); 1,772 price changes in total
- Items with at least one title change: 89 (0.3%)
- Rows with a non-numeric price: 0 (0.0%)
- Stored `is_noise` disagrees with the current rules on 5,391 of 29,747 rows (18.1%)

Missing or null rate per field:

| Field | Rows | Rate |
|---|---|---|
| `scanned_at` | 0 | 0.0% |
| `search_term` | 0 | 0.0% |
| `source` | 13,589 | 45.7% |
| `item_id` | 0 | 0.0% |
| `title` | 0 | 0.0% |
| `price` | 0 | 0.0% |
| `currency` | 0 | 0.0% |
| `created_at` | 0 | 0.0% |
| `url` | 0 | 0.0% |
| `is_noise` | 0 | 0.0% |

Per search term (terms shown in quotes to expose whitespace):

| Source | Term | Rows | Unique items | Distinct scanned_at values |
|---|---|---|---|---|
| vinted | "ace attorney DS" | 294 | 294 | 2 |
| vinted | "aliens infestation DS" | 287 | 287 | 3 |
| vinted | "blue dragon DS" | 737 | 737 | 2 |
| vinted | "castlevania DS" | 512 | 512 | 1 |
| vinted | "castlevania order of ecclesia DS" | 241 | 241 | 2 |
| vinted | "dragon ball origins 2 DS" | 235 | 235 | 2 |
| vinted | "dragon quest IX DS" | 239 | 239 | 3 |
| vinted | "dragon quest VI DS" | 225 | 225 | 2 |
| vinted | "dragon quest monsters DS" | 331 | 331 | 3 |
| vinted | "final fantasy tactics A2 DS" | 258 | 258 | 3 |
| vinted | "ghost trick DS" | 103 | 103 | 1 |
| vinted | "golden sun dark dawn DS" | 263 | 263 | 3 |
| vinted | "infinite space DS" | 20 | 20 | 1 |
| vinted | "kirby super star ultra DS" | 26 | 26 | 1 |
| vinted | "last window DS" | 139 | 139 | 2 |
| vinted | "legend of zelda phantom hourglass" | 318 | 318 | 1 |
| vinted | "legend of zelda spirit tracks" | 412 | 412 | 3 |
| vinted | "lote nintendo ds" | 933 | 933 | 3 |
| vinted | "nintendo ds lite" | 970 | 969 | 3 |
| vinted | "nintendo dsi" | 737 | 737 | 2 |
| vinted | "pokemon blanco " | 866 | 865 | 2 |
| vinted | "pokemon diamante DS" | 805 | 805 | 2 |
| vinted | "pokemon heartgold" | 833 | 833 | 3 |
| vinted | "pokemon mundo misterioso exploradores del cielo" | 22 | 22 | 1 |
| vinted | "pokemon negro " | 944 | 944 | 3 |
| vinted | "pokemon perla DS" | 734 | 734 | 1 |
| vinted | "pokemon platino" | 894 | 894 | 2 |
| vinted | "pokemon soulsilver" | 402 | 401 | 3 |
| vinted | "solatorobo DS" | 109 | 109 | 2 |
| vinted | "the world ends with you DS" | 313 | 313 | 3 |
| wallapop | "ace attorney DS" | 188 | 181 | 8 |
| wallapop | "aliens infestation DS" | 45 | 42 | 11 |
| wallapop | "blue dragon DS" | 71 | 58 | 15 |
| wallapop | "castlevania DS" | 1,574 | 1,351 | 44 |
| wallapop | "castlevania order of ecclesia DS" | 66 | 58 | 6 |
| wallapop | "dragon ball origins 2 DS" | 67 | 65 | 8 |
| wallapop | "dragon quest IX DS" | 79 | 69 | 11 |
| wallapop | "dragon quest VI DS" | 50 | 46 | 6 |
| wallapop | "dragon quest monsters DS" | 117 | 113 | 7 |
| wallapop | "final fantasy tactics A2 DS" | 92 | 87 | 13 |
| wallapop | "ghost trick DS" | 67 | 61 | 7 |
| wallapop | "golden sun dark dawn DS" | 57 | 52 | 5 |
| wallapop | "infinite space DS" | 34 | 33 | 6 |
| wallapop | "kirby super star ultra DS" | 55 | 55 | 8 |
| wallapop | "last window DS" | 48 | 47 | 7 |
| wallapop | "legend of zelda phantom hourglass" | 205 | 192 | 12 |
| wallapop | "legend of zelda phantom hourglass DS" | 39 | 39 | 1 |
| wallapop | "legend of zelda spirit tracks" | 86 | 74 | 10 |
| wallapop | "lote nintendo ds" | 2,125 | 1,843 | 78 |
| wallapop | "metal slug 7 DS" | 53 | 49 | 7 |
| wallapop | "nintendo ds lite" | 2,200 | 1,933 | 92 |
| wallapop | "nintendo dsi" | 1,713 | 1,525 | 62 |
| wallapop | "pokemon blanco " | 1,345 | 1,197 | 59 |
| wallapop | "pokemon diamante DS" | 734 | 657 | 33 |
| wallapop | "pokemon heartgold" | 646 | 599 | 21 |
| wallapop | "pokemon mundo misterioso exploradores del cielo" | 67 | 51 | 13 |
| wallapop | "pokemon negro " | 1,985 | 1,791 | 74 |
| wallapop | "pokemon perla DS" | 695 | 637 | 31 |
| wallapop | "pokemon platino" | 1,532 | 1,405 | 29 |
| wallapop | "pokemon soulsilver" | 393 | 322 | 29 |
| wallapop | "solatorobo DS" | 58 | 57 | 8 |
| wallapop | "the world ends with you DS" | 59 | 54 | 11 |

### Overlap between JSONL files (unique item ids)

| A | B | Source | Items in both | Only in A | Only in B |
|---|---|---|---|---|---|
| `snapshot-0621` | `full-backup-0627` | wallapop | 2,115 | 1,110 | 14,203 |
| `snapshot-0621` | `compaction-1` | wallapop | 2,115 | 1,110 | 14,414 |
| `snapshot-0621` | `compaction-2` | wallapop | 1,908 | 1,317 | 13,012 |
| `snapshot-0621` | `compaction-3` | wallapop | 1,850 | 1,375 | 11,812 |
| `snapshot-0621` | `current` | wallapop | 1,706 | 1,519 | 12,986 |
| `snapshot-0621` | `current` | vinted | 0 | 0 | 13,199 |
| `full-backup-0627` | `compaction-1` | wallapop | 16,318 | 0 | 211 |
| `full-backup-0627` | `compaction-2` | wallapop | 14,743 | 1,575 | 177 |
| `full-backup-0627` | `compaction-3` | wallapop | 13,495 | 2,823 | 167 |
| `full-backup-0627` | `current` | wallapop | 12,246 | 4,072 | 2,446 |
| `full-backup-0627` | `current` | vinted | 0 | 0 | 13,199 |
| `compaction-1` | `compaction-2` | wallapop | 14,920 | 1,609 | 0 |
| `compaction-1` | `compaction-3` | wallapop | 13,662 | 2,867 | 0 |
| `compaction-1` | `current` | wallapop | 12,371 | 4,158 | 2,321 |
| `compaction-1` | `current` | vinted | 0 | 0 | 13,199 |
| `compaction-2` | `compaction-3` | wallapop | 13,662 | 1,258 | 0 |
| `compaction-2` | `current` | wallapop | 12,158 | 2,762 | 2,534 |
| `compaction-2` | `current` | vinted | 0 | 0 | 13,199 |
| `compaction-3` | `current` | wallapop | 12,036 | 1,626 | 2,656 |
| `compaction-3` | `current` | vinted | 0 | 0 | 13,199 |

### Items removed between backups and the file they were taken from

`full-backup-0627` → `compaction-1`: 0 items dropped, 0 of them not noise under the current rules.

`compaction-1` → `compaction-2`: 1,609 items dropped, 772 of them not noise under the current rules.

| Last search term | Dropped items | Not noise | Items of that term before |
|---|---|---|---|
| "nintendo ds" | 1,609 | 772 | 1,626 |

`compaction-2` → `compaction-3`: 1,258 items dropped, 703 of them not noise under the current rules.

| Last search term | Dropped items | Not noise | Items of that term before |
|---|---|---|---|
| "coleccion ds" | 1,258 | 703 | 1,267 |

`compaction-3` → `current`: 1,626 items dropped, 445 of them not noise under the current rules.

| Last search term | Dropped items | Not noise | Items of that term before |
|---|---|---|---|
| "mario & luigi DS" | 1,626 | 445 | 1,629 |

### `snapshot-0621` state files

| File | Size |
|---|---|
| `seen.json` | 68.3 kB |
| `exclusions.json` | 1.8 kB |
| `reviewed.json` | 50.7 kB |

- `seen.json`: 4,268 ids (4,268 Wallapop, 0 Vinted); 680 not in any audited JSONL
- `exclusions.json`: 86 `excluded`, 0 `excludedFromCalc`; 0 excluded ids not in any audited JSONL
- `reviewed.json`: 2,534 ids; 86 also excluded; **2,448 reviewed but not excluded** (the legacy label trap: import as `legacy_unknown`); 0 excluded but never reviewed

### `current` state files

| File | Size |
|---|---|
| `seen.json` | 405.8 kB |
| `exclusions.json` | 14.9 kB |
| `reviewed.json` | 306.7 kB |
| `learned_filters.json` | 110.7 kB |

- `seen.json`: 25,363 ids (12,162 Wallapop, 13,201 Vinted); 2 not in any audited JSONL
- `exclusions.json`: 741 `excluded`, 0 `excludedFromCalc`; 0 excluded ids not in any audited JSONL
- `reviewed.json`: 15,333 ids; 643 also excluded; **14,690 reviewed but not excluded** (the legacy label trap: import as `legacy_unknown`); 98 excluded but never reviewed
- `learned_filters.json`: 368 rules (`next_id` 479); 95 never fire in the watcher because their term is not an exact current search term (95 of them only differ by whitespace); 19 have a single distinct word; 6 contain duplicated words

<!-- END GENERATED -->
