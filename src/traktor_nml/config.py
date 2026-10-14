"""Configuration: `config.toml` beside this project, read with the standard library.

It holds four directories and nothing else: the collection, the two lanes, and the pipeline state this tool
reads as data.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Config:
    """The four directories a run reads, and the one it writes."""

    collection: Path
    lossless: Path
    lossy: Path
    state: Path

    def lanes(self) -> tuple[Path, Path]:
        return (self.lossless, self.lossy)


# A working layout for someone with neither a config file nor a preference: the collection where Traktor puts
# it, and three directories of this tool's own. `config.example.toml` documents each one.
DEFAULTS = Config(
    collection=Path("~/Documents/Native Instruments/Traktor */collection.nml").expanduser(),
    lossless=Path("~/Music/music-agent/lossless").expanduser(),
    lossy=Path("~/Music/music-agent/lossy").expanduser(),
    state=Path("~/Music/music-agent/state").expanduser(),
)


def _resolve(value: str, base: Path) -> Path:
    """A path from the file: expanded, and resolved against the file's own directory when it is relative."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load(path: Path | None = None) -> Config:
    """Read the config, falling back to the defaults for anything it does not set.

    A missing file is not an error — the defaults are a working configuration — but a malformed one is,
    because ignoring it quietly would run against the wrong directories.
    """
    where = HERE / "config.toml" if path is None else Path(path).expanduser()
    base = where.parent
    if not where.is_file():
        return DEFAULTS

    with where.open("rb") as handle:
        paths = tomllib.load(handle).get("paths", {})

    return Config(
        collection=_resolve(paths.get("collection", str(DEFAULTS.collection)), base),
        lossless=_resolve(paths.get("lossless", str(DEFAULTS.lossless)), base),
        lossy=_resolve(paths.get("lossy", str(DEFAULTS.lossy)), base),
        state=_resolve(paths.get("state", str(DEFAULTS.state)), base),
    )
