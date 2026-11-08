# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Agreement between two methods on generated solids: mass, centre of mass and principal moments.

    python scripts/check_inertia.py [--count 300] [--seed 20260101]

Method 1 is what stepscribe reports: OpenCASCADE's exact integration over the B-rep
(``mass_properties`` plus ``principal_inertia``). Method 2 is independent of it: the solid is
tessellated finely and the closed triangle mesh is integrated with signed tetrahedra (each
triangle and the origin make one tetrahedron whose volume, first and second moments have closed
forms), in numpy only. OpenCASCADE is used by method 2 only to make the triangles.

The shapes are generated and deterministic (a seeded generator): boxes, cylinders, spheres and
boxes with cut holes, each rotated and offset at random. Nothing here is a measurement of a real
part, and agreement of two methods is not accuracy: both assume a closed solid of one uniform
density.

Tolerance. The mesh is inscribed in every curved surface, so it is slightly smaller than the
solid. For a chord that subtends an angle t, a circle's area is short by about t^2 / 6 of itself,
and a moment of a circle (it grows with the fourth power of the radius) by about 4 * t^2 / 6 at
the most. The meshes use an angular deflection of ``ANGULAR_DEFLECTION`` rad, so
t <= 0.03 gives 4 * 0.03^2 / 6 = 6e-4 as the worst case; the tolerance is ``REL_TOL`` = 1e-3,
above that bound with room for rounding. The centre of mass is compared to ``COM_TOL`` of the part's diagonal. A
difference above these means one of the two methods is wrong, not that the mesh is coarse.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape

from stepscribe.geometry.properties import mass_properties
from stepscribe.understanding.rigid_body import principal_inertia

ANGULAR_DEFLECTION = 0.03  # rad, the largest angle one mesh chord subtends
LINEAR_DEFLECTION_REL = 1e-4  # of the part's diagonal
REL_TOL = 1e-3  # mass and each principal moment, relative (see the module text)
COM_TOL = 1e-4  # centre of mass, as a share of the part's diagonal
# One sphere in seven: a sphere has by far the most triangles, so it dominates the run time.
KINDS = (
    "box",
    "cylinder",
    "sphere",
    "box_with_holes",
    "cylinder_with_holes",
    "box_with_holes",
    "cylinder_with_holes",
)


# ------------------------------------------------------------------ method 2: signed tetrahedra
def triangles(shape: TopoDS_Shape, diagonal: float) -> np.ndarray:
    """All triangles of the tessellated shape as an (n, 3, 3) array, wound outward."""
    BRepMesh_IncrementalMesh(
        shape, diagonal * LINEAR_DEFLECTION_REL, False, ANGULAR_DEFLECTION, False
    )
    out: list[np.ndarray] = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face(ex.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            raise RuntimeError("a face has no triangulation")
        trsf = loc.Transformation()
        nodes = np.array(
            [
                (p.X(), p.Y(), p.Z())
                for p in (tri.Node(i).Transformed(trsf) for i in range(1, tri.NbNodes() + 1))
            ]
        )
        idx = np.array([tri.Triangle(k).Get() for k in range(1, tri.NbTriangles() + 1)]) - 1
        if face.Orientation() == TopAbs_REVERSED:
            idx = idx[:, [0, 2, 1]]
        out.append(nodes[idx])
        ex.Next()
    return np.concatenate(out)


def mesh_properties(tri: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Volume, centroid and unit-density inertia tensor about the centroid of a closed mesh.

    Each triangle (a, b, c) with the origin makes a tetrahedron of signed volume V = a.(b x c) / 6;
    its first moment is V * (a + b + c) / 4 and its second moment tensor
    V / 20 * (a a' + b b' + c c' + s s'), with s = a + b + c. The signs cancel inside the solid
    for any origin, so the sums are those of the closed surface.
    """
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    v = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    s = a + b + c
    volume = float(v.sum())
    first = (v[:, None] * s / 4.0).sum(axis=0)
    second = (
        np.einsum("i,ij,ik->jk", v, a, a)
        + np.einsum("i,ij,ik->jk", v, b, b)
        + np.einsum("i,ij,ik->jk", v, c, c)
        + np.einsum("i,ij,ik->jk", v, s, s)
    ) / 20.0
    com = first / volume
    second = second - volume * np.outer(com, com)  # about the centroid
    inertia = np.trace(second) * np.eye(3) - second
    return volume, com, inertia


# ------------------------------------------------------------------ generated solids
@dataclass
class Case:
    kind: str
    index: int
    density: float  # g/cm3
    shape: TopoDS_Shape
    diagonal: float


def _transform(shape: TopoDS_Shape, rng: np.random.Generator) -> TopoDS_Shape:
    """Rotate about a random axis by a random angle and offset by up to 500 mm."""
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    rot = gp_Trsf()
    rot.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), float(rng.uniform(0, 2 * np.pi)))
    move = gp_Trsf()
    move.SetTranslation(gp_Vec(*(float(x) for x in rng.uniform(-500, 500, size=3))))
    move.Multiply(rot)
    return BRepBuilderAPI_Transform(shape, move, True).Shape()


def _holes(base: TopoDS_Shape, size: np.ndarray, rng: np.random.Generator) -> TopoDS_Shape:
    """Cut one to three cylindrical holes through the box (0, 0, 0)..size along z."""
    shape = base
    for _ in range(int(rng.integers(1, 4))):
        r = float(rng.uniform(0.06, 0.2) * min(size[0], size[1]))
        x = float(rng.uniform(r * 1.5, size[0] - r * 1.5))
        y = float(rng.uniform(r * 1.5, size[1] - r * 1.5))
        hole = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(x, y, -1.0), gp_Dir(0, 0, 1)), r, float(size[2]) + 2
        ).Shape()
        shape = BRepAlgoAPI_Cut(shape, hole).Shape()
    return shape


def make_case(index: int, seed: int) -> Case:
    """Case *index* of the set made from *seed*: the same call always gives the same solid."""
    rng = np.random.default_rng([seed, index])
    kind = KINDS[index % len(KINDS)]
    size = rng.uniform(15.0, 120.0, size=3)
    if kind in ("box", "box_with_holes"):
        shape = BRepPrimAPI_MakeBox(float(size[0]), float(size[1]), float(size[2])).Shape()
        if kind == "box_with_holes":
            shape = _holes(shape, size, rng)
        diag = float(np.linalg.norm(size))
    elif kind in ("cylinder", "cylinder_with_holes"):
        r, h = float(size[0] / 2), float(size[2])
        shape = BRepPrimAPI_MakeCylinder(r, h).Shape()
        if kind == "cylinder_with_holes":
            hole_r = float(rng.uniform(0.15, 0.4) * r)
            hole = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(float(rng.uniform(-0.3, 0.3) * r), 0, -1.0), gp_Dir(0, 0, 1)),
                hole_r,
                h + 2,
            ).Shape()
            shape = BRepAlgoAPI_Cut(shape, hole).Shape()
        diag = float(np.linalg.norm([2 * r, 2 * r, h]))
    else:
        r = float(size[0] / 2)
        shape = BRepPrimAPI_MakeSphere(r).Shape()
        diag = 2 * r
    shape = _transform(shape, rng)
    return Case(kind, index, float(rng.uniform(0.5, 8.0)), shape, diag)


# ------------------------------------------------------------------ the comparison
@dataclass
class Result:
    kind: str
    index: int
    mass_rel: float
    moments_rel: float  # the largest relative difference of the three sorted principal moments
    com_rel: float  # centre-of-mass distance over the diagonal

    @property
    def worst(self) -> float:
        return max(self.mass_rel, self.moments_rel)

    @property
    def ok(self) -> bool:
        return self.worst <= REL_TOL and self.com_rel <= COM_TOL


def compare(case: Case) -> Result:
    """Our values against the tessellation's for one solid."""
    ours = mass_properties(case.shape, "", case.density, "generated", "user")
    assert ours.mass_g is not None and ours.inertia_tensor_g_mm2 is not None
    our_moments = principal_inertia(np.array(ours.inertia_tensor_g_mm2), ours.mass_g).moments_g_mm2
    our_com = np.array([ours.centroid.x, ours.centroid.y, ours.centroid.z])

    volume, com, unit_inertia = mesh_properties(triangles(case.shape, case.diagonal))
    mass = volume * case.density / 1000.0  # mm3 * g/cm3 -> g
    tensor = unit_inertia * case.density / 1000.0
    moments = np.linalg.eigvalsh((tensor + tensor.T) / 2)
    return Result(
        case.kind,
        case.index,
        abs(mass - ours.mass_g) / ours.mass_g,
        float(np.max(np.abs(moments - our_moments) / our_moments)),
        float(np.linalg.norm(com - our_com) / case.diagonal),
    )


def run(indices: range | list[int], seed: int) -> list[Result]:
    return [compare(make_case(i, seed)) for i in indices]


def summary(results: list[Result]) -> dict[str, Any]:
    return {
        "shapes": len(results),
        "largest_mass_difference": max(r.mass_rel for r in results),
        "largest_moment_difference": max(r.moments_rel for r in results),
        "largest_centre_difference_over_diagonal": max(r.com_rel for r in results),
        "outside_tolerance": [(r.kind, r.index) for r in results if not r.ok],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260101)
    args = ap.parse_args(argv)
    s = summary(run(range(args.count), args.seed))
    print(
        f"{s['shapes']} generated solids, two methods (seed {args.seed}).\n"
        f"largest relative difference: mass {s['largest_mass_difference']:.2e}, "
        f"principal moments {s['largest_moment_difference']:.2e} (tolerance {REL_TOL:.0e}); "
        f"centre of mass {s['largest_centre_difference_over_diagonal']:.2e} of the diagonal "
        f"(tolerance {COM_TOL:.0e})."
    )
    for kind, i in s["outside_tolerance"]:
        print(f"outside tolerance: {kind} #{i}")
    return 1 if s["outside_tolerance"] else 0


if __name__ == "__main__":
    sys.exit(main())
