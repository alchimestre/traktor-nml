"""The file's own rules: the escaping, the layout Traktor writes, and the two checks that need the real
collection.

The layout check is the one that matters most: a generated entry is only Traktor's format if Traktor's own
entries come back through the same writer unchanged, byte for byte.
"""

from __future__ import annotations

import glob
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from traktor_nml import config as config_module
from traktor_nml import nml


def real_collection() -> Path:
    found = sorted(glob.glob(str(config_module.DEFAULTS.collection)))
    if not found:
        pytest.skip("no Traktor collection on this machine")
    return Path(found[0])


def entries_of(text: str) -> list[str]:
    """Every entry's own text, read out of the COLLECTION section in document order."""
    _start, _end = text.index("<COLLECTION"), text.index("</COLLECTION>")
    out: list[str] = []
    cursor = _start
    while True:
        at = text.find("<ENTRY", cursor)
        if at < 0 or at > _end:
            return out
        finish = text.index("</ENTRY>", at) + len("</ENTRY>")
        out.append(text[at:finish])
        cursor = finish


def test_a_path_survives_the_escaping_traktor_uses():
    """Read off the real collection: `/` is `/:` and a literal `:` is `//`. One of his entries is written
    `Le Piarre // Pica Pica Molinièra.mp3` while the file on disk carries the colon and the entry's own TITLE
    spells it `:`, and all 24 of Traktor's backups agree — so the two directions have to be exact inverses, or
    a repoint onto such a name is a path the app cannot follow."""
    for name in ["Jacques Puech - Le Piarre : Pica Pica Molinièra.mp3",
                 "Ø [Phase] - Edge Runner (Dub Edit).aiff",
                 "ΑΓΓΕΛΟΣ - Ωδή 4.aiff",
                 "/Users/vincent/Music/Losy Tracks/plain.mp3"]:
        assert nml.decode(nml.encode(name)) == name
    assert nml.encode("/Users/vincent/Music/Losy Tracks/plain.mp3") == \
        "/:Users/:vincent/:Music/:Losy Tracks/:plain.mp3"
    assert nml.encode("a:b") == "a//b"
    assert nml.encode("a/b") == "a/:b"


def test_a_path_splits_into_the_dir_and_the_file_traktor_writes():
    path = Path("/Users/vincent/Music/Losy Tracks/Jacques Puech - Le Piarre : Pica Pica Molinièra.mp3")
    assert nml.split(path) == (
        "/:Users/:vincent/:Music/:Losy Tracks/:",
        "Jacques Puech - Le Piarre // Pica Pica Molinièra.mp3",
    )


def test_the_volume_comes_off_the_entries():
    entries = ET.fromstring(
        '<C><ENTRY><LOCATION DIR="/:" FILE="a.mp3" VOLUME="Macintosh HD"></LOCATION></ENTRY>'
        '<ENTRY><LOCATION DIR="/:" FILE="b.mp3" VOLUME="Other"></LOCATION></ENTRY>'
        '<ENTRY><LOCATION DIR="/:" FILE="c.mp3" VOLUME="Macintosh HD"></LOCATION></ENTRY></C>'
    ).findall("ENTRY")
    assert nml.volume_of(entries) == "Macintosh HD"


def test_the_collection_is_found_by_pattern_and_refuses_two(tmp_path):
    """Traktor's version number is in the directory name, so the config carries a pattern — and guessing
    between two installed versions would edit whichever sorted first."""
    pattern = tmp_path / "Traktor *" / "collection.nml"
    with pytest.raises(nml.CollectionMissing) as empty:
        nml.find(pattern)
    assert "no collection at" in str(empty.value)

    for version in ("Traktor 4.5.1", "Traktor 4.6.0"):
        (tmp_path / version).mkdir()
        (tmp_path / version / "collection.nml").write_text("<NML></NML>", encoding="utf-8")
    with pytest.raises(nml.CollectionMissing) as two:
        nml.find(pattern)
    assert "point paths.collection" in str(two.value)

    (tmp_path / "Traktor 4.6.0" / "collection.nml").unlink()
    assert nml.find(pattern) == tmp_path / "Traktor 4.5.1" / "collection.nml"


def test_every_entry_traktor_wrote_survives_the_round_trip():
    """The format guard, and the reason a generated entry can be trusted: Traktor's own 1,600-odd entries come
    back byte for byte through the writer's own serializer, so what it emits is the app's layout rather than
    one that merely parses."""
    where = real_collection()
    text = where.read_text(encoding="utf-8")
    _text, entries = nml.read(where)
    assert len(entries) > 1000, "the guard is worthless against an empty collection"
    assert [nml.entry_text(entry) for entry in entries] == entries_of(text)


def test_every_location_in_the_real_collection_encodes_back_to_itself():
    """The escaping, checked against every path the app has written rather than the four above."""
    _text, entries = nml.read(real_collection())
    seen = 0
    for entry in entries:
        where = entry.find("LOCATION")
        if where is None:
            continue
        assert nml.split(nml.location(entry)) == (where.get("DIR"), where.get("FILE"))
        seen += 1
    assert seen > 1000
