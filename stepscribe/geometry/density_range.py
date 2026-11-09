# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""A range of density only where the density is an assumption with a documented reason.

Two reasons: the density was guessed from a part name, or the material is known only at family level
("steel", "aluminium", no grade). A density the designer states, one read from the STEP file, a material
with a grade and a measured mass have no range. The family ranges are in
``knowledge/material_density_ranges.yaml``. The point value is never changed by a range.
"""

from __future__ import annotations

import re

from stepscribe.features.hole_standards import load_table
from stepscribe.models.schema import DensityRange, MassProperties

NAME_REASON = "density guessed from the name; range for the family"
FAMILY_REASON = "material known only at family level; range for the family"
HOLLOW_SENTENCE = "If a part is hollow or cast, its real mass is lower than the estimate."


def family_range(keyword: str | None) -> tuple[float, float] | None:
    """(min, max) g/cm3 of a material family from the knowledge table, or None."""
    if keyword is None:
        return None
    row = load_table("material_density_ranges.yaml")["entries"].get(keyword)
    return None if row is None else (float(row["min_g_cm3"]), float(row["max_g_cm3"]))


def has_grade(material_text: str | None) -> bool:
    """A material text that carries a number ("aluminium 6061", "alu6061", "304") names a grade."""
    return bool(material_text and re.search(r"\d", material_text))


def family_note(keyword: str | None) -> str | None:
    """The family's own note (printed plastics: infill; cf: laminate and filament), or None."""
    if keyword is None:
        return None
    row = load_table("material_density_ranges.yaml")["entries"].get(keyword)
    return None if row is None else row.get("note")


def set_range(mass: MassProperties, keyword: str | None, reason: str) -> None:
    """Attach the family's range to a mass whose density is the family's point value; else clear it.

    The reason is the fixed one for the cause plus the family's note, when it has one.
    """
    r = family_range(keyword)
    ok = r is not None and mass.density_g_cm3 is not None and r[0] <= mass.density_g_cm3 <= r[1]
    note = family_note(keyword)
    mass.density_range = (
        DensityRange(min_g_cm3=r[0], max_g_cm3=r[1], reason=f"{reason}; {note}" if note else reason)
        if ok and r
        else None
    )
