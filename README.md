# traktor-nml

Reconcile a Traktor collection against the files it is meant to hold.

Traktor has no API and **no MCP of its own** — its collection is one XML file, `collection.nml`, which the app
reads whole at startup and rewrites whole as it exits. That file is the only surface there is, and this is the
tool that owns it: it points the entries that describe a file the pipeline replaced at the file that replaced
it, adds the tracks the lanes hold that the collection has never seen, and reports the rest.

```sh
traktor-nml            # what it would do, writing nothing — the default verb
traktor-nml status     # one paragraph: entries, lanes, and what a run would do
traktor-nml apply      # one backup, one write, entries repointed and added
traktor-nml purge      # the entries whose file is gone, out — dry run until --apply
```

The same four verbs are served over MCP by its own project,
[`traktor-mcp`](https://github.com/alchimestre/traktor-mcp) — `plan`, `status`, `apply` and `purge` (the last
one dry unless its `apply` argument is true) — each returning the text the command line prints.

## What it decides, per entry

| | |
|---|---|
| **kept** | the file is there. Untouched — the write is a text edit, not a re-serialize, so a diff of the collection is the list of what changed |
| **repointed** | the file is gone and a replacement is on disk. Established by the run that made it (`replaces` → `local_path` in music-agent's job state, read as data) and then by the name it carries (the same stem, folded, with a trailing *code* dropped) |
| **added** | a lane file no entry points at, written in the shape Traktor itself writes for an importer's work |
| **gone** | the file is not there and nothing replaced it. Reported by `plan`/`apply`, which never remove anything; `purge` is the verb that takes it out, dry run first |

`apply` never removes an entry; `purge` is the one verb that does, and it says what each removal costs before it
writes — a playlist line moved to the entry that keeps the track, or dropped when nothing does. An entry pointing
at nothing is residue rather than something that might come back: a collection is an index of files that exist.

A repointed entry keeps everything the app stored about the **track** — cues, play count, last played, import
date, artwork, the album, and its playlist membership — and gives up what described the old file's **audio**:
`AUDIO_ID`, `TEMPO`, `LOUDNESS`, `MUSICAL_KEY`, the auto grid, and the `FLAGS` that says "analyzed". Those come
back the moment Traktor analyzes the file it now points at, which its **Check Consistency → Analyze** does for
the tracks in exactly that state.

## Before it writes

- **Traktor must be closed.** It rewrites the collection on exit, over anything written while it was up;
  `apply` refuses while it is running.
- **`plan` and `status` write nothing**, and are cheap enough to run whenever.
- **A backup is taken beside the collection** (`collection.nml.<stamp>.backup`) unless `--no-backup` is given.

## What it knows about the format, and how

Every rule here is read off the file rather than out of a specification, and each carries its evidence:

- **The escaping.** `/` is written `/:` and a literal `:` is written `//`. One entry in a real collection is
  `Le Piarre // Pica Pica Molinièra.mp3` in its LOCATION while the file on disk carries the colon, and all 24 of
  Traktor's own backups agree. Both directions round-trip over every LOCATION in the collection.
- **The layout.** Traktor writes every element paired and never self-closed, and an entry opens on the same line
  as its first child. `nml.entry_text` reproduces all 1,600-odd entries of the collection byte for byte.
- **The numbers.** `FILESIZE` is KiB (a 5,195,526-byte mp3 says 5076) and `PLAYTIME` is the length rounded
  **up** (127.608162 says 128); `BITRATE` is bits per second. rekordbox's rows take kbps and bytes — the two
  collections are each written the way each of them reads.
- **The dates.** All 104 `RELEASE_DATE`s in the collection are a full `2024/12/4`, so a tag carrying only a year
  is left off rather than written in a shape the app has never written.

## Two things it will not place

A lane file that is not readable audio at all, and a file whose **name contains U+FEFF**: Traktor rewrote
`Kimia Koochakzadeh-Yazdi - \ufeffĀVĀR (feat. Anahita Azimi).m4a` as `… - ?ĀVĀR ….m4a` in its own rewrite at
2026-10-13 16:33, so an entry pointing at it cannot survive one quit of the app. Writing it again would be
undone every time, so both are reported with what to do — and the fix for the second is a rename.
(The U+06DD in one file's name came through the same rewrite verbatim, which is why the rule names the one
character there is evidence for rather than a Unicode category.)

## Configuration

`config.toml` beside this file: the collection as a **pattern** (Traktor's directory carries its version
number), the two lanes, and music-agent's job state. Nothing in it is a secret. `--config` reads another file.

## Development

```sh
uv run pytest          # 39 tests; the two that need a real collection skip without one
uv run traktor-nml     # against the live collection, read-only
```

**The MCP surface is its own project**, [`traktor-mcp`](https://github.com/alchimestre/traktor-mcp): it imports
this library and serves the same four verbs over stdio. This package is the command line and the library under
it.
