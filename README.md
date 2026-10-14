# traktor-nml

Reconcile a Traktor collection against the files it is meant to hold.

Traktor has no API: its collection is one XML file, `collection.nml`, which the app reads whole at startup and
rewrites whole as it exits. This tool owns that file — it points the entries that describe a replaced file at
the file that replaced it, adds the tracks the lanes hold that the collection has never seen, and reports the
rest.

```sh
traktor-nml            # what it would do, writing nothing — the default verb
traktor-nml status     # one paragraph: entries, lanes, and what a run would do
traktor-nml apply      # one backup, one write, entries repointed and added
traktor-nml purge      # the entries whose file is gone, out — dry run until --apply
```

The same four verbs are served over MCP by [`traktor-mcp`](https://github.com/alchimestre/traktor-mcp):
`plan`, `status`, `apply` and `purge` (the last one dry unless its `apply` argument is true), each returning
the text the command line prints.

## What it decides, per entry

| decision | when | what it does |
|---|---|---|
| kept | the file is there | nothing. The write is a text edit, not a re-serialize, so a diff of the collection is the list of what changed |
| repointed | the file is gone and a replacement is on disk | points the entry at the replacement. Established by the run that made it (`replaces` → `local_path` in music-agent's job state, read as data), then by the name it carries (the same stem, folded, with a trailing *code* dropped) |
| added | a lane file no entry points at | writes an entry in the shape Traktor itself writes for an importer's work |
| gone | the file is not there and nothing replaced it | reports it. `plan` and `apply` never remove anything; `purge` is the verb that does, dry run first |

`purge` says what each removal costs before it writes: a playlist line moves to the entry that keeps the track,
or is dropped when nothing does.

A repointed entry keeps everything the app stored about the track — cues, play count, last played, import
date, artwork, the album, its playlist membership — and gives up what described the old file's audio:
`AUDIO_ID`, `TEMPO`, `LOUDNESS`, `MUSICAL_KEY`, the auto grid, and the `FLAGS` that says "analyzed". Check
Consistency → Analyze in the app measures them again from the file the entry now points at.

## Before it writes

1. Close Traktor. It rewrites the collection on exit, over anything written while it was up; `apply` refuses
   while it is running.
2. Run `plan` first. It writes nothing.
3. `apply` copies the collection to `collection.nml.<stamp>.backup` beside it, unless `--no-backup` is given.

## The format, as read off the file

| rule | evidence |
|---|---|
| escaping | `/` is written `/:` and a literal `:` is written `//`; both directions round-trip over every LOCATION in the collection |
| layout | every element is written paired and never self-closed, and an entry opens on the same line as its first child. `nml.entry_text` reproduces all 1,600-odd entries byte for byte |
| numbers | `FILESIZE` is KiB (a 5,195,526-byte mp3 says 5076), `PLAYTIME` is the length rounded up (127.608162 says 128), `BITRATE` is bits per second |
| dates | all 104 `RELEASE_DATE`s in a real collection are a full `2024/12/4`, so a tag carrying only a year is left off rather than written in a shape the app has never written |

## Two things it will not place

A lane file that is not readable audio, and a file whose name contains U+FEFF: Traktor rewrites such a name
with a `?` in its place, so an entry pointing at it cannot survive one quit of the app. Both are reported with
what to do; the fix for the second is a rename.

## Configuration

`config.toml` beside this file: the collection as a pattern (Traktor's directory carries its version number),
the two lanes, and music-agent's job state. `--config` reads another file. No secrets.

## Development

```sh
uv run pytest          # 39 tests; the two that need a real collection skip without one
uv run traktor-nml     # against the live collection, read-only
```
