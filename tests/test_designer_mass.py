"""A mass the designer measured (``parts: <name>: mass_g``): scaling, the label, the refusals, bad values."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.geometry.designer_mass import LABEL, ratio_note, refusal
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


NOTE_TAIL = "; the part may be hollow, printed or made of a different material"


@pytest.mark.parametrize(
    "pct, expected",
    [
        (49.9, True),
        (50.0, False),
        (75.0, False),
        (100.0, False),
        (120.0, False),
        (120.1, True),
        (200.0, True),
    ],
)
def test_the_note_appears_below_50_and_above_120_percent_of_the_solid_estimate(
    pct: float, expected: bool
) -> None:
    note = ratio_note(pct, 100.0)
    assert (note is not None) is expected
    if note:
        assert note == f"the measured mass is {pct:.1f}% of the solid estimate{NOTE_TAIL}"
    assert ratio_note(10.0, None) is None  # no estimate, nothing to compare with


def test_the_note_has_no_judgement_words() -> None:
    low = (ratio_note(10.0, 100.0) or "").lower()
    for word in ("wrong", "error", "bad", "suspicious", "too ", "should", "mistake", "unrealistic"):
        assert word not in low


def test_the_note_sits_beside_the_part_in_every_output(plain, given) -> None:  # type: ignore[no-untyped-def]
    analysis, est = given  # twice the estimate: 200 %
    note = "the measured mass is 200.0% of the solid estimate" + NOTE_TAIL
    part = _part(analysis, PART)
    assert part.mass.designer_mass.ratio_note == note
    assert (
        json.loads(report_to_json(analysis.report))["parts"][analysis.report.parts.index(part)][
            "mass"
        ]["designer_mass"]["ratio_note"]
        == note
    )
    dist = md.mass_distribution(analysis.report)
    entry = next(p for p in dist["parts"] if p["id"] == part.id)
    assert entry["mass_ratio_note"] == note
    text = md.mass_markdown(dist, None)
    assert f"  - {note}" in text
    from stepscribe.describe.part_describer import mass_text

    assert note in mass_text(part)
    # a part with a given mass near its estimate, or none, carries no note
    other = next(p for p in analysis.report.parts if p.name != PART)
    assert other.mass.designer_mass is None and "ratio_note" not in json.dumps(
        report_to_json(plain.report)
    )


def test_a_given_mass_close_to_the_estimate_has_no_note(step_files, plain, tmp_path) -> None:  # type: ignore[no-untyped-def]
    est = next(p.mass.mass_g for p in plain.report.parts if p.name == PART)
    analysis = _run(
        step_files["arm_6_axis"], tmp_path, f"parts:\n  {PART}:\n    mass_g: {0.8 * est!r}\n"
    )
    dm = _part(analysis, PART).mass.designer_mass
    assert dm is not None and dm.used and dm.ratio_note is None
    assert "ratio_note" not in json.dumps(
        json.loads(report_to_json(analysis.report))["parts"][0]["mass"]
    )


# ---- review follow-up ------------------------------------------------------------------------------
def test_the_note_never_reads_as_the_threshold() -> None:
    low = ratio_note(49.96, 100.0)
    high = ratio_note(120.04, 100.0)
    assert low is not None and low.startswith("the measured mass is 49.9% ")
    assert high is not None and high.startswith("the measured mass is 120.1% ")
    assert ratio_note(50.0, 100.0) is None and ratio_note(120.0, 100.0) is None


def test_a_density_derived_from_the_mass_has_its_own_source_and_is_said_in_the_pack(  # type: ignore[no-untyped-def]
    step_files, tmp_path
) -> None:
    opts = AnalyzeOptions(no_timestamp=True)
    ctx = tmp_path / "c.yaml"
    ctx.write_text("parts:\n  plate_4xM3:\n    mass_g: 250.0\n", encoding="utf-8")
    apply_context(opts, load_context(ctx))
    report = analyze_full(step_files["plate_4xM3"], opts).report
    part = report.parts[0]
    assert part.mass.material_source == "designer_mass" and part.mass.density_g_cm3 is not None
    assert part.mass.density_g_cm3 == pytest.approx(250.0 * 1000.0 / part.mass.volume_mm3)
    text = md.mass_markdown(md.mass_distribution(report), None)
    assert "density derived from the mass given" in text
    from stepscribe.describe.part_describer import material_text

    assert material_text(part) == "density derived from the mass given by the designer"
    # a part whose density comes from a material keeps that source
    with_material = _run(
        step_files["plate_4xM3"], tmp_path, "parts:\n  plate_4xM3:\n    mass_g: 250.0\n"
    )
    assert with_material.report.parts[0].mass.material_source == "user"


def test_a_shared_name_warns_only_when_the_volumes_differ(  # type: ignore[no-untyped-def]
    step_files, tmp_path, monkeypatch
) -> None:
    from stepscribe import api

    def warnings_for(shift: float) -> list[str]:
        real = api._analyse_bodies

        def twice(*args, **kwargs):  # type: ignore[no-untyped-def]
            done = real(*args, **kwargs)
            key, geom, part = done[0]
            twin = part.model_copy(deep=True)
            twin.mass.volume_mm3 *= 1.0 + shift
            return [*done, (key, geom, twin)]

        monkeypatch.setattr(api, "_analyse_bodies", twice)
        ctx = tmp_path / f"c{shift}.yaml"
        ctx.write_text("parts:\n  plate_4xM3:\n    mass_g: 100\n", encoding="utf-8")
        opts = AnalyzeOptions(no_timestamp=True, material="steel")
        apply_context(opts, load_context(ctx))
        warnings = analyze_full(step_files["plate_4xM3"], opts).report.warnings
        monkeypatch.setattr(api, "_analyse_bodies", real)
        return [w for w in warnings if "differ" in w]

    assert warnings_for(0.0) == []  # identical copies: no warning
    assert warnings_for(0.005) == []  # within about 1%
    found = warnings_for(0.05)
    assert len(found) == 1 and "'plate_4xM3'" in found[0] and "2 parts" in found[0]


def test_rebuilding_the_mass_names_every_field_of_the_model() -> None:
    from stepscribe.geometry.designer_mass import FROM_NEW_MASS, KEPT_FROM_OLD_MASS
    from stepscribe.models.schema import MassProperties

    assert set(FROM_NEW_MASS) | set(KEPT_FROM_OLD_MASS) == set(MassProperties.model_fields), (
        "a field was added to the mass model: say whether a rebuilt mass takes it from the new "
        "computation (FROM_NEW_MASS) or keeps it from the earlier mass (KEPT_FROM_OLD_MASS)"
    )
    assert not set(FROM_NEW_MASS) & set(KEPT_FROM_OLD_MASS)


def test_a_rebuilt_mass_keeps_what_belongs_to_the_old_one_and_takes_the_rest_from_the_new() -> None:
    from stepscribe.geometry.designer_mass import FROM_NEW_MASS, KEPT_FROM_OLD_MASS, rebuild_mass
    from stepscribe.models.schema import DesignerMass, MassProperties, Vec3

    def mass(v: float, source: str) -> MassProperties:
        return MassProperties(
            volume_mm3=v,
            surface_area_mm2=v + 1,
            centroid=Vec3(x=v, y=0, z=0),
            density_g_cm3=v / 10,
            mass_g=v / 5,
            material_assumed=source,
            material_source="user",
            inertia_tensor_g_mm2=[[v, 0, 0], [0, v, 0], [0, 0, v]],
        )

    old = mass(1.0, "old")
    old.designer_mass = DesignerMass(given_g=5.0, used=False, note="kept")
    new = mass(2.0, "new")
    out = rebuild_mass(old, new)
    for name in FROM_NEW_MASS:
        assert getattr(out, name) == getattr(new, name), name
    for name in KEPT_FROM_OLD_MASS:
        assert getattr(out, name) == getattr(old, name) != getattr(new, name), name
    assert new.designer_mass is None  # the new mass is not changed in place


def test_the_schema_keeps_the_new_fields_optional(plain) -> None:  # type: ignore[no-untyped-def]
    from stepscribe.models.schema import Report, json_schema

    defs = json_schema()["$defs"]
    required = set(defs["MassProperties"].get("required", []))
    assert not required & {"designer_mass", "material_source"}
    assert {"given_g", "used", "note"} <= set(defs["DesignerMass"]["required"])
    assert "ratio_note" not in defs["DesignerMass"]["required"]
    assert "designer_mass" in defs["MassProperties"]["properties"]
    assert "designer_mass" in defs["MassProperties"]["properties"]["material_source"]["enum"]
    # a report without any of the new fields validates, and one with them validates and round-trips
    data = json.loads(report_to_json(plain.report))
    assert "designer_mass" not in json.dumps(data)
    Report.model_validate(data)
    data["parts"][0]["mass"]["designer_mass"] = {
        "given_g": 12.5,
        "used": True,
        "estimated_g": 10.0,
        "note": LABEL,
        "ratio_note": "the measured mass is 125.0% of the solid estimate; the part may be hollow, printed or made of a different material",
    }
    data["parts"][0]["mass"]["material_source"] = "designer_mass"
    again = Report.model_validate(data)
    assert again.parts[0].mass.designer_mass.given_g == 12.5  # type: ignore[union-attr]
    assert json.loads(report_to_json(again))["parts"][0]["mass"]["designer_mass"]["used"] is True
