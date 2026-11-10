"""Replay a recorded run through the remaining-time estimator.

    python scripts/eta_replay.py events.json [--image-set basic|standard|full|none] [--at 0.25 0.5 0.75]

``events.json`` is the list a Tracker records (``Tracker.events_as_dicts()``): one object per event with ``t``
(seconds since the run started) and ``kind`` (stage, plan_parts, workers, part, plan_pairs, pair, plan_images,
image, skip, done), plus the fields the event carries. For each point in the run (a share of its total time)
the script prints what the estimator showed at that moment and how much time really remained. Nothing is
read except the file, and nothing is run: the estimate is a pure function of the events.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stepscribe.eta import Estimate, Event, estimate


def load(path: Path) -> list[Event]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [Event(**{**r, "sizes": tuple(r.get("sizes", ()))}) for r in rows]


def replay(events: list[Event], image_set: str, shares: list[float]) -> list[dict[str, object]]:
    """The estimate at each share of the run's total time, with the remaining time that turned out true."""
    total = max(e.t for e in events)
    out: list[dict[str, object]] = []
    previous: Estimate | None = None
    stamps = sorted({round(total * s, 3) for s in shares} | {e.t for e in events})
    wanted = {round(total * s, 3): s for s in shares}
    for now in stamps:  # every moment is replayed, so "the number never rises" holds across the run
        seen = [e for e in events if e.t <= now]
        est = estimate(seen, now, image_set, previous)
        previous = est
        if now in wanted:
            out.append(
                {
                    "share": wanted[now],
                    "elapsed_s": now,
                    "shown": est.text,
                    "low_s": est.low_s,
                    "high_s": est.high_s,
                    "true_remaining_s": round(total - now, 1),
                }
            )
    return sorted(out, key=lambda r: float(r["share"]))  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("events", type=Path)
    ap.add_argument("--image-set", default="basic", choices=["none", "basic", "standard", "full"])
    ap.add_argument("--at", type=float, nargs="+", default=[0.25, 0.5, 0.75])
    args = ap.parse_args(argv)
    for row in replay(load(args.events), args.image_set, args.at):
        print(
            f"{float(row['share']) * 100:>3.0f}% ({float(row['elapsed_s']):7.1f} s): "  # type: ignore[arg-type]
            f"remaining {row['shown']}; really {float(row['true_remaining_s']) / 60:.1f} min"  # type: ignore[arg-type]
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
