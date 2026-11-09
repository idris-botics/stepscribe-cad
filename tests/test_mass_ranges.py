"""Ranges where the density is an assumption: a density guessed from a part name, or a material known only
at family level. A designer density, a measured mass, a grade or a density from the STEP file has none."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pytest
from build123d import Box, export_step

from stepscribe import config
from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.features.hole_standards import load_table
from stepscribe.geometry import density_range as dr
from stepscribe.io.report_writer import report_to_dict
from stepscribe.pack.design_context import apply_context, load_context
from stepscribe.pack.robot import build_robot
from stepscribe.pack.urdf import build_urdf
from stepscribe.understanding import mass_distribution as md
from stepscribe.understanding import mass_range as mr
from stepscribe.understanding.rigid_body import Body, JointSpec, combine, holding_loads

HOLLOW = "If a part is hollow or cast, its real mass is lower than the estimate."


def _named_step(tmp_path: Path, name: str) -> Path:
    box = Box(40, 30, 10)
    box.label = name
    path = tmp_path / f"{name}.step"
    export_step(box, str(path))
    return path


def _arm(step_files, **kw):  # type: ignore[no-untyped-def]
    return analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, **kw))


@pytest.fixture(scope="module")
def steel(step_files):  # type: ignore[no-untyped-def]
    return _arm(step_files, material="steel")


def test_every_family_range_contains_the_point_value_and_has_a_source() -> None:
    table = load_table("material_density_ranges.yaml")["entries"]
    for key, row in table.items():
        assert row["min_g_cm3"] <= config.MATERIAL_KEYWORDS[key] <= row["max_g_cm3"], key
        assert row["source"].startswith("general reference class")
    assert "pa12" not in table  # one specific polymer: no family spread


# ---- a density guessed from the name -------------------------------------------------------------
def test_a_density_guessed_from_the_name_shows_a_range_and_the_reason(tmp_path: Path) -> None:
    report = analyze_full(
        _named_step(tmp_path, "alu_bracket"), AnalyzeOptions(no_timestamp=True)
    ).report
    part = report.parts[0]
    assert part.mass.material_source == "name_guess"
    nominal = part.mass.volume_mm3 * 2.70 / 1000
    assert part.mass.mass_g == pytest.approx(nominal)  # the point value is the nominal one
    r = part.mass.density_range
    assert r is not None and (r.min_g_cm3, r.max_g_cm3) == (2.65, 2.85)
    assert r.reason == "density guessed from the name; range for the family"
    assert report_to_dict(report)["parts"][0]["mass"]["density_range"]["reason"] == r.reason
    dist = md.mass_distribution(report)
    rng = dist["parts"][0]["range"]
    assert rng["mass_g"] == pytest.approx([nominal * 2.65 / 2.70, nominal * 2.85 / 2.70])
    assert rng["radii_of_gyration_mm"][0][0] == rng["radii_of_gyration_mm"][0][1]
    text = md.mass_markdown(dist, None)
    assert "low to high (density guessed from the name; range for the family): mass" in text
    assert HOLLOW in text
    assert "alu_bracket" not in " ".join(ln for ln in text.splitlines() if "low to high" in ln)


def test_a_name_with_no_material_word_has_no_range(tmp_path: Path) -> None:
    report = analyze_full(
        _named_step(tmp_path, "bracket"), AnalyzeOptions(no_timestamp=True)
    ).report
    assert report.parts[0].mass.mass_g is None and report.parts[0].mass.density_range is None


# ---- a material known only at family level -------------------------------------------------------
def test_a_family_level_material_shows_a_range(steel) -> None:  # type: ignore[no-untyped-def]
    family = "material known only at family level; range for the family"
    for p in steel.report.parts:
        assert p.mass.density_range is not None and p.mass.density_range.reason == family
    data = build_robot(steel.report)
    assert data is not None
    for link in data["links"]:
        assert link["mass_range"]["min"] < link["mass_g"] < link["mass_range"]["max"]
        assert link["principal_inertia"]["range"]["moments_g_mm2"]
        assert link["mass_range"]["reason"]
    assert "Ranges exist" in build_urdf(data)


@pytest.mark.parametrize(
    "kw",
    [{"material": "aluminium 6061"}, {"material": "steel", "density": 7.9}, {"density": 7.9}],
)
def test_a_grade_or_a_density_the_designer_states_has_no_range(step_files, kw) -> None:  # type: ignore[no-untyped-def]
    analysis = _arm(step_files, **kw)
    assert all(p.mass.density_range is None for p in analysis.report.parts)
    data = build_robot(analysis.report)
    assert data is not None and not any("mass_range" in link for link in data["links"])
    assert not any("value_range" in j for j in data["static_holding_loads"]["joints"])
    assert "Ranges exist" not in build_urdf(data)
    assert "density_range" not in json.dumps(report_to_dict(analysis.report))


def test_a_measured_mass_has_no_range(step_files, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    ctx = tmp_path / "c.yaml"
    ctx.write_text("parts:\n  ARM_rev0_LINK2:\n    mass_g: 3000\n", encoding="utf-8")
    opts = AnalyzeOptions(no_timestamp=True, material="steel")
    apply_context(opts, load_context(ctx))
    report = analyze_full(step_files["arm_6_axis"], opts).report
    by_name = {p.name: p for p in report.parts}
    assert by_name["ARM_rev0_LINK2"].mass.density_range is None
    assert by_name["ARM_rev0_LINK1"].mass.density_range is not None


# ---- nominal values are unchanged ----------------------------------------------------------------
def test_ranges_never_change_the_nominal_values(steel) -> None:  # type: ignore[no-untyped-def]
    with_ranges = build_robot(steel.report)
    stripped = steel.report.model_copy(deep=True)
    for p in stripped.parts:
        p.mass.density_range = None
    without = build_robot(stripped)
    assert with_ranges is not None and without is not None
    for a, b in zip(with_ranges["links"], without["links"], strict=True):
        assert a["mass_g"] == b["mass_g"] and a["com_mm"] == b["com_mm"]
        assert np.array_equal(a["inertia_g_mm2"], b["inertia_g_mm2"])
        assert a["principal_inertia"]["moments_g_mm2"] == b["principal_inertia"]["moments_g_mm2"]
    for a, b in zip(
        with_ranges["static_holding_loads"]["joints"],
        without["static_holding_loads"]["joints"],
        strict=True,
    ):
        assert a["value"] == b["value"]
    assert "mass_range" in with_ranges["links"][0] and "mass_range" not in without["links"][0]


# ---- interval arithmetic of the static holding torque --------------------------------------------
def test_each_term_takes_its_own_min_and_max_with_a_counterweight() -> None:
    # two-link arm: link 1 (2 to 3 kg) adds +1.0 N*m per kg, a counterweight (1 to 2 kg) adds -4.0 per kg
    lo, hi = mr.interval_sum([(2.0, 3.0, 1.0), (1.0, 2.0, -4.0)])
    assert (lo, hi) == (
        -6.0,
        -1.0,
    )  # link 1 low with the counterweight high; link 1 high with it low
    all_low = 2.0 * 1.0 + 1.0 * -4.0
    all_high = 3.0 * 1.0 + 2.0 * -4.0
    assert (all_low, all_high) == (-2.0, -5.0)  # "all low" and "all high" are not the bounds
    assert lo < min(all_low, all_high) and hi > max(all_low, all_high)


def test_the_joint_ranges_enclose_every_corner_and_the_nominal(steel) -> None:  # type: ignore[no-untyped-def]
    data = build_robot(steel.report)
    assert data is not None
    report = steel.report
    assert report.assembly.up_axis == "+Z"
    up = np.array([0.0, 0.0, 1.0])
    specs = [
        JointSpec(
            j["id"],
            j["type"],
            j["parent"],
            j["child"],
            np.array(j["origin_mm"]),
            np.array(j["axis"]),
        )
        for j in data["joints"]
    ]
    parts = {p.id: p for p in report.parts}
    by_id = {i.id: i for i in report.assembly.instances}
    scales = {p.id: mr.factors(p) for p in report.parts}
    ids = sorted(scales)

    def value_at(bits: tuple[int, ...]) -> dict[str, float | None]:
        pick = dict(zip(ids, bits, strict=True))
        bodies = {}
        for g in report.understanding.kinematics.links:
            rows = []
            for iid in g.instance_ids:
                b = md._placed(parts[by_id[iid].part_id], by_id[iid])
                assert isinstance(b, Body)
                f = scales[by_id[iid].part_id][pick[by_id[iid].part_id]]
                rows.append(Body(b.mass_g * f, b.com_mm, b.inertia_g_mm2 * f))
            bodies[g.id] = combine(rows)
        return {h.joint: h.value for h in holding_loads(specs, bodies, up)}

    rows = {r["joint"]: r for r in data["static_holding_loads"]["joints"]}
    for jid, row in rows.items():
        assert row["value_range"]["min"] <= row["value"] <= row["value_range"]["max"], jid
    n = len(ids)
    probes = [(0,) * n, (1,) * n, *(tuple(int(i == k) for i in range(n)) for k in range(n))]
    probes += list(
        itertools.islice(itertools.product((0, 1), repeat=n), 0, 2**n, max(1, 2**n // 64))
    )
    for bits in probes:
        for jid, v in value_at(bits).items():
            rng = rows[jid]["value_range"]
            assert v is not None
            assert rng["min"] - 1e-5 <= v <= rng["max"] + 1e-5, (jid, bits)
    # the ends are reached: each term is linear in its part's mass, so its slope (from the all-low corner)
    # says which end of that part's range gives the max and which the min
    base = (0,) * n
    low = value_at(base)
    for jid, row in rows.items():
        slope = [
            (value_at(tuple(int(i == k) for i in range(n)))[jid] or 0.0) - (low[jid] or 0.0)
            for k in range(n)
        ]
        top = value_at(tuple(int(sl > 0) for sl in slope))[jid]
        bottom = value_at(tuple(int(sl < 0) for sl in slope))[jid]
        assert top == pytest.approx(row["value_range"]["max"], abs=1e-5), jid
        assert bottom == pytest.approx(row["value_range"]["min"], abs=1e-5), jid


def test_a_joint_that_is_not_computed_stays_so(step_files) -> None:  # type: ignore[no-untyped-def]
    bare = _arm(step_files)  # no material: nothing is computed
    data = build_robot(bare.report)
    assert data is not None
    for row in data["static_holding_loads"]["joints"]:
        assert row["value"] is None and "value_range" not in row


# ---- the fixed sentence and the new text ---------------------------------------------------------
def test_the_hollow_or_cast_sentence_is_one_fixed_assumption(steel) -> None:  # type: ignore[no-untyped-def]
    assert md.ASSUMPTIONS.count(HOLLOW) == 1
    data = build_robot(steel.report)
    assert data is not None and HOLLOW in data["static_holding_loads"]["assumptions"]
    assert dr.HOLLOW_SENTENCE == HOLLOW


def test_the_new_text_names_no_part(steel) -> None:  # type: ignore[no-untyped-def]
    report = steel.report
    dist = md.mass_distribution(report)
    data = build_robot(report)
    text = md.mass_markdown(dist, data)
    new_lines = [ln for ln in text.splitlines() if "low to high" in ln]
    assert new_lines
    names = {p.name for p in report.parts}
    for line in new_lines:
        assert not any(n in line for n in names), line
    for j in data["static_holding_loads"]["joints"]:
        assert not any(n in j["value_range"]["reason"] for n in names)
    assert not any(n in dr.NAME_REASON + dr.FAMILY_REASON for n in names)


# ---- notes by family, the approximate label, the table comments, the grade rule ------------------
PRINTED = "solid value; a printed part with infill is lighter"
CF = "the range covers both a carbon laminate and carbon-filled filament"


@pytest.mark.parametrize(
    "name, note",
    [
        ("pla_cover", PRINTED),
        ("petg_clip", PRINTED),
        ("abs_lid", PRINTED),
        ("nylon_gear", PRINTED),
        ("cf_plate", CF),
    ],
)
def test_printed_plastics_and_cf_carry_their_note_in_the_range_text_and_the_pack(
    tmp_path: Path, name: str, note: str
) -> None:
    report = analyze_full(_named_step(tmp_path, name), AnalyzeOptions(no_timestamp=True)).report
    r = report.parts[0].mass.density_range
    assert (
        r is not None and r.reason == f"density guessed from the name; range for the family; {note}"
    )
    text = md.mass_markdown(md.mass_distribution(report), None)
    assert f"low to high ({r.reason}): mass" in text and note in text


def test_metals_have_no_extra_note_and_family_level_plastics_do(step_files) -> None:  # type: ignore[no-untyped-def]
    steel_reason = _arm(step_files, material="steel").report.parts[0].mass.density_range.reason  # type: ignore[union-attr]
    assert steel_reason == "material known only at family level; range for the family"
    pla = _arm(step_files, material="pla").report.parts[0].mass.density_range
    assert pla is not None and pla.reason.endswith(PRINTED)


def test_the_corner_search_fallback_is_labelled_approximate(steel, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    exact = build_robot(steel.report)
    assert exact is not None
    assert all("label" not in link["mass_range"] for link in exact["links"])
    assert "approximate" not in md.mass_markdown(md.mass_distribution(steel.report), exact)
    monkeypatch.setattr(mr, "MAX_CORNER_PARTS", 3)  # the arm has 7 parts with an uncertain density
    approx = build_robot(steel.report)
    assert approx is not None
    multi = [
        link
        for link in approx["links"]
        if len(link["principal_inertia"].get("range", {}).get("parts", [])) > 3
    ]
    assert multi == [] or all(link["mass_range"]["label"] == "approximate range" for link in multi)
    dist = md.mass_distribution(steel.report)
    assert dist["assembly"]["range"]["label"] == "approximate range"
    assert "approximate range (" in md.mass_markdown(dist, approx)
    assert not any(
        "label" in j.get("value_range", {}) for j in approx["static_holding_loads"]["joints"]
    )


def test_every_range_has_its_reference_class_as_a_comment() -> None:
    lines = (
        (Path(config.__file__).parent / "knowledge" / "material_density_ranges.yaml")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    table = load_table("material_density_ranges.yaml")["entries"]
    for key, row in table.items():
        k = next(i for i, ln in enumerate(lines) if ln.startswith(f"  {key}:"))
        assert lines[k - 1].strip() == "# " + row["source"].split("(")[0].strip() or lines[
            k - 1
        ].strip().startswith("# general reference class"), key


def test_the_docs_say_any_digit_is_a_grade_and_the_fallback_is_approximate() -> None:
    text = (Path(__file__).parent.parent / "docs" / "mass_distribution.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(text.split())
    assert "Any digit in a material text counts as a grade" in flat
    assert (
        "approximate range" in flat
        and "exact extremes of the moments can then lie slightly outside it" in flat
    )
    assert (
        dr.has_grade("aluminium 6061") and dr.has_grade("alu6061") and not dr.has_grade("aluminium")
    )
