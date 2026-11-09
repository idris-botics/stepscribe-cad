# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""What to tell the person when a run stops outside the image stage.

Three things: a one-line reason, the path of a log file with the full traceback, and what was and was not
saved (a pack that already holds the text and ``data/report.json`` is kept and said to be kept).
"""

from __future__ import annotations

import platform
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from stepscribe.text_safety import clean_name

STAGE_TEXT = {
    "reading": "reading the STEP file",
    "parts": "analysing the parts",
    "assembly": "analysing the assembly",
    "understanding": "working out how the design moves",
    "render": "drawing the images",
    "write": "writing the pack files",
}


@dataclass
class Failure:
    message: str  # one line
    log: str | None  # path of the file with the full traceback
    saved: str  # what was and was not saved
    trace: str  # the traceback text (short form, for the server log)


def one_line(exc: BaseException, stage: str | None = None) -> str:
    """The reason in one line: a known error in plain words, else the type and the cleaned message."""
    from stepscribe.errors import friendly_message

    text = friendly_message(exc)
    if text is None:
        detail = clean_name(str(exc))[:200]
        text = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    where = STAGE_TEXT.get(stage or "")
    return f"The run stopped while {where}. {text}" if where else f"The run stopped. {text}"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "run"


def write_log(out_dir: Path, name: str, exc: BaseException, stage: str | None) -> Path | None:
    """The full traceback in ``<out_dir>/stepscribe_error_<name>.log``; None when it cannot be written."""
    from stepscribe import __version__

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"stepscribe_error_{_safe(name)}.log"
        header = (
            f"stepscribe {__version__}, Python {sys.version.split()[0]}, {platform.platform()}\n"
            f"file: {clean_name(name)}\nstage: {stage or 'unknown'}\n\n"
        )
        path.write_text(
            header + "".join(traceback.format_exception(exc)), encoding="utf-8", newline="\n"
        )
        return path
    except OSError:
        return None


def saved_summary(folder: Path | None, robot_expected: bool = False) -> str:
    """What the run left in *folder*, in words."""
    if folder is None or not folder.is_dir():
        return "Nothing was saved."
    files = [p for p in folder.rglob("*") if p.is_file()]
    if not files:
        return "Nothing was saved."
    if (folder / "data" / "report.json").is_file():
        missing = [
            n for n in ("robot.json", "robot.urdf") if robot_expected and not (folder / n).is_file()
        ]
        tail = f" Not written: {', '.join(missing)}." if missing else ""
        return (
            f"The text pack was already written and is kept in {folder} "
            f"({len(files)} files, with data/report.json).{tail}"
        )
    return (
        f"A partial pack is kept in {folder} ({len(files)} files). It has no data/report.json, "
        "so treat it as incomplete."
    )


def failure(
    exc: BaseException,
    out_dir: Path,
    name: str,
    stage: str | None,
    folder: Path | None,
    robot_expected: bool = False,
) -> Failure:
    log = write_log(out_dir, name, exc, stage)
    return Failure(
        one_line(exc, stage),
        str(log) if log else None,
        saved_summary(folder, robot_expected),
        "".join(traceback.format_exception(exc, limit=-6)),
    )
