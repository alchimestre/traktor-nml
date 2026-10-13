"""The reconciliation: what it decides, what it writes, and what it refuses.

Everything here runs over a throwaway collection, two throwaway lanes and a throwaway run state, so the only
tests that touch Vincent's own file are the two in `test_nml.py`.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest
from audio_files import aiff, mp4

from traktor_nml import config as config_module
from traktor_nml import files, nml, sync

VOLUME = "Macintosh HD"

# What Traktor writes for one file, copied from the real collection's own layout: the app writes every element
# paired and never self-closed, and the INFO carries the numbers a file has rather than the ones only its
# analyzer can measure. Kept literal rather than built with the module's own writer, because a fixture made by
# the code under test proves nothing about the format.
ENTRY = """<ENTRY MODIFIED_DATE="2026/8/17" MODIFIED_TIME="60723" AUDIO_ID="{audio_id}" TITLE="{title}" \
ARTIST="{artist}"><LOCATION DIR="{directory}" FILE="{name}" VOLUME="{volume}" VOLUMEID="{volume}"></LOCATION>
<MODIFICATION_INFO AUTHOR_TYPE="user"></MODIFICATION_INFO>
<INFO BITRATE="{bitrate}" FILESIZE="{size}" IMPORT_DATE="2026/8/17" PLAYTIME="128" PLAYTIME_FLOAT="127.6" \
FLAGS="{flags}"></INFO>
<TEMPO BPM="140.000000" BPM_QUALITY="100.000000"></TEMPO>
<LOUDNESS PEAK_DB="-0.900000" PERCEIVED_DB="-6.100000" ANALYZED_DB="-6.100000"></LOUDNESS>
<MUSICAL_KEY VALUE="21"></MUSICAL_KEY>
<CUE_V2 NAME="AutoGrid" DISPL_ORDER="0" TYPE="4" START="54.178480" LEN="0.000000" REPEATS="-1" \
HOTCUE="-1"><GRID BPM="143.000443"></GRID>
</CUE_V2>
{cues}</ENTRY>"""

HOTCUE = """<CUE_V2 NAME="n.n." DISPL_ORDER="0" TYPE="0" START="16.000000" LEN="0.000000" REPEATS="-1" \
HOTCUE="0"></CUE_V2>
"""


def coded(path: Path) -> tuple[str, str]:
    """The DIR and FILE Traktor writes for a path, spelled out here so the fixture does not lean on the
    module's own escaping."""
    encoded = str(path).replace(":", "//").replace("/", "/:")
    cut = encoded.rfind("/:")
    return encoded[:cut + 2], encoded[cut + 2:]


def entry_for(path: Path, *, title: str = "Blurred", artist: str = "Kiasmas", playcount: str = "",
              cues: str = HOTCUE) -> str:
    directory, name = coded(path)
    text = ENTRY.format(directory=directory, name=name, volume=VOLUME, title=title, artist=artist,
                        audio_id="AIAAAA==", flags="12", bitrate="320000", size="5076", cues=cues)
    if playcount:
        text = text.replace('PLAYTIME="128"', f'PLAYTIME="128" PLAYCOUNT="{playcount}"')
    return text


def collection_file(where: Path, entries: str) -> Path:
    """A collection in the app's own layout, with one playlist holding the first entry."""
    listed = ET.fromstring(f"<C>{entries}</C>")
    first = listed.find("ENTRY")
    key = f"{VOLUME}{nml.encode(nml.location(first))}" if first is not None else "none"
    where.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
        '<NML VERSION="20"><HEAD COMPANY="www.native-instruments.com" PROGRAM="Traktor Pro 4"></HEAD>'
        f'<COLLECTION ENTRIES="{len(listed.findall("ENTRY"))}">{entries}</COLLECTION><SETS></SETS>'
        '<PLAYLISTS><NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES COUNT="1">'
        '<NODE TYPE="PLAYLIST" NAME="Set">'
        '<PLAYLIST ENTRIES="1" TYPE="LIST" UUID="00000000000000000000000000000000">'
        f'<ENTRY><PRIMARYKEY TYPE="TRACK" KEY="{key}"></PRIMARYKEY></ENTRY>'
        '</PLAYLIST></NODE></SUBNODES></NODE></PLAYLISTS></NML>',
        encoding="utf-8",
    )
    return where


def lane(tmp_path: Path, name: str, *, where: str = "lossless") -> Path:
    """Where a lane file is — whether or not it has been made yet."""
    return tmp_path / where / name


def moved(tmp_path: Path, name: str, *, where: str = "lossless") -> Path:
    """A real file in one of the lanes, holding real numbers for the writer to read."""
    return aiff(lane(tmp_path, name, where=where))


def setup(tmp_path: Path, *, entries: str, run: tuple[Path, Path] | None = None,
          outside: Path | None = None) -> config_module.Config:
    """A config over a throwaway collection, two empty lanes, and at most one run's record.

    `outside` is a third directory, so that an entry pointing outside both lanes can be tested without
    Traktor's own recordings being on the machine.
    """
    for name in ("lossless", "lossy", "outside", "state"):
        (tmp_path / name).mkdir(exist_ok=True)
    where = collection_file(tmp_path / "collection.nml", entries)
    config = replace(config_module.DEFAULTS, collection=where, lossless=tmp_path / "lossless",
                     lossy=tmp_path / "lossy", state=tmp_path / "state")
    if run is not None:
        job = tmp_path / "state" / "20260101T000000Z-run"
        job.mkdir(exist_ok=True)
        (job / "tracks.jsonl").write_text(json.dumps(
            {"idx": 1, "artist": "Kiasmas", "title": "Blurred", "status": "tagged",
             "replaces": str(run[0]), "local_path": str(run[1])}) + "\n", encoding="utf-8")
    return config


def parsed(where: Path) -> list[ET.Element]:
    return ET.parse(where).getroot().find("COLLECTION").findall("ENTRY")


def an_entry(where: Path, title: str) -> ET.Element:
    return next(one for one in parsed(where) if one.get("TITLE") == title)


# --- the plan --------------------------------------------------------------------------------------------


def test_a_file_a_run_replaced_repoints_the_entry_that_described_it(tmp_path):
    """The whole point: the pass wrote `replaces` → `local_path`, and the collection still describes the file
    that is gone. The name is never the evidence when the run can say it instead."""
    config = setup(tmp_path, entries=entry_for(lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")),
                   run=(lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy"),
                        lane(tmp_path, "Kiasmas - Blurred.aiff")))
    now = moved(tmp_path, "Kiasmas - Blurred.aiff")

    found = sync.plan(config)
    assert [one.now for one in found.repoints] == [now]
    assert found.repoints[0].why == "the run that made it"
    assert not found.additions, "the file it moved onto must not be added a second time"
    assert found.kept == 0 and not found.gone()


def test_a_name_carries_the_replacement_when_no_run_does(tmp_path):
    """Half the collection predates this pipeline: `… Gladium [Mv2GrbiURW8].m4a` was re-acquired by hand as
    `… Gladium.aiff`, and a trailing bracket is code-like metadata by the pipeline's own rule."""
    was = lane(tmp_path, "Marina Herlop - Collige Virgo Gladium [Mv2GrbiURW8].m4a", where="lossy")
    config = setup(tmp_path, entries=entry_for(was, title="Collige Virgo Gladium [Mv2GrbiURW8]"))
    now = moved(tmp_path, "Marina Herlop - Collige Virgo Gladium.aiff")

    found = sync.plan(config)
    assert [one.now for one in found.repoints] == [now]
    assert found.repoints[0].why == "the name it carries"


def test_a_bracket_that_is_not_trailing_is_part_of_the_name(tmp_path):
    """`Ø [Phase]` is a name rather than metadata, so stripping brackets everywhere must not make two
    different tracks match."""
    was = lane(tmp_path, "Ø [Phase] - Edge Runner (Dub Edit).aiff", where="lossy")
    config = setup(tmp_path, entries=entry_for(was, artist="Ø [Phase]"))
    moved(tmp_path, "Ø - Edge Runner (Dub Edit).aiff")

    found = sync.plan(config)
    assert not found.repoints
    assert [one.was for one in found.missing] == [was]


def test_a_file_an_entry_already_points_at_is_never_a_replacement(tmp_path):
    """Two entries for one file is worse than a missing one: the lossless copy the pass made had already been
    imported into the collection by hand, so the stale entry is a duplicate rather than an upgrade."""
    was = lane(tmp_path, "Conntex - Conntex - Kokopelli [Free DL].m4a", where="lossy")
    now = lane(tmp_path, "Conntex - Kokopelli.aiff")
    config = setup(tmp_path, entries=entry_for(was, title="Kokopelli", artist="Conntex")
                   + entry_for(now, title="Kokopelli", artist="Conntex"), run=(was, now))
    moved(tmp_path, "Conntex - Kokopelli.aiff")

    found = sync.plan(config)
    assert not found.repoints
    assert not found.additions
    assert [one.was for one in found.superseded] == [was]
    assert "holds this track already" in found.superseded[0].why


def test_an_entry_whose_file_is_gone_from_a_lane_reads_as_a_gap(tmp_path):
    was = lane(tmp_path, "Someone - Gone.mp3", where="lossy")
    config = setup(tmp_path, entries=entry_for(was, title="Gone", artist="Someone"))

    found = sync.plan(config)
    assert [one.was for one in found.missing] == [was]
    assert found.missing[0].why == sync.INSIDE


def test_an_entry_whose_file_was_never_in_a_lane_reads_as_its_own(tmp_path):
    """Traktor's own recordings live in `~/Music/Traktor/Recordings`, and their going missing is the app's
    news rather than a gap in the library — so it reads differently, with the directory named."""
    was = tmp_path / "outside" / "Recording_2026-09-03_14h01m48s.wav"
    config = setup(tmp_path, entries=entry_for(was, title="Recording_2026-09-03", cues=""))

    found = sync.plan(config)
    assert [one.was for one in found.missing] == [was]
    assert sync.OUTSIDE in found.missing[0].why
    assert "outside" in found.missing[0].why, "the directory is what tells him which file this is"

    _, written = sync.run(config, apply=True)
    assert written is None, "a plan with nothing to repoint or add must not touch the file"


def test_a_file_the_collection_has_never_seen_is_an_addition(tmp_path):
    config = setup(tmp_path, entries="")
    now = moved(tmp_path, "Kiasmos - Blurred.aiff")

    found = sync.plan(config)
    assert found.additions == [now]
    assert found.total == 0 and found.kept == 0


def test_two_files_carrying_one_name_are_never_guessed_between(tmp_path):
    """The rule refuses what it cannot tell apart rather than picking one: the wrong repoint points an entry
    at another track's audio."""
    was = lane(tmp_path, "Someone - Thing.m4a", where="lossy")
    config = setup(tmp_path, entries=entry_for(was, title="Thing", artist="Someone"))
    moved(tmp_path, "Someone - Thing.aiff")
    moved(tmp_path, "Someone - Thing [2263738781].aiff")

    found = sync.plan(config)
    assert not found.repoints
    assert "several files carry the name" in found.missing[0].why


def test_a_file_that_is_not_audio_is_never_pointed_at(tmp_path):
    """A lane can hold something that is not a track at all: a test fixture once left a five-byte `audio`
    placeholder in Vincent's lossless lane, and pointing Traktor at it hands the app a file with nothing to
    analyze. It is reported instead."""
    config = setup(tmp_path, entries="")
    (config.lossless / "Kiasmos - Blurred.aiff").write_bytes(b"audio")
    real = moved(tmp_path, "Kiasmos - Real.aiff")

    found = sync.plan(config)
    assert found.additions == [real]
    assert [path.name for path, _why in found.unsupported] == ["Kiasmos - Blurred.aiff"]
    assert found.unsupported[0][1] == "not readable audio"

    sync.run(config, apply=True)
    assert len(parsed(config.collection)) == 1


def test_a_name_traktor_cannot_write_back_is_reported_rather_than_fought_over(tmp_path):
    """The app's own evidence: at 2026-10-13 16:33 it rewrote this file's name — a byte-order mark that leaked
    into it — as `?`, so an entry pointing at it cannot survive one quit of Traktor. Writing it again would be
    undone every time, so the tool reports it and the fix is a rename."""
    name = "Kimia Koochakzadeh-Yazdi - \ufeffĀVĀR (feat. Anahita Azimi).m4a"
    was = lane(tmp_path, "Kimia Koochakzadeh-Yazdi - ?ĀVĀR (feat. Anahita Azimi).m4a", where="lossy")
    config = setup(tmp_path, entries=entry_for(was, title="?ĀVĀR (feat. Anahita Azimi)",
                                               artist="Kimia Koochakzadeh-Yazdi"))
    aiff(lane(tmp_path, name, where="lossy"))

    found = sync.plan(config)
    assert not found.repoints, "it cannot be pointed at, so it must not be"
    assert not found.additions
    assert [path.name for path, _why in found.unsupported] == [name]
    assert "U+FEFF" in found.unsupported[0][1] and "rename the file" in found.unsupported[0][1]

    before = config.collection.read_bytes()
    sync.run(config, apply=True)
    assert config.collection.read_bytes() == before, "so the plan is stable rather than oscillating"

    # and the rule must not fire on the names the app demonstrably keeps: the U+06DD in another of his file
    # names came through Traktor's own rewrite verbatim, and accents, Greek and Turkish are ordinary
    for ordinary in ("Ø [Phase] - Edge Runner (Dub Edit).aiff", "ΑΓΓΕΛΟΣ - Ωδή 4.aiff",
                     "Şatellites - Yok Yok.aiff", "Cocanha - Fòrabanda.aiff", "Rødhåd - Target Line.aiff",
                     "Four Tet (Wingdings) - (\u06dd)\u06dd.aiff"):
        assert files.unwritable(Path(ordinary)) == "", ordinary


# --- the write -------------------------------------------------------------------------------------------


def test_a_repointed_entry_keeps_the_track_and_gives_up_the_old_files_audio(tmp_path):
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    config = setup(tmp_path, entries=entry_for(was, playcount="7"),
                   run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    now = moved(tmp_path, "Kiasmas - Blurred.aiff")
    before = config.collection.read_bytes()

    _found, written = sync.run(config, apply=True)
    assert written is not None and written.is_file()
    assert written.read_bytes() == before, "the backup has to be the collection as it was"

    entry = an_entry(config.collection, "Blurred")
    assert nml.location(entry) == now
    assert entry.find("INFO").get("PLAYCOUNT") == "7", "it is the same track, played seven times"
    assert entry.find("INFO").get("IMPORT_DATE") == "2026/8/17"
    assert entry.find("MODIFICATION_INFO").get("AUTHOR_TYPE") == "importer"

    # What described the file that is gone: the fingerprint, and everything measured from its audio.
    assert entry.get("AUDIO_ID") is None
    for name in ("TEMPO", "LOUDNESS", "MUSICAL_KEY"):
        assert entry.find(name) is None
    assert entry.find("INFO").get("FLAGS") is None
    assert [cue.get("TYPE") for cue in entry.findall("CUE_V2")] == ["0"], "his own cue survives"

    # The numbers are the new file's, in the collection's own units: KiB, bits per second, seconds rounded up.
    info = entry.find("INFO")
    assert info.get("BITRATE") == "1411200"
    assert info.get("FILESIZE") == str(round(now.stat().st_size / 1024))
    assert info.get("PLAYTIME") == "1"
    assert info.get("PLAYTIME_FLOAT", "").startswith("0.018")


def test_a_repoint_moves_the_playlist_entry_with_it(tmp_path):
    """A playlist references a track by volume and path, so without this the track drops out of every playlist
    that held it — which is why the pipeline chose a repoint over a delete in the first place."""
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    config = setup(tmp_path, entries=entry_for(was), run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    now = moved(tmp_path, "Kiasmas - Blurred.aiff")

    sync.run(config, apply=True)
    text = config.collection.read_text(encoding="utf-8")
    assert f'KEY="{VOLUME}{nml.encode(now)}"' in text
    assert f'KEY="{VOLUME}{nml.encode(was)}"' not in text


def test_an_added_entry_is_the_shape_traktor_writes_for_an_imported_file(tmp_path):
    """The app's own shape for a file whose audio it has not measured — his three recordings are written this
    way — and the count on the COLLECTION element, which is what Traktor reads."""
    config = setup(tmp_path, entries=entry_for(Path("/Users/vincent/Music/Losy Tracks/Old - Song.mp3")))
    now = moved(tmp_path, "Kiasmos - Blurred.aiff")

    found, _written = sync.run(config, apply=True)
    assert found.additions == [now]
    assert '<COLLECTION ENTRIES="2">' in config.collection.read_text(encoding="utf-8")

    added = an_entry(config.collection, "Kiasmos - Blurred")
    assert nml.location(added) == now
    assert added.get("AUDIO_ID") is None
    assert added.find("MODIFICATION_INFO").get("AUTHOR_TYPE") == "importer"
    assert added.find("INFO").get("IMPORT_DATE")
    assert added.find("TEMPO") is None and added.find("CUE_V2") is None


def test_every_entry_it_is_not_asked_to_touch_keeps_its_own_bytes(tmp_path):
    """The write edits the text rather than re-serializing the document, so a diff of the collection is the
    list of what changed — where re-serializing would re-encode every fingerprint in the file."""
    keep = Path("/Users/vincent/Music/Losy Tracks/Untouched - Song.mp3")
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    config = setup(tmp_path, entries=entry_for(keep, title="Song", artist="Untouched")
                   + entry_for(was), run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    moved(tmp_path, "Kiasmas - Blurred.aiff")

    before = config.collection.read_text(encoding="utf-8")
    sync.run(config, apply=True)
    after = config.collection.read_text(encoding="utf-8")

    def entry_text_of(text: str, title: str) -> str:
        at = text.index(f'TITLE="{title}"')
        start, end = text.rfind("<ENTRY", 0, at), text.index("</ENTRY>", at) + len("</ENTRY>")
        return text[start:end]

    assert entry_text_of(after, "Song") == entry_text_of(before, "Song")
    assert entry_text_of(after, "Blurred") != entry_text_of(before, "Blurred")


def test_nothing_is_written_without_apply(tmp_path):
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    config = setup(tmp_path, entries=entry_for(was), run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    moved(tmp_path, "Kiasmas - Blurred.aiff")
    before = config.collection.read_bytes()

    found, written = sync.run(config)
    assert found.repoints and written is None
    assert config.collection.read_bytes() == before


def test_a_second_pass_has_nothing_left_to_do(tmp_path):
    """The tool is meant to be run after every acquisition, so what it wrote has to read back as settled."""
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    config = setup(tmp_path, entries=entry_for(was), run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    moved(tmp_path, "Kiasmas - Blurred.aiff")
    moved(tmp_path, "Someone New - Fresh.aiff")

    first, _written = sync.run(config, apply=True)
    assert len(first.repoints) == 1 and len(first.additions) == 1

    second = sync.plan(config)
    assert not second.repoints and not second.additions and not second.gone()
    assert second.kept == 2
    assert sync.run(config, apply=True)[1] is None, "and it must not rewrite the file to say so"


def test_an_open_traktor_is_refused_and_the_collection_left_alone(tmp_path, monkeypatch):
    """It rewrites the collection as it exits, over anything written while it was up."""
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    config = setup(tmp_path, entries=entry_for(was), run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    before = config.collection.read_bytes()
    monkeypatch.setattr(nml, "running", lambda: True)

    with pytest.raises(nml.TraktorRunning):
        sync.write(sync.plan(config))
    assert config.collection.read_bytes() == before


# --- the file's own numbers and names ---------------------------------------------------------------------


def test_the_numbers_are_in_the_collections_own_units(tmp_path):
    """KiB, bits per second, seconds rounded **up** — measured against his own entries, where a 5,195,526-byte
    mp3 says 5076 and a 127.608162-second file says 128."""
    path = aiff(tmp_path / "tiny.aiff")
    facts = files.facts_of(path)
    assert facts.size_kb == round(path.stat().st_size / 1024)
    assert facts.bit_rate == 1411200
    assert facts.seconds == 1, "0.018 seconds rounds up to one"
    assert facts.length and 0.0 < facts.length < 0.1


def test_a_date_is_written_only_in_the_shape_traktor_writes():
    """All 104 of the collection's own dates are a full `2024/12/4`. A tag holding a year, a year and a month,
    or the `20211124` blob one of the files carries, is either filled out or left off — a shape the app has
    never written is not a shape to put into its collection."""
    assert sync.released("2024-05-03") == "2024/5/3"
    assert sync.released("2024/12/4") == "2024/12/4"
    assert sync.released("20211124") == "2021/11/24"
    assert sync.released("2026") == ""
    assert sync.released("2024-05") == ""


def test_an_m4a_keeps_its_atoms_when_it_is_read(tmp_path):
    """The lossy lane holds m4a files, whose names live in MP4 atoms rather than ID3 frames, and the run that
    renamed seven of them read exactly this."""
    from mutagen.mp4 import MP4

    path = mp4(tmp_path / "tagged.m4a")
    audio = MP4(path)
    audio["\xa9nam"] = ["Blurred"]
    audio["\xa9ART"] = ["Kiasmos"]
    audio["\xa9gen"] = ["Techno"]
    audio.save()

    assert files.tags_of(path).title == "Blurred"
    assert files.tags_of(path).artist == "Kiasmos"
    assert files.tags_of(path).genre == "Techno"


def test_a_name_is_folded_the_way_the_pipeline_folds_it():
    """Ported from the pipeline so that a name folded here and a name folded there cannot disagree."""
    assert files.fold("Ø [Phase]") == files.fold("ø [phase]")
    assert files.fold("Şatellites - Yok Yok") == files.fold("Satellites - Yok Yok")
    assert files.stem_key(Path("Lask - Astraylien [LASK005].m4a")) == \
        files.stem_key(Path("Lask - Astraylien.aiff"))
    assert files.stem_key(Path("a - b [B Side].aiff")) != files.stem_key(Path("a - b.aiff"))
