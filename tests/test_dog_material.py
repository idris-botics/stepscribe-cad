"""F5: a material the STEP file states is shown as unverified; the overview total agrees with the per-part masses;
loads and the URDF carry a visible flag when they rest on it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from step_data_fixtures import PartSpec, write_step_data_fixture

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.describe.part_describer import material_text
from stepscribe.pack.robot import build_robot
from stepscribe.pack.urdf import build_urdf
from stepscribe.pack.writer import write_pack
from stepscribe.understanding import mass_distribution as md

CAUTION = "CAD tools often assign a default material to every part, check it"
STEEL = ("Steel", "", 7.85)


@pytest.fixture(scope="module")
def mixed(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """Three bodies: two with a material stated in the file, one with none."""
    path = write_step_data_fixture(
        tmp_path_factory.mktemp("mixed") / "mixed.step",
        [PartSpec("one", material=STEEL), PartSpec("two", material=STEEL), PartSpec("three")],
    )
    return analyze_full(path, AnalyzeOptions(no_timestamp=True))


def test_the_part_text_says_the_material_is_stated_in_the_file_and_to_check_it(mixed) -> None:  # type: ignore[no-untyped-def]
    stated = [p for p in mixed.report.parts if p.mass.material_source == "step_file"]
    assert len(stated) == 2
    for p in stated:
        assert material_text(p) == f"material Steel (stated in the STEP file; {CAUTION})"


def test_the_overview_total_is_consistent_with_the_per_part_masses(mixed, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    known = [p for p in mixed.report.parts if p.mass.mass_g is not None]
    assert len(known) == 2 and len(mixed.report.parts) == 3
    folder = write_pack(mixed, tmp_path, images=False)
    overview = (folder / "01_overview.md").read_text(encoding="utf-8")
    assert "Total mass: unknown" not in overview
    assert "2 of 3 parts have a mass" in overview and "1 have no material" in overview
    assert (
        "the materials that are known are stated in the STEP file" in overview
        and CAUTION in overview
    )
    assert "design_context.yaml" in overview


def test_a_total_from_the_files_material_alone_says_to_check_it(tmp_path: Path) -> None:
    path = write_step_data_fixture(
        tmp_path / "all.step",
        [PartSpec("one", material=STEEL), PartSpec("two", material=STEEL)],
    )
    folder = write_pack(
        analyze_full(path, AnalyzeOptions(no_timestamp=True)), tmp_path / "out", images=False
    )
    overview = (folder / "01_overview.md").read_text(encoding="utf-8")
    assert "Total mass:" in overview and f"material stated in the STEP file; {CAUTION}" in overview


def test_the_designer_can_override_with_a_material(tmp_path: Path) -> None:
    path = write_step_data_fixture(
        tmp_path / "o.step", [PartSpec("one", material=STEEL), PartSpec("two")]
    )
    report = analyze_full(path, AnalyzeOptions(no_timestamp=True, material="alu")).report
    assert {p.mass.material_source for p in report.parts} == {"user"}
    assert all(p.mass.material_assumed == "alu" for p in report.parts)


# ---- loads, robot.json and the URDF
@pytest.fixture(scope="module")
def arm_from_file(step_files):  # type: ignore[no-untyped-def]
    """The generated six-axis arm whose parts take their material from the file: the source is switched after
    the analysis (the masses are the same numbers)."""
    report = analyze_full(
        step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, material="steel")
    ).report
    for p in report.parts:
        p.mass.material_source = "step_file"
    return report


def test_robot_json_flags_masses_that_rest_on_the_files_material(arm_from_file: Any) -> None:
    robot = build_robot(arm_from_file)
    assert robot is not None
    flagged = [link for link in robot["links"] if link.get("mass_material_from_step_file")]
    assert flagged
    assert any("not verified" in w and CAUTION in w for w in robot["warnings"])
    # the numbers are still used (the flag is added, nothing is removed)
    assert all(link["mass_g"] is not None for link in flagged)


def test_the_urdf_and_the_load_text_carry_the_flag(arm_from_file: Any) -> None:
    robot = build_robot(arm_from_file)
    assert robot is not None
    header = build_urdf(robot).split("-->")[0]
    assert "use the material the STEP file states, which is not verified" in header
    text = md.mass_markdown(md.mass_distribution(arm_from_file), robot)
    assert f"not verified ({CAUTION}), used for the mass of: " in text


def test_nothing_is_flagged_when_the_designer_gave_the_material(step_files) -> None:  # type: ignore[no-untyped-def]
    report = analyze_full(
        step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, material="steel")
    ).report
    robot = build_robot(report)
    assert robot is not None
    assert not any("mass_material_from_step_file" in link for link in robot["links"])
    assert "not verified" not in " ".join(robot["warnings"])
    assert "not verified" not in md.mass_markdown(md.mass_distribution(report), robot)


def test_the_no_material_warning_is_not_said_when_some_links_have_a_mass(
    mixed, arm_from_file: Any
) -> None:  # type: ignore[no-untyped-def]
    robot = build_robot(arm_from_file)
    assert robot is not None
    assert not any(w.startswith("No material is set") for w in robot["warnings"])
