"""A mass the designer measured (``parts: <name>: mass_g``): scaling, the label, the refusals, bad values."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.geometry.designer_mass import LABEL, refusal
from stepscribe.io.report_writer import report_to_json
from stepscribe.pack.design_context import apply_context, load_context
from stepscribe.pack.robot import build_robot
from stepscribe.pack.urdf import build_urdf
from stepscribe.understanding import mass_distribution as md

LABEL_TEXT = "mass from designer; inertia assumes the same distribution as the estimate"
PART = "ARM_rev0_LINK2"


def _run(path: Path, tmp_path: Path, yaml_text: str | None, material: str = "steel"):  # type: ignore[no-untyped-def]
    opts = AnalyzeOptions(no_timestamp=True, material=material)
    if yaml_text is not None:
        ctx = tmp_path / "design_context.yaml"
        ctx.write_text(yaml_text, encoding="utf-8")
        apply_context(opts, load_context(ctx))
    return analyze_full(path, opts)


@pytest.fixture(scope="module")
def plain(step_files, tmp_path_factory):  # type: ignore[no-untyped-def]
    return _run(step_files["arm_6_axis"], tmp_path_factory.mktemp("plain"), None)


@pytest.fixture(scope="module")
def given(step_files, plain, tmp_path_factory):  # type: ignore[no-untyped-def]
    est = next(p.mass.mass_g for p in plain.report.parts if p.name == PART)
    text = f"parts:\n  {PART}:\n    mass_g: {2 * est!r}\n"
    return _run(step_files["arm_6_axis"], tmp_path_factory.mktemp("given"), text), est


def _part(analysis, name: str):  # type: ignore[no-untyped-def]
    return next(p for p in analysis.report.parts if p.name == name)


def test_the_label_is_the_one_the_designer_sees() -> None:
    assert LABEL == LABEL_TEXT


def test_the_mass_is_replaced_and_the_inertia_scaled_by_measured_over_estimated(
    plain, given
) -> None:  # type: ignore[no-untyped-def]
    analysis, est = given
    before, after = _part(plain, PART).mass, _part(analysis, PART).mass
    assert after.mass_g == pytest.approx(2 * est, rel=1e-12)
    assert np.array(after.inertia_tensor_g_mm2) == pytest.approx(
        2 * np.array(before.inertia_tensor_g_mm2), rel=1e-12
    )
    assert after.centroid == before.centroid and after.volume_mm3 == before.volume_mm3
    dm = after.designer_mass
    assert dm is not None and dm.used and dm.given_g == pytest.approx(2 * est)
    assert dm.estimated_g == pytest.approx(est) and dm.note == LABEL_TEXT


def test_other_parts_and_the_assembly_total_follow(plain, given) -> None:  # type: ignore[no-untyped-def]
    analysis, est = given
    for p in plain.report.parts:
        if p.name != PART:
            assert _part(analysis, p.name).mass == p.mass
    assert analysis.report.assembly.total_mass_g == pytest.approx(
        plain.report.assembly.total_mass_g + est, rel=1e-9
    )


def test_the_pack_text_and_robot_json_and_urdf_carry_the_label(given) -> None:  # type: ignore[no-untyped-def]
    analysis, _est = given
    report = analysis.report
    pid = _part(analysis, PART).id
    dist = md.mass_distribution(report)
    entry = next(p for p in dist["parts"] if p["id"] == pid)
    assert entry["mass_source"] == "designer" and entry["mass_label"] == LABEL_TEXT
    robot = build_robot(report)
    assert robot is not None
    labelled = [link for link in robot["links"] if link.get("mass_label")]
    assert len(labelled) == 1 and labelled[0]["mass_label"] == LABEL_TEXT
    assert labelled[0]["mass_from_designer_parts"] == [pid]
    assert all("mass_label" not in link for link in robot["links"] if link not in labelled)
    text = md.mass_markdown(dist, robot)
    assert LABEL_TEXT in text and pid in text
    assert LABEL_TEXT in build_urdf(robot)
    assert any(LABEL_TEXT.capitalize() in w for w in robot["warnings"])


def test_a_part_that_is_refused_keeps_the_refusal_and_says_the_mass_was_not_used(
    step_files, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    analysis = _run(
        step_files["freeform_housing"], tmp_path, "parts:\n  freeform_housing:\n    mass_g: 500\n"
    )
    part = analysis.report.parts[0]
    estimate = _run(step_files["freeform_housing"], tmp_path, None).report.parts[0]
    assert part.mass.mass_g == estimate.mass.mass_g != 500
    dm = part.mass.designer_mass
    assert dm is not None and not dm.used and dm.given_g == 500
    assert "was not used" in dm.note and "complex or free-form" in dm.note
    dist = md.mass_distribution(analysis.report)
    assert "was not used" in dist["parts"][0]["designer_mass_not_used"]
    assert "was not used" in md.mass_markdown(dist, None)
    assert "mass_label" not in dist["parts"][0]


def test_an_open_shell_is_refused_too(plain) -> None:  # type: ignore[no-untyped-def]
    part = plain.report.parts[0].model_copy(deep=True)
    part.is_valid_solid = False
    assert "not a closed valid solid" in (refusal(part) or "")
    part = plain.report.parts[0].model_copy(deep=True)
    part.topology.solids = 0
    assert refusal(part) is not None


def test_a_closed_solid_without_a_material_gets_its_inertia_from_the_given_mass(
    step_files, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    text = "parts:\n  plate_4xM3:\n    mass_g: 250.0\n"
    opts = AnalyzeOptions(no_timestamp=True)
    ctx = tmp_path / "c.yaml"
    ctx.write_text(text, encoding="utf-8")
    apply_context(opts, load_context(ctx))
    part = analyze_full(step_files["plate_4xM3"], opts).report.parts[0]
    steel = analyze_full(
        step_files["plate_4xM3"], AnalyzeOptions(no_timestamp=True, material="steel")
    ).report.parts[0]
    assert part.mass.mass_g == 250.0 and part.mass.designer_mass.used
    assert part.mass.designer_mass.estimated_g is None
    assert np.array(part.mass.inertia_tensor_g_mm2) == pytest.approx(
        np.array(steel.mass.inertia_tensor_g_mm2) * 250.0 / steel.mass.mass_g, rel=1e-9
    )


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "'12'", "true", ".nan", ".inf", "[1, 2]"])
def test_a_bad_value_is_rejected_with_a_message_that_names_the_part(
    bad: str, tmp_path: Path
) -> None:
    ctx = tmp_path / "design_context.yaml"
    ctx.write_text(f"parts:\n  Bracket:\n    mass_g: {bad}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"parts: Bracket: mass_g must be a number"):
        load_context(ctx)


def test_a_mass_for_a_name_that_is_not_a_part_is_warned_about(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    analysis = _run(step_files["plate_4xM3"], tmp_path, "parts:\n  Nope:\n    mass_g: 5\n")
    assert any("'Nope'" in w and "not a part name" in w for w in analysis.report.warnings)


def test_without_mass_g_the_report_is_the_same_as_before(step_files, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = step_files["arm_6_axis"]
    base = report_to_json(
        analyze_full(path, AnalyzeOptions(no_timestamp=True, material="steel")).report
    )
    with_ctx = report_to_json(
        _run(path, tmp_path, "parts:\n  ARM_rev0_LINK1:\n    material: steel\n").report
    )
    assert with_ctx == base
    assert "designer_mass" not in base
    robot = build_robot(
        analyze_full(path, AnalyzeOptions(no_timestamp=True, material="steel")).report
    )
    assert "mass_label" not in json.dumps(robot) and LABEL_TEXT not in build_urdf(robot)
