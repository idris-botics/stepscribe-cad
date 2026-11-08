# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""The list of images a pack run will make, built before any of them is drawn.

The planned total is the length of this list. Every entry ends as drawn or as skipped (a cap, nothing to
show, or a failure) and each of those counts in the progress counter, so the counter ends at the total.

The caps live here and are used by the renderers: at most ``MAX_PARTS_PER_TYPE`` parts per image type,
``MAX_EXTRA_IMAGES`` extra part images in all, and parts of more than ``MAX_FACES`` faces are left out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from stepscribe.describe.budget import rank_parts
from stepscribe.models.schema import Part, Report

if TYPE_CHECKING:
    from stepscribe.analysis import AnalyzedPart
    from stepscribe.api import Analysis

ASSEMBLY_BASE_VIEWS = ("iso", "front", "top")
# files of each whole-assembly image type (robots and assemblies, standard and full sets)
ASSEMBLY_TYPE_FILES: dict[str, tuple[str, ...]] = {
    "contacts": ("images/contact_map.png",),
    "links": ("images/link_map.png",),
    "kinematic": ("images/kinematic_diagram.png", "images/kinematic_axes.png"),
    "ranges": ("images/kinematic_ranges.png",),
}


@dataclass
class ImagePlan:
    """Planned image paths (relative to the pack folder), by group, in the order they are made."""

    base: list[str] = field(
        default_factory=list
    )  # assembly views, exploded view, link-coloured view
    parts: list[str] = field(default_factory=list)  # the basic per-part images
    extra: dict[str, list[str]] = field(default_factory=dict)  # per-part image type -> its slots
    assembly: dict[str, list[str]] = field(default_factory=dict)  # whole-assembly type -> its files

    @property
    def total(self) -> int:
        return (
            len(self.base)
            + len(self.parts)
            + sum(len(v) for v in self.extra.values())
            + sum(len(v) for v in self.assembly.values())
        )

    def names(self) -> list[str]:
        out = [*self.base, *self.parts]
        for v in self.extra.values():
            out += v
        for v in self.assembly.values():
            out += v
        return out


def applies(kind: str, part: Part, report: Report) -> bool:
    """False only when the image type certainly has nothing to show for the part."""
    if kind == "holes":
        return bool(part.holes)
    if kind == "weak":
        from stepscribe.describe.image_captions import part_weak_spots

        return bool(part_weak_spots(report, part))
    return True


def eligible_parts(
    kind: str, ranked: list[Part], by_id: dict[str, AnalyzedPart], report: Report
) -> list[Part]:
    """Parts that may get an image of *kind*, most important first, without the cap on how many."""
    from stepscribe.render.extra_images import MAX_FACES

    return [
        p
        for p in ranked
        if len(by_id[p.id].geom.table.faces) <= MAX_FACES and applies(kind, p, report)
    ]


def plan_images(
    analysis: Analysis, image_set: str, has_scene: bool = True, max_part_images: int | None = None
) -> ImagePlan:
    """Every image this run would make for *image_set* ("basic", "standard" or "full")."""
    from stepscribe.render import MAX_PART_IMAGES, dominant_hole_axis
    from stepscribe.render.extra_images import (
        MAX_EXTRA_IMAGES,
        MAX_PARTS_PER_TYPE,
        assembly_types_for,
        types_for,
    )

    report = analysis.report
    plan = ImagePlan()
    kin = report.understanding.kinematics if report.understanding else None
    has_joints = bool(kin is not None and kin.joints)
    if has_scene:
        plan.base = [f"images/assembly_{v}.png" for v in ASSEMBLY_BASE_VIEWS]
        plan.base.append("images/assembly_exploded.png")
        if has_joints:
            plan.base.append("images/kinematics_iso.png")
    by_id = {ap.part.id: ap for ap in analysis.parts}
    ranked = rank_parts([ap.part for ap in analysis.parts])
    for part in ranked[: max_part_images or MAX_PART_IMAGES]:
        plan.parts.append(f"images/parts/{part.id}_iso.png")
        if dominant_hole_axis(part) is not None:
            plan.parts.append(f"images/parts/{part.id}_axis.png")
    budget = MAX_EXTRA_IMAGES
    for kind in types_for(image_set):
        slots = eligible_parts(kind, ranked, by_id, report)[: min(MAX_PARTS_PER_TYPE, budget)]
        plan.extra[kind] = [f"images/parts/{p.id}_{kind}.png" for p in slots]
        budget -= len(slots)
    for kind in assembly_types_for(image_set):
        if kind == "contacts" and report.assembly is None:
            continue
        if kind in ("links", "kinematic", "ranges") and not has_joints:
            continue
        if kind == "ranges" and not any(
            j.range_source == "designer" and j.range_deg_or_mm for j in (kin.joints if kin else [])
        ):
            continue
        plan.assembly[kind] = list(ASSEMBLY_TYPE_FILES[kind])
    return plan
