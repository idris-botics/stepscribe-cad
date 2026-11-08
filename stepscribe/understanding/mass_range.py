# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Low-to-high ranges of mass, principal moments, radii of gyration and static holding torque.

Only parts whose density is an assumption with a documented reason carry a range
(``Part.mass.density_range``: a density guessed from the name, or a material known only at family
level). Their point values stay the nominal ones everywhere; a range is shown beside them.

Nothing here invents a lower bound for a hollow or cast part: the density ranges are those of the
material family, and the fixed sentence in the assumptions says a hollow or cast part is lighter.

Ranges of a link or the assembly are taken over the corners of the parts' density ranges (each
uncertain part at its low or its high density; one factor per part, so instances of one part move
together). With more than ``MAX_CORNER_PARTS`` uncertain parts the corners are replaced by all-low,
all-high and every single flip from either. Static holding torque is exact interval arithmetic: each
part's term is linear in its mass and may have either sign, so each term takes its own min and max.
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np

from stepscribe.models.schema import Part, Report
from stepscribe.understanding.mass_distribution import _placed, reliable_body
from stepscribe.understanding.rigid_body import (
    Body,
    G,
    JointSpec,
    Payload,
    combine,
    principal_inertia,
)

MAX_CORNER_PARTS = 10


def factors(part: Part) -> tuple[float, float] | None:
    """(low, high) multipliers of the part's nominal mass, or None when it has no range."""
    r, d = part.mass.density_range, part.mass.density_g_cm3
    if r is None or not d:
        return None
    return r.min_g_cm3 / d, r.max_g_cm3 / d


def _scaled(body: Body, f: float) -> Body:
    return Body(body.mass_g * f, body.com_mm, body.inertia_g_mm2 * f)


def _lo(rows: list[np.ndarray]) -> np.ndarray:
    return np.asarray(np.min(np.array(rows), axis=0))


def _hi(rows: list[np.ndarray]) -> np.ndarray:
    return np.asarray(np.max(np.array(rows), axis=0))


def _combos(n: int) -> list[tuple[int, ...]]:
    if n <= MAX_CORNER_PARTS:
        return list(itertools.product((0, 1), repeat=n))
    out = {tuple([0] * n), tuple([1] * n)}
    for i in range(n):
        for base in (0, 1):
            v = [base] * n
            v[i] = 1 - base
            out.add(tuple(v))
    return sorted(out)


def _instances(report: Report, instance_ids: list[str]) -> list[tuple[Part, Any]]:
    assert report.assembly is not None
    parts = {p.id: p for p in report.parts}
    by_id = {i.id: i for i in report.assembly.instances}
    return [(parts[by_id[i].part_id], by_id[i]) for i in instance_ids]


def body_range(report: Report, instance_ids: list[str]) -> dict[str, Any] | None:
    """Range of mass, principal moments and radii of the instances, or None when none is uncertain."""
    pairs = _instances(report, instance_ids)
    placed = [(p, _placed(p, inst)) for p, inst in pairs]
    if any(isinstance(b, str) for _p, b in placed):
        return None
    uncertain = sorted({p.id: p for p, _b in placed if factors(p)}.values(), key=lambda p: p.id)
    if not uncertain:
        return None
    index = {p.id: k for k, p in enumerate(uncertain)}
    masses: list[float] = []
    moments: list[np.ndarray] = []
    radii: list[np.ndarray] = []
    for combo in _combos(len(uncertain)):
        bodies = []
        for p, b in placed:
            assert isinstance(b, Body)
            fr = factors(p)
            f = 1.0 if fr is None else fr[combo[index[p.id]]]
            bodies.append(_scaled(b, f))
        total = combine(bodies)
        pr = principal_inertia(total.inertia_g_mm2, total.mass_g)
        masses.append(total.mass_g)
        moments.append(pr.moments_g_mm2)
        radii.append(pr.radii_mm)
    reasons = sorted({p.mass.density_range.reason for p in uncertain if p.mass.density_range})
    return {
        "mass_g": [min(masses), max(masses)],
        "moments_g_mm2": [
            [float(a), float(b)] for a, b in zip(_lo(moments), _hi(moments), strict=True)
        ],
        "radii_of_gyration_mm": [
            [float(a), float(b)] for a, b in zip(_lo(radii), _hi(radii), strict=True)
        ],
        "reason": "; ".join(reasons),
        "parts": [p.id for p in uncertain],
    }


def interval_sum(terms: list[tuple[float, float, float]]) -> tuple[float, float]:
    """Interval of a sum of terms ``mass * coefficient``; each term is ``(mass low, mass high, coefficient)``.

    A coefficient may be negative (a counterweight): each term takes its own min and max, never all
    masses low or all high.
    """
    lo = sum(min(a * c, b * c) for a, b, c in terms)
    hi = sum(max(a * c, b * c) for a, b, c in terms)
    return lo, hi


def joint_ranges(
    report: Report,
    link_instances: dict[str, list[str]],
    joints: list[JointSpec],
    nominal: dict[str, float | None],
    up: np.ndarray,
    payload: Payload | None,
) -> dict[str, dict[str, Any]]:
    """Static holding-torque range per computed joint that rests on an uncertain part.

    *nominal* maps a joint ID to its computed value (None when not computed: such a joint stays so).
    """
    from stepscribe.understanding.rigid_body import _descendants

    gravity = -np.asarray(up, dtype=float) / np.linalg.norm(up) * G
    out: dict[str, dict[str, Any]] = {}
    for j in joints:
        if nominal.get(j.id) is None:
            continue
        axis = np.asarray(j.axis, dtype=float)
        origin = np.asarray(j.origin_mm, dtype=float) / 1000.0
        terms: list[tuple[float, float, float]] = []
        reasons: set[str] = set()
        any_range = False
        for lid in _descendants(joints, j.child):
            for p, inst in _instances(report, link_instances[lid]):
                body = reliable_body(p, inst)
                if isinstance(body, str):
                    break  # cannot happen for a computed joint
                m_kg = body.mass_g / 1000.0
                f = np.cross(body.com_mm / 1000.0 - origin, gravity)  # per kg
                w = float(-(axis @ gravity)) if j.kind == "prismatic" else float(-(axis @ f))
                fr = factors(p)
                terms.append((m_kg, m_kg, w) if fr is None else (m_kg * fr[0], m_kg * fr[1], w))
                if fr is not None and p.mass.density_range is not None:
                    any_range = True
                    reasons.add(p.mass.density_range.reason)
        if not any_range:
            continue
        if payload is not None:
            tip = (np.asarray(joints[-1].origin_mm, dtype=float) + payload.offset_mm) / 1000.0
            f = payload.mass_kg * gravity
            term = (
                float(-(axis @ f))
                if j.kind == "prismatic"
                else float(-(axis @ np.cross(tip - origin, f)))
            )
            terms.append((1.0, 1.0, term))
        lo_sum, hi_sum = interval_sum(terms)
        out[j.id] = {
            "min": lo_sum + 0.0,
            "max": hi_sum + 0.0,
            "reason": "interval over the parts with an uncertain density, each term at its own low or "
            "high mass (a term may have either sign): " + "; ".join(sorted(reasons)),
        }
    return out
