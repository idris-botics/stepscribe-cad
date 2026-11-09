"""Generated models that reproduce what a hobby robot dog does to the analysis: many rigid groups and one
joint, a part with a modelled thread and a serration, servo holders, and a STEP file that assigns a default
material to some parts. Everything is made here; no outside file is used."""

from __future__ import annotations

import math
from pathlib import Path

from assembly_fixtures import Node, write_assembly
from assembly_fixtures_u import X_AXIS, bearing_608
from build123d import Box, Cylinder, Location, Pos, Rot, Shape


def loose_arm_many(out: Path, loose: int = 5) -> Path:
    """A two-link arm (two joints) and *loose* small blocks that nothing touches: rigid groups with no joint."""
    base = Pos(0, 0, 22.5) * Box(40, 30, 45) - Pos(0, 0, 30) * X_AXIS * Cylinder(11, 50)
    arm1 = (
        Box(10, 30, 90)
        - Pos(0, 0, -37) * X_AXIS * Cylinder(4, 12)
        - Pos(0, 0, 28) * X_AXIS * Cylinder(11, 12)
    )
    arm2 = Box(10, 30, 63) - Pos(0, 0, -26) * X_AXIS * Cylinder(4, 12)
    protos = {
        "Base": base,
        "Bearing608": bearing_608(),
        "ShaftA": Cylinder(4, 42),
        "ShaftB": Cylinder(4, 20),
        "ArmLink1": arm1,
        "ArmLink2": arm2,
        "LooseBlock": Box(20, 20, 20),
    }
    children = [
        Node("Base", "Base", Location()),
        Node("Bearing1", "Bearing608", Pos(0, 0, 30) * X_AXIS),
        Node("Shaft1", "ShaftA", Pos(11, 0, 30) * X_AXIS),
        Node("Arm1", "ArmLink1", Pos(27, 0, 67)),
        Node("Bearing2", "Bearing608", Pos(27, 0, 95) * X_AXIS),
        Node("Shaft2", "ShaftB", Pos(34, 0, 95) * X_AXIS),
        Node("Arm2", "ArmLink2", Pos(39, 0, 121)),
    ]
    for k in range(loose):
        angle = 2 * math.pi * k / max(loose, 1)
        children.append(
            Node(
                f"Loose{k}",
                "LooseBlock",
                Pos(400 * math.cos(angle), 400 * math.sin(angle), 10),
            )
        )
    return write_assembly(
        out / f"loose_arm_{loose}.step", protos, Node("LooseArm", children=children)
    )


def threaded_axe(teeth: int = 20) -> Shape:
    """A small pin like a servo axle: a ring of *teeth* equal serrations round Ø4.9, a stack of alternating
    Ø2.07 / Ø2.52 bores (a modelled M2.5 thread), 14 mm long."""
    body = Cylinder(2.45, 14)
    tooth = Box(0.5, 0.35, 5)
    for k in range(teeth):
        a = 360.0 * k / teeth
        body = body - Rot(0, 0, a) * Pos(2.45, 0, 4.0) * tooth
    z = -7.0
    for k in range(10):
        r = 1.26 if k % 2 else 1.035
        body = body - Pos(0, 0, z + 0.3 + 0.6 * k) * Cylinder(r, 0.6)
    return body


def servo_holder(with_pocket: bool) -> Shape:
    """A 40 x 30 x 4 mm plate; with a 23 x 12.5 mm through pocket (the size of a small hobby servo) or not."""
    plate = Box(40, 30, 4)
    return plate - Box(23, 12.5, 6) if with_pocket else plate


def clearance_holder() -> Shape:
    """A 50 x 30 x 4 mm plate with a 24.7 x 13.2 mm through pocket: a micro servo body (22.5 x 12 mm) with
    clearance, the size of the opening in the dog's main servo holder."""
    return Box(50, 30, 4) - Box(24.7, 13.2, 6)


def named_parts(out: Path) -> Path:
    """An assembly of three plates named like the dog's: a servo holder with no pocket, a holder with a
    servo-sized pocket, and a connector plate named after a servo model; plus the threaded axe."""
    protos = {
        "main servo holder": servo_holder(False),
        "servo bracket pocket": servo_holder(True),
        "mg90 connector hole": Box(20, 10, 3),
        "clearance holder": clearance_holder(),
        "axe": threaded_axe(),
        "frame plate": Box(60, 60, 4) - Box(30, 30, 6),
    }
    root = Node(
        "NamedParts",
        children=[
            Node("Holder", "main servo holder", Location()),
            Node("Pocket", "servo bracket pocket", Pos(60, 0, 0)),
            Node("Connector", "mg90 connector hole", Pos(0, 60, 0)),
            Node("Clearance", "clearance holder", Pos(0, -60, 0)),
            Node("Axe", "axe", Pos(60, 60, 0)),
            Node("Frame", "frame plate", Pos(-60, 0, 0)),
        ],
    )
    return write_assembly(out / "named_parts.step", protos, root)


def edge_hole_plate(out: Path) -> Path:
    """A 100 x 100 x 10 mm plate with a 3 mm hole whose edge is 1 mm from the plate edge: an edge-distance
    finding under any process guideline."""
    from build123d import export_step

    body = Box(100, 100, 10) - Pos(-47.5, 0, 0) * Cylinder(1.5, 30)
    path = out / "edge_hole_plate.step"
    export_step(body, str(path))
    return path
