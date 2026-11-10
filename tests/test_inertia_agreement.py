"""Agreement between two methods on generated shapes (not accuracy): OpenCASCADE's exact integration, which
stepscribe reports, against a signed-tetrahedra integral of a fine tessellation (numpy only).
The same code runs as ``python scripts/check_inertia.py``; see docs/mass_distribution.md for the tolerance."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_inertia.py"
SEED = 20260101
FULL = 300


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_inertia", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_inertia"] = mod  # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


ci = _load()


def test_the_tetrahedra_integral_is_exact_on_a_box() -> None:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    volume, com, inertia = ci.mesh_properties(ci.triangles(box, math.sqrt(1400)))
    assert volume == pytest.approx(6000.0, rel=1e-12)
    assert com == pytest.approx([5, 10, 15], rel=1e-12)
    # unit density: I = m/12 (b^2 + c^2) about each axis through the centre
    assert np.diag(inertia) == pytest.approx(
        [6000 / 12 * (400 + 900), 6000 / 12 * (100 + 900), 6000 / 12 * (100 + 400)], rel=1e-12
    )


def test_the_tetrahedra_integral_of_a_sphere_is_inside_the_stated_bound() -> None:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere

    volume, _com, inertia = ci.mesh_properties(
        ci.triangles(BRepPrimAPI_MakeSphere(25.0).Shape(), 50.0)
    )
    exact_v = 4 / 3 * math.pi * 25.0**3
    assert abs(volume - exact_v) / exact_v <= ci.REL_TOL
    exact_i = 2 / 5 * exact_v * 25.0**2
    assert np.allclose(np.diag(inertia), exact_i, rtol=ci.REL_TOL)


def test_a_wrong_value_would_be_outside_the_tolerance() -> None:
    """The tolerance is not vacuous: one per cent in the mass is far outside it."""
    case = ci.make_case(0, SEED)
    ok = ci.compare(case)
    assert ok.ok and ok.worst < ci.REL_TOL / 3
    assert 0.01 > 3 * ci.REL_TOL


def test_cases_are_deterministic_and_cover_every_kind() -> None:
    a = [ci.make_case(i, SEED) for i in range(len(ci.KINDS))]
    b = [ci.make_case(i, SEED) for i in range(len(ci.KINDS))]
    assert [(c.kind, c.density, c.diagonal) for c in a] == [
        (c.kind, c.density, c.diagonal) for c in b
    ]
    assert set(c.kind for c in a) == set(ci.KINDS)
    assert {"box", "cylinder", "sphere", "box_with_holes", "cylinder_with_holes"} <= set(ci.KINDS)


def _assert_agree(indices: range) -> None:
    results = ci.run(indices, SEED)
    bad = ci.summary(results)["outside_tolerance"]
    assert not bad, f"outside tolerance: {bad}"


def test_fast_subset_agrees() -> None:
    """One of each kind, rotated and offset, in the normal run."""
    _assert_agree(range(len(ci.KINDS)))


def test_full_set_of_generated_solids_agrees() -> None:
    """The full set (listed in tests/slow_tests.txt, so marked slow; CI runs it)."""
    _assert_agree(range(FULL))
