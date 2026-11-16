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


def test_apply_writes_it_and_names_the_backup(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sync.nml, "running", lambda: False)
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
    settings = config_for(tmp_path, entries=entry_for(Path("/Music/Losy Tracks/Gone.mp3")))
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


def test_verify_json_reports_existing_collection_paths_without_writing(tmp_path, capsys):
    present = tmp_path / "outside the lanes" / "Track Name.mp3"
    present.parent.mkdir()
    present.write_bytes(b"audio")
    missing_membership = tmp_path / "lossless" / "not in collection.mp3"
    missing_membership.parent.mkdir()
    missing_membership.write_bytes(b"audio")
    missing_file = tmp_path / "outside the lanes" / "gone.mp3"
    settings = config_for(tmp_path, entries=entry_for(present) + entry_for(missing_file))
    before = settings.collection.read_bytes()
    requested = [present, missing_membership, missing_file]

    assert cli.main(["--config", str(config_file(tmp_path, settings)), "verify", "--json",
                     *(str(path) for path in requested)]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "collection": str(settings.collection.resolve()),
        "paths": {
            str(present.resolve()): True,
            str(missing_membership.resolve()): False,
            str(missing_file.resolve()): False,
        },
    }
    assert settings.collection.read_bytes() == before
    assert not list(tmp_path.glob("collection.nml.*.backup"))


def test_verify_json_rejects_a_malformed_collection(tmp_path, capsys):
    settings = config_for(tmp_path, entries="")
    settings.collection.write_text("<NML>", encoding="utf-8")

    assert cli.main(["--config", str(config_file(tmp_path, settings)), "verify", "--json",
                     str(tmp_path / "track.mp3")]) == 1
    assert capsys.readouterr().err


def test_verify_json_works_while_traktor_is_running(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sync.nml, "running", lambda: True)
    present = tmp_path / "Track Name.mp3"
    present.write_bytes(b"audio")
    settings = config_for(tmp_path, entries=entry_for(present))

    assert cli.main(["--config", str(config_file(tmp_path, settings)), "verify", "--json",
                     str(present)]) == 0
    assert json.loads(capsys.readouterr().out)["paths"][str(present.resolve())] is True
