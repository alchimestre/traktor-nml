# AGENTS.md

Working on this repository means working on a tool that rewrites a live DJ library's only index. Three rules
dominate everything else.

## Before touching a library

1. **Traktor has to be closed.** It reads `collection.nml` whole at startup and rewrites it whole as it exits,
   over anything written while it was up. `apply` refuses while the app is running; say so rather than retrying.
2. **Dry run first.** `traktor-nml` (or the `plan` tool) writes nothing and prints every action it would take.
   Put the report to Vincent whenever it is anything other than `0 repointed · 0 added`.
3. **A backup is per write** (`collection.nml.<stamp>.backup`, beside the collection) and is byte-identical to
   the file as it was read. Check one exists before reporting a change as done.
4. **The app's own follow-up is part of the report**: what it leaves unanalyzed is what **Check Consistency →
   Analyze** in Traktor is for, and that is also the only place the app proves it parsed what was written.

## Repo conventions

- **Nothing here is guessed from a specification.** Every rule about the file — the escaping, the element
  layout, the units, the date shape — is read off `collection.nml` and carries its evidence in a comment or a
  docstring, and each is guarded by a test against the real collection (`tests/test_nml.py`, skipped when there
  is none). If the app's behaviour contradicts a rule, the rule changes, not the evidence.
- **The write is a text edit, never a re-serialization.** An entry nobody is repointing has to come out byte
  for byte as Traktor wrote it, so a diff of the collection is the list of what changed. `nml.entry_spans` and
  `nml.entry_text` are the two halves of that, and both are pinned by the round-trip test.
- **`apply` never removes anything; `purge` is the one verb that does.** Vincent's word, 2026-10-13: *"There's
  no detached drive. Treat those missing files as incoherence."* A collection is an index of files that exist,
  so an entry pointing at nothing is residue: `purge` takes it out, moving a playlist reference to the entry
  that keeps the track and dropping it when nothing does, and it is a dry run until `--apply` — naming what each
  removal costs (playlist lines, cues, plays) before it writes. `plan` and `apply` still only add and repoint.
- **A repoint keeps the track and gives up the old file's audio.** Cues, play count, last played, import date,
  artwork and playlists stay; `AUDIO_ID`, tempo, loudness, key, the auto grid and `FLAGS` go, because Traktor
  measures them again from the file the entry now points at. Rekordbox's side of this lesson is music-agent's
  ticket 26 — the same mistake, found in the same week.
- **music-agent's job state is read as data**, never imported: `.state/jobs/<run>/tracks.jsonl` carries one JSON
  object per track, and a record with both `replaces` and `local_path` is the pipeline's own word that one file
  took another's place. Without that directory only the name rule applies.
- `uv run pytest` must pass. The two tests that need a real collection skip without one; everything else runs
  over a throwaway collection, two throwaway lanes and a throwaway run state.
