"""The files' side of the question: what a lane holds, and what each file says about itself.

Nothing here knows about Traktor's XML. It answers three questions — which files are the pipeline's, can
this one be read at all, and what does its header and its tags say — and the collection side is `nml.py`.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import Config

# The pipeline's own vocabulary (music-agent's `rules`): an `.aif` is an AIFF like any other, and the lossy
# containers keep their codec. A lane file with a suffix outside this set is not a track.
LOSSLESS_EXTENSIONS = frozenset({"flac", "wav", "aiff", "aif"})
AUDIO_EXTENSIONS = LOSSLESS_EXTENSIONS | frozenset({"m4a", "mp3", "ogg", "opus"})

# A trailing bracket is metadata only when it looks like a code and sits at the very end — the pipeline's own
# rule. It is what lets `… Gladium [Mv2GrbiURW8].m4a` in the collection match `… Gladium.aiff` in a lane, and
# it has to stay that narrow: `[B Side]` is part of a title.
TRAILER = re.compile(r"\s*(\[[^\]]*\])\s*$")


def path_key(path: str | Path) -> str:
    """A path reduced to what identifies the file: NFC and casefolded — the two copies of a macOS name."""
    return unicodedata.normalize("NFC", str(path)).casefold()


def fold(text: str) -> str:
    """The comparison fold: Latin accents stripped, punctuation to spaces, case folded, spacing collapsed.

    Ported from the pipeline so that a name folded here and a name folded there cannot disagree. Only a mark
    following an ASCII letter is dropped, because that is what a Latin accent decomposes to; Japanese voicing
    and Cyrillic marks are parts of letters, and folding them would collide two different names.
    """
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFC", text))
    kept: list[str] = []
    for character in decomposed:
        if unicodedata.combining(character) and kept and kept[-1].isascii():
            continue
        kept.append(character)
    spaced = "".join(ch if (ch.isalnum() or unicodedata.combining(ch)) else " " for ch in kept)
    return unicodedata.normalize("NFC", " ".join(spaced.casefold().split()))


def _code(bracket: str) -> bool:
    """Whether a trailing bracket's contents look like a code rather than a word: nothing spaced, and long
    enough to be an identifier.

    `[LASK005]`, `[EhL-ztDTUYE]` and `[250120]` are codes; `[B Side]` and `[Free DL]` are words. Requiring a
    digit is not the test — his `EhL-ztDTUYE` has none.
    """
    inside = bracket.strip("[]")
    return len(inside) >= 4 and not any(character.isspace() for character in inside)


def stem_key(path: Path) -> str:
    """A file's name reduced to what identifies the track: folded, trailing codes dropped, spaced once."""
    stem = path.stem
    while (trailer := TRAILER.search(stem)) is not None and _code(trailer.group(1)):
        stem = stem[:trailer.start()]
    return " ".join(fold(stem).split())


def lane(config: Config) -> list[Path]:
    """The files the pipeline owns, both lanes, in one list — whether or not the collection has heard of them.

    A dotfile is not a track (the normalizer keeps its state in the lane, and Finder its `.DS_Store`).
    """
    found: list[Path] = []
    for folder in config.lanes():
        if not folder.is_dir():
            continue
        found += [path for path in sorted(folder.iterdir())
                  if path.is_file() and not path.name.startswith(".")
                  and path.suffix.lower().lstrip(".") in AUDIO_EXTENSIONS]
    return found


@dataclass(frozen=True)
class Facts:
    """What a file's header says, in the units the collection already uses.

    Measured against his own entries rather than assumed: `FILESIZE` is KiB (a 5,195,526-byte mp3 says 5076)
    and `PLAYTIME` is the length rounded **up** (127.608162 says 128, and 64.000000 says 64). `BITRATE` is
    bits per second, the AIFFs saying 1411200 — where rekordbox's rows take kbps and bytes, so each collection
    is written the way it reads.
    """

    size_kb: int = 0
    bit_rate: int = 0
    seconds: int = 0
    length: float | None = None


@dataclass(frozen=True)
class Tags:
    """The names a file carries. Empty fields are left alone rather than written blank."""

    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    label: str = ""
    genre: str = ""


# The frames this tool reads, ID3 first and the MP4 atoms second: an AIFF in this library carries ID3, an
# `.m4a` carries atoms, and `LABEL` is a freeform atom because MP4 has no standard one.
_FRAMES = {
    "title": ["TIT2", "\xa9nam"],
    "artist": ["TPE1", "\xa9ART"],
    "album": ["TALB", "\xa9alb"],
    "year": ["TDRC", "\xa9day"],
    "label": ["TPUB", "----:com.apple.iTunes:LABEL"],
    "genre": ["TCON", "\xa9gen"],
}


def _first(tags, keys: list[str]) -> str:
    for key in keys:
        if key in tags:
            value = tags[key]
            text = getattr(value, "text", None)
            if text:
                return str(text[0])
            if isinstance(value, list) and value:
                return str(value[0])
            if isinstance(value, str):
                return value
    return ""


def tags_of(path: Path) -> Tags:
    """What the file says it is, as far as the fields the collection writes go."""
    from mutagen import File as MutagenFile

    found = getattr(MutagenFile(path), "tags", None)
    if found is None:
        return Tags()
    return Tags(**{name: _first(found, keys) for name, keys in _FRAMES.items()})


def facts_of(path: Path) -> Facts:
    """A file's own numbers, read from its header rather than measured from its audio."""
    from mutagen import File as MutagenFile

    try:
        info = getattr(MutagenFile(path), "info", None)
    except Exception:                      # noqa: BLE001 — a container mutagen cannot open is a file with
        info = None                        # no numbers, whatever it raised on the way
    length = float(info.length) if info is not None and getattr(info, "length", None) else None
    return Facts(
        size_kb=round(path.stat().st_size / 1024),
        bit_rate=getattr(info, "bitrate", 0) or 0,
        seconds=math.ceil(length) if length else 0,
        length=length,
    )


def readable(path: Path) -> bool:
    """Whether a lane file is one this tool can read a header and tags out of.

    Tested by reading it, because there is no cheaper question. A lane can hold something that is not audio at
    all — a five-byte placeholder left by a test fixture, on this machine — and pointing the collection at one
    hands Traktor a file with nothing to analyze.
    """
    try:
        tags_of(path)
        facts_of(path)
    except Exception:                      # noqa: BLE001 — the question is exactly whether it can be read
        return False
    return True


# The characters Traktor rewrites when it writes a file name back. Read off the app rather than guessed at
# broadly: in its backup-and-rewrite cycle at 2026-10-13 16:33 it turned
# `Kimia Koochakzadeh-Yazdi - \ufeffĀVĀR (feat. Anahita Azimi).m4a` into `… - ?ĀVĀR ….m4a`, while the U+06DD
# in another of his names (`Four Tet (Wingdings) - …`) came through the same rewrite verbatim and is in the
# collection now — so "a format character" is too broad a rule, and the byte-order mark is what there is
# evidence for.
UNWRITABLE = frozenset({"\ufeff"})


def unwritable(path: Path) -> str:
    """Why a name cannot be written into the collection, or `""` when it can.

    The offending character is named, because the fix is his — a rename — and a rename is the only thing that
    settles it: this tool writing the name again would be rewritten by Traktor on its next quit, forever.
    """
    for character in path.name:
        if character in UNWRITABLE:
            return f"Traktor writes a ? where {character!r} (U+{ord(character):04X}) stands — rename the file"
    return ""
