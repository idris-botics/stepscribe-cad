# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Progress and ETA reporting for long runs (analysis quality is never traded for speed).

The Tracker records what happened as a list of events (``stepscribe.eta.Event``); the remaining time shown
by the page and the command line is the pure function ``stepscribe.eta.estimate`` applied to that list, so a
run can be replayed from its events (``scripts/eta_replay.py``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from stepscribe.eta import Estimate, Event
from stepscribe.eta import estimate as estimate_eta


@dataclass
class Progress:
    """A snapshot sent to the callback."""

    stage: str
    message: str
    fraction: float  # 0..1 overall, monotonic non-decreasing
    elapsed_s: float
    eta_s: float | None  # the middle of the range, seconds; None while estimating
    eta_text: str = "estimating..."  # what to show after "remaining": a range in whole minutes
    eta_low_s: float | None = None
    eta_high_s: float | None = None


ProgressFn = Callable[[Progress], None]


class Tracker:
    """Collects events and emits :class:`Progress` through an optional callback."""

    def __init__(
        self, callback: ProgressFn | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        self.callback = callback
        self.clock = clock
        self.start = clock()
        self.events: list[Event] = []
        self.n_parts = 0
        self.parts_done = 0
        self.pairs_total = 0
        self.pairs_done = 0
        self.images_total = 0
        self.images_done = 0  # drawn plus skipped: the counter ends at images_total
        self.images_skipped = 0
        self.stage_name = "reading"
        self.images_wanted = False
        self.image_set = "basic"
        self._last_fraction = 0.0
        self._previous: Estimate | None = None

    def _now(self) -> float:
        return self.clock() - self.start

    def _record(self, kind: str, **fields: object) -> None:
        self.events.append(Event(self._now(), kind, **fields))  # type: ignore[arg-type]

    def events_as_dicts(self) -> list[dict[str, object]]:
        """The events, for saving a run so it can be replayed."""
        return [asdict(e) for e in self.events]

    # ---- planning
    def plan_parts(
        self,
        n_parts: int,
        total_faces: int,
        expect_assembly: bool,
        images: int = 0,
        sizes: tuple[int, ...] = (),
        workers: int = 1,
    ) -> None:
        """Called once the STEP file is read and part sizes are known."""
        self.n_parts = n_parts
        self.images_total = images
        self._record(
            "plan_parts",
            n=n_parts,
            faces=total_faces,
            assembly=expect_assembly,
            sizes=tuple(sizes),
            workers=workers,
        )
        self.stage_name = "parts"
        self.emit(f"analysing {n_parts} part(s), {total_faces} faces")

    def set_workers(self, workers: int) -> None:
        """The part pool turned out to have this many processes."""
        self._record("workers", workers=workers)

    def plan_images(self, total: int, image_set: str | None = None) -> None:
        """The exact number of images the renderer will make or skip, known once the analysis is done."""
        if image_set:
            self.image_set = image_set
        self.images_total = total
        self.images_done = 0
        self.images_skipped = 0
        self._record("plan_images", n=total)

    def plan_pairs(self, pairs: int) -> None:
        """Called after the contact broad phase."""
        self.pairs_total = pairs
        self._record("plan_pairs", n=pairs)
        self.stage_name = "assembly"
        self.emit(f"checking {pairs} touching candidate pair(s)")

    # ---- events
    def stage(self, name: str, message: str) -> None:
        self.stage_name = name
        self._record("stage", stage=name)
        self.emit(message)

    def part_done(self, name: str, faces: int, seconds: float, cpu_s: float | None = None) -> None:
        """A part finished. *seconds* is its wall-clock share; *cpu_s* the time it took in its own process."""
        self.parts_done += 1
        self._record("part", n=faces, cpu_s=seconds if cpu_s is None else cpu_s)
        self.emit(f"part {self.parts_done}/{self.n_parts}: {name} ({faces} faces, {seconds:.1f}s)")

    def pair_done(self, seconds: float) -> None:
        self.pairs_done += 1
        self._record("pair", cpu_s=seconds)
        if self.pairs_done % 5 == 0 or self.pairs_done == self.pairs_total:
            self.emit(f"contact pair {self.pairs_done}/{self.pairs_total}")

    def image_done(self, name: str, seconds: float) -> None:
        self.images_done += 1
        self._record("image", cpu_s=seconds)
        self.emit(f"rendered {name} ({self.images_done}/{self.images_total})")

    def image_skipped(self, name: str, reason: str) -> None:
        """A planned image that was not drawn (a cap, nothing to show, or a failure): it still counts."""
        self.images_done += 1
        self.images_skipped += 1
        self._record("skip")
        self.emit(f"skipped {name} ({self.images_done}/{self.images_total}): {reason}")

    # ---- estimate
    def estimate(self) -> Estimate:
        """The remaining-time estimate from the events so far (the number shown never rises within a stage)."""
        image_set = self.image_set if self.images_wanted else "none"
        est = estimate_eta(self.events, self._now(), image_set, self._previous)
        self._previous = est
        return est

    def emit(self, message: str) -> None:
        if self.callback is None:
            return
        est = self.estimate()
        self._last_fraction = max(self._last_fraction, min(est.fraction, 0.99))
        self.callback(
            Progress(
                self.stage_name,
                message,
                self._last_fraction,
                self._now(),
                est.mid_s,
                est.text,
                est.low_s,
                est.high_s,
            )
        )

    def finish(self, message: str = "done") -> None:
        self.stage_name = "done"
        self._record("done")
        if self.callback:
            self.callback(Progress("done", message, 1.0, self._now(), 0.0, "done", 0.0, 0.0))
