"""The reconciliation itself: what every entry is owed, and the one write that settles it.

The decision per entry is deliberately narrow. An entry whose file is there is never touched. An entry whose
file is gone is either **repointed** at the file that replaced it, or reported — as a duplicate the collection
holds elsewhere, or as a file that is not there and was not replaced. A file in a lane that no entry points at
is **added**. Nothing is ever removed: a file that is not there may be a detached drive, and an entry that is
gone is cheaper to look at than to lose.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from . import nml
from .config import Config
from .files import (
    Tags,
    facts_of,
    fold,
    lane,
    path_key,
    readable,
    stem_key,
    tags_of,
    unwritable,
)
from .nml import TraktorRunning, location

# The cue Traktor computes from the audio rather than one Vincent placed: an auto grid is worth nothing on a
# file whose length the app has not measured.
AUTO_GRID = "4"

# Why an entry's file being gone reads the way it does. The two are different news: a lane file that vanished
# is a gap in the library, while a file outside both lanes was never this tool's to place — Traktor's own
# recordings live in `~/Music/Traktor/Recordings`, and their going missing is the app's business, not the
# pipeline's.
INSIDE = "nothing on disk carries the name"
OUTSIDE = "outside both lanes"


@dataclass
class Repoint:
    """One entry that describes a file a run replaced, and the file it made instead."""

    entry: ET.Element
    was: Path
    now: Path
    why: str


@dataclass
class Gone:
    """One entry whose file is not there, with the reason it is worth reading."""

    was: Path
    why: str


@dataclass
class Plan:
    """What reconciling the collection against the lanes comes to, before anything is written.

    A snapshot: the parsed entries, the files on disk, and the pipeline's records as they were read. Every
    report below is derived from it rather than from a previous run's output, so a reader sees what a writer
    would do right now.
    """

    where: Path
    volume: str
    entries: list[ET.Element] = field(default_factory=list, repr=False)
    total: int = 0
    kept: int = 0
    repoints: list[Repoint] = field(default_factory=list)
    additions: list[Path] = field(default_factory=list)
    superseded: list[Gone] = field(default_factory=list)
    missing: list[Gone] = field(default_factory=list)
    # Lane files this tool will not write an entry for, with the reason: not readable audio at all, or a name
    # Traktor cannot keep (see `files.unwritable`). Both are reported rather than acted on.
    unsupported: list[tuple[Path, str]] = field(default_factory=list)

    def gone(self) -> list[Gone]:
        return self.superseded + self.missing

    def writes(self) -> int:
        return len(self.repoints) + len(self.additions)

    def report(self) -> str:
        parts = [f"{len(self.repoints)} repointed", f"{len(self.additions)} added",
                 f"{self.kept} left alone"]
        if self.gone():
            parts.append(f"{len(self.gone())} whose file is gone")
        if self.unsupported:
            parts.append(f"{len(self.unsupported)} it cannot place")
        return " · ".join(parts)

    def lines(self) -> list[str]:
        """The report as lines: every action named, then everything reported rather than acted on."""
        out: list[str] = []
        for repoint in self.repoints:
            out.append(f"repoint  {repoint.was.name}")
            out.append(f"    ->   {repoint.now.name}   ({repoint.why})")
        for path in self.additions:
            out.append(f"add      {path.name}")
        for one in self.gone():
            out.append(f"gone     {one.was.name} — {one.why}")
        for path, why in self.unsupported:
            out.append(f"skip     {path.name} — {why}")
        return out


def identity(entry: ET.Element) -> tuple[str, str]:
    """What Traktor calls the track: the two names it displays, folded.

    The collection's own answer to "have I got this?", separate from the name a file carries, because the two
    copies of a track can be named quite differently (`… [Free DL].m4a` beside `… .aiff`). It only ever labels
    a report: nothing is written from it, and the pipeline's ±1 s length test is not available for a file that
    is gone.
    """
    return fold(entry.get("ARTIST") or ""), fold(entry.get("TITLE") or "")


def replacements(config: Config) -> dict[str, Path]:
    """Which file replaced which, out of music-agent's own records: `replaces` → `local_path`, newest last.

    Read as **data** rather than imported: the job state is a documented on-disk format — one JSON object per
    track — and a record carrying both fields is the pipeline's own word that a file took another's place, which
    is the strongest evidence a repoint can have. A later run's record for the same track overrides an earlier
    one's, which is why the runs are read oldest first.
    """
    found: dict[str, Path] = {}
    if not config.state.is_dir():
        return found
    for job in sorted(path for path in config.state.iterdir() if path.is_dir()):
        tracks = job / "tracks.jsonl"
        if not tracks.is_file():
            continue
        for line in tracks.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("replaces") and record.get("local_path"):
                found[path_key(record["replaces"])] = Path(record["local_path"])
    return found


def plan(config: Config) -> Plan:
    """Read the collection and the lanes, and decide per entry what to do — writing and moving nothing.

    Two things establish that a file replaced a file, in this order: the run that made it, and the name it
    carries. Only a file no entry points at can be a replacement, which is what keeps a repoint from putting
    the same track into the collection twice.
    """
    where = nml.find(config.collection)
    _text, entries = nml.read(where)
    found = Plan(where=where, volume=nml.volume_of(entries), entries=entries, total=len(entries))

    claimed = {path_key(location(entry)) for entry in entries}
    files = lane(config)
    found.unsupported = [(path, "not readable audio") for path in files if not readable(path)]
    found.unsupported += [(path, why) for path in files if (why := unwritable(path))]
    unsupported = {path_key(path) for path, _why in found.unsupported}
    spare = {path_key(path): path for path in files
             if path_key(path) not in claimed and path_key(path) not in unsupported}
    found.kept = sum(1 for entry in entries if location(entry).is_file())

    by_name: dict[str, list[Path]] = {}
    for path in spare.values():
        by_name.setdefault(stem_key(path), []).append(path)
    held = {identity(entry) for entry in entries if location(entry).is_file()}
    known = replacements(config)
    lanes = [path_key(folder) for folder in config.lanes()]

    for entry in entries:
        was = location(entry)
        if was.is_file():
            continue
        now = known.get(path_key(was))
        why = "the run that made it"
        if now is None or path_key(now) not in spare:
            candidates = by_name.get(stem_key(was), [])
            if len(candidates) > 1:
                found.missing.append(Gone(
                    was, "several files carry the name: " + ", ".join(one.name for one in candidates)))
                continue
            now = candidates[0] if candidates else None
            why = "the name it carries"
        if now is not None:
            found.repoints.append(Repoint(entry=entry, was=was, now=now, why=why))
            spare.pop(path_key(now), None)
            if (group := by_name.get(stem_key(now))) and now in group:
                group.remove(now)
            continue
        named = identity(entry)
        if named[1] and named in held:
            found.superseded.append(Gone(was, "the collection holds this track already"))
        elif any(path_key(was).startswith(f"{one}/") for one in lanes):
            found.missing.append(Gone(was, INSIDE))
        else:
            found.missing.append(Gone(was, f"{OUTSIDE} — {short(was.parent)}"))

    found.additions = sorted(spare.values())
    return found


def short(path: Path) -> str:
    """A directory with the home prefix abbreviated, for a report line."""
    text = str(path)
    home = str(Path.home())
    return text.replace(home, "~", 1) if text.startswith(home) else text


def numbers(info: ET.Element, facts) -> None:
    """The file-derived numbers on an INFO, replaced rather than left describing a file that is gone."""
    for name in ("FILESIZE", "BITRATE", "PLAYTIME", "PLAYTIME_FLOAT"):
        info.attrib.pop(name, None)
    if facts.size_kb:
        info.set("FILESIZE", str(facts.size_kb))
    if facts.bit_rate:
        info.set("BITRATE", str(facts.bit_rate))
    if facts.seconds:
        info.set("PLAYTIME", str(facts.seconds))
    if facts.length:
        info.set("PLAYTIME_FLOAT", f"{facts.length:.6f}")


def released(value: str) -> str:
    """A release date in the shape Traktor writes, or nothing at all.

    All 104 dates in his collection are a full `2024/12/4`, so a tag carrying only a year — or the `20211124`
    blob one of his files holds — is either filled out from the digits it does have or left off. Leaving it off
    loses a year from a column; writing a shape the app never writes puts a string into its collection that
    nothing has ever read.
    """
    digits = re.findall(r"\d+", value)
    if len(digits) == 1 and len(digits[0]) == 8:
        digits = [digits[0][:4], digits[0][4:6], digits[0][6:]]
    if len(digits) < 3:
        return ""
    return f"{digits[0]}/{int(digits[1])}/{int(digits[2])}"


def _tag_fields(info: ET.Element, written: Tags) -> None:
    """The tag-derived fields on an INFO, filled in only when the file carries them."""
    for name, value in (("GENRE", written.genre), ("LABEL", written.label),
                        ("RELEASE_DATE", released(written.year))):
        if value:
            info.set(name, value)


def repoint_entry(entry: ET.Element, path: Path, written: Tags, when: tuple[str, str]) -> None:
    """Move one entry onto the file that replaced the one it described.

    The location and the numbers that describe a file change; the cues, the play count, the last played and the
    import date do not, because they describe the track rather than the bytes. The fingerprint and everything
    the analyzer computed from the old encode go, so that what the app shows next was measured on the file it
    now points at — which is the mistake that was caught in rekordbox when a repointed row kept the old file's
    metadata.
    """
    directory, name = nml.split(path)
    entry.set("MODIFIED_DATE", when[0])
    entry.set("MODIFIED_TIME", when[1])
    entry.attrib.pop("AUDIO_ID", None)
    for name_of, value in (("TITLE", written.title), ("ARTIST", written.artist)):
        if value:
            entry.set(name_of, value)
    if (where := entry.find("LOCATION")) is not None:
        where.set("DIR", directory)
        where.set("FILE", name)
    for name_of in ("TEMPO", "LOUDNESS", "MUSICAL_KEY"):
        if (child := entry.find(name_of)) is not None:
            entry.remove(child)
    for cue in entry.findall("CUE_V2"):
        if cue.get("TYPE") == AUTO_GRID:
            entry.remove(cue)
    if (info := entry.find("INFO")) is not None:
        info.attrib.pop("FLAGS", None)          # what said "analyzed", which it is not any more
        info.attrib.pop("KEY", None)            # the key the analysis found
        numbers(info, facts_of(path))
        _tag_fields(info, written)
    if (modified := entry.find("MODIFICATION_INFO")) is not None:
        modified.set("AUTHOR_TYPE", "importer")


def added_entry(path: Path, volume: str, when: tuple[str, str]) -> ET.Element:
    """A new entry for a file the collection has never seen, in the shape Traktor writes for an importer's
    work: the names and the numbers the file carries, and nothing the analyzer would have to measure."""
    written = tags_of(path)
    directory, name = nml.split(path)
    entry = ET.Element("ENTRY", {"MODIFIED_DATE": when[0], "MODIFIED_TIME": when[1]})
    entry.set("TITLE", written.title or path.stem)
    if written.artist:
        entry.set("ARTIST", written.artist)
    ET.SubElement(entry, "LOCATION",
                  {"DIR": directory, "FILE": name, "VOLUME": volume, "VOLUMEID": volume})
    if written.album:
        ET.SubElement(entry, "ALBUM", {"TITLE": written.album})
    ET.SubElement(entry, "MODIFICATION_INFO", {"AUTHOR_TYPE": "importer"})
    info = ET.SubElement(entry, "INFO", {"IMPORT_DATE": when[0]})
    numbers(info, facts_of(path))
    _tag_fields(info, written)
    return entry


def write(found: Plan, *, backup: bool = True) -> Path | None:
    """Write the plan into the collection: one backup, one edit, and the app's own bytes everywhere else.

    The edits are made on the text rather than by re-serializing the document, so an entry nobody is repointing
    comes out exactly as Traktor left it — including the fingerprint that would otherwise be re-encoded on
    every entry in the file.
    """
    if nml.running():
        raise TraktorRunning(
            "Traktor is running, and it rewrites the collection as it exits — over anything written while it "
            "was up: close it, then run this again"
        )
    if not found.writes():
        return None

    where = found.where
    text = where.read_text(encoding="utf-8")
    spans = nml.entry_spans(text, found.entries)
    when = nml.stamp()

    edits: list[tuple[int, int, str]] = []
    for repoint in found.repoints:
        where_at = spans.get(id(repoint.entry))
        if where_at is None:
            raise nml.Changed(
                f"{where} is not the collection that was read: {repoint.was.name} is not in it")
        repoint_entry(repoint.entry, repoint.now, tags_of(repoint.now), when)
        edits.append((where_at[0], where_at[1], nml.entry_text(repoint.entry)))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]

    # A playlist references a track by its volume and path, so an entry that moved has to move in every
    # playlist that held it, or the track drops out of them.
    for repoint in found.repoints:
        was = nml.key_of(repoint.was, found.volume)
        text = text.replace(f'KEY="{was}"', f'KEY="{nml.key_of(repoint.now, found.volume)}"')

    if found.additions:
        added = "".join(f"{nml.entry_text(added_entry(path, found.volume, when))}\n"
                        for path in found.additions)
        anchor = "</COLLECTION>"
        if anchor not in text:
            raise nml.CollectionMissing(f"{where} holds no COLLECTION to add to")
        text = text.replace(anchor, f"{added}{anchor}", 1)

    counted = f'<COLLECTION ENTRIES="{found.total}">'
    if counted not in text:
        raise nml.Changed(f"{where} says something other than {counted}")
    text = text.replace(counted, f'<COLLECTION ENTRIES="{found.total + len(found.additions)}">', 1)

    written = nml.backup(where) if backup else None
    nml.replace(where, text)
    return written


def run(config: Config, *, apply: bool = False, backup: bool = True) -> tuple[Plan, Path | None]:
    """Read, decide, and write only when asked — the whole tool in one call, for both front ends."""
    found = plan(config)
    if not apply or not found.writes():
        return found, None
    return found, write(found, backup=backup)


def status(config: Config) -> str:
    """Where the collection and the lanes stand, in one paragraph and without listing anything."""
    found = plan(config)
    return (
        f"{found.where}\n"
        f"{found.total} entries · {found.kept} whose file is there · {len(lane(config))} files in the lanes\n"
        f"{len(found.repoints)} to repoint · {len(found.additions)} to add · "
        f"{len(found.superseded)} duplicate · {len(found.missing)} missing · "
        f"{len(found.unsupported)} it cannot place"
    )
