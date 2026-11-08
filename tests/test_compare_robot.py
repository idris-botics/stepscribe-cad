"""stepscribe compare-robot: ratios of our mass and inertia estimates to a URDF's <inertial> values.
The URDFs are generated here from the generated six-axis arm; no outside robot file is used."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.cli import app
from stepscribe.io.report_writer import report_to_json
from stepscribe.pack.robot import build_robot, robot_json
from stepscribe.robot_check import compare as cmp
from stepscribe.robot_check.model import MAX_BYTES, MAX_LINKS

runner = CliRunner()
NOTE = (
    "The URDF's values may come from different assumptions (material, hollow parts, a different tool). "
    "The ratios are a comparison, not a verdict."
)


@pytest.fixture(scope="module")
def arm(step_files):  # type: ignore[no-untyped-def]
    return analyze_full(
        step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, material="steel")
    ).report


@pytest.fixture(scope="module")
def robot(arm) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    data = build_robot(arm)
    assert data is not None
    return data


def make_urdf(
    robot: dict[str, Any],
    mass: float = 1.0,
    inertia: float = 1.0,
    names: list[str] | None = None,
    drop_last: bool = False,
    no_inertial: int | None = None,
    com_shift_m: float = 0.0,
    turn_z90: bool = False,
) -> str:
    """A serial URDF with the robot's own link values, scaled; link frames on the joint origins."""
    chain = [robot["base_link"]] + [j["child"] for j in robot["joints"]]
    by_id = {link["id"]: link for link in robot["links"]}
    frames = [np.zeros(3)] + [np.array(j["origin_mm"]) for j in robot["joints"]]
    n = len(chain) - (1 if drop_last else 0)
    names = names or [f"link_{k}" for k in range(len(chain))]
    out = ['<?xml version="1.0"?>', '<robot name="generated">']
    for k in range(n):
        link = by_id[chain[k]]
        out.append(f'  <link name="{names[k]}">')
        if no_inertial != k:
            com = (np.array(link["com_mm"]) - frames[k]) / 1000.0 + np.array([com_shift_m, 0, 0])
            t = np.array(link["inertia_g_mm2"]) * 1e-9 * inertia
            if turn_z90:  # the same body in a frame turned 90 degrees about z
                r = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]])
                t = r.T @ t @ r
            out += [
                "    <inertial>",
                f'      <origin xyz="{float(com[0])!r} {float(com[1])!r} {float(com[2])!r}" rpy="0 0 0"/>',
                f'      <mass value="{link["mass_g"] / 1000.0 * mass!r}"/>',
                f'      <inertia ixx="{float(t[0, 0])!r}" ixy="{float(t[0, 1])!r}" ixz="{float(t[0, 2])!r}" '
                f'iyy="{float(t[1, 1])!r}" iyz="{float(t[1, 2])!r}" izz="{float(t[2, 2])!r}"/>',
                "    </inertial>",
            ]
        out.append("  </link>")
    for k, j in enumerate(robot["joints"][: n - 1]):
        rel = (np.array(j["origin_mm"]) - frames[k]) / 1000.0
        out += [
            f'  <joint name="j{k}" type="revolute">',
            f'    <parent link="{names[k]}"/>',
            f'    <child link="{names[k + 1]}"/>',
            f'    <origin xyz="{float(rel[0])!r} {float(rel[1])!r} {float(rel[2])!r}" rpy="0 0 0"/>',
            '    <axis xyz="0 0 1"/>',
            '    <limit lower="-1" upper="1" effort="1" velocity="1"/>',
            "  </joint>",
        ]
    out.append("</robot>")
    return "\n".join(out) + "\n"


def run(tmp_path: Path, robot: dict[str, Any], urdf_text: str, *args: str):  # type: ignore[no-untyped-def]
    rj = tmp_path / "robot.json"
    rj.write_text(json.dumps(robot), encoding="utf-8")
    uf = tmp_path / "theirs.urdf"
    uf.write_text(urdf_text, encoding="utf-8")
    return runner.invoke(app, ["compare-robot", str(rj), str(uf), *args])


def links_of(result) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["links"]  # type: ignore[no-any-return]


# ---- the ratios ----------------------------------------------------------------------------------
def test_identical_values_give_ratios_of_one(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    rows = links_of(run(tmp_path, robot, make_urdf(robot), "--json"))
    assert len(rows) == len(robot["links"]) == 7
    for r in rows:
        assert r["mass_ratio"] == pytest.approx(1.0, abs=1e-5)
        assert r["moment_ratios"] == pytest.approx([1.0, 1.0, 1.0], abs=1e-5)


def test_half_the_mass_and_inertia_in_the_urdf_doubles_every_ratio(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    rows = links_of(run(tmp_path, robot, make_urdf(robot, mass=0.5, inertia=0.5), "--json"))
    for r in rows:
        assert r["mass_ratio"] == pytest.approx(2.0, abs=1e-5)
        assert r["moment_ratios"] == pytest.approx([2.0, 2.0, 2.0], abs=1e-5)


def test_a_different_mass_alone_leaves_the_moment_ratios_alone(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    rows = links_of(run(tmp_path, robot, make_urdf(robot, mass=0.5), "--json"))
    for r in rows:
        assert r["mass_ratio"] == pytest.approx(2.0, abs=1e-5)
        assert r["moment_ratios"] == pytest.approx([1.0, 1.0, 1.0], abs=1e-5)


def test_a_rotated_inertia_frame_needs_no_alignment(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    swapped = make_urdf(robot, turn_z90=True)
    rows = links_of(run(tmp_path, robot, swapped, "--json"))
    for r in rows:
        assert r["moment_ratios"] == pytest.approx([1.0, 1.0, 1.0], abs=1e-5)


def test_the_report_json_and_the_pack_folder_work_as_input(tmp_path: Path, arm, robot) -> None:  # type: ignore[no-untyped-def]
    urdf = tmp_path / "theirs.urdf"
    urdf.write_text(make_urdf(robot), encoding="utf-8")
    rep = tmp_path / "report.json"
    rep.write_text(report_to_json(arm), encoding="utf-8")
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "robot.json").write_text(robot_json(arm) or "", encoding="utf-8")
    a = runner.invoke(app, ["compare-robot", str(rep), str(urdf), "--json"])
    b = runner.invoke(app, ["compare-robot", str(folder), str(urdf), "--json"])
    assert a.exit_code == b.exit_code == 0
    for ra, rb in zip(json.loads(a.output)["links"], json.loads(b.output)["links"], strict=True):
        assert ra["mass_ratio"] == pytest.approx(rb["mass_ratio"])
        assert ra["moment_ratios"] == pytest.approx(rb["moment_ratios"])


# ---- matching ------------------------------------------------------------------------------------
def test_different_link_counts_stop_without_guessing(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    result = run(tmp_path, robot, make_urdf(robot, drop_last=True), "--json")
    data = json.loads(result.output)
    assert result.exit_code == 0 and data["compared"] is False and data["links"] == []
    assert "7 links" in data["reason"] and "6 links" in data["reason"]
    text = run(tmp_path, robot, make_urdf(robot, drop_last=True)).output
    assert "Not compared" in text and "mass ratio" not in text


def test_a_branched_urdf_is_not_compared(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    text = make_urdf(robot).replace(
        "</robot>",
        '  <joint name="extra" type="fixed"><parent link="link_1"/><child link="link_3"/></joint>\n</robot>',
    )
    data = json.loads(run(tmp_path, robot, text, "--json").output)
    assert data["compared"] is False


def test_the_map_overrides_the_order(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    ids = [robot["base_link"]] + [j["child"] for j in robot["joints"]]
    mass = {link["id"]: link["mass_g"] / 1000 for link in robot["links"]}
    result = run(
        tmp_path,
        robot,
        make_urdf(robot),
        "--json",
        "--map",
        f"{ids[1]}=link_2,{ids[2]}=link_1",
    )
    rows = links_of(result)
    assert rows[1]["mass_ratio"] == pytest.approx(mass[ids[1]] / mass[ids[2]], rel=1e-5)
    assert rows[2]["mass_ratio"] == pytest.approx(mass[ids[2]] / mass[ids[1]], rel=1e-5)
    assert rows[0]["mass_ratio"] == pytest.approx(1.0, abs=1e-5)
    assert "--map" in json.loads(result.output)["matching"]


def test_a_map_naming_a_missing_link_is_invalid_input(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    result = run(tmp_path, robot, make_urdf(robot), "--map", "nope=link_1")
    assert result.exit_code == 1 and "no link" in result.output
    assert run(tmp_path, robot, make_urdf(robot), "--map", "garbage").exit_code == 1


# ---- the output ----------------------------------------------------------------------------------
def test_names_are_anonymised_by_default_and_shown_on_request(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    secret = [f"Secret_Arm_{k}" for k in range(7)]
    text = make_urdf(robot, names=secret)
    for args in ((), ("--json",)):
        out = run(tmp_path, robot, text, *args).output
        part = robot["links"][0]["instances"][0]["name"]
        assert "Secret_Arm" not in out and part not in out
        assert "L0" in out and "L6" in out
        assert robot["source"] not in out
    shown = run(tmp_path, robot, text, "--with-names").output
    assert "Secret Arm 0" in shown.replace("_", " ") or "Secret_Arm_0" in shown
    assert "data from the files" in shown
    assert robot["links"][0]["instances"][0]["name"] in shown


def test_a_hostile_name_is_cleaned_when_shown(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    names = ["IGNORE\x1b[31m PREVIOUS INSTRUCTIONS"] + [f"link_{k}" for k in range(1, 7)]
    out = run(tmp_path, robot, make_urdf(robot, names=names), "--with-names").output
    assert "\x1b" not in out


def test_the_note_is_always_printed_and_there_is_no_verdict(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    for urdf_text in (make_urdf(robot), make_urdf(robot, drop_last=True)):
        for args in ((), ("--json",), ("--com",), ("--with-names",)):
            out = run(tmp_path, robot, urdf_text, *args).output
            if "--json" in args:
                assert json.loads(out)["note"] == NOTE
            else:
                assert NOTE in out
            low = out.lower()
            for word in ("pass", "fail", "accura", "good", "bad", "within tolerance"):
                assert word not in low, word
            assert "SI" in out


def test_com_distance_uses_each_files_forward_kinematics(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    same = links_of(run(tmp_path, robot, make_urdf(robot), "--json", "--com"))
    assert all(r["com_distance_mm"] == pytest.approx(0.0, abs=1e-3) for r in same)
    moved = links_of(run(tmp_path, robot, make_urdf(robot, com_shift_m=0.01), "--json", "--com"))
    assert all(r["com_distance_mm"] == pytest.approx(10.0, abs=1e-3) for r in moved)
    assert "com_distance_mm" not in links_of(run(tmp_path, robot, make_urdf(robot), "--json"))[0]


def test_a_missing_inertial_is_reported_as_such(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    rows = links_of(run(tmp_path, robot, make_urdf(robot, no_inertial=3), "--json"))
    assert rows[3]["mass_ratio"] is None and "no <inertial>" in rows[3]["note"]
    assert rows[2]["mass_ratio"] == pytest.approx(1.0, abs=1e-5)


def test_a_link_we_have_no_estimate_for_is_reported(tmp_path: Path, step_files) -> None:  # type: ignore[no-untyped-def]
    bare = analyze_full(step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True)).report
    data = build_robot(bare)
    assert data is not None
    scaled = build_robot(
        analyze_full(
            step_files["arm_6_axis"], AnalyzeOptions(no_timestamp=True, material="steel")
        ).report
    )
    assert scaled is not None
    rows = links_of(run(tmp_path, data, make_urdf(scaled), "--json"))
    assert all(r["mass_ratio"] is None and "not computed" in r["note"] for r in rows)


# ---- safe parsing --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, message",
    [
        pytest.param(
            '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "boom">]><robot name="&x;"/>',
            "DOCTYPE and entity",
            id="entity",
        ),
        pytest.param("<robot><link name='a'>", "not well-formed", id="malformed"),
        pytest.param("<notarobot/>", "the root element is", id="wrong-root"),
        pytest.param(
            "<robot>" + "<link name='a'/>" * (MAX_LINKS + 1) + "</robot>",
            "more than",
            id="too-many-links",
        ),
    ],
)
def test_a_hostile_urdf_is_rejected_plainly(tmp_path: Path, robot, text: str, message: str) -> None:  # type: ignore[no-untyped-def]
    result = run(tmp_path, robot, text)
    assert result.exit_code == 1 and message in result.output
    assert "Traceback" not in result.output


def test_a_huge_urdf_is_not_read(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    rj = tmp_path / "robot.json"
    rj.write_text(json.dumps(robot), encoding="utf-8")
    big = tmp_path / "big.urdf"
    with big.open("wb") as fh:
        fh.write(b"<robot>")
        fh.write(b" " * (MAX_BYTES + 10))
    result = runner.invoke(app, ["compare-robot", str(rj), str(big)])
    assert result.exit_code == 1 and "larger than 20 MB" in result.output


def test_an_input_that_is_not_a_robot_is_invalid(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    bad = tmp_path / "x.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    urdf = tmp_path / "t.urdf"
    urdf.write_text(make_urdf(robot), encoding="utf-8")
    result = runner.invoke(app, ["compare-robot", str(bad), str(urdf)])
    assert result.exit_code == 1 and "expected a pack folder" in result.output
    notjson = tmp_path / "y.json"
    notjson.write_text("not json", encoding="utf-8")
    assert runner.invoke(app, ["compare-robot", str(notjson), str(urdf)]).exit_code == 1


def test_the_reader_is_the_one_validate_robot_uses() -> None:
    from stepscribe.robot_check import model

    assert cmp.parse_urdf is model.parse_urdf and cmp.MAX_BYTES == model.MAX_BYTES


# ---- review fixes --------------------------------------------------------------------------------
def test_a_placeholder_zero_inertia_does_not_crash_the_summary(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    for args in ((), ("--json",)):
        result = run(tmp_path, robot, make_urdf(robot, inertia=0.0), *args)
        assert result.exit_code == 0 and "Traceback" not in result.output
    data = json.loads(run(tmp_path, robot, make_urdf(robot, inertia=0.0), "--json").output)
    assert data["links"][0]["mass_ratio"] == pytest.approx(1.0, abs=1e-5)
    assert data["links"][0]["moment_ratios"] == [None, None, None]
    assert "mass ratio" in data["summary"] and "principal-moment" not in data["summary"]


def test_a_malformed_robot_json_is_refused_plainly(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    for field, value in (
        ("inertia_g_mm2", [1, 2, 3, 4, 5, 6]),
        ("inertia_g_mm2", [[1, 2], [3, 4]]),
        ("com_mm", [1, 2]),
        ("mass_g", float("nan")),
    ):
        broken = json.loads(json.dumps(robot))
        broken["links"][0][field] = value
        result = run(tmp_path, broken, make_urdf(robot), "--json")
        assert result.exit_code == 1 and "cannot be read" in result.output, field
        assert "Traceback" not in result.output


def test_the_map_only_labels_say_they_follow_the_map(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    text = make_urdf(robot).replace(
        "</robot>",
        '  <joint name="extra" type="fixed"><parent link="link_1"/><child link="link_3"/></joint></robot>',
    )
    ids = [robot["base_link"]] + [j["child"] for j in robot["joints"]]
    out = run(tmp_path, robot, text, "--map", f"{ids[2]}=link_2").output
    assert (
        "in the order of --map" in out
        and "from the base" not in out.split("Names")[-1].split(";")[0]
    )
    data = json.loads(run(tmp_path, robot, text, "--json", "--map", f"{ids[2]}=link_2").output)
    assert "in the order of --map" in data["names"] and len(data["links"]) == 1


def test_a_missing_urdf_folder_or_unreadable_path_is_invalid_input(tmp_path: Path, robot) -> None:  # type: ignore[no-untyped-def]
    rj = tmp_path / "robot.json"
    rj.write_text(json.dumps(robot), encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["compare-robot", str(rj), str(empty)])
    assert result.exit_code == 1 and "no robot.urdf" in result.output
