# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Modelled threads: coaxial bores that alternate between a minor and a major diameter.

Some CAD models draw a screw thread as rings (or a helix) instead of a plain bore. Read as ordinary holes
they give a nearest "edge" a fraction of a millimetre away: the thread's own flank. A thread found here is
named ("modelled thread, likely M2.5") with its evidence, and its faces are not counted as an edge.
"""

from __future__ import annotations

import numpy as np

from stepscribe.geometry.part_geom import PartGeom
from stepscribe.geometry.surfaces import cylinder_params
from stepscribe.models.schema import Hole, ModelledThread

MIN_FACES = 6  # alternating coaxial bores needed
MIN_RATIO, MAX_RATIO = (
    0.75,
    0.95,
)  # minor / major diameter of an ISO metric thread is about 0.8 to 0.87
MAX_ZONE_GAP_MM = 2.0  # major-diameter bores further apart than this are not one threaded zone
MIN_SWITCHES = 0.6  # share of neighbouring bores that change between minor and major
AXIS_TOL = 0.05  # mm: how far a bore's axis may be from the hole's
RADIUS_TOL = 0.03  # mm: bores within this are the same radius
NOMINAL_TOL = 0.04  # relative: the major diameter this close to a nominal size names it
# ISO metric coarse nominal diameters (mm): the thread sizes small enough to be modelled as rings.
NOMINAL_MM = (1.6, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0)


def _nominal(major_mm: float) -> str | None:
    best = min(NOMINAL_MM, key=lambda n: abs(n - major_mm))
    return f"M{best:g}" if abs(best - major_mm) / best <= NOMINAL_TOL else None


def detect_threads(part: PartGeom, holes: list[Hole]) -> dict[str, ModelledThread]:
    """The modelled thread of each hole that has one, by hole ID."""
    table = part.table
    cylinders = [
        (i, f, cylinder_params(f.face)) for i, f in enumerate(table.faces) if f.kind == "cylinder"
    ]
    out: dict[str, ModelledThread] = {}
    for h in holes:
        d = np.array([h.axis.direction.x, h.axis.direction.y, h.axis.direction.z], float)
        d /= np.linalg.norm(d)
        o = np.array([h.axis.origin.x, h.axis.origin.y, h.axis.origin.z], float)
        length = (h.depth_mm if h.depth_mm is not None else 1e6) + 0.5
        rows: list[tuple[float, float, int]] = []
        for i, f, cp in cylinders:
            axis = np.asarray(cp.direction, float)
            if abs(abs(float(np.dot(axis, d))) - 1.0) > 1e-3 or cp.radius > 1.6 * h.diameter_mm / 2:
                continue
            offset = np.asarray(cp.origin, float) - o
            if float(np.linalg.norm(offset - np.dot(offset, d) * d)) > AXIS_TOL:
                continue
            t = float(np.dot(np.asarray(f.centroid, float) - o, d))
            if -0.1 <= t <= length:
                rows.append((t, float(cp.radius), i))
        if len(rows) < MIN_FACES:
            continue
        rows.sort()
        radii = sorted({round(r, 2) for _t, r, _i in rows})
        merged: list[float] = []
        for r in radii:
            if not merged or r - merged[-1] > RADIUS_TOL:
                merged.append(r)
        if len(merged) != 2:
            continue
        lo, hi = merged
        # the exact radii: the mean of the bores in each of the two clusters
        lo = float(np.mean([r for _t, r, _i in rows if abs(r - lo) <= RADIUS_TOL]))
        hi = float(np.mean([r for _t, r, _i in rows if abs(r - hi) <= RADIUS_TOL]))
        if not MIN_RATIO <= lo / hi <= MAX_RATIO:
            continue
        # the threaded zone: the run of major-diameter bores (the rest of the hole may be a plain bore)
        major_t = [t for t, r, _i in rows if abs(r - hi) <= RADIUS_TOL]
        clusters: list[list[float]] = [[major_t[0]]]
        for t in major_t[1:]:
            if t - clusters[-1][-1] > MAX_ZONE_GAP_MM:
                clusters.append([])
            clusters[-1].append(t)
        zone = max(clusters, key=len)
        t0, t1 = zone[0] - 0.3, zone[-1] + 0.3
        every = rows  # all the coaxial bores, for the faces the thread owns
        rows = [row for row in rows if t0 <= row[0] <= t1]
        seq = [0 if abs(r - lo) < abs(r - hi) else 1 for _t, r, _i in rows]
        if len(rows) < MIN_FACES or seq.count(0) < 3 or seq.count(1) < 3:
            continue
        switches = sum(a != b for a, b in zip(seq, seq[1:], strict=False))
        if switches < MIN_SWITCHES * (len(seq) - 1):
            continue
        # every major-diameter bore is the thread's (the run-out too); the minor-diameter ones are the hole
        ids = {table.faces[i].id for _t, _r, i in rows}
        ids |= {table.faces[i].id for _t, r, i in every if abs(r - hi) <= RADIUS_TOL}
        free = 0
        for f in table.faces:
            if f.kind not in ("bspline", "plane") or f.id in ids:
                continue
            rel = np.asarray(f.centroid, float) - o
            radial = float(np.linalg.norm(rel - np.dot(rel, d) * d))
            along = float(np.dot(rel, d))
            # a free-form face inside the major radius of the bore is a thread flank wherever it is along the
            # hole (the helix runs on past the rings); a plane only counts inside the threaded zone
            inside = -0.3 <= along <= length if f.kind == "bspline" else t0 <= along <= t1
            if radial <= hi * 1.15 and inside:
                ids.add(f.id)
                free += f.kind == "bspline"
        major = 2 * hi
        out[h.id] = ModelledThread(
            nominal=_nominal(major),
            minor_mm=round(2 * lo, 3),
            major_mm=round(major, 3),
            n_faces=len(rows),
            free_form_faces=free,
            face_ids=sorted(ids),
            evidence=(
                f"{len(rows)} coaxial cylinder faces alternate between dia {2 * lo:.2f} and "
                f"{major:.2f} mm (minor/major {lo / hi:.2f}); {free} free-form flank face(s) between them"
            ),
        )
    return out
