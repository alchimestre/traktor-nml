"""Real, if tiny, audio files, so a test that reads a header has a real header to read.

`aiff` is built byte by byte and needs nothing at all. `mp4` goes through ffmpeg — which the pipeline itself
requires for its own conversions — and skips when it is not to hand rather than failing for a reason that is
not the code's.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

import pytest


def aiff(path: Path, frames: int = 800) -> Path:
    """A real AIFF: FORM/AIFF with a COMM chunk and some silence in SSND."""
    channels, bits = 2, 16
    data = b"\x00\x00" * frames * channels
    comm = struct.pack(">hLh", channels, frames, bits) + b"\x40\x0e\xac\x44" + b"\x00" * 6
    chunks = b"COMM" + struct.pack(">L", len(comm)) + comm
    body = struct.pack(">LL", 0, 0) + data
    chunks += b"SSND" + struct.pack(">L", len(body)) + body
    path.write_bytes(b"FORM" + struct.pack(">L", 4 + len(chunks)) + b"AIFF" + chunks)
    return path


def mp4(path: Path, seconds: float = 0.2) -> Path:
    """A real m4a, with atoms of its own. Fabricating one by hand is not worth it."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not here to make an m4a with")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={seconds}",
         "-c:a", "aac", str(path)],
        capture_output=True, check=True,
    )
    return path
