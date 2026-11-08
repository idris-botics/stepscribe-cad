# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Rigid groups that no joint touches, and what that does to the headline.

When many groups have no joint evidence the joint count is not the degrees of freedom: the model says how
many joints were found, how many groups have none, and that the real DOF may be higher; and the headline
confidence never exceeds what the share without joints leaves.
"""

from __future__ import annotations

from stepscribe.features.hole_standards import load_table
from stepscribe.models.schema import KinematicModel


def unjointed_groups(model: KinematicModel) -> tuple[int, int]:
    """(rigid groups that no joint touches, all rigid groups)."""
    touched = {j.child_link for j in model.joints} | {j.parent_link for j in model.joints}
    return sum(g.id not in touched for g in model.links), len(model.links)


def many_unjointed(model: KinematicModel) -> bool:
    """True when so many rigid groups have no joint evidence that the joint count says little."""
    cfg = load_table("roles.yaml")["kinematics"]["unjointed"]
    free, total = unjointed_groups(model)
    return bool(
        total and free >= int(cfg["many_min_groups"]) and free / total >= float(cfg["many_share"])
    )


def unjointed_share(model: KinematicModel) -> float:
    free, total = unjointed_groups(model)
    return free / total if total else 0.0


def unjointed_text(model: KinematicModel) -> str:
    """ "1 joint found; 23 of 25 rigid groups have no joint evidence; the real DOF may be higher"."""
    free, total = unjointed_groups(model)
    n = len(model.joints)
    return (
        f"{n} joint{'s' if n != 1 else ''} found; {free} of {total} rigid groups have no joint "
        "evidence; the real DOF may be higher"
    )
