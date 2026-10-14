"""Traktor's own file: how it escapes a path, and how it writes an element.

Everything here is read off `collection.nml` rather than out of a specification, and each rule carries the
evidence with it. The two directions of the escaping are exact inverses over every LOCATION the app has ever
written, and `element_text`/`entry_text` reproduce all of the collection's entries byte for byte — which is
what makes a generated entry the app's format rather than one that merely parses.

`tests/test_nml.py` holds both of those checks against the real file.
"""

from __future__ import annotations

import glob
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

# The app's own process name, which its bundle declares as `CFBundleExecutable`.
PROCESS = "Traktor Pro 4"

# `\`/` is written `/:` and a literal `:` is written `//`. One entry is written
# `Le Piarre // Pica Pica Molinièra.mp3` in its LOCATION while the file on disk carries the colon and the
# entry's own TITLE spells it `:`, and all 24 of Traktor's own backups agree.
ESCAPES = {"/": "/:", ":": "//"}


class CollectionMissing(RuntimeError):
    """There is no collection to reconcile, or more than one matches."""


class TraktorRunning(RuntimeError):
    """Traktor is up, and it rewrites the collection as it exits."""


class Changed(RuntimeError):
    """The collection on disk is not the one that was read — something wrote to it in between."""


# --- the path codec ---------------------------------------------------------------------------------------


def encode(path: str | Path) -> str:
    """A path in Traktor's escaping."""
    return "".join(ESCAPES.get(character, character) for character in str(path))


def decode(text: str) -> str:
    """The inverse of `encode`."""
    out: list[str] = []
    index = 0
    while index < len(text):
        pair = text[index:index + 2]
        if pair == "/:":
            out.append("/")
            index += 2
        elif pair == "//":
            out.append(":")
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def split(path: Path) -> tuple[str, str]:
    """A path as Traktor splits it: the DIR, escaped and ending with the separator, and the FILE."""
    encoded = encode(path)
    cut = encoded.rfind("/:")
    return (encoded[:cut + 2], encoded[cut + 2:]) if cut >= 0 else ("", encoded)


def location(entry: ET.Element) -> Path:
    """The file an entry describes."""
    where = entry.find("LOCATION")
    if where is None:
        return Path()
    return Path(decode(f"{where.get('DIR') or ''}{where.get('FILE') or ''}"))


def key_of(path: Path, volume: str) -> str:
    """The string a playlist entry references a track by: the volume, then the escaped path."""
    return f"{volume}{encode(path)}"


# --- writing an entry the way Traktor writes one ----------------------------------------------------------


def _quoted(value: object) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def attributes(attributes: dict) -> str:
    return "".join(f' {name}="{_quoted(value)}"' for name, value in attributes.items())


def element_text(element: ET.Element) -> str:
    """One element as Traktor writes it: children on their own lines, and never self-closed.

    Not a guess — every one of the collection's 1,600-odd entries comes back byte for byte through this and
    `entry_text`, so an entry built here is in the app's own layout.
    """
    head = f"<{element.tag}{attributes(element.attrib)}>"
    if len(element):
        return f"{head}{''.join(element_text(child) for child in element)}</{element.tag}>\n"
    return f"{head}</{element.tag}>\n"


def entry_text(entry: ET.Element) -> str:
    """A whole ENTRY, which opens on the same line as its first child."""
    return f"<ENTRY{attributes(entry.attrib)}>" + "".join(element_text(child) for child in entry) + "</ENTRY>"


def entry_spans(text: str, entries: list[ET.Element]) -> dict[int, tuple[int, int]]:
    """Where each entry sits in the document, in document order so that a path two entries share still lands
    where it belongs."""
    found: dict[int, tuple[int, int]] = {}
    cursor = 0
    for entry in entries:
        where = entry.find("LOCATION")
        if where is None:
            continue
        marker = f"<LOCATION{attributes(where.attrib)}"
        at = text.find(marker, cursor)
        if at < 0:
            continue
        cursor = at + len(marker)
        start, end = text.rfind("<ENTRY", 0, at), text.find("</ENTRY>", at)
        if start >= 0 and end >= 0:
            found[id(entry)] = (start, end + len("</ENTRY>"))
    return found


# --- the file itself -------------------------------------------------------------------------------------


def stamp() -> tuple[str, str]:
    """Traktor's own two stamps: the date as `2026/10/13`, and seconds since local midnight.

    His own entries say `MODIFIED_DATE="2026/8/17" MODIFIED_TIME="60723"`, which is 16:52:03.
    """
    now = datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.strftime("%Y/%m/%d"), str(int((now - midnight).total_seconds()))


def find(pattern: Path) -> Path:
    """The collection this machine has, found by pattern so a Traktor upgrade needs no config edit.

    `glob.glob` rather than `Path.glob`: a wildcard in the *base* of a Path is taken literally, so
    `Path("Traktor *").glob("collection.nml")` finds nothing at all on every version.
    """
    found = sorted(Path(one) for one in glob.glob(str(pattern)))
    if not found:
        raise CollectionMissing(f"no collection at {pattern} — is Traktor installed?")
    if len(found) > 1:
        raise CollectionMissing(
            f"{len(found)} collections match {pattern}: they are "
            + ", ".join(str(one) for one in found)
            + " — point paths.collection at the one Traktor uses"
        )
    return found[0]


def read(where: Path) -> tuple[str, ET.Element, list[ET.Element]]:
    """The file's text, its root and its entries, parsed once so a write edits the very elements that were
    planned, and so the playlists and the collection come from the same reading of the file."""
    text = where.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    element = root.find("COLLECTION")
    if element is None:
        raise CollectionMissing(f"{where} holds no COLLECTION — that is not a Traktor collection")
    return text, root, element.findall("ENTRY")


def volume_of(entries: list[ET.Element]) -> str:
    """The volume the entries are on, read off the entries rather than assumed."""
    seen: dict[str, int] = {}
    for entry in entries:
        where = entry.find("LOCATION")
        if where is not None and where.get("VOLUME"):
            seen[where.get("VOLUME")] = seen.get(where.get("VOLUME"), 0) + 1
    return max(seen, key=seen.get) if seen else "Macintosh HD"


def running() -> bool:
    """Whether Traktor is up. It rewrites the collection as it exits, over anything written while it was."""
    return subprocess.run(["pgrep", "-x", PROCESS], capture_output=True, check=False).returncode == 0


def backup(where: Path) -> Path:
    """A copy beside the collection, stamped, before anything is written."""
    when = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = where.with_name(f"{where.name}.{when}.backup")
    shutil.copy2(where, target)
    return target


def replace(where: Path, text: str) -> None:
    """Write the collection through a scratch file, so a crash cannot leave half of one behind."""
    scratch = where.with_name(f"{where.name}.new")
    scratch.write_text(text, encoding="utf-8")
    scratch.replace(where)
