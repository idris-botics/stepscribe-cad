# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""A mass the designer measured (``design_context.yaml``: ``parts: <name>: mass_g``).

For a closed valid solid the mass replaces the estimate and the inertia is scaled by the ratio of the
given to the estimated mass, so the distribution of mass stays that of the estimate. A part that is
refused for mass and inertia (not closed, a shell, complex or free-form geometry) keeps its refusal; the
given mass is recorded as not used, with the reason.
"""

from __future__ import annotations

import math
from typing import Any

from OCP.TopoDS import TopoDS_Shape

from stepscribe.models.schema import DesignerMass, Part

LABEL = "mass from designer; inertia assumes the same distribution as the estimate"
KEY = "mass_g"
LOW_PCT = 50.0  # a given mass below this share of the solid estimate gets a note
HIGH_PCT = 120.0  # or above this one


def parse_masses(ctx: dict[str, Any]) -> dict[str, float]:
    """The designer's ``mass_g`` per part name; ValueError with a plain message for a bad value."""
    parts = ctx.get("parts") or {}
    if not isinstance(parts, dict):
        return {}
    out: dict[str, float] = {}
    for name, entry in parts.items():
        if not isinstance(entry, dict) or KEY not in entry:
            continue
        value = entry[KEY]
        where = f"design_context.yaml, parts: {name}: {KEY}"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{where} must be a number in grams, not {value!r}")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{where} must be a number above 0 grams, not {value!r}")
        out[str(name)] = float(value)
    return out


def ratio_note(given_g: float, estimated_g: float | None) -> str | None:
    """A neutral note when the given mass is below 50 % or above 120 % of the solid estimate, else None."""
    if estimated_g is None or estimated_g <= 0:
        return None
    pct = given_g / estimated_g * 100.0
    if LOW_PCT <= pct <= HIGH_PCT:
        return None
    return (
        f"the measured mass is {pct:.0f}% of the solid estimate; "
        "the part may be hollow, printed or made of a different material"
    )


def refusal(part: Part) -> str | None:
    """Why a part's mass and inertia are refused, or None for a closed valid solid of real geometry."""
    from stepscribe.understanding.process import complex_geometry_reason

    if not part.is_valid_solid or part.topology.solids < 1:
        return "not a closed valid solid (an open shell or surface has no volume to scale an inertia from)"
    why = complex_geometry_reason(part)
    if why is not None:
        return f"complex or free-form geometry ({why}): its volume is not that of a real solid"
    return None


def apply_designer_mass(part: Part, shape: TopoDS_Shape, given_g: float) -> None:
    """Replace the part's mass by *given_g* and scale its inertia, or record why it was not used."""
    why = refusal(part)
    m = part.mass
    if why is not None:
        m.designer_mass = DesignerMass(
            given_g=given_g,
            used=False,
            note=f"the mass given ({given_g:g} g) was not used: {why}; the part keeps its refusal",
        )
        return
    estimated = m.mass_g
    if estimated is not None and m.inertia_tensor_g_mm2 is not None:
        scale = given_g / estimated
        inertia = [[v * scale for v in row] for row in m.inertia_tensor_g_mm2]
    else:  # no density: the same scaling from a unit density, i.e. a uniform density of mass over volume
        from stepscribe.geometry.properties import mass_properties

        if m.volume_mm3 <= 0:
            m.designer_mass = DesignerMass(
                given_g=given_g,
                used=False,
                note=f"the mass given ({given_g:g} g) was not used: the part has no volume",
            )
            return
        unit = mass_properties(shape, "", 1.0)
        assert unit.inertia_tensor_g_mm2 is not None and unit.mass_g is not None
        scale = given_g / unit.mass_g
        inertia = [[v * scale for v in row] for row in unit.inertia_tensor_g_mm2]
        m.density_g_cm3 = given_g * 1000.0 / m.volume_mm3
    m.mass_g = given_g
    m.density_range = None  # a measured mass has no range
    m.inertia_tensor_g_mm2 = inertia
    m.designer_mass = DesignerMass(
        given_g=given_g,
        used=True,
        estimated_g=estimated,
        note=LABEL,
        ratio_note=ratio_note(given_g, estimated),
    )
