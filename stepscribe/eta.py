# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""The remaining-time estimate: one pure function from what has happened to the text and numbers shown.

``estimate(events, now, image_set, previous)`` is used by the UI and the command line alike (through
``Tracker``); nothing here reads a clock, a file or a global, so a run can be replayed from its events.

How it works
------------
- Until two parts are done, or 20 s of the parts stage have passed, it says "estimating...".
- In the parts stage the remaining time is observed throughput weighted by part cost (the face count, the
  cost model the part pool uses): faces left divided by faces per second so far, never less than what the
  biggest unfinished part still needs (the pool starts the biggest first, so it has been running since the
  stage began).
- The stages after the parts have no measured speed yet, so they use a rough prior built from the recorded
  stage times of eleven runs of one robot model (``PRIOR``): each stage as a share of the part CPU time.
  It is shown as a range, "about N to M minutes", never to the second. A stage whose own size is known (the
  contact pairs, the planned images) switches to its observed speed after a few steps.
- It is never negative. When the time for the current stage is used up the text says "taking longer than
  expected", and the last stage says "almost done".
- Whole minutes, and within a stage the shown range never rises (it can rise when a new stage starts).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MIN_PARTS_DONE = 2  # parts finished before the first number is shown
MIN_STAGE_SECONDS = 20.0  # or this long in the parts stage
LOW_FACTOR = 0.75  # range around the middle estimate of the parts stage
HIGH_FACTOR = 1.45
MIN_PAIRS_OBSERVED = 3
MIN_IMAGES_OBSERVED = 3
PRIOR_PAIR_SECONDS = (
    4.0  # a contact pair costs between 2 and 12 s on the recorded robot; this is a middle
)
PRIOR_IMAGE_SECONDS = (1.5, 5.0)

# Stage cost as a share of the CPU seconds all parts took (low, high). Recorded: eleven runs of one
# six-axis robot model, from stage timings (data/timings.json): assembly 0.13 to 0.25, understanding 0.04 to
# 0.07, images 0.08 to 0.14 for the basic set and 0.22 for the one recorded standard run. The full set was
# never recorded: its range is a wide assumption, not a measurement.
PRIOR: dict[str, tuple[float, float]] = {
    "assembly": (0.12, 0.30),
    "understanding": (0.04, 0.08),
    "images:none": (0.0, 0.0),
    "images:basic": (0.07, 0.16),
    "images:standard": (0.09, 0.26),
    "images:full": (0.12, 0.45),
    "write": (0.02, 0.06),
}
PRIOR_SECONDS_PER_FACE = 0.06  # one part worker, before any part has finished
STAGE_ORDER = ("reading", "parts", "assembly", "understanding", "render", "write", "done")


@dataclass(frozen=True)
class Event:
    """One thing that happened, *t* seconds after the run started."""

    t: float
    kind: str  # stage, plan_parts, part, plan_pairs, pair, plan_images, image, skip, done
    stage: str = ""  # stage: its name
    n: int = 0  # plan_parts: parts; plan_pairs: pairs; plan_images: images; part: faces
    faces: int = 0  # plan_parts: all faces
    cpu_s: float = 0.0  # part and pair: seconds the work took in its own process
    workers: int = 1  # plan_parts: part processes
    sizes: tuple[int, ...] = ()  # plan_parts: the face count of every part
    assembly: bool = False  # plan_parts: an assembly follows the parts


@dataclass(frozen=True)
class Estimate:
    state: str  # estimating, range, longer, almost_done, done
    stage: str
    low_s: float | None  # remaining seconds, never negative
    high_s: float | None
    text: str  # what to show after "remaining"
    fraction: float  # 0..1 for the bar
    low_min: int | None = None  # the whole minutes shown
    high_min: int | None = None

    @property
    def mid_s(self) -> float | None:
        if self.low_s is None or self.high_s is None:
            return None
        return 0.5 * (self.low_s + self.high_s)


def _minutes(seconds: float) -> int:
    return max(0, int(seconds / 60.0 + 0.5))


def range_text(low_min: int, high_min: int) -> str:
    """ "about 3 to 5 minutes", "about 4 minutes", "less than 2 minutes", "less than a minute"."""
    if high_min <= 0:
        return "less than a minute"
    if low_min >= high_min:
        return f"about {high_min} minute{'s' if high_min != 1 else ''}"
    if low_min <= 0:
        return "less than a minute" if high_min <= 1 else f"less than {high_min} minutes"
    return f"about {low_min} to {high_min} minutes"


def _stage_rank(stage: str) -> int:
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else len(STAGE_ORDER) - 2


@dataclass
class _Run:
    """What the events add up to."""

    stage: str = "reading"
    stage_t: float = 0.0
    plan_t: float | None = None
    n_parts: int = 0
    total_faces: int = 0
    workers: int = 1
    expect_assembly: bool = False
    sizes: tuple[int, ...] = ()
    part_faces: list[int] = None  # type: ignore[assignment]
    part_t: list[float] = None  # type: ignore[assignment]
    part_cpu: float = 0.0
    pairs_total: int = 0
    pairs_done: int = 0
    pair_t0: float = 0.0
    pair_t_last: float = 0.0
    images_total: int = 0
    images_done: int = 0
    image_t0: float = 0.0
    image_t_last: float = 0.0
    done: bool = False
    done_t: float = 0.0

    def __post_init__(self) -> None:
        self.part_faces = []
        self.part_t = []


def fold(events: Sequence[Event]) -> _Run:
    run = _Run()
    for e in events:
        if e.kind == "stage":
            run.stage, run.stage_t = e.stage, e.t
        elif e.kind == "plan_parts":
            run.plan_t, run.n_parts, run.total_faces = e.t, e.n, e.faces
            run.workers, run.expect_assembly = max(1, e.workers), e.assembly
            run.sizes = e.sizes
            run.stage, run.stage_t = "parts", e.t
        elif e.kind == "workers":
            run.workers = max(1, e.workers)
        elif e.kind == "part":
            run.part_faces.append(e.n)
            run.part_t.append(e.t)
            run.part_cpu += e.cpu_s
        elif e.kind == "plan_pairs":
            run.pairs_total, run.pair_t0, run.pair_t_last = e.n, e.t, e.t
            run.stage, run.stage_t = "assembly", e.t
        elif e.kind == "pair":
            run.pairs_done += 1
            run.pair_t_last = e.t
        elif e.kind == "plan_images":
            run.images_total, run.images_done = e.n, 0
            run.image_t0 = run.image_t_last = e.t
        elif e.kind in ("image", "skip"):
            run.images_done += 1
            run.image_t_last = e.t
        elif e.kind == "done":
            run.done, run.done_t = True, e.t
    return run


def _parts_remaining(run: _Run, now: float) -> tuple[float, float, float]:
    """(low, mid, high) seconds left in the parts stage.

    Observed throughput weighted by part cost (faces): the faces still to do divided by the faces per wall
    second so far, and never less than what the biggest unfinished part still needs. The pool starts the
    biggest part first, so that part has been running since the stage began."""
    faces_done = sum(run.part_faces)
    t0 = run.plan_t if run.plan_t is not None else 0.0
    cpu_per_face = (
        run.part_cpu / faces_done if faces_done and run.part_cpu > 0 else PRIOR_SECONDS_PER_FACE
    )
    left = list(run.sizes)
    for done in run.part_faces:
        if done in left:
            left.remove(done)
    faces_left = sum(left) if left else max(0, run.total_faces - faces_done)
    if not run.part_faces:
        mid = cpu_per_face * run.total_faces / run.workers
        return mid * LOW_FACTOR, mid, mid * HIGH_FACTOR
    span = max(run.part_t[-1] - t0, 1e-6)
    rate = faces_done / span  # faces per wall second, all workers together
    mid = faces_left / rate if rate > 0 else cpu_per_face * faces_left / run.workers
    if left:
        mid = max(mid, max(left) * cpu_per_face - max(0.0, now - t0))
    mid = max(0.0, mid)
    return mid * LOW_FACTOR, mid, mid * HIGH_FACTOR


def _stage_prior(name: str, cpu_total: float) -> tuple[float, float]:
    lo, hi = PRIOR[name]
    return lo * cpu_total, hi * cpu_total


def estimate(
    events: Sequence[Event],
    now: float,
    image_set: str = "basic",
    previous: Estimate | None = None,
) -> Estimate:
    """The estimate after *events*, *now* seconds into the run; *previous* keeps the number from rising."""
    run = fold(events)
    if run.done:
        return Estimate("done", "done", 0.0, 0.0, "done", 1.0, 0, 0)
    if run.plan_t is None or run.stage == "reading" or not run.total_faces:
        return Estimate("estimating", run.stage, None, None, "estimating...", 0.0)
    stage = run.stage
    images_key = f"images:{image_set if image_set in ('basic', 'standard', 'full') else 'none'}"
    t0 = run.plan_t
    p_low, p_mid, p_high = _parts_remaining(run, now)
    cpu_total = (
        run.part_cpu / sum(run.part_faces) * run.total_faces
        if run.part_faces and run.part_cpu > 0
        else PRIOR_SECONDS_PER_FACE * run.total_faces
    )
    rank = _stage_rank(stage)

    # ---- the time still to come, stage by stage, as (low, high) seconds
    low = high = 0.0
    expired = False  # the current stage has used up what was expected of it
    if rank <= _stage_rank("parts"):
        if len(run.part_faces) < MIN_PARTS_DONE and now - t0 < MIN_STAGE_SECONDS:
            return Estimate("estimating", stage, None, None, "estimating...", 0.0)
        low, high = p_low, p_high
        expired = len(run.part_faces) < run.n_parts and p_mid <= 0.0
    after = ["assembly"] if run.expect_assembly else []
    after += ["understanding", images_key, "write"]
    for name in after:
        s_rank = _stage_rank(name.split(":")[0] if not name.startswith("images") else "render")
        s_low, s_high = _stage_prior(name, cpu_total)
        in_stage = rank == s_rank
        if rank > s_rank:
            continue
        if in_stage:
            elapsed = max(0.0, now - run.stage_t)
            if name == "assembly" and run.pairs_total:
                per_pair = (
                    (run.pair_t_last - run.pair_t0) / run.pairs_done
                    if run.pairs_done >= MIN_PAIRS_OBSERVED
                    else PRIOR_PAIR_SECONDS
                )
                left = max(0, run.pairs_total - run.pairs_done) * per_pair
                s_low, s_high = left * LOW_FACTOR, left * HIGH_FACTOR
            elif name.startswith("images") and run.images_total:
                if run.images_done >= MIN_IMAGES_OBSERVED:
                    per = (run.image_t_last - run.image_t0) / run.images_done
                    left = max(0, run.images_total - run.images_done) * per
                    s_low, s_high = left * LOW_FACTOR, left * HIGH_FACTOR
                else:
                    left = max(0, run.images_total - run.images_done)
                    s_low, s_high = left * PRIOR_IMAGE_SECONDS[0], left * PRIOR_IMAGE_SECONDS[1]
            else:
                s_low, s_high = max(0.0, s_low - elapsed), max(0.0, s_high - elapsed)
            expired = s_high <= 0.0
        low += s_low
        high += s_high
    last_stage = stage in ("write", "render") and (
        stage == "write" or (run.images_total and run.images_done >= run.images_total)
    )
    low, high = max(0.0, low), max(high, 0.0)
    elapsed_total = max(now, 1e-6)
    mid = 0.5 * (low + high)
    fraction = elapsed_total / (elapsed_total + mid) if (elapsed_total + mid) > 0 else 0.0

    if last_stage:
        return Estimate(
            "almost_done", stage, 0.0, min(high, 60.0), "almost done", min(fraction, 0.99)
        )
    if expired or high <= 0.0:
        return Estimate(
            "longer", stage, 0.0, 0.0, "taking longer than expected", min(fraction, 0.99)
        )
    low_min, high_min = _minutes(low), max(_minutes(high), 1)
    low_min = min(low_min, high_min)
    if previous is not None and previous.state == "range" and previous.stage == stage:
        if previous.high_min is not None and high_min > previous.high_min:
            high_min = previous.high_min
        if previous.low_min is not None and low_min > previous.low_min:
            low_min = previous.low_min
        low_min = min(low_min, high_min)
    return Estimate(
        "range",
        stage,
        low,
        high,
        range_text(low_min, high_min),
        min(fraction, 0.99),
        low_min,
        high_min,
    )
