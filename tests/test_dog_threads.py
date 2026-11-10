"""F4: modelled threads and serrations. A thread drawn as alternating bores is named ("modelled thread, likely
M2.5") with its evidence and is not an edge; equal repeats that fit no gear module are a serration, not a gear."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from build123d import export_step
from dog_fixtures import named_parts
from mechanism_fixtures import spur_gear

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.describe.part_describer import hole_row
from stepscribe.features import holes as holes_module
from stepscribe.features.shape_class import matches_standard_module
from stepscribe.geometry.thickness import sample_wall_thickness
from stepscribe.models.schema import Report


@pytest.fixture(scope="module")
def analysis(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    path = named_parts(tmp_path_factory.mktemp("threads"))
    return analyze_full(path, AnalyzeOptions(no_timestamp=True, material="steel"))


def axe(analysis: Any) -> tuple[Any, Any]:
    ap = next(a for a in analysis.parts if a.part.name.startswith("axe"))
    return ap.part, ap.geom


def test_the_alternating_bores_are_one_modelled_thread_with_its_evidence(analysis: Any) -> None:
    part, _geom = axe(analysis)
    threaded = [h for h in part.holes if h.thread is not None]
    assert threaded, "the thread must be found on a hole"
    t = threaded[0].thread
    assert t.nominal == "M2.5" and t.minor_mm == pytest.approx(2.07, abs=0.01)
    assert t.major_mm == pytest.approx(2.52, abs=0.01) and t.n_faces >= 6
    assert "alternate between dia 2.07 and 2.52 mm" in t.evidence and t.face_ids


def test_the_hole_table_calls_it_a_modelled_thread(analysis: Any) -> None:
    part, _geom = axe(analysis)
    hole = next(h for h in part.holes if h.thread is not None)
    assert hole_row(hole)["threaded"] == "modelled thread (likely M2.5)"


def test_the_edge_distance_is_the_real_wall_and_thread_faces_are_left_out_of_it(
    analysis: Any,
) -> None:
    part, geom = axe(analysis)
    hole = next(h for h in part.holes if h.thread is not None)
    wall = 2.45 - 1.26  # the outer radius less the thread's major radius
    assert hole.edge_distance_mm == pytest.approx(wall, abs=0.15)
    # the faces a thread names are not edges: name the outer wall as thread faces and the distance grows
    outer = {
        f.id
        for f in geom.table.faces
        if f.kind == "cylinder"
        and f.centroid is not None
        and f.area > 0
        and abs(float(f.area) - 0.0) >= 0
    }
    assert outer
    before = hole.edge_distance_mm
    original = list(hole.thread.face_ids)
    hole.thread.face_ids = sorted(set(original) | outer)
    try:
        holes_module.compute_edge_distances(geom, part.holes)
        after = hole.edge_distance_mm
    finally:
        hole.thread.face_ids = original
        holes_module.compute_edge_distances(geom, part.holes)
    assert after is None or after > before + 0.05
    assert hole.edge_distance_mm == pytest.approx(before)


def test_no_thin_wall_or_edge_finding_comes_from_the_thread_flank(analysis: Any) -> None:
    part, _geom = axe(analysis)
    spots = [
        w
        for w in analysis.report.understanding.weak_spots
        if part.id in w.refs and w.category in ("edge_distance", "thin_wall")
    ]
    for w in spots:  # any finding left is measured on the real wall, never a 0.2 mm flank
        assert w.value is None or w.value > 0.5, w.message


def test_the_serration_is_not_a_gear(analysis: Any) -> None:
    part, _geom = axe(analysis)
    assert part.shape_class.label == "serrated"
    assert "no standard gear module fits" in part.shape_class.evidence
    assert "a serration or spline, not a gear" in part.shape_class.evidence
    labels = {r.label for r in part.understanding.roles}
    assert "gear" not in labels and "pulley" not in labels


def test_a_real_gear_is_still_a_gear(tmp_path: Path) -> None:
    path = tmp_path / "gear.step"
    export_step(spur_gear(24, module=1.5), str(path))
    report = analyze_full(path, AnalyzeOptions(no_timestamp=True)).report
    assert report.parts[0].shape_class.label == "gear_like"


def test_the_module_rule_names_the_standard_module() -> None:
    assert matches_standard_module(24, 1.5 * 26 / 2) == 1.5  # OD = m (N + 2)
    assert matches_standard_module(20, 4.88 / 2) is None  # the dog's axe: m = 0.22


def test_thread_and_tooth_faces_do_not_count_as_walls(
    analysis: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stepscribe.geometry import thickness

    part, geom = axe(analysis)
    left_out = {fid for h in part.holes if h.thread is not None for fid in h.thread.face_ids}
    assert left_out
    started: list[str] = []
    real = thickness._face_samples

    def spy(g: Any, i: int, count: int, rng: Any) -> Any:
        started.append(g.table.faces[i].id)
        return real(g, i, count, rng)

    monkeypatch.setattr(thickness, "_face_samples", spy)
    assert sample_wall_thickness(geom, exclude=left_out) is not None
    assert started and not set(started) & left_out
    started.clear()
    sample_wall_thickness(geom)
    assert set(started) & left_out  # without the exclusion the thread faces are sampled


def test_the_new_field_is_optional_and_round_trips(analysis: Any) -> None:
    part, _geom = axe(analysis)
    hole = next(h for h in part.holes if h.thread is not None)
    data = hole.model_dump(mode="json")
    assert data["thread"]["nominal"] == "M2.5"
    plain = hole.model_copy(update={"thread": None})
    assert "thread" not in plain.model_dump(mode="json")
    Report.model_validate_json(analysis.report.model_dump_json())
