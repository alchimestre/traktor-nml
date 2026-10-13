"""The command line: that the default verb writes nothing, that `apply` is the only one that does, and that a
missing collection is a message rather than a traceback."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from test_sync import collection_file, entry_for, lane, moved

from traktor_nml import cli, sync
from traktor_nml import config as config_module


def config_for(tmp_path: Path, *, entries: str, run: tuple[Path, Path] | None = None):
    for name in ("lossless", "lossy"):
        (tmp_path / name).mkdir(exist_ok=True)
    where = collection_file(tmp_path / "collection.nml", entries)
    settings = replace(config_module.DEFAULTS, collection=where, lossless=tmp_path / "lossless",
                       lossy=tmp_path / "lossy", state=tmp_path / "state")
    if run is not None:
        (tmp_path / "state").mkdir(exist_ok=True)
        job = tmp_path / "state" / "20260101T000000Z-run"
        job.mkdir()
        (job / "tracks.jsonl").write_text(
            json.dumps({"replaces": str(run[0]), "local_path": str(run[1])}) + "\n", encoding="utf-8")
    return settings


def config_file(tmp_path: Path, settings) -> Path:
    """The config as a file, so the CLI is exercised through the loader it really uses."""
    where = tmp_path / "config.toml"
    where.write_text(
        "[paths]\n"
        f'collection = "{settings.collection}"\n'
        f'lossless = "{settings.lossless}"\n'
        f'lossy = "{settings.lossy}"\n'
        f'state = "{settings.state}"\n',
        encoding="utf-8",
    )
    return where


def test_the_default_verb_writes_nothing(tmp_path, capsys):
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    settings = config_for(tmp_path, entries=entry_for(was),
                          run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    moved(tmp_path, "Kiasmas - Blurred.aiff")
    before = settings.collection.read_bytes()

    assert cli.main(["--config", str(config_file(tmp_path, settings))]) == 0
    printed = capsys.readouterr().out
    assert "1 to repoint" in printed
    assert "nothing written yet" in printed
    assert settings.collection.read_bytes() == before


def test_apply_writes_it_and_names_the_backup(tmp_path, capsys):
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    settings = config_for(tmp_path, entries=entry_for(was),
                          run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    moved(tmp_path, "Kiasmas - Blurred.aiff")

    assert cli.main(["--config", str(config_file(tmp_path, settings)), "apply"]) == 0
    printed = capsys.readouterr().out
    assert "backed up to" in printed and "Check Consistency" in printed
    assert len(sync.plan(settings).repoints) == 0
    assert sync.plan(settings).kept == 1


def test_apply_on_a_settled_collection_says_so(tmp_path, capsys):
    settings = config_for(tmp_path, entries=entry_for(Path("/Users/vincent/Music/Losy Tracks/Gone.mp3")))
    before = settings.collection.read_bytes()

    assert cli.main(["--config", str(config_file(tmp_path, settings)), "apply"]) == 0
    assert "nothing to write" in capsys.readouterr().out
    assert settings.collection.read_bytes() == before


def test_status_prints_one_paragraph(tmp_path, capsys):
    settings = config_for(tmp_path, entries="")
    moved(tmp_path, "Kiasmos - Blurred.aiff")

    assert cli.main(["--config", str(config_file(tmp_path, settings)), "status"]) == 0
    printed = capsys.readouterr().out
    assert "1 to add" in printed and "files in the lanes" in printed


def test_a_missing_collection_is_a_message_not_a_traceback(tmp_path, capsys):
    settings = config_for(tmp_path, entries="")
    settings = replace(settings, collection=tmp_path / "nowhere" / "collection.nml")
    assert cli.main(["--config", str(config_file(tmp_path, settings)), "plan"]) == 1
    assert "no collection at" in capsys.readouterr().err


def test_the_help_says_what_the_verbs_are(capsys):
    try:
        cli.main(["--help"])
    except SystemExit:
        pass
    printed = capsys.readouterr().out
    for verb in ("plan", "status", "apply"):
        assert verb in printed
